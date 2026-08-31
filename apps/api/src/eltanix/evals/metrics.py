"""Métricas de qualidade de recuperação, puras — sem I/O, sem banco.

Separadas do `runner.py` porque são o que o gate de CI compara entre
execuções: precisam ser testáveis sem Postgres, sem embedding e sem rede.

Nomenclatura, para o número não ser lido como outra coisa:

- `hit_rate` — fração de casos com ao menos um hit relevante dentro do `limit`.
  Como cada caso do dataset tem um alvo (o trecho que deveria ter vindo), isto
  é o `recall@k` do dataset. Não é recall sobre o conjunto completo de
  documentos relevantes do repositório, que ninguém rotulou.
- `mrr` — média do inverso da posição do primeiro relevante. Penaliza achar
  na quinta posição o que deveria estar na primeira.
- `ndcg` — desconto logarítmico sobre *todas* as posições relevantes, não só
  a primeira. É o que separa "achou um" de "achou os três".
"""

from __future__ import annotations

import math
from typing import Any


def dcg(relevancias: list[int]) -> float:
    """Ganho cumulativo descontado. Posição 1 não é descontada (log2(2) = 1)."""
    return sum(rel / math.log2(posicao + 1) for posicao, rel in enumerate(relevancias, start=1))


def ndcg(relevancias: list[int]) -> float:
    """DCG normalizado pelo DCG da ordenação ideal das mesmas relevâncias.

    Sem nenhum relevante o ideal é zero e a divisão não existe: devolve 0.0,
    que é o valor certo (nada relevante foi recuperado) e não um erro.
    """
    ideal = dcg(sorted(relevancias, reverse=True))
    if ideal == 0:
        return 0.0
    return dcg(relevancias) / ideal


def aggregate(results: list[dict[str, Any]]) -> dict[str, float]:
    """Agrega os dicionários de `score_case` num conjunto de métricas."""
    if not results:
        return {"cases": 0, "hit_rate": 0.0, "mrr": 0.0, "ndcg": 0.0}
    total = len(results)
    return {
        "cases": total,
        "hit_rate": sum(1 for r in results if r.get("hit")) / total,
        "mrr": sum(float(r.get("reciprocal_rank", 0.0)) for r in results) / total,
        "ndcg": sum(float(r.get("ndcg", 0.0)) for r in results) / total,
    }


def aggregate_by(results: list[dict[str, Any]], chave: str) -> dict[str, dict[str, float]]:
    """Mesma agregação, fatiada por `source` ou por tag.

    Uma média única esconde regressão localizada: a recuperação pode cair 30%
    só nas consultas sobre o router e a média geral mal se mexer.
    """
    grupos: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        valores = r.get(chave)
        if isinstance(valores, list):
            for valor in valores:
                grupos.setdefault(str(valor), []).append(r)
        elif valores is not None:
            grupos.setdefault(str(valores), []).append(r)
    return {nome: aggregate(itens) for nome, itens in sorted(grupos.items())}
