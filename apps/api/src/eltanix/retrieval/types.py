"""Item comum devolvido pelas quatro fontes de RAG.

Esta camada **não** funde os stores. `context/store.py`, `documents/store.py`,
`notes/store.py` e `graphify/store.py` continuam independentes, cada um dono do
seu SQL — a duplicação entre eles é deliberada e está registrada no CLAUDE.md.
O que existe aqui é uma vista comum sobre o que eles já devolveram, para que
rerank, diversidade e empacotamento sejam escritos uma vez em vez de três.

A diferença é a direção da dependência: `retrieval/` importa dos stores, nunca
o contrário.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Source = Literal["context", "documents", "notes", "graph"]


@dataclass(slots=True)
class RetrievedItem:
    """Um trecho recuperado, já normalizado entre as fontes.

    `score` é o score da fonte de origem — escalas **não** são comparáveis
    entre fontes, e é justamente por isso que a fusão entre fontes usa rank
    (RRF), não o score bruto. Ver `retrieval/fusion.py`.
    """

    source: Source
    # Identidade estável dentro da fonte: caminho:linha para código,
    # documento#chunk para documentos, nota#chunk para notas.
    key: str
    citation: str
    content: str
    score: float
    token_count: int = 0
    # Rank em cada perna da fusão interna da fonte, quando ela expõe.
    vector_rank: int | None = None
    text_rank: int | None = None
    trigram_rank: int | None = None
    # Vetor do item, quando disponível — só o MMR precisa dele, e só quando a
    # fonte consegue devolver sem custo extra.
    embedding: list[float] | None = None
    # Espaço para o que é específico da fonte (path, symbol, filename, título)
    # sem forçar todas as fontes a declarar campos que não têm.
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def path(self) -> str:
        """Agrupador para diversidade: dois trechos do mesmo arquivo ou do
        mesmo documento competem entre si por espaço no contexto."""
        return str(self.meta.get("path") or self.meta.get("group") or self.key.split("#")[0])
