"""`compose_system_prompt` (fonte única da composição, usada pelo grafo) e a
rota de debug `GET /api/agent/sessions/{id}/system-prompt` que a reusa.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from eltanix.agent.prompts import SYSTEM_PROMPT, compose_system_prompt
from eltanix.api.routes.agent import get_session_system_prompt


def test_compose_is_just_the_base_when_no_addenda():
    assert compose_system_prompt() == SYSTEM_PROMPT


def test_compose_appends_each_block_in_a_stable_order():
    # Sentinelas improváveis de colidir com o texto do SYSTEM_PROMPT base.
    out = compose_system_prompt(
        custom_instructions="§INSTR§",
        specialization_prompt="§ESPEC§",
        routed_skills_prompt="## Habilidades\n\n§SKILLS§",
        context_rules_prompt="## Regras\n\n§RULES§",
    )
    assert out.startswith(SYSTEM_PROMPT)
    assert (
        out.index("§INSTR§") < out.index("§ESPEC§") < out.index("§SKILLS§") < out.index("§RULES§")
    )
    assert "## Instruções do projeto\n\n§INSTR§" in out
    assert "## Especialização deste agente\n\n§ESPEC§" in out


def test_compose_skips_falsy_blocks():
    out = compose_system_prompt(custom_instructions="", context_rules_prompt="## R\n\n§RULES§")
    assert "Instruções do projeto" not in out
    assert out.endswith("## R\n\n§RULES§")


def test_compose_matches_what_build_graph_would_produce():
    """A rota de debug tem que devolver o MESMO texto que o grafo monta — se
    `build_graph` deixar de usar `compose_system_prompt`, este teste é o alarme."""
    import inspect

    from eltanix.agent import graph

    fonte = inspect.getsource(graph.build_graph)
    assert "compose_system_prompt(" in fonte


@pytest.mark.asyncio
async def test_debug_route_recomposes_from_session_context():
    ctx = SimpleNamespace(
        custom_instructions="use tabs",
        specialization_prompt=None,
        routed_skills_prompt="## Habilidades\n\nTDD",
        context_rules_prompt=None,
    )
    sessao = SimpleNamespace(context=ctx)
    runner = SimpleNamespace(get_session=lambda _sid: sessao)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(agent_runner=runner)))

    payload = await get_session_system_prompt("sess-xyz", request)  # type: ignore[arg-type]

    assert payload["session_id"] == "sess-xyz"
    assert payload["system_prompt"] == compose_system_prompt(
        custom_instructions="use tabs", routed_skills_prompt="## Habilidades\n\nTDD"
    )
    assert payload["length"] == len(payload["system_prompt"])
    assert payload["blocks"] == {
        "custom_instructions": True,
        "specialization_prompt": False,
        "routed_skills_prompt": True,
        "context_rules_prompt": False,
    }
