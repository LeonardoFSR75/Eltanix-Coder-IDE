"""Gate de qualidade de recuperação: compara um relatório com o baseline.

O problema que isto resolve: mexer no chunker, no RRF ou no modelo de
embedding muda a qualidade da busca, e hoje ninguém percebe até a IDE começar
a responder pior. Lint e teste barram regressão de código; nada barrava
regressão de recuperação.

Fluxo:

    uv run eltanix-eval-rag --json /tmp/eval.json
    uv run eltanix-eval-gate --report /tmp/eval.json          # compara e falha
    uv run eltanix-eval-gate --report /tmp/eval.json --write   # promove a baseline

O baseline (`config/eval_baseline.json`) é versionado de propósito: a régua
tem de mudar por decisão registrada em commit, não por alguém rodar de novo
até passar.

A comparação é separada da execução porque assim ela é pura — `tests/
test_eval_gate.py` exercita a decisão de aprovar/reprovar sem Postgres, sem
embedding e sem rede.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from eltanix.config import get_settings

# Métricas comparadas, na ordem em que aparecem no relatório.
METRICAS = ("hit_rate", "mrr", "ndcg")

# Folga absoluta antes de chamar de regressão. Recuperação tem ruído real
# (ordem de empate no RRF, desempate por id), e um gate que dispara com
# 0,3 pp de variação vira ruído que todo mundo aprende a ignorar.
TOLERANCIA_PADRAO = 0.02


class Regressao(dict[str, Any]):
    """Uma métrica que caiu além da tolerância. `dict` para serializar direto."""


def comparar(
    baseline: dict[str, Any],
    relatorio: dict[str, Any],
    *,
    tolerancia: float = TOLERANCIA_PADRAO,
) -> list[Regressao]:
    """Regressões de `relatorio` contra `baseline`. Lista vazia = aprovado.

    Compara o agregado geral e cada fonte/tag que o baseline conhece. Uma
    fonte nova no relatório não reprova nada (não havia régua para ela); uma
    fonte que sumiu reprova, porque significa que o dataset encolheu e a média
    ficou mais fácil.
    """
    regressoes: list[Regressao] = []

    def _checa(escopo: str, antes: dict[str, Any], agora: dict[str, Any] | None) -> None:
        if agora is None:
            regressoes.append(
                Regressao(
                    scope=escopo,
                    metric="cases",
                    baseline=float(antes.get("cases", 0)),
                    current=0.0,
                    delta=-float(antes.get("cases", 0)),
                    reason="escopo presente no baseline sumiu do relatório",
                )
            )
            return

        casos_antes = int(antes.get("cases", 0))
        casos_agora = int(agora.get("cases", 0))
        if casos_agora < casos_antes:
            # Menos casos com a mesma média é uma média diferente, não a mesma
            # qualidade: sem isto, apagar os casos difíceis passa no gate.
            regressoes.append(
                Regressao(
                    scope=escopo,
                    metric="cases",
                    baseline=float(casos_antes),
                    current=float(casos_agora),
                    delta=float(casos_agora - casos_antes),
                    reason="o dataset encolheu",
                )
            )

        for metrica in METRICAS:
            valor_antes = float(antes.get(metrica, 0.0))
            valor_agora = float(agora.get(metrica, 0.0))
            delta = valor_agora - valor_antes
            if delta < -tolerancia:
                regressoes.append(
                    Regressao(
                        scope=escopo,
                        metric=metrica,
                        baseline=valor_antes,
                        current=valor_agora,
                        delta=delta,
                        reason=f"caiu {abs(delta):.3f} (tolerância {tolerancia:.3f})",
                    )
                )

    _checa("overall", baseline.get("overall") or {}, relatorio.get("overall"))

    for grupo in ("by_source", "by_tag"):
        do_baseline = baseline.get(grupo) or {}
        do_relatorio = relatorio.get(grupo) or {}
        for nome, antes in do_baseline.items():
            _checa(f"{grupo}:{nome}", antes, do_relatorio.get(nome))

    return regressoes


def _somente_metricas(relatorio: dict[str, Any]) -> dict[str, Any]:
    """Baseline sem o detalhe por caso: o diff do commit precisa ser legível."""
    return {
        chave: relatorio[chave]
        for chave in ("overall", "by_source", "by_tag")
        if chave in relatorio
    }


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        prog="eltanix-eval-gate",
        description="Compara um relatório de eval de RAG com o baseline versionado.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        required=True,
        help="JSON produzido por `eltanix-eval-rag --json`",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=settings.config_dir / "eval_baseline.json",
        help="baseline versionado (padrão: config/eval_baseline.json)",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=TOLERANCIA_PADRAO,
        help=f"queda absoluta aceita por métrica (padrão: {TOLERANCIA_PADRAO})",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="promove o relatório a baseline em vez de comparar",
    )
    args = parser.parse_args()

    if not args.report.exists():
        print(f"relatório não encontrado: {args.report}", file=sys.stderr)
        raise SystemExit(2)
    relatorio = json.loads(args.report.read_text(encoding="utf-8"))

    if args.write:
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        args.baseline.write_text(
            json.dumps(_somente_metricas(relatorio), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"baseline gravado em {args.baseline} — revise o diff antes de commitar.")
        return

    if not args.baseline.exists():
        # Falhar aqui seria pior que inútil: o primeiro uso legítimo é
        # justamente não ter baseline ainda.
        print(
            f"sem baseline em {args.baseline}. Gere um com:\n"
            f"  uv run eltanix-eval-gate --report {args.report} --write",
            file=sys.stderr,
        )
        raise SystemExit(2)

    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    regressoes = comparar(baseline, relatorio, tolerancia=args.tolerance)

    geral = relatorio.get("overall") or {}
    base_geral = baseline.get("overall") or {}
    print(
        f"recall@k {base_geral.get('hit_rate', 0):.3f} -> {geral.get('hit_rate', 0):.3f}   "
        f"MRR {base_geral.get('mrr', 0):.3f} -> {geral.get('mrr', 0):.3f}   "
        f"nDCG {base_geral.get('ndcg', 0):.3f} -> {geral.get('ndcg', 0):.3f}"
    )

    if not regressoes:
        print("gate de recuperação: OK")
        return

    print("\ngate de recuperação: REPROVADO", file=sys.stderr)
    for r in regressoes:
        print(
            f"  {r['scope']} | {r['metric']}: {r['baseline']:.3f} -> {r['current']:.3f} "
            f"({r['reason']})",
            file=sys.stderr,
        )
    raise SystemExit(1)


if __name__ == "__main__":
    main()
