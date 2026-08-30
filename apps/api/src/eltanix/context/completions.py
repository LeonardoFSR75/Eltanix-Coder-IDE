"""Autocompletar inline / ghost text — Onda 1.1 (`docs/adr/0014-autocompletar-inline-ghost-text.md`).

Completar no cursor por **prompting FIM sobre chat**: nenhum modelo do catálogo
anuncia capacidade `fim` nativa, então o prefixo (até o cursor) e o sufixo
(depois do cursor) vão numa mensagem, com a instrução de devolver só o texto a
inserir. Toda a chamada passa pelo `RouterEngine` (ADR 0001) — este módulo só
monta o prompt e limpa a resposta.

A parte pura (`clamp_context`, `build_messages`, `clean_completion`) é o que
`tests/test_completions.py` exercita; a chamada de LLM fica na rota.
"""

from __future__ import annotations

import re

# Tetos de contexto (ADR 0014 §3). Prefixo é trimado pela esquerda e sufixo pela
# direita — o que importa é o que está colado no cursor.
MAX_PREFIX_CHARS = 4000
MAX_SUFFIX_CHARS = 2000
# `max_tokens` da completion. Ghost text longo demais atrapalha mais que ajuda;
# 64 cobre de um identificador a um corpo de função curto.
MAX_TOKENS = 64

SYSTEM_PROMPT = """Você completa código na posição exata de um cursor, como o autocompletar \
inline (ghost text) de um editor. Recebe o código ANTES do cursor e o código DEPOIS do cursor.

Devolva APENAS o texto a inserir na posição do cursor — o que vem entre o "antes" e o "depois". \
Sem markdown, sem crases (```), sem explicação, sem repetir o código que já existe antes ou \
depois do cursor. Se nada faz sentido para completar ali, devolva uma linha vazia. Preserve a \
indentação e o estilo do código ao redor. Prefira completar só até o fim da linha ou do bloco \
lógico imediato — não escreva a função inteira."""

_FENCE_RE = re.compile(r"^\s*```[a-zA-Z0-9_+-]*\r?\n?|\r?\n?```\s*$")


def clamp_context(prefix: str, suffix: str) -> tuple[str, str]:
    """Limita prefixo/sufixo ao que está perto do cursor. Prefixo perde o
    começo, sufixo perde o fim."""
    if len(prefix) > MAX_PREFIX_CHARS:
        prefix = prefix[-MAX_PREFIX_CHARS:]
    if len(suffix) > MAX_SUFFIX_CHARS:
        suffix = suffix[:MAX_SUFFIX_CHARS]
    return prefix, suffix


def build_messages(
    *, prefix: str, suffix: str, path: str, language: str | None
) -> list[dict[str, str]]:
    """Monta as mensagens FIM-sobre-chat para o `engine.complete()`."""
    prefix, suffix = clamp_context(prefix, suffix)
    lang = language or "texto"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Arquivo: {path} (linguagem: {lang})\n\n"
                f"--- CÓDIGO ANTES DO CURSOR ---\n{prefix}\n"
                f"--- CÓDIGO DEPOIS DO CURSOR ---\n{suffix}\n\n"
                f"Texto a inserir na posição do cursor:"
            ),
        },
    ]


def _strip_fence(text: str) -> str:
    # Modelo às vezes embrulha em ```; tira a cerca de abertura e a de fechamento.
    prev = None
    while prev != text:
        prev = text
        text = _FENCE_RE.sub("", text)
    return text


def _longest_prefix_overlap(base_tail: str, candidate: str) -> int:
    """Maior k tal que `candidate[:k]` termina `base_tail` — usado para não
    repetir o que já está antes do cursor."""
    limit = min(len(base_tail), len(candidate))
    for k in range(limit, 0, -1):
        if base_tail.endswith(candidate[:k]):
            return k
    return 0


def clean_completion(text: str, *, prefix: str, suffix: str) -> str:
    """Tira cercas de código e o que o modelo repetiu do contexto. Devolve ""
    quando não sobra nada útil (ghost text vazio é o caminho de degradação)."""
    if not text:
        return ""
    cleaned = _strip_fence(text)

    # Repetição do fim do prefixo no começo da completion (o erro mais comum:
    # o modelo "recomeça" a linha atual em vez de continuá-la).
    if prefix:
        overlap = _longest_prefix_overlap(prefix[-200:], cleaned)
        if overlap:
            cleaned = cleaned[overlap:]

    # Repetição do começo do sufixo no fim da completion.
    if suffix:
        head = suffix[:200]
        for k in range(min(len(head), len(cleaned)), 0, -1):
            if cleaned.endswith(head[:k]) and head.startswith(cleaned[-k:]):
                cleaned = cleaned[:-k]
                break

    return cleaned if cleaned.strip() else ""


def extract_completion(payload: dict, *, prefix: str, suffix: str) -> str:
    """`clean_completion` aplicada direto no payload do `RouterEngine`."""
    choice = (payload.get("choices") or [{}])[0]
    raw = (choice.get("message") or {}).get("content") or ""
    return clean_completion(raw, prefix=prefix, suffix=suffix)
