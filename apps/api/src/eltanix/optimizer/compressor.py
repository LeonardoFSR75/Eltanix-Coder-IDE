"""Compressão de contexto antes de enviar ao modelo.

Numa sessão agêntica longa o histórico cresce de forma desequilibrada: a saída
de um `pytest` sozinha passa de mil linhas, o mesmo arquivo é relido três vezes,
e turnos de vinte passos atrás continuam sendo reenviados inteiros a cada
chamada. Como o input é cobrado a cada requisição, esse peso morto é pago
repetidamente.

As técnicas estão em ordem de retorno sobre esforço, e cada uma reporta quantos
tokens economizou. Sem essa medição, "otimização de token" vira fé — e algumas
técnicas caras dão ganho desprezível no uso real.

Uma regra atravessa todas: **nunca comprimir o que está em jogo agora.** A
última rodada de mensagens, a tarefa original e os diffs vão íntegros. O que se
comprime é o que já cumpriu seu papel.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from eltanix.logging_setup import get_logger
from eltanix.optimizer.tokens import count_text, estimate_prompt_tokens

log = get_logger(__name__)

# Mensagens recentes preservadas na íntegra, sempre.
PROTECTED_RECENT_MESSAGES = 8
# A partir daqui uma saída de ferramenta é candidata a truncamento.
TOOL_RESULT_TOKEN_LIMIT = 700
HEAD_LINES = 30
TAIL_LINES = 40
MAX_ERROR_LINES = 40
# Abaixo disto não vale gastar chamada de sumarização.
HISTORY_PRUNE_THRESHOLD_TOKENS = 12_000

_ERROR_RE = re.compile(
    r"(error|failed|failure|exception|traceback|assert|✗|FAIL|E\s{3})", re.IGNORECASE
)

Summarizer = Callable[[str], Awaitable[str]]


@dataclass(slots=True)
class CompressionResult:
    messages: list[dict[str, Any]]
    tokens_before: int
    tokens_after: int
    savings: dict[str, int] = field(default_factory=dict)

    @property
    def tokens_saved(self) -> int:
        return max(0, self.tokens_before - self.tokens_after)

    @property
    def ratio(self) -> float:
        if self.tokens_before == 0:
            return 0.0
        return self.tokens_saved / self.tokens_before


def truncate_output(text: str, *, head: int = HEAD_LINES, tail: int = TAIL_LINES) -> str:
    """Preserva cabeça, cauda e as linhas com sinal de erro.

    Cortar só o início jogaria fora justamente o que interessa numa saída de
    teste: o resumo final e as falhas.
    """
    lines = text.splitlines()
    if len(lines) <= head + tail:
        return text

    meio = lines[head:-tail]
    erros = [linha for linha in meio if _ERROR_RE.search(linha)][:MAX_ERROR_LINES]

    partes = ["\n".join(lines[:head])]
    if erros:
        partes.append(f"\n... [{len(meio)} linhas omitidas; as com erro foram preservadas] ...\n")
        partes.append("\n".join(erros))
    else:
        partes.append(f"\n... [{len(meio)} linhas omitidas] ...\n")
    partes.append("\n".join(lines[-tail:]))
    return "\n".join(partes)


class ContextCompressor:
    def __init__(
        self,
        *,
        enabled: bool = True,
        protected_recent: int = PROTECTED_RECENT_MESSAGES,
        tool_result_limit: int = TOOL_RESULT_TOKEN_LIMIT,
        prune_threshold: int = HISTORY_PRUNE_THRESHOLD_TOKENS,
        summarizer: Summarizer | None = None,
    ) -> None:
        self.enabled = enabled
        self.protected_recent = protected_recent
        self.tool_result_limit = tool_result_limit
        self.prune_threshold = prune_threshold
        self.summarizer = summarizer

    async def compress(
        self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None
    ) -> CompressionResult:
        antes = estimate_prompt_tokens(messages, tools)
        if not self.enabled or len(messages) <= self.protected_recent:
            return CompressionResult(messages=messages, tokens_before=antes, tokens_after=antes)

        trabalho = [dict(m) for m in messages]
        economias: dict[str, int] = {}

        trabalho, economias["tool_truncation"] = self._truncate_tool_results(trabalho)
        trabalho, economias["file_dedup"] = self._dedupe_repeated_reads(trabalho)
        trabalho, economias["history_pruning"] = await self._prune_history(trabalho)

        depois = estimate_prompt_tokens(trabalho, tools)
        resultado = CompressionResult(
            messages=trabalho,
            tokens_before=antes,
            tokens_after=depois,
            savings={k: v for k, v in economias.items() if v > 0},
        )

        if resultado.tokens_saved > 0:
            log.info(
                "compressor.applied",
                before=antes,
                after=depois,
                saved=resultado.tokens_saved,
                ratio=round(resultado.ratio, 3),
                by_technique=resultado.savings,
            )
        return resultado

    # ── 1. Truncamento de saída de ferramenta ───────────────────────────────

    def _truncate_tool_results(
        self, messages: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], int]:
        """O maior desperdício de uma sessão agêntica, e o mais fácil de cortar."""
        limite = len(messages) - self.protected_recent
        economizado = 0

        for indice, mensagem in enumerate(messages):
            if indice >= limite or mensagem.get("role") != "tool":
                continue
            conteudo = mensagem.get("content")
            if not isinstance(conteudo, str):
                continue

            atual = count_text(conteudo)
            if atual <= self.tool_result_limit:
                continue

            truncado = truncate_output(conteudo)
            novo = count_text(truncado)
            if novo < atual:
                mensagem["content"] = truncado
                economizado += atual - novo

        return messages, economizado

    # ── 2. Deduplicação de leituras repetidas ───────────────────────────────

    def _dedupe_repeated_reads(
        self, messages: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], int]:
        """Mantém apenas a leitura mais recente de cada arquivo.

        Um agente relê o mesmo arquivo várias vezes numa sessão. As cópias
        antigas só ocupam espaço — e pior, podem estar desatualizadas em relação
        à versão que ele acabou de editar, confundindo o modelo.
        """
        limite = len(messages) - self.protected_recent
        economizado = 0

        # Percorre de trás para frente: a última leitura é a que vale.
        vistos: set[str] = set()
        for indice in range(len(messages) - 1, -1, -1):
            mensagem = messages[indice]
            if mensagem.get("role") != "tool" or mensagem.get("name") != "read_file":
                continue

            conteudo = mensagem.get("content")
            if not isinstance(conteudo, str) or not conteudo.strip():
                continue

            chave = _read_key(conteudo)
            if chave not in vistos:
                vistos.add(chave)
                continue
            if indice >= limite:
                continue

            atual = count_text(conteudo)
            substituto = (
                "[leitura anterior deste arquivo omitida — "
                "uma versão mais recente aparece adiante no histórico]"
            )
            mensagem["content"] = substituto
            economizado += atual - count_text(substituto)

        return messages, economizado

    # ── 3. Poda do histórico antigo ─────────────────────────────────────────

    async def _prune_history(
        self, messages: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], int]:
        """Condensa o miolo do histórico, preservando tarefa e turnos recentes."""
        antes = estimate_prompt_tokens(messages)
        if antes < self.prune_threshold:
            return messages, 0

        # A primeira mensagem carrega a tarefa: perdê-la faria o agente esquecer
        # o que estava fazendo.
        cabeca = messages[:1]
        cauda = messages[-self.protected_recent :]
        miolo = messages[1 : -self.protected_recent]
        if not miolo:
            return messages, 0

        custo_miolo = estimate_prompt_tokens(miolo)
        resumo = await self._summarize(miolo)
        mensagem_resumo = {
            "role": "user",
            "content": f"[Resumo dos passos anteriores desta sessão]\n{resumo}",
        }
        novo_custo = count_text(str(mensagem_resumo["content"]))

        if novo_custo >= custo_miolo:
            # Resumo maior que o original: nada a ganhar.
            return messages, 0

        return [*cabeca, mensagem_resumo, *cauda], custo_miolo - novo_custo

    async def _summarize(self, messages: list[dict[str, Any]]) -> str:
        if self.summarizer is not None:
            try:
                bruto = "\n".join(_describe(m) for m in messages)
                return await self.summarizer(bruto)
            except Exception as exc:
                log.warning("compressor.summarizer.failed", error=str(exc)[:200])

        # Sem modelo disponível, um resumo estrutural: quais ferramentas foram
        # chamadas e sobre o quê. Perde nuance, mas preserva a trilha.
        return "\n".join(f"- {_describe(m)}" for m in messages[-40:])


def _describe(message: dict[str, Any]) -> str:
    papel = message.get("role", "?")
    if papel == "tool":
        conteudo = str(message.get("content", ""))
        estado = "erro" if conteudo.startswith("ERRO") else "ok"
        return f"{message.get('name', 'ferramenta')} → {estado}"
    if chamadas := message.get("tool_calls"):
        nomes = ", ".join((c.get("function") or {}).get("name", "?") for c in chamadas)
        return f"assistente chamou: {nomes}"
    conteudo = str(message.get("content") or "").strip().replace("\n", " ")
    return f"{papel}: {conteudo[:180]}"


def _read_key(conteudo: str) -> str:
    """Identidade de uma leitura, para detectar repetição.

    Usa o conteúdo inteiro: dois `read_file` do mesmo arquivo com conteúdos
    diferentes (porque houve edição entre eles) não são duplicata, e colapsá-los
    apagaria justamente a versão atual.
    """
    return str(hash(conteudo))
