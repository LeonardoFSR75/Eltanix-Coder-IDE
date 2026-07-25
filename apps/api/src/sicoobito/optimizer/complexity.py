"""Roteamento por complexidade da tarefa.

O maior desperdício de dinheiro numa plataforma agêntica não é prompt inchado —
é mandar para um modelo caro trabalho que um modelo pequeno resolve. Gerar
mensagem de commit, classificar intenção, resumir histórico e nomear um PR não
precisam do modelo forte.

A classificação é heurística de propósito: um classificador por LLM custaria uma
chamada para decidir sobre outra chamada, o que só se paga quando a diferença de
preço entre os modelos é enorme. Sinais explícitos (a origem do request, a
presença de ferramentas) valem mais que adivinhação sobre o texto.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sicoobito.optimizer.tokens import estimate_prompt_tokens


class Complexity(StrEnum):
    TRIVIAL = "trivial"  # mensagem de commit, título, classificação
    SIMPLES = "simples"  # pergunta pontual, leitura, explicação curta
    COMPLEXA = "complexa"  # refactor multi-arquivo, depuração, uso de ferramentas


# Perfil sugerido por complexidade. Nomes têm de existir em routes.yaml.
PROFILE_BY_COMPLEXITY: dict[Complexity, str] = {
    Complexity.TRIVIAL: "utility",
    Complexity.SIMPLES: "auto",
    Complexity.COMPLEXA: "coding",
}

# Origens que sabidamente pedem trabalho auxiliar.
_UTILITY_SOURCES = {"indexer", "search", "summarizer", "commit-message", "pr-title"}

_TRIVIAL_HINTS = re.compile(
    r"\b(mensagem de commit|commit message|t[ií]tulo|classifiqu|resum[ai]|"
    r"nomeie|traduz|uma palavra|sim ou n[ãa]o)\b",
    re.IGNORECASE,
)

# Radicais de verbos que indicam pedido de alteração de código.
#
# Cuidado com a morfologia do português: o imperativo é justamente a forma que
# o usuário digita ao dar uma ordem, e ele altera o radical. "corrigir" vira
# "corrija" (g→j) e "migrar" vira "migre" — um radical `corrig` ou `migra`
# perderia exatamente os casos mais comuns.
_COMPLEX_HINTS = re.compile(
    r"\b(refator|refactor|implement|corrig|corrij|depur|debug|migr|arquitet|"
    r"reescrev|reescrit|otimiz|adicion|remov|ajust|atualiz|"
    r"teste[s]? (para|de|do|da))\w*\b",
    re.IGNORECASE,
)

# Acima disto, a tarefa envolve contexto demais para um modelo pequeno.
_LARGE_PROMPT_TOKENS = 6000
# Abaixo disto, o pedido é curto o bastante para ser mecânico mesmo sem pista
# textual. O limiar é propositalmente baixo: a contagem local é aproximada, e
# rebaixar por engano uma pergunta real para o modelo pequeno custa qualidade.
_TINY_PROMPT_TOKENS = 120


@dataclass(slots=True)
class ComplexityVerdict:
    complexity: Complexity
    profile: str
    reason: str


def classify(
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    source: str = "unknown",
) -> ComplexityVerdict:
    if source in _UTILITY_SOURCES:
        return ComplexityVerdict(
            Complexity.TRIVIAL,
            PROFILE_BY_COMPLEXITY[Complexity.TRIVIAL],
            f"origem '{source}' é trabalho auxiliar",
        )

    # Ferramentas disponíveis significam um loop agêntico, não uma pergunta.
    if tools:
        return ComplexityVerdict(
            Complexity.COMPLEXA,
            PROFILE_BY_COMPLEXITY[Complexity.COMPLEXA],
            "request com ferramentas: exige raciocínio multi-passo",
        )

    tokens = estimate_prompt_tokens(messages, tools)
    if tokens > _LARGE_PROMPT_TOKENS:
        return ComplexityVerdict(
            Complexity.COMPLEXA,
            PROFILE_BY_COMPLEXITY[Complexity.COMPLEXA],
            f"prompt grande ({tokens} tokens)",
        )

    texto = " ".join(
        str(m.get("content") or "")
        for m in messages
        if m.get("role") == "user" and isinstance(m.get("content"), str)
    )

    if _COMPLEX_HINTS.search(texto):
        return ComplexityVerdict(
            Complexity.COMPLEXA,
            PROFILE_BY_COMPLEXITY[Complexity.COMPLEXA],
            "pedido de alteração de código",
        )

    # A checagem de trivial vem depois da de complexa: "resuma o refactor que
    # fizemos" contém as duas pistas, e a que importa é a mais exigente.
    if _TRIVIAL_HINTS.search(texto) or tokens < _TINY_PROMPT_TOKENS:
        return ComplexityVerdict(
            Complexity.TRIVIAL,
            PROFILE_BY_COMPLEXITY[Complexity.TRIVIAL],
            "tarefa curta e mecânica",
        )

    return ComplexityVerdict(
        Complexity.SIMPLES,
        PROFILE_BY_COMPLEXITY[Complexity.SIMPLES],
        "pergunta de tamanho médio, sem alteração de código",
    )
