"""Testes do roteamento automático de skills por embedding (Fase 1 do upgrade do agente).

Cobre as duas pontas: `SkillService.find_relevant` delegando pro store (mesmo padrão
de mock de `session_scope`/`store` já usado em `test_propose_skill_tool.py`), e
`AgentRunner._route_skills` degradando silenciosamente em cada caminho de falha.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from sicoobito.agent.runner import AgentRunner
from sicoobito.db.models import Skill
from sicoobito.skills.service import SkillService


@pytest.mark.asyncio
async def test_find_relevant_delegates_to_store(monkeypatch):
    @asynccontextmanager
    async def _fake_session_scope():
        yield None

    esperado = [
        Skill(
            id=MagicMock(),
            name="test-driven-development",
            description="Ciclo TDD: teste falha, implementa, teste passa.",
            category="engineering",
            system_prompt="Escreva o teste antes da implementação.",
            parameters_json="{}",
        )
    ]

    chamada = {}

    async def _fake_search_by_similarity(session, *, query_embedding, top_k, min_score):
        chamada["query_embedding"] = query_embedding
        chamada["top_k"] = top_k
        chamada["min_score"] = min_score
        return esperado

    from sicoobito.skills import service as skills_service_module

    monkeypatch.setattr(skills_service_module, "session_scope", _fake_session_scope)
    monkeypatch.setattr(
        skills_service_module.store, "search_by_similarity", _fake_search_by_similarity
    )

    service = SkillService()
    resultado = await service.find_relevant([0.1, 0.2, 0.3], top_k=2, min_score=0.72)

    assert resultado == esperado
    assert chamada == {"query_embedding": [0.1, 0.2, 0.3], "top_k": 2, "min_score": 0.72}


def _make_runner(*, skills: SkillService | None) -> AgentRunner:
    return AgentRunner(
        settings=MagicMock(embedding_profile="embedding"),
        engine=MagicMock(),
        indexer=MagicMock(),
        sandboxes=MagicMock(),
        skills=skills,
    )


@pytest.mark.asyncio
async def test_route_skills_empty_task_returns_none():
    runner = _make_runner(skills=MagicMock(spec=SkillService))
    assert await runner._route_skills("   ") is None


@pytest.mark.asyncio
async def test_route_skills_no_skill_service_returns_none():
    runner = _make_runner(skills=None)
    assert await runner._route_skills("escreva testes para o módulo X") is None


@pytest.mark.asyncio
async def test_route_skills_embed_failure_degrades_to_none():
    runner = _make_runner(skills=MagicMock(spec=SkillService))
    runner.engine.embed = AsyncMock(side_effect=RuntimeError("provedor de embedding fora do ar"))

    assert await runner._route_skills("escreva testes para o módulo X") is None


@pytest.mark.asyncio
async def test_route_skills_no_match_returns_none():
    runner = _make_runner(skills=AsyncMock(spec=SkillService))
    runner.engine.embed = AsyncMock(
        return_value=SimpleNamespace(payload={"data": [{"embedding": [0.1, 0.2]}]})
    )
    runner.skills.find_relevant.return_value = []

    assert await runner._route_skills("tarefa qualquer") is None


@pytest.mark.asyncio
async def test_route_skills_injects_matched_skill_section():
    runner = _make_runner(skills=AsyncMock(spec=SkillService))
    runner.engine.embed = AsyncMock(
        return_value=SimpleNamespace(payload={"data": [{"embedding": [0.1, 0.2]}]})
    )
    runner.skills.find_relevant.return_value = [
        Skill(
            id=MagicMock(),
            name="test-driven-development",
            description="Ciclo TDD.",
            category="engineering",
            system_prompt="Escreva o teste antes da implementação.",
            parameters_json="{}",
        )
    ]

    resultado = await runner._route_skills("escreva testes para o módulo X")

    assert resultado is not None
    assert "roteada automaticamente" in resultado
    assert "### test-driven-development (roteada automaticamente" in resultado
    assert "Escreva o teste antes da implementação." in resultado
    runner.skills.find_relevant.assert_awaited_once_with(
        [0.1, 0.2], top_k=AgentRunner._SKILLS_TOP_K, min_score=AgentRunner._SKILLS_MIN_SCORE
    )


@pytest.mark.asyncio
async def test_route_skills_slash_command_forces_skill_without_embedding_match():
    runner = _make_runner(skills=AsyncMock(spec=SkillService))
    runner.engine.embed = AsyncMock(
        return_value=SimpleNamespace(payload={"data": [{"embedding": [0.1, 0.2]}]})
    )
    runner.skills.get_by_name.return_value = Skill(
        id=MagicMock(),
        name="test-driven-development",
        description="Ciclo TDD.",
        category="engineering",
        system_prompt="Escreva o teste antes da implementação.",
        parameters_json="{}",
    )
    runner.skills.find_relevant.return_value = []

    resultado = await runner._route_skills("/test crie testes para o módulo X")

    assert resultado is not None
    assert "### test-driven-development (ativada por `/test`)" in resultado
    runner.skills.get_by_name.assert_awaited_once_with("test-driven-development")


@pytest.mark.asyncio
async def test_route_skills_forced_and_routed_skill_never_duplicate():
    runner = _make_runner(skills=AsyncMock(spec=SkillService))
    runner.engine.embed = AsyncMock(
        return_value=SimpleNamespace(payload={"data": [{"embedding": [0.1, 0.2]}]})
    )
    mesma_skill = Skill(
        id=MagicMock(),
        name="test-driven-development",
        description="Ciclo TDD.",
        category="engineering",
        system_prompt="Escreva o teste antes da implementação.",
        parameters_json="{}",
    )
    runner.skills.get_by_name.return_value = mesma_skill
    runner.skills.find_relevant.return_value = [mesma_skill]

    resultado = await runner._route_skills("/test crie testes para o módulo X")

    assert resultado is not None
    assert resultado.count("### test-driven-development") == 1
    assert "(ativada por `/test`)" in resultado
    assert "(roteada automaticamente" not in resultado


@pytest.mark.asyncio
async def test_route_skills_unrecognized_slash_command_falls_back_to_routing():
    runner = _make_runner(skills=AsyncMock(spec=SkillService))
    runner.engine.embed = AsyncMock(
        return_value=SimpleNamespace(payload={"data": [{"embedding": [0.1, 0.2]}]})
    )
    runner.skills.find_relevant.return_value = []

    resultado = await runner._route_skills("/naoexiste faça algo")

    assert resultado is None
    runner.skills.get_by_name.assert_not_awaited()


def _skill(name: str) -> Skill:
    return Skill(
        id=MagicMock(),
        name=name,
        description=f"descrição de {name}",
        category="engineering",
        system_prompt=f"processo de {name}",
        parameters_json="{}",
    )


@pytest.mark.asyncio
async def test_route_skills_plan_mode_forces_spec_and_planning_skills():
    runner = _make_runner(skills=AsyncMock(spec=SkillService))
    runner.engine.embed = AsyncMock(
        return_value=SimpleNamespace(payload={"data": [{"embedding": [0.1, 0.2]}]})
    )
    runner.skills.find_relevant.return_value = []
    runner.skills.get_by_name.side_effect = lambda nome: _skill(nome)

    resultado = await runner._route_skills("implemente uma feature nova", "plan")

    assert resultado is not None
    assert "### spec-driven-development (padrão do Modo Planejar)" in resultado
    assert "### planning-and-task-breakdown (padrão do Modo Planejar)" in resultado
    assert runner.skills.get_by_name.await_count == 2


@pytest.mark.asyncio
async def test_route_skills_non_plan_mode_does_not_force_spec_skills():
    runner = _make_runner(skills=AsyncMock(spec=SkillService))
    runner.engine.embed = AsyncMock(
        return_value=SimpleNamespace(payload={"data": [{"embedding": [0.1, 0.2]}]})
    )
    runner.skills.find_relevant.return_value = []

    resultado = await runner._route_skills("implemente uma feature nova", "agent")

    assert resultado is None
    runner.skills.get_by_name.assert_not_awaited()


@pytest.mark.asyncio
async def test_route_skills_plan_mode_slash_spec_does_not_duplicate_forced_skill():
    runner = _make_runner(skills=AsyncMock(spec=SkillService))
    runner.engine.embed = AsyncMock(
        return_value=SimpleNamespace(payload={"data": [{"embedding": [0.1, 0.2]}]})
    )
    runner.skills.find_relevant.return_value = []
    runner.skills.get_by_name.side_effect = lambda nome: _skill(nome)

    resultado = await runner._route_skills("/spec crie a especificação", "plan")

    assert resultado is not None
    assert resultado.count("### spec-driven-development") == 1
    assert "(ativada por `/spec`)" in resultado
    assert "### planning-and-task-breakdown (padrão do Modo Planejar)" in resultado
    # /spec já resolveu spec-driven-development — só falta buscar planning-and-task-breakdown.
    assert runner.skills.get_by_name.await_count == 2
