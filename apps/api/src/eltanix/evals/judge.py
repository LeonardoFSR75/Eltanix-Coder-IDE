"""Calibração e concordância do juiz de geração (`evals/ragas.py`).

O problema que isto resolve: `judge_generation` devolve `faithfulness: 0.82` e
ninguém sabe o que 0,82 quer dizer. É um número produzido por um LLM sobre a
saída de outro LLM, sem nada que o ancore. Duas perguntas ficavam sem resposta:

1. **O juiz concorda com um humano?** Sem isso, a métrica mede a opinião de um
   modelo, não a qualidade da resposta. Um juiz que dá 0,8 para tudo tem média
   ótima e valor zero.
2. **O juiz concorda consigo mesmo?** Temperatura 0 não garante determinismo, e
   um juiz que oscila 0,3 entre execuções não consegue detectar uma regressão
   de 0,05 — que é a ordem de grandeza que interessa.

O que este módulo faz, sobre um conjunto rotulado por humano
(`config/judge_labels.yaml`):

- **Concordância com o humano**: erro absoluto médio, correlação de Pearson e
  kappa de Cohen sobre a decisão binarizada (aprovado/reprovado). MAE diz o
  tamanho do erro, Pearson diz se a ordem está certa, kappa desconta a
  concordância que aconteceria por acaso — as três respondem coisas diferentes
  e nenhuma sozinha basta.
- **Auto-concordância**: o mesmo item julgado `repeats` vezes. O desvio entre
  execuções é o **piso de ruído** da métrica: variação menor que ele em qualquer
  comparação futura não é sinal.
- **Calibração afim**: os juízes LLM erram sistematicamente para cima (bondade)
  e comprimem a faixa. Uma reta ajustada por mínimos quadrados corrige as duas
  coisas de uma vez, é interpretável (dá para ler o viés no `intercept`) e não
  inventa estrutura que ~30 pontos rotulados não sustentam — que é justamente o
  risco de um isotônico aqui.
- **Intervalo de confiança por bootstrap**: a razão de existir do módulo. Um
  número sem intervalo não distingue melhora de ruído amostral, e é assim que
  se fecha PR celebrando +0,02 num conjunto de 30 casos.

O `Calibration` gravado em JSON é lido de volta por quem reporta a métrica, e
carrega o `n` e o intervalo: uma calibração ajustada em 8 casos continua
utilizável, contanto que ninguém finja que ela vale o mesmo que uma de 200.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import statistics
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from eltanix.evals.ragas import GenerationScore, judge_generation
from eltanix.logging_setup import get_logger

log = get_logger(__name__)

METRICAS = ("faithfulness", "answer_relevance")
# Corte para binarizar a nota antes do kappa. 0,5 é o ponto em que uma resposta
# deixa de ser "mais sustentada que não" — a decisão que um humano tomaria.
LIMIAR_APROVACAO = 0.5
# Reamostragens do bootstrap. 2000 estabiliza o percentil de 95% para conjuntos
# desta ordem sem custo perceptível (é aritmética, não chamada de modelo).
BOOTSTRAP_N = 2000
# Semente fixa: o intervalo tem de ser o mesmo entre duas execuções sobre os
# mesmos dados, ou vira mais uma fonte de variação para explicar.
BOOTSTRAP_SEED = 20260830


# ── estatística ──────────────────────────────────────────────────────────────


def mean_absolute_error(a: Sequence[float], b: Sequence[float]) -> float:
    if not a:
        return 0.0
    return sum(abs(x - y) for x, y in zip(a, b, strict=True)) / len(a)


def pearson(a: Sequence[float], b: Sequence[float]) -> float:
    """Correlação linear. `0.0` quando um dos lados é constante.

    Constante acontece de verdade: um juiz que dá 0,9 para tudo, ou um conjunto
    rotulado só com casos bons. Nos dois casos a correlação é indefinida, e
    devolver 0 diz a coisa certa — não há ordem a comparar.
    """
    n = len(a)
    if n < 2:
        return 0.0
    ma, mb = statistics.fmean(a), statistics.fmean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True))
    da = sum((x - ma) ** 2 for x in a)
    db = sum((y - mb) ** 2 for y in b)
    if da == 0 or db == 0:
        return 0.0
    return num / ((da**0.5) * (db**0.5))


def cohen_kappa(a: Sequence[bool], b: Sequence[bool]) -> float:
    """Concordância binária descontada do acaso.

    `1.0` = concordância perfeita, `0.0` = igual ao acaso, negativo = pior que o
    acaso. A correção importa porque num conjunto com 90% de casos bons um juiz
    que aprova tudo acerta 90% — e kappa mostra que ele não sabe nada.
    """
    n = len(a)
    if n == 0:
        return 0.0
    concordam = sum(1 for x, y in zip(a, b, strict=True) if x == y)
    po = concordam / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    if pe >= 1.0:
        # Os dois lados constantes e iguais: concordância trivial, sem
        # informação. Reportar 1.0 aqui seria mentir sobre o que foi medido.
        return 0.0
    return (po - pe) / (1 - pe)


def bootstrap_ci(
    valores: Sequence[float], *, confianca: float = 0.95, n: int = BOOTSTRAP_N
) -> tuple[float, float]:
    """Intervalo percentil da média, por reamostragem com reposição."""
    if not valores:
        return (0.0, 0.0)
    if len(valores) == 1:
        return (float(valores[0]), float(valores[0]))
    rng = random.Random(BOOTSTRAP_SEED)
    tamanho = len(valores)
    medias = sorted(statistics.fmean(rng.choices(valores, k=tamanho)) for _ in range(n))
    cauda = (1.0 - confianca) / 2.0
    baixo = medias[int(cauda * n)]
    alto = medias[min(n - 1, int((1.0 - cauda) * n))]
    return (round(baixo, 4), round(alto, 4))


# ── calibração ───────────────────────────────────────────────────────────────


@dataclass(slots=True)
class Calibration:
    """Reta `humano ≈ slope × juiz + intercept`, com o que a sustenta.

    `n` e `mae_after` andam junto com os coeficientes de propósito: usar uma
    calibração sem saber em quantos pontos ela foi ajustada é trocar um número
    sem contexto por outro.
    """

    metric: str
    slope: float = 1.0
    intercept: float = 0.0
    n: int = 0
    mae_before: float = 0.0
    mae_after: float = 0.0
    pearson: float = 0.0
    kappa: float = 0.0
    # Desvio médio do próprio juiz entre execuções repetidas — o piso de ruído.
    self_consistency_sd: float = 0.0
    ci_low: float = 0.0
    ci_high: float = 0.0

    def apply(self, valor: float) -> float:
        return max(0.0, min(1.0, self.slope * valor + self.intercept))

    @property
    def usable(self) -> bool:
        """Calibração ajustada em pouca coisa é registro, não corretor.

        Abaixo de 8 pontos a reta acompanha o ruído do próprio conjunto, e
        aplicá-la piora a nota em vez de melhorar. O objeto continua sendo
        gravado — o que ele não faz é corrigir nada em silêncio.
        """
        return self.n >= 8


def fit_calibration(metric: str, juiz: Sequence[float], humano: Sequence[float]) -> Calibration:
    """Mínimos quadrados de `humano` sobre `juiz`, com as métricas de acordo."""
    n = len(juiz)
    calibracao = Calibration(metric=metric, n=n)
    if n == 0:
        return calibracao

    calibracao.mae_before = round(mean_absolute_error(juiz, humano), 4)
    calibracao.pearson = round(pearson(juiz, humano), 4)
    calibracao.kappa = round(
        cohen_kappa(
            [v >= LIMIAR_APROVACAO for v in juiz],
            [v >= LIMIAR_APROVACAO for v in humano],
        ),
        4,
    )

    mj, mh = statistics.fmean(juiz), statistics.fmean(humano)
    var = sum((x - mj) ** 2 for x in juiz)
    if var > 0 and n >= 2:
        cov = sum((x - mj) * (y - mh) for x, y in zip(juiz, humano, strict=True))
        calibracao.slope = round(cov / var, 4)
        calibracao.intercept = round(mh - calibracao.slope * mj, 4)
    else:
        # Juiz constante: não há inclinação a estimar, mas o viés médio ainda é
        # corrigível — e corrigir só o viés é honesto sobre o que os dados dão.
        calibracao.slope = 0.0
        calibracao.intercept = round(mh, 4)

    corrigido = [calibracao.apply(v) for v in juiz]
    calibracao.mae_after = round(mean_absolute_error(corrigido, humano), 4)
    erros = [abs(x - y) for x, y in zip(corrigido, humano, strict=True)]
    calibracao.ci_low, calibracao.ci_high = bootstrap_ci(erros)
    return calibracao


# ── conjunto rotulado ────────────────────────────────────────────────────────


@dataclass(slots=True)
class LabeledCase:
    """Um caso julgado por humano.

    `answer` já vem escrita: o objetivo é medir o **juiz**, e regenerar a
    resposta a cada execução mediria o gerador junto, misturando as duas fontes
    de variação num número só.
    """

    id: str
    query: str
    answer: str
    context: list[str]
    faithfulness: float
    answer_relevance: float
    note: str = ""


def load_labels(path: Path) -> list[LabeledCase]:
    with path.open("r", encoding="utf-8") as fh:
        bruto = yaml.safe_load(fh) or {}
    casos: list[LabeledCase] = []
    for i, entrada in enumerate(bruto.get("cases") or []):
        casos.append(
            LabeledCase(
                id=str(entrada.get("id") or f"case-{i + 1}"),
                query=str(entrada["query"]),
                answer=str(entrada["answer"]),
                context=[str(c) for c in (entrada.get("context") or [])],
                faithfulness=float(entrada["faithfulness"]),
                answer_relevance=float(entrada["answer_relevance"]),
                note=str(entrada.get("note") or ""),
            )
        )
    return casos


# ── execução ─────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class JudgeReport:
    cases: int = 0
    repeats: int = 1
    unparseable: int = 0
    calibrations: dict[str, Calibration] = field(default_factory=dict)
    per_case: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cases": self.cases,
            "repeats": self.repeats,
            "unparseable": self.unparseable,
            "calibrations": {k: asdict(v) for k, v in self.calibrations.items()},
            "per_case": self.per_case,
        }


def _desvio(valores: Sequence[float]) -> float:
    return statistics.pstdev(valores) if len(valores) > 1 else 0.0


async def calibrate(
    engine: Any,
    casos: Sequence[LabeledCase],
    *,
    repeats: int = 3,
    source: str = "eval:judge",
) -> JudgeReport:
    """Julga cada caso `repeats` vezes e ajusta a calibração por métrica.

    Repetir mede a auto-concordância; a média das repetições é o que entra no
    ajuste, porque é ela que o consumidor da métrica veria numa execução única
    bem-comportada.
    """
    relatorio = JudgeReport(cases=len(casos), repeats=max(1, repeats))
    coletado: dict[str, tuple[list[float], list[float]]] = {m: ([], []) for m in METRICAS}
    ruido: dict[str, list[float]] = {m: [] for m in METRICAS}

    for caso in casos:
        execucoes: list[GenerationScore] = []
        for _ in range(relatorio.repeats):
            nota = await judge_generation(
                engine,
                query=caso.query,
                answer=caso.answer,
                context_blocks=caso.context,
                source=source,
            )
            if nota.unparseable:
                relatorio.unparseable += 1
            execucoes.append(nota)

        linha: dict[str, Any] = {"id": caso.id, "note": caso.note}
        for metrica in METRICAS:
            valores = [getattr(n, metrica) for n in execucoes]
            media = statistics.fmean(valores)
            rotulo = float(getattr(caso, metrica))
            coletado[metrica][0].append(media)
            coletado[metrica][1].append(rotulo)
            ruido[metrica].append(_desvio(valores))
            linha[metrica] = {
                "judge": round(media, 4),
                "human": rotulo,
                "sd": round(_desvio(valores), 4),
                "error": round(abs(media - rotulo), 4),
            }
        relatorio.per_case.append(linha)

    for metrica in METRICAS:
        juiz, humano = coletado[metrica]
        calibracao = fit_calibration(metrica, juiz, humano)
        calibracao.self_consistency_sd = round(statistics.fmean(ruido[metrica] or [0.0]), 4)
        relatorio.calibrations[metrica] = calibracao

    return relatorio


def load_calibration(path: Path) -> dict[str, Calibration]:
    """Lê o JSON gravado pelo CLI. Arquivo ausente = sem calibração.

    Ausência não é erro: a métrica crua continua existindo, só sem correção. O
    contrário — falhar a eval inteira porque ninguém rotulou nada ainda — seria
    transformar uma melhoria opcional em pré-requisito.
    """
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            bruto = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("evals.judge.calibration_unreadable", path=str(path), error=str(exc)[:200])
        return {}
    saida: dict[str, Calibration] = {}
    for metrica, dados in (bruto.get("calibrations") or {}).items():
        if metrica not in METRICAS:
            continue
        campos = {k: v for k, v in dados.items() if k in Calibration.__slots__}
        campos["metric"] = metrica
        saida[metrica] = Calibration(**campos)
    return saida


def apply_calibration(
    score: GenerationScore, calibracoes: dict[str, Calibration]
) -> GenerationScore:
    """Aplica a calibração utilizável, deixando o resto intacto."""
    faith = calibracoes.get("faithfulness")
    rel = calibracoes.get("answer_relevance")
    return GenerationScore(
        faithfulness=(
            faith.apply(score.faithfulness)
            if faith is not None and faith.usable
            else score.faithfulness
        ),
        answer_relevance=(
            rel.apply(score.answer_relevance)
            if rel is not None and rel.usable
            else score.answer_relevance
        ),
        rationale=score.rationale,
        unparseable=score.unparseable,
    )


# ── CLI ──────────────────────────────────────────────────────────────────────


def _resumo(relatorio: JudgeReport) -> str:
    linhas = [
        f"casos: {relatorio.cases}  repeticoes: {relatorio.repeats}  "
        f"ilegiveis: {relatorio.unparseable}",
    ]
    for metrica, cal in relatorio.calibrations.items():
        marca = "ok" if cal.usable else "poucos dados"
        linhas.append(
            f"  {metrica:<18} MAE {cal.mae_before:.3f} -> {cal.mae_after:.3f}  "
            f"IC95 [{cal.ci_low:.3f}, {cal.ci_high:.3f}]  "
            f"pearson {cal.pearson:+.3f}  kappa {cal.kappa:+.3f}  "
            f"ruido {cal.self_consistency_sd:.3f}  "
            f"reta {cal.slope:+.3f}x {cal.intercept:+.3f}  [{marca}]"
        )
    return "\n".join(linhas)


async def _julgar(casos: Sequence[LabeledCase], *, repeats: int) -> JudgeReport:
    # Import tardio: montar o `RouterEngine` puxa catálogo e preços, e quem só
    # quer `--help` não deveria pagar por isso.
    from eltanix.config import get_settings
    from eltanix.db.session import init_engine
    from eltanix.evals.runner import build_engine

    settings = get_settings()
    # O `RouterEngine` grava telemetria de custo em Postgres; sem engine de
    # banco inicializada a primeira chamada estoura.
    init_engine(settings.database_url)
    return await calibrate(build_engine(settings), casos, repeats=repeats)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="eltanix-eval-judge",
        description="Mede a concordancia do juiz de geracao com rotulos humanos e ajusta a calibracao.",
    )
    parser.add_argument(
        "--labels",
        default=os.getenv("ELTANIX_JUDGE_LABELS", "config/judge_labels.yaml"),
        help="YAML com os casos rotulados por humano",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=3,
        help="Quantas vezes julgar cada caso (mede a auto-concordancia)",
    )
    parser.add_argument("--out", default="", help="Grava o relatorio/calibracao em JSON")
    parser.add_argument("--json", action="store_true", help="Imprime o relatorio em JSON")
    args = parser.parse_args()

    from eltanix.config import get_settings

    caminho = Path(args.labels)
    if not caminho.is_absolute() and not caminho.exists():
        caminho = get_settings().config_dir / caminho.name
    casos = load_labels(caminho)
    if not casos:
        print(f"nenhum caso rotulado em {caminho}")
        return 1

    relatorio = asyncio.run(_julgar(casos, repeats=args.repeats))
    print(_resumo(relatorio))

    if args.out:
        destino = Path(args.out)
        destino.parent.mkdir(parents=True, exist_ok=True)
        with destino.open("w", encoding="utf-8") as fh:
            json.dump(relatorio.to_dict(), fh, indent=2, ensure_ascii=False)
        print(f"calibracao gravada em {destino}")

    if args.json:
        print(json.dumps(relatorio.to_dict(), ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
