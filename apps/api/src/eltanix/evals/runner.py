"""Roda os casos de `config/eval_dataset.yaml` contra os buscadores híbridos
reais (`DocumentService.search`, `NoteService.search`,
`ContextIndexer.search`) e imprime hit@k / MRR por fonte.

Com `--judge` (ou `EVALS_JUDGE=1`), também gera uma resposta a partir dos
trechos recuperados e mede `faithfulness` e `answer_relevance` no espírito do
RAGAS (ver `evals/ragas.py`) — juiz LLM via `RouterEngine`.

Não entra no `pytest` padrão (`tests/test_evals.py` / `tests/test_ragas.py`
cobrem só a lógica pura de score) — precisa de Postgres+pgvector+embeddings
reais no ar, é ferramenta de desenvolvedor, não teste de unidade. Uso:

    uv run eltanix-eval-rag
    uv run eltanix-eval-rag --judge
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from eltanix.config import Settings, get_settings
from eltanix.context.indexer import ContextIndexer
from eltanix.db.session import init_engine, shutdown_engine
from eltanix.documents.service import DocumentService
from eltanix.evals import metrics, ragas
from eltanix.evals.dataset import EvalCase, load_dataset
from eltanix.notes.service import NoteService
from eltanix.optimizer.cache import ResponseCache
from eltanix.router.budget import BudgetGuard
from eltanix.router.catalog import load_catalog
from eltanix.router.engine import RouterEngine
from eltanix.router.health import HealthTracker
from eltanix.router.pricing import PriceTable
from eltanix.storage.blob import BlobStore


def _relevancias(hits: list[tuple[str, str]], case: EvalCase) -> list[int]:
    """Relevância binária de cada hit, na ordem em que foram devolvidos."""
    marcas: list[int] = []
    for content, hit_id in hits:
        relevante = bool(case.expected_ids and hit_id in case.expected_ids) or bool(
            case.expected_keywords
            and any(kw.lower() in content.lower() for kw in case.expected_keywords)
        )
        marcas.append(1 if relevante else 0)
    return marcas


def _first_hit_rank(hits: list[tuple[str, str]], case: EvalCase) -> int | None:
    """Posição 1-based do primeiro hit que bate com o caso, ou None."""
    for rank, relevante in enumerate(_relevancias(hits, case), start=1):
        if relevante:
            return rank
    return None


def score_case(hits: list[tuple[str, str]], case: EvalCase) -> dict[str, Any]:
    """Puro — sem I/O, o que `tests/test_evals.py` exercita diretamente."""
    marcas = _relevancias(hits, case)
    rank = next((i for i, rel in enumerate(marcas, start=1) if rel), None)
    return {
        "query": case.query,
        "source": case.source,
        "tags": list(case.tags),
        "hit": rank is not None,
        "rank": rank,
        "reciprocal_rank": (1.0 / rank) if rank else 0.0,
        # nDCG olha todas as posições relevantes; `reciprocal_rank` só a
        # primeira. Um caso com três trechos certos, todos recuperados mas
        # embaralhados, tem MRR alto e nDCG médio — e é a diferença entre
        # "achou" e "ordenou bem".
        "ndcg": metrics.ndcg(marcas),
        "relevant_hits": sum(marcas),
    }


async def _run_case(
    case: EvalCase,
    *,
    documents: DocumentService,
    notes: NoteService,
    indexer: ContextIndexer,
    engine: RouterEngine | None = None,
    judge: bool = False,
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
            root=Path(case.root),
            query=case.query,
            limit=case.limit,
            git_aware=indexer.settings.context_git_aware_search,
        )
        hits = [(h.content, h.citation) for h in code_results]

    result = score_case(hits, case)

    if judge and engine is not None and hits:
        context_blocks = [content for content, _ in hits[: case.limit]]
        answer, gen = await ragas.score_generation(
            engine, query=case.query, context_blocks=context_blocks, source="eval"
        )
        result["answer"] = answer
        result["faithfulness"] = gen.faithfulness
        result["answer_relevance"] = gen.answer_relevance
        result["judge_unparseable"] = gen.unparseable
    return result


def build_report(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Relatório serializável — é o que o gate de CI compara entre execuções."""
    relatorio: dict[str, Any] = {
        "overall": metrics.aggregate(results),
        "by_source": metrics.aggregate_by(results, "source"),
        "by_tag": metrics.aggregate_by(results, "tags"),
    }
    julgados = [r for r in results if "faithfulness" in r]
    if julgados:
        relatorio["judge"] = {
            "cases": len(julgados),
            "faithfulness": sum(r["faithfulness"] for r in julgados) / len(julgados),
            "answer_relevance": sum(r["answer_relevance"] for r in julgados) / len(julgados),
            "unparseable": sum(1 for r in julgados if r.get("judge_unparseable")),
        }
    return relatorio


def _print_report(results: list[dict[str, Any]]) -> dict[str, Any]:
    print(f"{'fonte':<12} {'query':<42} {'hit':<5} {'rank':<5} {'nDCG':<6}")
    print("-" * 74)
    for r in results:
        print(
            f"{r['source']:<12} {r['query'][:40]:<42} "
            f"{'sim' if r['hit'] else 'não':<5} {r['rank'] or '-':<5} {r['ndcg']:<6.2f}"
        )

    relatorio = build_report(results)

    print()
    for source, agg in relatorio["by_source"].items():
        print(
            f"{source}: recall@k={agg['hit_rate']:.0%}  MRR={agg['mrr']:.3f}  "
            f"nDCG={agg['ndcg']:.3f}  ({int(agg['cases'])} casos)"
        )

    if relatorio["by_tag"]:
        print()
        for tag, agg in relatorio["by_tag"].items():
            print(
                f"  [{tag}] recall@k={agg['hit_rate']:.0%}  MRR={agg['mrr']:.3f}  "
                f"nDCG={agg['ndcg']:.3f}  ({int(agg['cases'])} casos)"
            )

    geral = relatorio["overall"]
    print()
    print(
        f"TOTAL: recall@k={geral['hit_rate']:.1%}  MRR={geral['mrr']:.3f}  "
        f"nDCG={geral['ndcg']:.3f}  ({int(geral['cases'])} casos)"
    )

    juiz = relatorio.get("judge")
    if juiz:
        linha = (
            f"JUIZ: faithfulness={juiz['faithfulness']:.2f}  "
            f"answer_rel={juiz['answer_relevance']:.2f}"
        )
        if juiz["unparseable"]:
            linha += f"  (ilegível em {juiz['unparseable']})"
        print(linha)

    return relatorio


def build_engine(settings: Settings) -> RouterEngine:
    """`RouterEngine` para as CLIs de eval, com as mesmas regras do boot da API.

    Mesmas regras de propósito: avaliar a recuperação com um catálogo que a
    aplicação recusaria mediria outra coisa. Sem Redis — cache e health ficam em
    memória, porque uma eval não deve herdar (nem sujar) o estado de um
    ambiente que está rodando.
    """
    catalog = load_catalog(
        settings.providers_file,
        settings.routes_file,
        expected_embedding_dim=settings.embedding_dim,
    )
    engine = RouterEngine(
        settings=settings,
        catalog=catalog,
        prices=PriceTable.load(settings.pricing_file),
        health=HealthTracker(None, catalog.resilience),
        cache=ResponseCache(None, enabled=False),
        budget=BudgetGuard(settings),
    )
    engine.build()
    return engine


async def _main_async() -> None:
    settings = get_settings()
    judge = "--judge" in sys.argv or os.getenv("EVALS_JUDGE") == "1"
    init_engine(settings.database_url)
    try:
        cases = load_dataset(settings.config_dir / "eval_dataset.yaml")
        if not cases:
            print(f"Nenhum caso em {settings.config_dir / 'eval_dataset.yaml'}.")
            return

        engine = build_engine(settings)

        documents = DocumentService(settings=settings, engine=engine, blob=BlobStore(settings))
        notes = NoteService(settings=settings, engine=engine)
        indexer = ContextIndexer(settings=settings, engine=engine)

        if judge:
            print("modo --judge: gerando resposta e medindo faithfulness/answer_relevance\n")
        results = [
            await _run_case(
                case,
                documents=documents,
                notes=notes,
                indexer=indexer,
                engine=engine,
                judge=judge,
            )
            for case in cases
        ]
        relatorio = _print_report(results)

        destino = _json_destino()
        if destino is not None:
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(
                json.dumps({**relatorio, "cases_detail": results}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"\nrelatório salvo em {destino}")
    finally:
        await shutdown_engine()


def _json_destino() -> Path | None:
    """Caminho do relatório JSON, por `--json <path>` ou `EVALS_JSON`.

    É o arquivo que `eltanix-eval-gate` compara com o baseline: sem ele, a
    execução só imprime números que ninguém consegue conferir depois.
    """
    if "--json" in sys.argv:
        indice = sys.argv.index("--json")
        if indice + 1 < len(sys.argv):
            return Path(sys.argv[indice + 1])
    do_ambiente = os.getenv("EVALS_JSON")
    return Path(do_ambiente) if do_ambiente else None


def main() -> None:
    asyncio.run(_main_async())


if __name__ == "__main__":
    main()
