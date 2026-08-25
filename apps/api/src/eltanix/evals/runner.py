"""Roda os casos de `config/eval_dataset.yaml` contra os buscadores híbridos
reais (`DocumentService.search`, `NoteService.search`,
`ContextIndexer.search`) e imprime hit@k / MRR por fonte.

Não entra no `pytest` padrão (`tests/test_evals.py` cobre só a lógica de
score) — precisa de Postgres+pgvector+embeddings reais no ar, é ferramenta
de desenvolvedor, não teste de unidade. Uso:

    uv run eltanix-eval-rag
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from eltanix.config import get_settings
from eltanix.context.indexer import ContextIndexer
from eltanix.db.session import init_engine, shutdown_engine
from eltanix.documents.service import DocumentService
from eltanix.evals.dataset import EvalCase, load_dataset
from eltanix.notes.service import NoteService
from eltanix.optimizer.cache import ResponseCache
from eltanix.router.budget import BudgetGuard
from eltanix.router.catalog import load_catalog
from eltanix.router.engine import RouterEngine
from eltanix.router.health import HealthTracker
from eltanix.router.pricing import PriceTable
from eltanix.storage.blob import BlobStore


def _first_hit_rank(hits: list[tuple[str, str]], case: EvalCase) -> int | None:
    """Posição 1-based do primeiro hit que bate com o caso, ou None."""
    for rank, (content, hit_id) in enumerate(hits, start=1):
        if case.expected_ids and hit_id in case.expected_ids:
            return rank
        if case.expected_keywords and any(
            kw.lower() in content.lower() for kw in case.expected_keywords
        ):
            return rank
    return None


def score_case(hits: list[tuple[str, str]], case: EvalCase) -> dict[str, Any]:
    """Puro — sem I/O, o que `tests/test_evals.py` exercita diretamente."""
    rank = _first_hit_rank(hits, case)
    return {
        "query": case.query,
        "source": case.source,
        "hit": rank is not None,
        "rank": rank,
        "reciprocal_rank": (1.0 / rank) if rank else 0.0,
    }


async def _run_case(
    case: EvalCase,
    *,
    documents: DocumentService,
    notes: NoteService,
    indexer: ContextIndexer,
) -> dict[str, Any]:
    if case.source == "documents":
        doc_results = await documents.search(case.query, limit=case.limit)
        hits = [(h.content, f"{h.document_id}#{h.chunk_index}") for h in doc_results]
    elif case.source == "notes":
        note_results = await notes.search(case.query, limit=case.limit)
        hits = [(h.content, f"{h.note_id}#{h.chunk_index}") for h in note_results]
    else:
        assert case.root is not None
        code_results = await indexer.search(
            root=Path(case.root), query=case.query, limit=case.limit
        )
        hits = [(h.content, h.citation) for h in code_results]
    return score_case(hits, case)


def _print_report(results: list[dict[str, Any]]) -> None:
    print(f"{'fonte':<12} {'query':<42} {'hit':<5} {'rank':<5}")
    print("-" * 66)
    for r in results:
        print(
            f"{r['source']:<12} {r['query'][:40]:<42} "
            f"{'sim' if r['hit'] else 'não':<5} {r['rank'] or '-':<5}"
        )

    by_source: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        by_source.setdefault(r["source"], []).append(r)

    print()
    for source, items in by_source.items():
        hit_rate = sum(1 for i in items if i["hit"]) / len(items)
        mrr = sum(i["reciprocal_rank"] for i in items) / len(items)
        print(f"{source}: hit@k={hit_rate:.0%}  MRR={mrr:.2f}  ({len(items)} casos)")


async def _main_async() -> None:
    settings = get_settings()
    init_engine(settings.database_url)
    try:
        cases = load_dataset(settings.config_dir / "eval_dataset.yaml")
        if not cases:
            print(f"Nenhum caso em {settings.config_dir / 'eval_dataset.yaml'}.")
            return

        catalog = load_catalog(settings.providers_file, settings.routes_file)
        prices = PriceTable.load(settings.pricing_file)
        health = HealthTracker(None, catalog.resilience)
        cache = ResponseCache(None, enabled=False)
        engine = RouterEngine(
            settings=settings,
            catalog=catalog,
            prices=prices,
            health=health,
            cache=cache,
            budget=BudgetGuard(settings),
        )
        engine.build()

        documents = DocumentService(settings=settings, engine=engine, blob=BlobStore(settings))
        notes = NoteService(settings=settings, engine=engine)
        indexer = ContextIndexer(settings=settings, engine=engine)

        results = [
            await _run_case(case, documents=documents, notes=notes, indexer=indexer)
            for case in cases
        ]
        _print_report(results)
    finally:
        await shutdown_engine()


def main() -> None:
    asyncio.run(_main_async())


if __name__ == "__main__":
    main()
