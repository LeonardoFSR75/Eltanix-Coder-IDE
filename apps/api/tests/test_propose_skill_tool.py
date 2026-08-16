"""Testes da ferramenta propose_skill (Self-Improving Skills)."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sicoobito.agent.tools.base import RiskClass, ToolContext
from sicoobito.agent.tools.skills import propose_skill
from sicoobito.db.models import Skill
from sicoobito.skills.service import SkillService


def test_propose_skill_risk_class():
    assert propose_skill.risk == RiskClass.WRITE


@pytest.mark.asyncio
async def test_propose_skill_missing_parameters():
    ctx = MagicMock(spec=ToolContext)
    ctx.skills = MagicMock(spec=SkillService)

    resultado = await propose_skill.handler(
        ctx,
        {"name": "", "description": "", "system_prompt": ""},
    )
    assert resultado.ok is False
    assert "obrigatórios" in resultado.content


@pytest.mark.asyncio
async def test_propose_skill_success(tmp_path: Path):
    ws_dir = tmp_path / "meu_projeto"
    ws_dir.mkdir()

    mock_skill = Skill(
        id=MagicMock(),
        name="padrao-fastapi-router",
        description="Convenção para rotas no FastAPI",
        category="learned",
        system_prompt="Sempre use APIRouter com prefixo /api.",
        parameters_json="{}",
    )

    mock_service = AsyncMock(spec=SkillService)
    mock_service.propose_and_save.return_value = mock_skill

    ctx = MagicMock(spec=ToolContext)
    ctx.skills = mock_service
    ctx.workspace_root = ws_dir

    resultado = await propose_skill.handler(
        ctx,
        {
            "name": "padrao-fastapi-router",
            "description": "Convenção para rotas no FastAPI",
            "system_prompt": "Sempre use APIRouter com prefixo /api.",
            "category": "learned",
            "rationale": "Padrão recorrente nos módulos api/routes",
        },
    )

    assert resultado.ok is True
    assert "padrao-fastapi-router" in resultado.content
    assert "Motivo: Padrão recorrente nos módulos api/routes" in resultado.content

    mock_service.propose_and_save.assert_called_once_with(
        name="padrao-fastapi-router",
        description="Convenção para rotas no FastAPI",
        category="learned",
        system_prompt="Sempre use APIRouter com prefixo /api.",
        workspace_root=ws_dir,
    )


from contextlib import asynccontextmanager


@pytest.mark.asyncio
async def test_skill_service_propose_and_save_writes_file(tmp_path: Path, monkeypatch):
    @asynccontextmanager
    async def _fake_session_scope():
        yield None

    async def _fake_create_skill(
        session, *, name, description, category, system_prompt, parameters_json
    ):
        return Skill(
            id=MagicMock(),
            name=name,
            description=description,
            category=category,
            system_prompt=system_prompt,
            parameters_json=parameters_json,
        )

    from sicoobito.skills import service as skills_service_module

    monkeypatch.setattr(skills_service_module, "session_scope", _fake_session_scope)
    monkeypatch.setattr(skills_service_module.store, "create_skill", _fake_create_skill)

    service = SkillService()
    ws_dir = tmp_path / "repo_teste"
    ws_dir.mkdir()

    skill = await service.propose_and_save(
        name="padrao-teste",
        description="Teste de gravação no arquivo",
        category="learned",
        system_prompt="Diretriz de teste",
        workspace_root=ws_dir,
    )

    assert skill is not None
    assert skill.name == "padrao-teste"

    skill_file = ws_dir / ".sicoobito" / "skills" / "padrao-teste.md"
    assert skill_file.exists()
    conteudo = skill_file.read_text(encoding="utf-8")
    assert "name: padrao-teste" in conteudo
    assert "Diretriz de teste" in conteudo


@pytest.mark.asyncio
async def test_skill_service_get_by_name_found(monkeypatch):
    @asynccontextmanager
    async def _fake_session_scope():
        yield None

    esperada = Skill(
        id=MagicMock(),
        name="revisor-python",
        description="Revisa código Python",
        category="learned",
        system_prompt="Você revisa código Python com rigor.",
        parameters_json="{}",
    )

    async def _fake_get_skill_by_name(session, name):
        assert name == "revisor-python"
        return esperada

    from sicoobito.skills import service as skills_service_module

    monkeypatch.setattr(skills_service_module, "session_scope", _fake_session_scope)
    monkeypatch.setattr(
        skills_service_module.store, "get_skill_by_name", _fake_get_skill_by_name
    )

    service = SkillService()
    resultado = await service.get_by_name("revisor-python")
    assert resultado is esperada


@pytest.mark.asyncio
async def test_skill_service_get_by_name_not_found(monkeypatch):
    @asynccontextmanager
    async def _fake_session_scope():
        yield None

    async def _fake_get_skill_by_name(session, name):
        return None

    from sicoobito.skills import service as skills_service_module

    monkeypatch.setattr(skills_service_module, "session_scope", _fake_session_scope)
    monkeypatch.setattr(
        skills_service_module.store, "get_skill_by_name", _fake_get_skill_by_name
    )

    service = SkillService()
    resultado = await service.get_by_name("nao-existe")
    assert resultado is None

