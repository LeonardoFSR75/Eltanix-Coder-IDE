"""Gate de qualidade de recuperação: a decisão de aprovar ou reprovar.

Separada da execução justamente para ser testável sem infraestrutura — é o
que permite o gate existir em CI.
"""

from __future__ import annotations

from eltanix.evals.gate import comparar

BASELINE = {
    "overall": {"cases": 10, "hit_rate": 0.80, "mrr": 0.70, "ndcg": 0.75},
    "by_source": {"context": {"cases": 10, "hit_rate": 0.80, "mrr": 0.70, "ndcg": 0.75}},
    "by_tag": {"rag": {"cases": 5, "hit_rate": 0.90, "mrr": 0.80, "ndcg": 0.85}},
}


def _relatorio(**overall):
    base = {"cases": 10, "hit_rate": 0.80, "mrr": 0.70, "ndcg": 0.75}
    base.update(overall)
    return {
        "overall": base,
        "by_source": {"context": {"cases": 10, "hit_rate": 0.80, "mrr": 0.70, "ndcg": 0.75}},
        "by_tag": {"rag": {"cases": 5, "hit_rate": 0.90, "mrr": 0.80, "ndcg": 0.85}},
    }


def test_relatorio_identico_ao_baseline_passa() -> None:
    assert comparar(BASELINE, _relatorio()) == []


def test_melhora_passa() -> None:
    assert comparar(BASELINE, _relatorio(hit_rate=0.95, mrr=0.90, ndcg=0.92)) == []


def test_queda_dentro_da_tolerancia_passa() -> None:
    # Recuperação tem ruído real (desempate do RRF); um gate que dispara com
    # meio ponto percentual vira ruído que todo mundo aprende a ignorar.
    assert comparar(BASELINE, _relatorio(hit_rate=0.79), tolerancia=0.02) == []


def test_queda_acima_da_tolerancia_reprova() -> None:
    regressoes = comparar(BASELINE, _relatorio(hit_rate=0.70), tolerancia=0.02)

    assert len(regressoes) == 1
    assert regressoes[0]["scope"] == "overall"
    assert regressoes[0]["metric"] == "hit_rate"
    assert regressoes[0]["delta"] < 0


def test_dataset_encolhido_reprova_mesmo_com_metrica_igual() -> None:
    """Sem isto, apagar os casos difíceis é o jeito mais fácil de passar."""
    regressoes = comparar(BASELINE, _relatorio(cases=6))

    assert [r["metric"] for r in regressoes] == ["cases"]
    assert "encolheu" in regressoes[0]["reason"]


def test_escopo_que_sumiu_reprova() -> None:
    relatorio = _relatorio()
    del relatorio["by_tag"]["rag"]

    regressoes = comparar(BASELINE, relatorio)

    assert [r["scope"] for r in regressoes] == ["by_tag:rag"]
    assert "sumiu" in regressoes[0]["reason"]


def test_escopo_novo_nao_reprova() -> None:
    """Não havia régua para ele — cobrar seria inventar um número."""
    relatorio = _relatorio()
    relatorio["by_tag"]["editor"] = {"cases": 3, "hit_rate": 0.1, "mrr": 0.1, "ndcg": 0.1}

    assert comparar(BASELINE, relatorio) == []


def test_regressao_em_uma_tag_com_media_geral_estavel() -> None:
    """O motivo de o gate olhar tag a tag: a média geral mal se mexe quando a
    recuperação cai só numa área."""
    relatorio = _relatorio()
    relatorio["by_tag"]["rag"] = {"cases": 5, "hit_rate": 0.50, "mrr": 0.40, "ndcg": 0.45}

    regressoes = comparar(BASELINE, relatorio)

    assert {r["metric"] for r in regressoes} == {"hit_rate", "mrr", "ndcg"}
    assert all(r["scope"] == "by_tag:rag" for r in regressoes)


def test_saida_do_gate_e_ascii() -> None:
    """O console do Windows usa cp1252 por padrão, onde a seta `→` não existe.
    Uma seta no `print` fazia o gate morrer com UnicodeEncodeError justamente
    no caminho de sucesso — o comando falhava sem nenhuma regressão real."""
    import inspect

    from eltanix.evals import gate

    fonte = inspect.getsource(gate.main)
    for linha in fonte.splitlines():
        if "print(" not in linha and not linha.strip().startswith(('f"', '"')):
            continue
        linha.encode("cp1252")  # levanta UnicodeEncodeError se voltar a escapar
