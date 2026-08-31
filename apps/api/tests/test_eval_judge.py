"""Calibração e concordância do juiz de geração (`evals/judge.py`, item 47)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eltanix.evals.judge import (
    Calibration,
    apply_calibration,
    bootstrap_ci,
    calibrate,
    cohen_kappa,
    fit_calibration,
    load_calibration,
    load_labels,
    mean_absolute_error,
    pearson,
)
from eltanix.evals.ragas import GenerationScore

REPO = Path(__file__).resolve().parents[3]


# ── estatística ─────────────────────────────────────────────────────────────


def test_mae_e_pearson_em_acordo_perfeito():
    a = [0.1, 0.5, 0.9]
    assert mean_absolute_error(a, a) == 0.0
    assert pearson(a, a) == pytest.approx(1.0)


def test_pearson_com_lado_constante_e_zero():
    """Juiz que dá a mesma nota para tudo não tem ordem a comparar."""
    assert pearson([0.8, 0.8, 0.8], [0.0, 0.5, 1.0]) == 0.0


def test_pearson_captura_ordem_invertida():
    assert pearson([0.1, 0.5, 0.9], [0.9, 0.5, 0.1]) == pytest.approx(-1.0)


def test_kappa_desconta_o_acaso():
    """Juiz que aprova tudo num conjunto 90% bom acerta 90% e não sabe nada."""
    humano = [True] * 9 + [False]
    juiz = [True] * 10
    assert cohen_kappa(juiz, humano) == 0.0


def test_kappa_perfeito_com_as_duas_classes_presentes():
    assert cohen_kappa([True, False, True, False], [True, False, True, False]) == pytest.approx(1.0)


def test_kappa_negativo_quando_e_pior_que_o_acaso():
    assert cohen_kappa([True, False], [False, True]) < 0


def test_bootstrap_ci_e_deterministico_e_contem_a_media():
    valores = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
    primeiro = bootstrap_ci(valores)
    assert primeiro == bootstrap_ci(valores)
    assert primeiro[0] <= 0.35 <= primeiro[1]


def test_bootstrap_ci_com_um_ponto_e_degenerado():
    assert bootstrap_ci([0.4]) == (0.4, 0.4)


# ── ajuste da reta ──────────────────────────────────────────────────────────


def test_fit_calibration_corrige_o_viés_de_bondade():
    """O juiz comprime a faixa para cima; a reta desfaz a compressão."""
    juiz = [0.9, 0.85, 0.8, 0.75, 0.7, 0.65, 0.6, 0.55, 0.5, 0.95]
    humano = [1.0, 0.9, 0.8, 0.6, 0.5, 0.3, 0.2, 0.1, 0.0, 1.0]
    cal = fit_calibration("faithfulness", juiz, humano)
    assert cal.n == 10 and cal.usable
    assert cal.mae_after < cal.mae_before
    assert cal.slope > 1.0  # descomprime
    assert cal.ci_low <= cal.mae_after <= cal.ci_high


def test_fit_calibration_com_juiz_constante_corrige_so_o_viés():
    cal = fit_calibration("faithfulness", [0.8] * 10, [0.5] * 10)
    assert cal.slope == 0.0
    assert cal.intercept == pytest.approx(0.5)
    assert cal.apply(0.8) == pytest.approx(0.5)


def test_fit_calibration_vazia_nao_estoura():
    cal = fit_calibration("faithfulness", [], [])
    assert cal.n == 0 and not cal.usable and cal.apply(0.7) == pytest.approx(0.7)


def test_apply_clampa_na_faixa_valida():
    cal = Calibration(metric="faithfulness", slope=3.0, intercept=-1.0, n=20)
    assert cal.apply(1.0) == 1.0
    assert cal.apply(0.0) == 0.0


def test_calibracao_com_poucos_dados_nao_e_usable():
    """Uma reta ajustada em 3 pontos segue o ruído do próprio conjunto."""
    cal = fit_calibration("faithfulness", [0.9, 0.5, 0.1], [1.0, 0.5, 0.0])
    assert cal.n == 3 and not cal.usable


def test_apply_calibration_so_corrige_o_que_e_usable():
    score = GenerationScore(faithfulness=0.8, answer_relevance=0.8, rationale="x")
    calibracoes = {
        "faithfulness": Calibration(metric="faithfulness", slope=0.5, intercept=0.0, n=30),
        # n=2: registrada, mas não corrige.
        "answer_relevance": Calibration(metric="answer_relevance", slope=0.5, intercept=0.0, n=2),
    }
    corrigido = apply_calibration(score, calibracoes)
    assert corrigido.faithfulness == pytest.approx(0.4)
    assert corrigido.answer_relevance == pytest.approx(0.8)


def test_apply_calibration_sem_calibracao_devolve_o_bruto():
    score = GenerationScore(faithfulness=0.8, answer_relevance=0.3, rationale="x")
    corrigido = apply_calibration(score, {})
    assert (corrigido.faithfulness, corrigido.answer_relevance) == (0.8, 0.3)


# ── persistência ────────────────────────────────────────────────────────────


def test_load_calibration_ausente_nao_e_erro(tmp_path):
    """Ninguém rotulou nada ainda: métrica crua, não eval quebrada."""
    assert load_calibration(tmp_path / "nao-existe.json") == {}


def test_load_calibration_corrompida_degrada(tmp_path):
    caminho = tmp_path / "cal.json"
    caminho.write_text("{ isto nao e json", encoding="utf-8")
    assert load_calibration(caminho) == {}


def test_load_calibration_ida_e_volta(tmp_path):
    caminho = tmp_path / "cal.json"
    caminho.write_text(
        json.dumps(
            {
                "calibrations": {
                    "faithfulness": {"slope": 2.0, "intercept": -0.5, "n": 30},
                    "inventada": {"slope": 9.0},
                }
            }
        ),
        encoding="utf-8",
    )
    carregada = load_calibration(caminho)
    assert set(carregada) == {"faithfulness"}  # métrica desconhecida é ignorada
    assert carregada["faithfulness"].apply(0.8) == pytest.approx(1.0)


# ── conjunto rotulado versionado ────────────────────────────────────────────


def test_conjunto_rotulado_do_repo_carrega():
    casos = load_labels(REPO / "config" / "judge_labels.yaml")
    assert len(casos) >= 8, "abaixo de 8 a calibração não fica `usable`"
    assert all(c.context for c in casos)
    assert all(0.0 <= c.faithfulness <= 1.0 for c in casos)
    assert all(0.0 <= c.answer_relevance <= 1.0 for c in casos)
    assert len({c.id for c in casos}) == len(casos)


def test_conjunto_rotulado_cobre_os_dois_extremos():
    """Conjunto só com casos bons não mede discriminação nenhuma."""
    casos = load_labels(REPO / "config" / "judge_labels.yaml")
    assert any(c.faithfulness == 0.0 for c in casos)
    assert any(c.faithfulness == 1.0 for c in casos)
    assert any(c.answer_relevance == 0.0 for c in casos)


# ── execução ────────────────────────────────────────────────────────────────


class JuizFake:
    """Juiz com viés fixo e uma oscilação controlada entre execuções."""

    def __init__(self, *, vies: float = 0.2, oscilacao: float = 0.0) -> None:
        self.vies = vies
        self.oscilacao = oscilacao
        self.chamadas = 0

    async def complete(self, *, requested_model, params, source, **_):
        self.chamadas += 1
        # A "verdade" vai escondida na resposta que o caso carrega, para o juiz
        # falso conseguir errar de forma previsível em cima dela.
        texto = params["messages"][-1]["content"]
        alvo = 1.0 if "SUSTENTADA" in texto else 0.0
        deslocamento = self.oscilacao if self.chamadas % 2 == 0 else 0.0
        nota = max(0.0, min(1.0, alvo * (1 - self.vies) + self.vies + deslocamento))
        return type(
            "R",
            (),
            {
                "payload": {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "faithfulness": nota,
                                        "answer_relevance": nota,
                                        "rationale": "fake",
                                    }
                                )
                            }
                        }
                    ]
                }
            },
        )()


def _casos_sinteticos(n: int = 10):
    from eltanix.evals.judge import LabeledCase

    casos = []
    for i in range(n):
        sustentada = i % 2 == 0
        casos.append(
            LabeledCase(
                id=f"c{i}",
                query="pergunta",
                answer="resposta SUSTENTADA" if sustentada else "resposta inventada",
                context=["trecho"],
                faithfulness=1.0 if sustentada else 0.0,
                answer_relevance=1.0 if sustentada else 0.0,
            )
        )
    return casos


@pytest.mark.asyncio
async def test_calibrate_mede_o_viés_e_o_corrige():
    relatorio = await calibrate(JuizFake(vies=0.2), _casos_sinteticos(), repeats=1)
    assert relatorio.cases == 10 and relatorio.unparseable == 0
    cal = relatorio.calibrations["faithfulness"]
    # Viés de bondade: só levanta os casos ruins (0.0 -> 0.2); os bons já estão
    # no teto. Metade dos casos errando 0.2 dá MAE 0.1.
    assert cal.mae_before == pytest.approx(0.1, abs=0.01)
    assert cal.mae_after < 0.01
    assert cal.pearson == pytest.approx(1.0)
    assert cal.kappa == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_calibrate_registra_o_piso_de_ruido():
    """Um juiz que oscila entre execuções não detecta regressão menor que isso."""
    relatorio = await calibrate(JuizFake(vies=0.0, oscilacao=-0.1), _casos_sinteticos(4), repeats=2)
    assert relatorio.calibrations["faithfulness"].self_consistency_sd > 0.0


@pytest.mark.asyncio
async def test_calibrate_conta_resposta_ilegivel_sem_estourar():
    class Ilegivel:
        async def complete(self, **_):
            return type("R", (), {"payload": {"choices": [{"message": {"content": "???"}}]}})()

    relatorio = await calibrate(Ilegivel(), _casos_sinteticos(3), repeats=1)
    assert relatorio.unparseable == 3
    assert relatorio.calibrations["faithfulness"].n == 3


@pytest.mark.asyncio
async def test_calibrate_relata_por_caso():
    relatorio = await calibrate(JuizFake(vies=0.3), _casos_sinteticos(2), repeats=1)
    assert [linha["id"] for linha in relatorio.per_case] == ["c0", "c1"]
    assert set(relatorio.per_case[0]["faithfulness"]) == {"judge", "human", "sd", "error"}
