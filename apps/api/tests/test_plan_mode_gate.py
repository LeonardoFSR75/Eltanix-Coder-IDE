"""Testes do gate humano em `write_todos` no modo Planejar/Orquestra (Fase 3 do
upgrade do agente, estilo Antigravity).

Cobre `_todos_risk` isoladamente, o encadeamento de `ToolContext` através de
`Tool.resolve_risk`, e o handler marcando `plan_registered` na primeira
chamada que de fato registra um plano.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sicoobito.agent.tools.base import RiskClass, ToolContext, ToolRegistry, tool
from sicoobito.agent.tools.plan import _todos_risk, write_todos
from sicoobito.workspace.fs import WorkspaceFS


def _ctx(tmp_path: Path, *, mode: str = "agent") -> ToolContext:
    return ToolContext(
        session_id="teste",
        workspace_root=tmp_path,
        fs=WorkspaceFS(tmp_path),
        mode=mode,
    )


ITENS_COM_CONTEUDO = [{"content": "fazer algo", "status": "pending"}]
ITENS_VAZIOS: list[dict[str, str]] = []


class TestTodosRiskFn:
    def test_read_when_context_missing(self):
        assert _todos_risk({"items": ITENS_COM_CONTEUDO}, None) is RiskClass.READ

    def test_read_outside_plan_and_orchestra_modes(self, tmp_path):
        ctx = _ctx(tmp_path, mode="agent")
        assert _todos_risk({"items": ITENS_COM_CONTEUDO}, ctx) is RiskClass.READ

    @pytest.mark.parametrize("modo", ["plan", "orchestra"])
    def test_write_on_first_non_empty_call_in_gated_modes(self, tmp_path, modo):
        ctx = _ctx(tmp_path, mode=modo)
        assert _todos_risk({"items": ITENS_COM_CONTEUDO}, ctx) is RiskClass.WRITE

    def test_read_when_items_empty_even_in_plan_mode(self, tmp_path):
        ctx = _ctx(tmp_path, mode="plan")
        assert _todos_risk({"items": ITENS_VAZIOS}, ctx) is RiskClass.READ

    def test_read_once_plan_already_registered(self, tmp_path):
        ctx = _ctx(tmp_path, mode="plan")
        ctx.session_state.plan_registered = True
        assert _todos_risk({"items": ITENS_COM_CONTEUDO}, ctx) is RiskClass.READ


class TestResolveRiskThreadsContext:
    def test_resolve_risk_passes_context_through_to_callable(self, tmp_path):
        registro = ToolRegistry()
        capturado: list[ToolContext | None] = []

        def _risk_fn(args, context):
            capturado.append(context)
            return RiskClass.READ

        async def _handler(ctx, args):  # pragma: no cover - não exercitado aqui
            raise AssertionError("não deveria rodar")

        ferramenta = registro.register(
            tool(
                name="ferramenta_teste",
                description="teste",
                risk=_risk_fn,
                parameters={"type": "object", "properties": {}},
            )(_handler)
        )

        ctx = _ctx(tmp_path, mode="plan")
        resultado = ferramenta.resolve_risk({}, ctx)

        assert resultado is RiskClass.READ
        assert capturado == [ctx]

    def test_base_risk_calls_callable_with_none_context(self, tmp_path):
        # `base_risk` decide o schema por modo (`_tool_schemas`) sem sessão
        # real — `write_todos` precisa continuar RiskClass.READ aqui, senão
        # some da lista de ferramentas disponível no modo Planejar antes do
        # plano existir.
        assert write_todos.base_risk is RiskClass.READ


class TestPlanRegisteredFlag:
    @pytest.mark.asyncio
    async def test_first_write_todos_in_plan_mode_sets_plan_registered(self, tmp_path):
        ctx = _ctx(tmp_path, mode="plan")
        assert ctx.session_state.plan_registered is False

        await write_todos.handler(ctx, {"items": ITENS_COM_CONTEUDO})

        assert ctx.session_state.plan_registered is True

    @pytest.mark.asyncio
    async def test_empty_items_in_plan_mode_does_not_set_plan_registered(self, tmp_path):
        ctx = _ctx(tmp_path, mode="plan")

        await write_todos.handler(ctx, {"items": ITENS_VAZIOS})

        assert ctx.session_state.plan_registered is False

    @pytest.mark.asyncio
    async def test_agent_mode_never_sets_plan_registered(self, tmp_path):
        ctx = _ctx(tmp_path, mode="agent")

        await write_todos.handler(ctx, {"items": ITENS_COM_CONTEUDO})

        assert ctx.session_state.plan_registered is False

    @pytest.mark.asyncio
    async def test_risk_drops_back_to_read_after_plan_registered(self, tmp_path):
        ctx = _ctx(tmp_path, mode="plan")

        primeira_chamada = _todos_risk({"items": ITENS_COM_CONTEUDO}, ctx)
        assert primeira_chamada is RiskClass.WRITE

        await write_todos.handler(ctx, {"items": ITENS_COM_CONTEUDO})

        segunda_chamada = _todos_risk(
            {"items": [{"content": "outra etapa", "status": "pending"}]}, ctx
        )
        assert segunda_chamada is RiskClass.READ
