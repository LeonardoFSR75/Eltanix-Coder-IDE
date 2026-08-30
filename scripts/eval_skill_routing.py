"""Eval do roteamento automático de skills (Fase 1 do upgrade do agente) — item 57.

Mede precision@1: para cada tarefa do golden-set (`config/skill_routing_eval.yaml`),
embeda o texto pelo provedor real e verifica se a skill de maior similaridade é
a esperada.

Precisa da stack de verdade: Postgres com as skills seedadas e um provedor de
embedding acessível (mesmo requisito de `tests/test_hybrid_search.py`). Não roda
no CI unitário; é a contraparte "de integração" que se roda à mão ou num job
noturno.

    uv run python scripts/eval_skill_routing.py --profile embedding

Sai com código != 0 se a precisão ficar abaixo de `--min-precision` (default 0.7),
para poder virar gate opcional.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import yaml

ROOT_DIR = Path(__file__).parent.parent.resolve()
DATASET = ROOT_DIR / "config" / "skill_routing_eval.yaml"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


async def _run(profile: str, min_precision: float, top_k: int) -> int:
    # Import tardio: puxa a stack (engine, DB) só quando o script roda de fato.
    # Mesma montagem manual de engine usada por `eltanix.evals.runner`.
    from eltanix.config import get_settings
    from eltanix.db.session import init_engine, shutdown_engine
    from eltanix.optimizer.cache import ResponseCache
    from eltanix.router.budget import BudgetGuard
    from eltanix.router.catalog import load_catalog
    from eltanix.router.engine import RouterEngine
    from eltanix.router.health import HealthTracker
    from eltanix.router.pricing import PriceTable
    from eltanix.skills.service import SkillService

    cases = yaml.safe_load(DATASET.read_text(encoding="utf-8"))["cases"]
    settings = get_settings()
    init_engine(settings.database_url)
    catalog = load_catalog(settings.providers_file, settings.routes_file)
    engine = RouterEngine(
        settings=settings,
        catalog=catalog,
        prices=PriceTable.load(settings.pricing_file),
        health=HealthTracker(None, catalog.resilience),
        cache=ResponseCache(None, enabled=False),
        budget=BudgetGuard(settings),
    )
    engine.build()
    skills = SkillService()

    acertos = 0
    falhas: list[str] = []
    for caso in cases:
        tarefa, esperado = caso["task"], caso["expect"]
        resultado = await engine.embed(
            requested_model=profile, inputs=[tarefa], source="eval.skill_routing"
        )
        data = resultado.payload.get("data") or []
        vetor = data[0].get("embedding") if data else None
        if not vetor:
            falhas.append(f"[sem-embedding] {tarefa!r}")
            continue

        relevantes = await skills.find_relevant(vetor, top_k=top_k, min_score=0.0)
        top1 = relevantes[0].name if relevantes else "(nenhuma)"
        if top1 == esperado:
            acertos += 1
        else:
            falhas.append(f"esperado {esperado!r}, veio {top1!r}  ←  {tarefa!r}")

    await shutdown_engine()

    total = len(cases)
    precisao = acertos / total if total else 0.0
    print(f"\nprecision@1: {acertos}/{total} = {precisao:.2%}\n")
    for linha in falhas:
        print(f"  MISS  {linha}")

    return 0 if precisao >= min_precision else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="embedding", help="perfil de embedding (routes.yaml)")
    parser.add_argument("--min-precision", type=float, default=0.7)
    parser.add_argument("--top-k", type=int, default=1)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args.profile, args.min_precision, args.top_k)))


if __name__ == "__main__":
    main()
