"""Git-Aware RAG — Fase 4 do Git Intelligence (`docs/proposals/git-code-intelligence.md`).

Pega os hits do `store.hybrid_search` do RAG de **código** e:

1. **Expande por vizinhança de 1 hop** no Code Knowledge Graph (`code_edge`):
   quem o chunk contém, quem o contém, o que o arquivo importa e quem importa
   o arquivo. Vizinho entra com score derivado do hit que o puxou, sempre
   abaixo dele.
2. **Re-rankeia com sinais do git**: arquivos que co-mudam com os top hits
   ganham boost; trechos tocados por commit recente ganham um empurrão, os
   muito antigos um leve desconto (`git blame` + `git co_change`).

Fica separado de `store.py` porque precisa do `Path` do repositório — `store.py`
só fala com o banco. **Não** é o "helper compartilhado entre as 4 fontes de RAG"
que o `CLAUDE.md` proíbe: só o RAG de código usa isto; documentos, notas e
graphify continuam intocados.

Degrada, não quebra: sem git, sem grafo, ou com qualquer passo falhando, cai
para os hits originais do `hybrid_search`.
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from eltanix.context import store
from eltanix.context.store import SearchHit
from eltanix.logging_setup import get_logger
from eltanix.workspace import git as git_ops

log = get_logger(__name__)

# Quantos hits do topo alimentam a expansão de grafo e o cálculo de co-mudança
# — o resto do pool raramente muda o ranking final e cada um custa I/O.
_TOP_N_EXPAND = 5
_TOP_N_COCHANGE = 3
# Score de um vizinho de grafo = score do hit que o puxou × isto. Sempre < 1
# para o vizinho nunca passar na frente da própria origem.
_NEIGHBOR_FACTOR = 0.6
# Teto do bônus multiplicativo por co-mudança forte (arquivo que aparece em
# todos os commits recentes de um top hit).
_COCHANGE_MAX_BOOST = 0.25
# Recência do `git blame` do trecho: meia-vida da exponencial e amplitude do
# ajuste. Trecho novo → ~+RECENCY_AMPLITUDE; trecho antigo → ~-RECENCY_AMPLITUDE.
_RECENCY_HALFLIFE_DAYS = 45.0
_RECENCY_AMPLITUDE = 0.15
# `git blame` é O(histórico) por arquivo — só roda nos caminhos distintos dos
# candidatos mais bem ranqueados, nunca no pool inteiro.
_MAX_BLAME_PATHS = 12


@dataclass(slots=True)
class RecencySignal:
    """Sinais de git já resolvidos, prontos para a parte pura do re-rank."""

    co_changed: dict[str, int]  # path -> nº de commits recentes em que co-mudou
    blame_age_days: dict[str, float]  # path -> idade (dias) do commit mais recente do arquivo

    @property
    def cochange_peak(self) -> int:
        return max(self.co_changed.values(), default=0)


def _dedupe_key(hit: SearchHit) -> tuple[str, int]:
    return (hit.path, hit.start_line)


def rerank(
    base: list[SearchHit],
    neighbors: list[SearchHit],
    signal: RecencySignal,
    *,
    limit: int,
) -> list[SearchHit]:
    """Parte pura: funde base + vizinhos (dedupe), aplica os multiplicadores de
    co-mudança e recência sobre o score, ordena e trunca. Sem I/O — é o que
    `tests/test_git_aware_rag.py` exercita direto."""
    seen: set[tuple[str, int]] = set()
    merged: list[SearchHit] = []
    for hit in [*base, *neighbors]:
        key = _dedupe_key(hit)
        if key in seen:
            continue
        seen.add(key)
        merged.append(hit)

    peak = signal.cochange_peak or 1
    adjusted: list[SearchHit] = []
    for hit in merged:
        factor = 1.0

        count = signal.co_changed.get(hit.path, 0)
        if count:
            factor *= 1.0 + _COCHANGE_MAX_BOOST * (count / peak)

        age = signal.blame_age_days.get(hit.path)
        if age is not None:
            # 2*e^(-age/HL) - 1 vai de +1 (idade 0) a -1 (idade ≫ HL).
            recency = 2.0 * math.exp(-age / _RECENCY_HALFLIFE_DAYS) - 1.0
            factor *= 1.0 + _RECENCY_AMPLITUDE * recency

        adjusted.append(replace(hit, score=hit.score * factor))

    adjusted.sort(key=lambda h: h.score, reverse=True)
    return adjusted[:limit]


async def _graph_neighbors(
    session: AsyncSession, *, workspace: str, base: list[SearchHit]
) -> list[SearchHit]:
    """Vizinhos de 1 hop dos top hits, como `SearchHit` de score derivado."""
    out: list[SearchHit] = []
    for parent in base[:_TOP_N_EXPAND]:
        try:
            graph = await store.code_graph(
                session,
                workspace=workspace,
                path=parent.path,
                symbol=parent.symbol,
                line=parent.start_line,
            )
        except Exception as exc:  # grafo indisponível para este chunk — pula
            log.warning("git_aware.graph_expand.failed", path=parent.path, error=str(exc)[:200])
            continue

        neighbor_chunks = list(graph.contains)
        if graph.contained_by is not None:
            neighbor_chunks.append(graph.contained_by)
        for path in (*graph.imports, *graph.imported_by):
            mod = await store.find_chunk(session, workspace=workspace, path=path)
            if mod is not None:
                neighbor_chunks.append(mod)

        for chunk in neighbor_chunks:
            out.append(
                SearchHit(
                    path=chunk.path,
                    symbol=chunk.symbol,
                    parent=chunk.parent,
                    kind=chunk.kind,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    content=chunk.content,
                    language=chunk.language,
                    token_count=chunk.token_count,
                    score=parent.score * _NEIGHBOR_FACTOR,
                )
            )
    return out


def _collect_recency(root: Path, base: list[SearchHit], candidates: list[SearchHit]) -> RecencySignal:
    """Roda `git co_change` nos top hits e `git blame`-lite (idade do commit
    mais recente do arquivo) nos caminhos mais bem ranqueados. Cada passo
    degrada isolado."""
    co_changed: dict[str, int] = {}
    for parent in base[:_TOP_N_COCHANGE]:
        try:
            for entry in git_ops.co_change(root, parent.path):
                co_changed[entry.path] = max(co_changed.get(entry.path, 0), entry.count)
        except Exception as exc:
            log.warning("git_aware.co_change.failed", path=parent.path, error=str(exc)[:200])

    # Caminhos distintos, na ordem dos candidatos, limitados — blame é caro.
    paths: list[str] = []
    for hit in candidates:
        if hit.path not in paths:
            paths.append(hit.path)
        if len(paths) >= _MAX_BLAME_PATHS:
            break

    blame_age_days: dict[str, float] = {}
    now = datetime.now(UTC)
    for path in paths:
        try:
            hunks = git_ops.blame(root, path)
        except Exception:
            continue  # arquivo novo / sem histórico — sem sinal de recência
        ages: list[float] = []
        for hunk in hunks:
            try:
                dt = datetime.fromisoformat(hunk.date)
            except ValueError:
                continue
            ages.append((now - dt).total_seconds() / 86400.0)
        if ages:
            blame_age_days[path] = min(ages)
    return RecencySignal(co_changed=co_changed, blame_age_days=blame_age_days)


async def git_aware_search(
    session: AsyncSession,
    *,
    root: Path | None,
    workspace: str,
    query_text: str,
    query_embedding: list[float] | None,
    limit: int = 12,
    path_prefix: str | None = None,
    expand: bool = True,
    recency: bool = True,
) -> list[SearchHit]:
    """`hybrid_search` de código + expansão de grafo + re-rank por git.

    Puxa um pool maior que `limit` do `hybrid_search` para a expansão e o
    re-rank terem folga, depois trunca em `limit`.
    """
    base = await store.hybrid_search(
        session,
        workspace=workspace,
        query_text=query_text,
        query_embedding=query_embedding,
        limit=max(limit * 2, limit + 6),
        path_prefix=path_prefix,
    )
    if not base:
        return []

    neighbors: list[SearchHit] = []
    if expand:
        try:
            neighbors = await _graph_neighbors(session, workspace=workspace, base=base)
        except Exception as exc:
            log.warning("git_aware.expand.failed", error=str(exc)[:200])

    signal = RecencySignal(co_changed={}, blame_age_days={})
    if recency and root is not None:
        try:
            # git blame/log são bloqueantes — fora do event loop.
            signal = await asyncio.to_thread(_collect_recency, root, base, [*base, *neighbors])
        except Exception as exc:
            log.warning("git_aware.recency.failed", error=str(exc)[:200])

    return rerank(base, neighbors, signal, limit=limit)
