"""Schemas de ferramenta por modo (`agent/graph.py`).

`_tool_schemas` é a fronteira que decide o que o modelo pode chamar — os
testes aqui não sobem o grafo inteiro (isso exigiria um RouterEngine de
verdade), só verificam a função pura que decide o schema, o mesmo padrão dos
testes de `registry.schemas` em test_agent_tools.py.
"""

from __future__ import annotations

from sicoobito.agent.graph import (
    REPETITION_THRESHOLD,
    _is_stuck_repeat,
    _next_repetition_state,
    _para_api,
    _telemetry_span_name,
    _tool_fingerprint,
    _tool_schemas,
)


def _names(schemas: list[dict]) -> set[str]:
    return {s["function"]["name"] for s in schemas}


def test_ask_mode_ignores_has_plan_and_stays_read_only():
    for has_plan in (False, True):
        nomes = _names(_tool_schemas("ask", has_plan))
        assert "read_file" in nomes
        assert "write_file" not in nomes
        assert "run_command" not in nomes


def test_edit_mode_allows_write_but_not_exec():
    nomes = _names(_tool_schemas("edit", False))
    assert "edit_file" in nomes
    assert "run_command" not in nomes


def test_plan_mode_without_a_plan_yet_is_read_only_but_keeps_write_todos():
    # É o ponto central da correção: sem isto, o modelo podia pular direto
    # para editar/executar em "Modo Planejar" sem nunca mostrar um plano.
    nomes = _names(_tool_schemas("plan", False))
    assert "write_todos" in nomes
    assert "read_file" in nomes
    assert "write_file" not in nomes
    assert "edit_file" not in nomes
    assert "run_command" not in nomes
    assert "git_commit" not in nomes


def test_plan_mode_with_a_plan_already_gets_the_full_toolset():
    nomes = _names(_tool_schemas("plan", True))
    assert "write_file" in nomes
    assert "edit_file" in nomes
    assert "run_command" in nomes


def test_agent_and_auto_modes_get_the_full_toolset_regardless_of_plan():
    for modo in ("agent", "auto"):
        for has_plan in (False, True):
            nomes = _names(_tool_schemas(modo, has_plan))
            assert "run_command" in nomes
            assert "write_file" in nomes


# ── _para_api ────────────────────────────────────────────────────────────
#
# Regressão real: `data`/`ok` (Fase 1, para o card por tipo de ferramenta)
# viajavam dentro do mesmo dict enviado de volta ao provedor a cada turno —
# o Groq rejeita com 400 qualquer propriedade fora do schema numa mensagem
# `role: tool`, travando a sessão inteira depois da primeira ferramenta
# chamada (sem candidato que aceitasse a mensagem "suja", nenhum turno
# seguinte completava).


def test_para_api_strips_ui_only_fields_from_tool_messages():
    mensagens = [
        {"role": "system", "content": "prompt"},
        {"role": "user", "content": "tarefa"},
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "name": "read_file",
            "content": "conteúdo",
            "data": {"path": "a.py", "lines": 3},
            "ok": True,
        },
    ]

    limpas = _para_api(mensagens)

    assert limpas[0] == {"role": "system", "content": "prompt"}
    assert limpas[2] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "name": "read_file",
        "content": "conteúdo",
    }
    assert "data" not in limpas[2]
    assert "ok" not in limpas[2]


def test_para_api_keeps_tool_calls_field_on_assistant_messages():
    mensagens = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "read_file"}}],
        }
    ]

    limpas = _para_api(mensagens)

    assert limpas[0]["tool_calls"] == mensagens[0]["tool_calls"]


def test_para_api_filters_out_empty_assistant_messages():
    mensagens = [
        {"role": "user", "content": "olá"},
        {"role": "assistant", "content": "", "tool_calls": None},
        {"role": "user", "content": "continuar"},
    ]

    limpas = _para_api(mensagens)

    assert len(limpas) == 2
    assert [m["role"] for m in limpas] == ["user", "user"]



# ── Guard de repetição ──────────────────────────────────────────────────────
#
# Sem isto, um agente que tenta a mesma `edit_file` com os mesmos argumentos e
# falha repetidamente queima até DEFAULT_MAX_ITERATIONS rodadas antes de parar.
# As três funções são puras de propósito — testáveis sem subir o grafo nem um
# RouterEngine de verdade, mesmo padrão de `_tool_schemas`/`_para_api` acima.


def test_fingerprint_is_stable_regardless_of_argument_order():
    a = _tool_fingerprint("edit_file", {"path": "x.py", "old": "a", "new": "b"})
    b = _tool_fingerprint("edit_file", {"new": "b", "path": "x.py", "old": "a"})
    assert a == b


def test_fingerprint_differs_for_different_arguments():
    a = _tool_fingerprint("edit_file", {"path": "x.py"})
    b = _tool_fingerprint("edit_file", {"path": "y.py"})
    assert a != b


def test_is_stuck_repeat_false_below_threshold():
    fp = _tool_fingerprint("edit_file", {"path": "x.py"})
    assert _is_stuck_repeat(fp, fp, REPETITION_THRESHOLD - 1) is False


def test_is_stuck_repeat_true_at_threshold():
    fp = _tool_fingerprint("edit_file", {"path": "x.py"})
    assert _is_stuck_repeat(fp, fp, REPETITION_THRESHOLD) is True


def test_is_stuck_repeat_false_for_a_different_call():
    fp = _tool_fingerprint("edit_file", {"path": "x.py"})
    outra = _tool_fingerprint("edit_file", {"path": "y.py"})
    assert _is_stuck_repeat(fp, outra, REPETITION_THRESHOLD) is False


def test_next_repetition_state_clears_on_success():
    fp = _tool_fingerprint("run_command", {"command": "pytest"})
    assert _next_repetition_state(fp, True, fp, 2) == (None, 0)


def test_next_repetition_state_increments_on_identical_failure():
    fp = _tool_fingerprint("edit_file", {"path": "x.py"})
    assert _next_repetition_state(fp, False, fp, 1) == (fp, 2)


def test_next_repetition_state_restarts_on_a_different_failing_call():
    # O ciclo do modo Orquestra roda `run_command` várias vezes de propósito
    # entre edições — falhar em algo diferente não pode acumular na mesma
    # contagem, senão o guard travaria um fluxo legítimo.
    anterior = _tool_fingerprint("run_command", {"command": "pytest"})
    nova = _tool_fingerprint("edit_file", {"path": "x.py"})
    assert _next_repetition_state(nova, False, anterior, 2) == (nova, 1)


def test_telemetry_span_name_appends_sub_action_for_composite_tools():
    # Item 11 do plano de robustez do navegador interno: `browser_action`
    # (e outras ferramentas compostas com um campo `action`) não podem virar
    # um único span genérico na telemetria — impossível saber qual sub-ação
    # foi lenta ou falhou.
    assert (
        _telemetry_span_name("browser_action", {"action": "navigate", "url": "http://x"})
        == "browser_action.navigate"
    )
    assert (
        _telemetry_span_name("manage_packages", {"action": "install"})
        == "manage_packages.install"
    )


def test_telemetry_span_name_falls_back_to_tool_name_without_action_field():
    assert _telemetry_span_name("run_command", {"command": "pytest"}) == "run_command"
    assert _telemetry_span_name("edit_file", {}) == "edit_file"


def test_telemetry_span_name_ignores_non_identifier_action_values():
    # Um `action` que não pareça um identificador curto (ex.: veio de outro
    # campo por coincidência, ou é um valor arbitrário do modelo) não deve
    # virar sufixo do nome do span — evita span names inesperados/ilimitados.
    assert _telemetry_span_name("some_tool", {"action": "abre a URL http://x.com"}) == "some_tool"
    assert _telemetry_span_name("some_tool", {"action": 123}) == "some_tool"
    assert _telemetry_span_name("some_tool", {"action": "a" * 60}) == "some_tool"
