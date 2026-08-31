"""Qual fonte consultar para cada pergunta.

Consultar as quatro fontes sempre custa quatro idas ao banco e um embedding
por fonte, para na maioria das vezes descartar três. Pior: nota e documento
entram no pool competindo com código em perguntas que são claramente sobre o
repositório aberto, e ocupam espaço de contexto que o código precisava.

A classificação é heurística de propósito, mesmo motivo de
`optimizer/complexity.py`: um classificador por LLM custaria uma chamada para
decidir sobre outra, e aqui o custo evitado é uma query, não um modelo caro.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from eltanix.retrieval.types import Source

# Pergunta que cita caminho, extensão ou convenção de identificador é sobre o
# código aberto, não sobre a documentação.
_SINAIS_DE_CODIGO = re.compile(
    r"(\.(py|ts|tsx|js|jsx|rs|go|java|rb|svelte|yaml|yml|toml|sql)\b"
    r"|[a-z]+_[a-z]+|[a-z]+[A-Z][a-z]+|::|/|\bdef\b|\bclass\b|\bimport\b)"
)

# Pergunta sobre decisão, motivo ou histórico costuma estar em ADR e nota, não
# no corpo de uma função.
_SINAIS_DE_CONHECIMENTO = re.compile(
    r"\b(por ?qu[eê]|decis[ãa]o|decidimos|adr|hist[óo]rico|racional|"
    r"documenta[çc][ãa]o|manual|pol[íi]tica|contrato|requisito)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class SourcePlan:
    sources: tuple[Source, ...]
    reason: str

    def __contains__(self, source: object) -> bool:
        return source in self.sources


def plan_sources(
    query: str,
    *,
    allow_documents: bool = True,
    allow_notes: bool = True,
) -> SourcePlan:
    """Fontes a consultar para `query`.

    Código está sempre presente: numa IDE, a pergunta que não é sobre o
    repositório é a exceção, e errar para o lado de incluir código custa uma
    query barata — errar para o lado de excluí-lo custa a resposta.
    """
    fontes: list[Source] = ["context"]

    conhecimento = bool(_SINAIS_DE_CONHECIMENTO.search(query))
    codigo = bool(_SINAIS_DE_CODIGO.search(query))

    if conhecimento or not codigo:
        if allow_documents:
            fontes.append("documents")
        if allow_notes:
            fontes.append("notes")
        motivo = "pergunta conceitual ou sobre decisão" if conhecimento else "sem sinal de código"
    else:
        motivo = "pergunta com sinal explícito de código"

    return SourcePlan(sources=tuple(fontes), reason=motivo)
