"""Diversidade: MMR e supressão de quase-duplicata.

O problema que isto resolve é concreto. A busca por "como o agente aprova uma
ferramenta" devolve oito trechos, e os oito são de `agent/graph.py` — variações
do mesmo bloco, porque um arquivo que fala do assunto fala dele várias vezes.
O orçamento de contexto foi gasto repetindo, e o arquivo que dá a outra metade
da resposta (`agent/tools/base.py`) ficou de fora.

Dentro de um orçamento fixo, cobertura vale mais que redundância. Nenhuma das
duas funções aqui joga informação fora sozinha: elas reordenam e rebaixam, o
corte é do empacotador (`retrieval/pack.py`).
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence

from eltanix.retrieval.types import RetrievedItem

# Similaridade de conteúdo acima disto = mesma coisa dita duas vezes.
NEAR_DUPLICATE_THRESHOLD = 0.92
# Quanto o MMR privilegia relevância sobre diversidade. 0.7 mantém o topo
# estável (o primeiro colocado nunca muda) e mexe na cauda, que é onde a
# repetição realmente custa.
DEFAULT_LAMBDA = 0.7

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def _shingles(texto: str) -> set[str]:
    """Conjunto de identificadores do trecho.

    Comparar por identificador em vez de por caractere é o certo para código:
    dois trechos com a mesma lógica e indentação diferente têm de contar como
    parecidos, e dois trechos com identificadores distintos não.
    """
    return set(_TOKEN_RE.findall(texto.lower()))


def jaccard(a: str, b: str) -> float:
    """Sobreposição de identificadores entre dois trechos, de 0 a 1."""
    sa, sb = _shingles(a), _shingles(b)
    if not sa or not sb:
        return 0.0
    intersecao = len(sa & sb)
    if intersecao == 0:
        return 0.0
    return intersecao / len(sa | sb)


def cosine(a: Sequence[float] | None, b: Sequence[float] | None) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    produto = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return produto / (na * nb)


def _similaridade(a: RetrievedItem, b: RetrievedItem) -> float:
    """Vetor quando as duas pontas têm; senão, sobreposição de identificadores.

    O fallback importa: chunk sem embedding (modelo fora do ar na indexação)
    continua entrando na busca pelas pernas lexicais, e sem o fallback ele
    escaparia da deduplicação justamente por ser o caso degradado.
    """
    if a.embedding and b.embedding:
        return cosine(a.embedding, b.embedding)
    return jaccard(a.content, b.content)


def drop_near_duplicates(
    itens: Sequence[RetrievedItem], *, threshold: float = NEAR_DUPLICATE_THRESHOLD
) -> list[RetrievedItem]:
    """Remove o que é repetição do que já foi mantido, preservando a ordem.

    Mantém sempre o primeiro (melhor colocado) de cada grupo de duplicatas.
    """
    mantidos: list[RetrievedItem] = []
    for item in itens:
        if any(_similaridade(item, anterior) >= threshold for anterior in mantidos):
            continue
        mantidos.append(item)
    return mantidos


def mmr(
    itens: Sequence[RetrievedItem],
    *,
    limit: int,
    lambda_: float = DEFAULT_LAMBDA,
    path_penalty: float = 0.15,
) -> list[RetrievedItem]:
    """Maximal Marginal Relevance sobre itens já ordenados por relevância.

    A cada passo escolhe o candidato que maximiza
    `λ·relevância − (1−λ)·similaridade_com_o_já_escolhido`.

    `path_penalty` é um acréscimo sobre a similaridade quando o candidato vem
    do mesmo arquivo de algo já escolhido. Similaridade de conteúdo sozinha não
    pega o caso mais comum de redundância num repositório: dois trechos
    *diferentes* do mesmo arquivo, que respondem à mesma pergunta pelo mesmo
    ângulo.
    """
    if limit <= 0 or not itens:
        return []
    restantes = list(itens)
    # O primeiro é o mais relevante, sem concorrência: MMR não deve mexer no
    # topo, só na composição do resto.
    escolhidos = [restantes.pop(0)]

    while restantes and len(escolhidos) < limit:
        melhor_indice = 0
        melhor_valor = -math.inf
        for indice, candidato in enumerate(restantes):
            redundancia = max(
                _similaridade(candidato, escolhido)
                + (path_penalty if candidato.path == escolhido.path else 0.0)
                for escolhido in escolhidos
            )
            valor = lambda_ * candidato.score - (1.0 - lambda_) * redundancia
            if valor > melhor_valor:
                melhor_valor, melhor_indice = valor, indice
        escolhidos.append(restantes.pop(melhor_indice))

    return escolhidos


def diversify(
    itens: Sequence[RetrievedItem],
    *,
    limit: int,
    lambda_: float = DEFAULT_LAMBDA,
    duplicate_threshold: float = NEAR_DUPLICATE_THRESHOLD,
) -> list[RetrievedItem]:
    """Deduplica e depois diversifica — nesta ordem.

    Ao contrário, o MMR gastaria escolhas comparando cópias entre si e a
    penalidade de redundância ficaria dominada por pares idênticos.
    """
    return mmr(
        drop_near_duplicates(itens, threshold=duplicate_threshold),
        limit=limit,
        lambda_=lambda_,
    )
