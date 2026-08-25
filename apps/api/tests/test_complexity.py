"""Roteamento por complexidade.

O maior desperdício numa plataforma agêntica não é prompt inchado — é mandar
para o modelo caro trabalho que um modelo pequeno resolve.
"""

from __future__ import annotations

from novaai_studio.optimizer.complexity import Complexity, classify


def _user(texto: str) -> list[dict]:
    return [{"role": "user", "content": texto}]


def test_utility_sources_go_to_the_cheap_profile():
    for origem in ("indexer", "search", "commit-message"):
        veredito = classify(messages=_user("qualquer coisa"), source=origem)
        assert veredito.complexity is Complexity.TRIVIAL
        assert veredito.profile == "utility"


def test_requests_with_tools_are_always_complex():
    # Ferramentas disponíveis significam um loop agêntico, não uma pergunta.
    veredito = classify(
        messages=_user("oi"),
        tools=[{"type": "function", "function": {"name": "read_file"}}],
    )
    assert veredito.complexity is Complexity.COMPLEXA
    assert veredito.profile == "coding"


def test_code_change_requests_are_complex():
    for pedido in (
        "refatore o adaptador do Databricks",
        "implemente o tratamento de rate limit",
        "corrija o bug do fallback",
        "escreva testes para a policy",
        "otimize a consulta de métricas",
        "adicione um campo em request_log",
    ):
        assert classify(messages=_user(pedido)).complexity is Complexity.COMPLEXA, pedido


def test_portuguese_imperatives_are_recognized():
    # O imperativo é a forma que o usuário digita ao dar uma ordem, e ele altera
    # o radical: "corrigir" vira "corrija" (g→j), "migrar" vira "migre". Um
    # radical ingênuo perderia justamente os casos mais comuns.
    for pedido in ("corrija o teste", "migre para a nova API", "ajuste o timeout"):
        assert classify(messages=_user(pedido)).complexity is Complexity.COMPLEXA, pedido


def test_mechanical_tasks_are_trivial():
    veredito = classify(messages=_user("gere a mensagem de commit para este diff"))
    assert veredito.complexity is Complexity.TRIVIAL
    assert veredito.profile == "utility"


def test_complex_wins_over_trivial_when_both_hints_appear():
    # "resuma o refactor que fizemos" tem as duas pistas; a que importa é a
    # mais exigente.
    veredito = classify(messages=_user("resuma o refactor que implementamos ontem"))
    assert veredito.complexity is Complexity.COMPLEXA


def test_large_prompts_are_complex_regardless_of_wording():
    grande = "contexto irrelevante " * 3000
    veredito = classify(messages=_user(grande))
    assert veredito.complexity is Complexity.COMPLEXA
    assert "prompt grande" in veredito.reason


def test_medium_questions_use_the_balanced_profile():
    # Uma pergunta conceitual de tamanho razoável não é trabalho mecânico nem
    # alteração de código.
    veredito = classify(
        messages=_user(
            "Como o circuit breaker decide abrir o circuito e quanto tempo "
            "dura o cooldown? Explique a lógica de backoff usada. " * 8
        )
    )
    assert veredito.complexity is Complexity.SIMPLES
    assert veredito.profile == "auto"


def test_very_short_prompts_are_trivial_even_without_hints():
    assert classify(messages=_user("qual a versão?")).complexity is Complexity.TRIVIAL


def test_every_verdict_carries_a_reason():
    # O motivo aparece no log: sem ele, um roteamento inesperado é impossível
    # de investigar.
    for origem in ("unknown", "indexer"):
        assert classify(messages=_user("oi"), source=origem).reason
