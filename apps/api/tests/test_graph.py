"""Schemas de ferramenta por modo (`agent/graph.py`).

`_tool_schemas` é a fronteira que decide o que o modelo pode chamar — os
testes aqui não sobem o grafo inteiro (isso exigiria um RouterEngine de
verdade), só verificam a função pura que decide o schema, o mesmo padrão dos
testes de `registry.schemas` em test_agent_tools.py.
"""

from __future__ import annotations

from sicoobito.agent.graph import _para_api, _tool_schemas


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
