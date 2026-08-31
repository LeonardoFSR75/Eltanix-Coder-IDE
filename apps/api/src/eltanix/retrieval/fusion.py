"""Fusão entre fontes e os pesos que cada fonte usa internamente.

Dois níveis de fusão, deliberadamente separados:

1. **Dentro de uma fonte** (SQL de cada store): vetor + full-text + trigrama,
   por RRF ponderado. Fica no SQL porque só ali as três pernas podem ser
   calculadas numa ida ao banco.
2. **Entre fontes** (aqui): código, documentos e notas devolvem scores em
   escalas incomparáveis — um score 0,03 de RRF de código não significa nada
   ao lado de 0,05 de nota. Fundir por **rank**, não por score, é o que torna
   a comparação possível sem calibrar escalas.

Este módulo só define pesos e ordena. Ele não constrói SQL nem sabe qual
tabela cada fonte usa — isso continua sendo assunto de cada store.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from eltanix.retrieval.types import RetrievedItem, Source

# Mesmo `k` do artigo original (Cormack et al.): amortece a diferença entre as
# primeiras posições. Só que agora é ponto de partida medido, não dogma.
RRF_K = 60


@dataclass(frozen=True, slots=True)
class SignalWeights:
    """Pesos das pernas **dentro** de uma fonte, repassados ao SQL do store.

    O trigrama nasce com peso menor de propósito: ele acerta nome parecido,
    o que é sinal de apoio, não par do vetor e do full-text. Um trigrama com
    peso 1.0 faz qualquer arquivo de nome parecido subir acima do trecho que
    responde a pergunta.
    """

    vector: float = 1.0
    text: float = 1.0
    trigram: float = 0.5
    k: int = RRF_K


@dataclass(frozen=True, slots=True)
class SourceWeights:
    """Peso de cada fonte na fusão entre fontes.

    Código pesa mais numa IDE: a pergunta quase sempre é sobre o repositório
    aberto. Documento e nota entram como contexto de apoio.
    """

    context: float = 1.0
    documents: float = 0.7
    notes: float = 0.7
    graph: float = 0.6

    def of(self, source: Source) -> float:
        return float(getattr(self, source, 0.0))


def fuse(
    grupos: Sequence[Sequence[RetrievedItem]],
    *,
    weights: SourceWeights | None = None,
    k: int = RRF_K,
    limit: int | None = None,
) -> list[RetrievedItem]:
    """Funde listas já ordenadas de fontes distintas, por RRF ponderado.

    Cada lista chega ordenada pela própria fonte; o que conta aqui é a
    posição, não o score. Item repetido entre fontes (a mesma função citada
    num documento e no código) soma as contribuições — aparecer em duas
    fontes é evidência, e o RRF trata isso naturalmente.
    """
    pesos = weights or SourceWeights()
    acumulado: dict[str, float] = {}
    melhor: dict[str, RetrievedItem] = {}

    for grupo in grupos:
        for posicao, item in enumerate(grupo, start=1):
            peso = pesos.of(item.source)
            if peso <= 0:
                continue
            chave = f"{item.source}:{item.key}"
            acumulado[chave] = acumulado.get(chave, 0.0) + peso / (k + posicao)
            # Guarda a primeira ocorrência: é a de melhor rank na fonte dela.
            melhor.setdefault(chave, item)

    ordenados = sorted(acumulado.items(), key=lambda par: (-par[1], par[0]))
    saida: list[RetrievedItem] = []
    for chave, score in ordenados:
        item = melhor[chave]
        # `score` passa a ser o da fusão entre fontes; o da fonte já cumpriu
        # seu papel ao definir a posição.
        saida.append(
            RetrievedItem(
                source=item.source,
                key=item.key,
                citation=item.citation,
                content=item.content,
                score=score,
                token_count=item.token_count,
                vector_rank=item.vector_rank,
                text_rank=item.text_rank,
                trigram_rank=item.trigram_rank,
                embedding=item.embedding,
                meta=item.meta,
            )
        )
    return saida[:limit] if limit is not None else saida
