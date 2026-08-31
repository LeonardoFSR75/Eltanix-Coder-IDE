"""Indexa um workspace pela linha de comando, sem subir a API.

Existe para o gate de qualidade em CI: antes de medir recuperação é preciso
ter o que recuperar, e o caminho normal (`POST /api/context/index`) exige a
aplicação de pé, autenticação e um projeto cadastrado — cerimônia que não
acrescenta nada quando quem chama é um passo de workflow.

    uv run python -m eltanix.evals.index_workspace /caminho/do/repo
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from eltanix.config import get_settings
from eltanix.context.indexer import ContextIndexer
from eltanix.db.session import init_engine, shutdown_engine
from eltanix.optimizer.cache import ResponseCache
from eltanix.router.budget import BudgetGuard
from eltanix.router.catalog import load_catalog
from eltanix.router.engine import RouterEngine
from eltanix.router.health import HealthTracker
from eltanix.router.pricing import PriceTable


async def _main_async(root: Path) -> int:
    settings = get_settings()
    init_engine(settings.database_url)
    try:
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

        indexer = ContextIndexer(settings=settings, engine=engine)
        report = await indexer.index_workspace(root, force=True)

        print(
            f"workspace={report.workspace}\n"
            f"arquivos={report.indexed}/{report.scanned}  chunks={report.chunks}\n"
            f"vetores={report.embedded}  falhas={report.embedding_failures}  "
            f"modelo={report.embedding_model or 'nenhum'}\n"
            f"duração={report.duration_ms} ms"
        )
        for erro in report.errors[:10]:
            print(f"  erro: {erro}")

        if report.embedded == 0:
            # Índice sem vetor mede full-text puro. Deixar passar aqui faria o
            # gate comparar duas coisas diferentes e chamar isso de regressão
            # (ou, pior, de melhora).
            print(
                "\nnenhum vetor foi gerado — o modelo de embedding não respondeu. "
                "Medir recuperação assim mede outra coisa.",
                file=sys.stderr,
            )
            return 1
        return 0
    finally:
        await shutdown_engine()


def main() -> None:
    if len(sys.argv) < 2:
        print("uso: python -m eltanix.evals.index_workspace <caminho>", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(asyncio.run(_main_async(Path(sys.argv[1]))))


if __name__ == "__main__":
    main()
