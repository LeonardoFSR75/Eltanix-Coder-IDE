"""Testes dos modos customizáveis do agente (Fase 6 do upgrade do agente):
resolução em `AgentRunner._resolve_custom_mode`, gate de ferramentas em
`agent/graph.py::_tool_schemas`, e injeção do bloco de prompt em
`agent/prompts.py::build_task_prompt`.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from novaai_studio.agent.graph import _tool_schemas
from novaai_studio.agent.prompts import build_task_prompt
from novaai_studio.agent.runner import AgentRunner
from novaai_studio.agent.state import BUILTIN_MODES
from novaai_studio.agent.tools.base import ToolContext
from novaai_studio.workspace.fs import WorkspaceFS


def _make_runner(*, custom_modes) -> AgentRunner:
    return AgentRunner(
        settings=MagicMock(embedding_profile="embedding"),
        engine=MagicMock(),
        indexer=MagicMock(),
        sandboxes=MagicMock(),
        skills=None,
        custom_modes=custom_modes,
    )


class TestBuiltinModesConstant:
    def test_covers_the_seven_known_modes(self):
        assert BUILTIN_MODES == {
            "ask",
            "edit",
            "agent",
            "plan",
            "auto",
            "orchestra",
            "explore",
        }


class TestResolveCustomMode:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", sorted(BUILTIN_MODES))
    async def test_builtin_mode_never_resolves(self, modo):
        runner = _make_runner(custom_modes=AsyncMock())
        assert await runner._resolve_custom_mode(modo) == (None, None)
        runner.custom_modes.get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_custom_modes_service_returns_none(self):
        runner = _make_runner(custom_modes=None)
        assert await runner._resolve_custom_mode(str(uuid.uuid4())) == (None, None)

    @pytest.mark.asyncio
    async def test_invalid_uuid_returns_none(self):
        runner = _make_runner(custom_modes=AsyncMock())
        assert await runner._resolve_custom_mode("nao-e-um-uuid") == (None, None)
        runner.custom_modes.get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_id_returns_none(self):
        runner = _make_runner(custom_modes=AsyncMock())
        runner.custom_modes.get.return_value = None
        mode_id = uuid.uuid4()
        assert await runner._resolve_custom_mode(str(mode_id)) == (None, None)
        runner.custom_modes.get.assert_awaited_once_with(mode_id)

    @pytest.mark.asyncio
    async def test_lookup_failure_degrades_to_none(self):
        runner = _make_runner(custom_modes=AsyncMock())
        runner.custom_modes.get.side_effect = RuntimeError("banco fora do ar")
        assert await runner._resolve_custom_mode(str(uuid.uuid4())) == (None, None)

    @pytest.mark.asyncio
    async def test_resolved_mode_returns_tools_and_prompt(self):
        runner = _make_runner(custom_modes=AsyncMock())
        runner.custom_modes.get.return_value = SimpleNamespace(
            allowed_tools=["read_file", "search_code"],
            prompt_block="Revise só a camada de dados.",
        )
        allowed, prompt = await runner._resolve_custom_mode(str(uuid.uuid4()))
        assert allowed == ["read_file", "search_code"]
        assert prompt == "Revise só a camada de dados."

    @pytest.mark.asyncio
    async def test_empty_allowed_tools_list_is_preserved_not_none(self):
        # Lista vazia salva de propósito ("nenhuma ferramenta") precisa
        # continuar distinguível de "não resolvido" (None) — é isso que faz
        # `_tool_schemas` filtrar para nada em vez de cair no fallback.
        runner = _make_runner(custom_modes=AsyncMock())
        runner.custom_modes.get.return_value = SimpleNamespace(allowed_tools=[], prompt_block="")
        allowed, prompt = await runner._resolve_custom_mode(str(uuid.uuid4()))
        assert allowed == []
        assert prompt is None


class TestToolSchemasCustomMode:
    def _ctx(self, tmp_path, *, allowed_tools):
        return ToolContext(
            session_id="teste",
            workspace_root=tmp_path,
            fs=WorkspaceFS(tmp_path),
            custom_mode_allowed_tools=allowed_tools,
        )

    def test_unresolved_custom_mode_without_context_is_read_only(self):
        todas = {t["function"]["name"] for t in _tool_schemas("id-desconhecido", True, None)}
        somente_leitura = {t["function"]["name"] for t in _tool_schemas("ask", True, None)}
        assert todas == somente_leitura

    def test_unresolved_custom_mode_with_context_but_none_allowed_is_read_only(self, tmp_path):
        ctx = self._ctx(tmp_path, allowed_tools=None)
        resolvido = {t["function"]["name"] for t in _tool_schemas("id-qualquer", True, ctx)}
        somente_leitura = {t["function"]["name"] for t in _tool_schemas("ask", True, None)}
        assert resolvido == somente_leitura

    def test_resolved_custom_mode_filters_to_allowed_tools_only(self, tmp_path):
        ctx = self._ctx(tmp_path, allowed_tools=["read_file", "search_code"])
        nomes = {t["function"]["name"] for t in _tool_schemas("id-qualquer", True, ctx)}
        assert nomes == {"read_file", "search_code"}

    def test_resolved_custom_mode_with_empty_list_grants_nothing(self, tmp_path):
        ctx = self._ctx(tmp_path, allowed_tools=[])
        assert _tool_schemas("id-qualquer", True, ctx) == []

    def test_resolved_custom_mode_ignores_names_not_in_registry(self, tmp_path):
        ctx = self._ctx(tmp_path, allowed_tools=["read_file", "ferramenta_que_nao_existe"])
        nomes = {t["function"]["name"] for t in _tool_schemas("id-qualquer", True, ctx)}
        assert nomes == {"read_file"}

    def test_builtin_modes_unaffected_by_custom_mode_branch(self, tmp_path):
        ctx = self._ctx(tmp_path, allowed_tools=["read_file"])
        # Um modo embutido nunca deveria consultar `custom_mode_allowed_tools`,
        # mesmo que o contexto tenha um valor setado (não deveria acontecer na
        # prática, mas o branch de modo embutido tem que vir primeiro sempre).
        agente = {t["function"]["name"] for t in _tool_schemas("agent", True, ctx)}
        assert "write_file" in agente
        assert "run_command" in agente


class TestBuildTaskPromptCustomMode:
    def test_unresolved_custom_mode_adds_no_extra_section(self):
        prompt = build_task_prompt(
            "faça algo", mode="id-desconhecido", custom_mode_prompt_block=None
        )
        assert "MODO CUSTOMIZADO" not in prompt

    def test_resolved_custom_mode_injects_prompt_block(self):
        prompt = build_task_prompt(
            "faça algo",
            mode="id-qualquer",
            custom_mode_prompt_block="Revise só a camada de dados.",
        )
        assert "## 🧩 MODO CUSTOMIZADO ATIVO:" in prompt
        assert "Revise só a camada de dados." in prompt

    def test_builtin_mode_ignores_custom_mode_prompt_block(self):
        # Um modo embutido nunca deveria receber `custom_mode_prompt_block`
        # preenchido na prática (mode e o bloco resolvido vêm da mesma
        # resolução), mas o branch embutido precisa vencer se isso acontecer.
        prompt = build_task_prompt(
            "faça algo", mode="plan", custom_mode_prompt_block="não deveria aparecer"
        )
        assert "MODO PLANEJAR ATIVO" in prompt
        assert "não deveria aparecer" not in prompt
