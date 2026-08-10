"""Sobe o grafo compilado de verdade (não só as funções puras de
`agent/graph.py` que `test_graph.py` cobre) para provar o que a arquitetura
promete: uma tool `READ` vai direto para `act`, uma tool `WRITE`/`EXEC` para
em `interrupt()` e só executa depois de uma aprovação explícita — e negar a
aprovação não executa nada. Sem isso, nada garantia que o `RiskClass` de uma
tool realmente barra a execução no grafo, só que ele decide o schema exposto
ao modelo (o que `test_graph.py` já cobre).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from sicoobito.agent.approval_policy import ApprovalPolicy, EditPathRule, ExecCommandRule
from sicoobito.agent.graph import build_graph
from sicoobito.agent.tools import ToolContext
from sicoobito.workspace.fs import WorkspaceFS


@dataclass
class _FakeUsage:
    total_tokens: int = 10


@dataclass
class _FakeResult:
    payload: dict
    usage: _FakeUsage = field(default_factory=_FakeUsage)
    cost_usd: Decimal = Decimal("0")


def _tool_call_response(call_id: str, tool_name: str, arguments: dict) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": tool_name, "arguments": json.dumps(arguments)},
                        }
                    ],
                }
            }
        ]
    }


_FINISHED_RESPONSE = {
    "choices": [{"message": {"role": "assistant", "content": "pronto", "tool_calls": None}}]
}


class FakeRouterEngine:
    """Só implementa `.complete()` — devolve as respostas na ordem passada,
    uma por chamada. `graph.py::think()` não usa mais nada do RouterEngine
    real."""

    def __init__(self, respostas: list[dict]) -> None:
        self._respostas = list(respostas)
        self.chamadas = 0

    async def complete(self, *, requested_model, params, source, project_slug=None):
        self.chamadas += 1
        payload = self._respostas.pop(0)
        return _FakeResult(payload=payload)


@pytest.fixture
def ctx(tmp_path):
    return ToolContext(
        session_id="teste-integracao",
        workspace_root=tmp_path,
        fs=WorkspaceFS(tmp_path),
    )


def _initial_state(session_id: str) -> dict:
    return {
        "messages": [{"role": "user", "content": "tarefa de teste"}],
        "session_id": session_id,
        "mode": "agent",
        "iterations": 0,
        "max_iterations": 25,
        "finished": False,
        "files_changed": [],
        "total_cost_usd": 0.0,
        "total_tokens": 0,
    }


async def test_read_tool_runs_direto_sem_passar_por_approve(ctx, tmp_path):
    (tmp_path / "foo.py").write_text("print(1)\n", encoding="utf-8")

    engine = FakeRouterEngine(
        [
            _tool_call_response("call1", "read_file", {"path": "foo.py"}),
            _FINISHED_RESPONSE,
        ]
    )
    compilado = build_graph(engine, ctx).compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "t-read"}}

    nos_visitados: list[str] = []
    entrada = _initial_state("t-read")
    async for evento in compilado.astream(entrada, config=config, stream_mode="updates"):
        nos_visitados.extend(evento.keys())

    assert "approve" not in nos_visitados, "tool READ não deveria passar pelo nó de aprovação"
    assert "act" in nos_visitados

    estado_final = await compilado.aget_state(config)
    assert not estado_final.tasks, "sem WRITE/EXEC pendente, o grafo não deveria ficar interrompido"

    mensagens_tool = [
        m
        for m in estado_final.values["messages"]
        if m.get("role") == "tool" and m.get("name") == "read_file"
    ]
    assert len(mensagens_tool) == 1
    assert mensagens_tool[0]["ok"] is True


async def test_write_tool_para_em_interrupt_e_so_executa_apos_aprovacao(ctx, tmp_path):
    alvo = tmp_path / "bar.py"
    engine = FakeRouterEngine(
        [
            _tool_call_response("call1", "write_file", {"path": "bar.py", "content": "x = 1\n"}),
            _FINISHED_RESPONSE,
        ]
    )
    compilado = build_graph(engine, ctx).compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "t-write"}}

    entrada = _initial_state("t-write")
    async for _ in compilado.astream(entrada, config=config, stream_mode="updates"):
        pass  # o generator para sozinho quando bate no interrupt

    estado_pausado = await compilado.aget_state(config)
    assert estado_pausado.tasks, "tool WRITE deveria deixar o grafo interrompido"
    assert not alvo.exists(), "act() não pode ter rodado antes da aprovação"

    async for _ in compilado.astream(
        Command(resume={"call1": {"approved": True, "reason": ""}}),
        config=config,
        stream_mode="updates",
    ):
        pass

    estado_final = await compilado.aget_state(config)
    assert not estado_final.tasks
    assert alvo.exists(), "act() deveria ter rodado depois da aprovação"
    assert alvo.read_text(encoding="utf-8") == "x = 1\n"


async def test_write_tool_rejeitado_nao_executa(ctx, tmp_path):
    alvo = tmp_path / "baz.py"
    engine = FakeRouterEngine(
        [
            _tool_call_response("call1", "write_file", {"path": "baz.py", "content": "x = 1\n"}),
            _FINISHED_RESPONSE,
        ]
    )
    compilado = build_graph(engine, ctx).compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "t-reject"}}

    entrada = _initial_state("t-reject")
    async for _ in compilado.astream(entrada, config=config, stream_mode="updates"):
        pass

    async for _ in compilado.astream(
        Command(resume={"call1": {"approved": False, "reason": "não agora"}}),
        config=config,
        stream_mode="updates",
    ):
        pass

    assert not alvo.exists(), "recusar a aprovação não pode deixar o arquivo ser escrito"

    estado_final = await compilado.aget_state(config)
    mensagens_tool = [
        m
        for m in estado_final.values["messages"]
        if m.get("role") == "tool" and m.get("name") == "write_file"
    ]
    assert len(mensagens_tool) == 1
    assert mensagens_tool[0]["ok"] is False
    assert "recusou" in mensagens_tool[0]["content"] or "não agora" in mensagens_tool[0]["content"]


# ── Política de auto-aprovação: WRITE/EXEC que casa nunca vê interrupt ──────


async def test_write_tool_auto_approved_by_policy_skips_interrupt(ctx, tmp_path):
    ctx.approval_policy = ApprovalPolicy(
        rules=[EditPathRule(tools=["write_file"], path_glob="*.py", max_changed_lines=50)]
    )
    alvo = tmp_path / "bar.py"
    engine = FakeRouterEngine(
        [
            _tool_call_response("call1", "write_file", {"path": "bar.py", "content": "x = 1\n"}),
            _FINISHED_RESPONSE,
        ]
    )
    compilado = build_graph(engine, ctx).compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "t-auto-write"}}

    nos_visitados: list[str] = []
    entrada = _initial_state("t-auto-write")
    async for evento in compilado.astream(entrada, config=config, stream_mode="updates"):
        nos_visitados.extend(evento.keys())

    assert "approve" in nos_visitados, "o nó approve roda mesmo quando tudo auto-aprova"
    estado_final = await compilado.aget_state(config)
    assert not estado_final.tasks, "política deveria ter liberado sem pausar em interrupt"
    assert alvo.exists(), "act() deveria ter rodado sem esperar aprovação humana"
    assert alvo.read_text(encoding="utf-8") == "x = 1\n"


async def test_write_tool_outside_policy_glob_still_pauses(ctx, tmp_path):
    # Mesma política do teste acima, mas o arquivo não bate no glob — precisa
    # continuar pausando normalmente, prova que a política não libera tudo.
    ctx.approval_policy = ApprovalPolicy(
        rules=[EditPathRule(tools=["write_file"], path_glob="*.md", max_changed_lines=50)]
    )
    alvo = tmp_path / "bar.py"
    engine = FakeRouterEngine(
        [_tool_call_response("call1", "write_file", {"path": "bar.py", "content": "x = 1\n"})]
    )
    compilado = build_graph(engine, ctx).compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "t-not-auto"}}

    entrada = _initial_state("t-not-auto")
    async for _ in compilado.astream(entrada, config=config, stream_mode="updates"):
        pass

    estado_pausado = await compilado.aget_state(config)
    assert estado_pausado.tasks, "arquivo fora do glob não deveria auto-aprovar"
    assert not alvo.exists()


async def test_exec_tool_auto_approved_by_policy_skips_interrupt(ctx):
    ctx.approval_policy = ApprovalPolicy(
        rules=[ExecCommandRule(allowed_prefixes=["echo hello"])]
    )
    engine = FakeRouterEngine(
        [
            _tool_call_response("call1", "run_command", {"command": "echo hello"}),
            _FINISHED_RESPONSE,
        ]
    )
    compilado = build_graph(engine, ctx).compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "t-auto-exec"}}

    nos_visitados: list[str] = []
    entrada = _initial_state("t-auto-exec")
    async for evento in compilado.astream(entrada, config=config, stream_mode="updates"):
        nos_visitados.extend(evento.keys())

    estado_final = await compilado.aget_state(config)
    assert not estado_final.tasks, "comando EXEC dentro do prefixo permitido não deveria pausar"

    mensagens_tool = [
        m
        for m in estado_final.values["messages"]
        if m.get("role") == "tool" and m.get("name") == "run_command"
    ]
    assert len(mensagens_tool) == 1
    # Sem sandbox no fixture, a ferramenta falha ao executar de verdade — o
    # ponto do teste é que ela CHEGOU a rodar sem esperar aprovação humana,
    # não que o comando teve sucesso.
    assert "Sandbox indisponível" in mensagens_tool[0]["content"]


async def test_exec_tool_with_dangerous_characters_still_pauses_despite_prefix(ctx):
    # Mesmo prefixo permitido do teste anterior, mas com `;` anexado — a
    # regra tem que recusar e deixar isso parar em interrupt como qualquer
    # EXEC normal, mesmo caso adversarial coberto em test_approval_policy.py,
    # agora validado no grafo compilado de verdade.
    ctx.approval_policy = ApprovalPolicy(
        rules=[ExecCommandRule(allowed_prefixes=["echo hello"])]
    )
    engine = FakeRouterEngine(
        [_tool_call_response("call1", "run_command", {"command": "echo hello; rm -rf /"})]
    )
    compilado = build_graph(engine, ctx).compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "t-exec-danger"}}

    entrada = _initial_state("t-exec-danger")
    async for _ in compilado.astream(entrada, config=config, stream_mode="updates"):
        pass

    estado_pausado = await compilado.aget_state(config)
    assert estado_pausado.tasks, "comando com caractere perigoso não pode auto-aprovar"


# ── Segunda opinião automática (Fase C) ─────────────────────────────────────


def _interrupt_payload(estado):
    for tarefa in estado.tasks:
        for interrupcao in getattr(tarefa, "interrupts", []) or []:
            return interrupcao.value
    raise AssertionError("nenhuma interrupção encontrada no estado")


async def test_second_opinion_note_attached_when_enabled(ctx, tmp_path):
    ctx.approval_policy = ApprovalPolicy(second_opinion=True)  # sem regra de auto-aprovação
    engine = FakeRouterEngine(
        [
            _tool_call_response("call1", "write_file", {"path": "bar.py", "content": "x = 1\n"}),
            {"choices": [{"message": {"content": "VEREDITO: APROVADO\nMudança pequena e segura."}}]},
        ]
    )
    compilado = build_graph(engine, ctx).compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "t-second-opinion"}}

    entrada = _initial_state("t-second-opinion")
    async for _ in compilado.astream(entrada, config=config, stream_mode="updates"):
        pass

    estado_pausado = await compilado.aget_state(config)
    assert estado_pausado.tasks, "ainda precisa de aprovação humana — segunda opinião é consultiva"
    payload = _interrupt_payload(estado_pausado)
    pendente = payload["actions"][0]
    assert pendente["review"]["verdict"] == "approved"
    assert "Mudança pequena" in pendente["review"]["summary"]
    # 2 chamadas ao engine: a de think() pedindo a tool_call, e a da revisão
    # — nenhuma terceira, porque o grafo ainda está pausado esperando humano.
    assert engine.chamadas == 2


async def test_second_opinion_failure_marks_unavailable_not_approved(ctx, tmp_path):
    ctx.approval_policy = ApprovalPolicy(second_opinion=True)

    class _FailingReviewEngine(FakeRouterEngine):
        async def complete(self, *, requested_model, params, source, project_slug=None):
            if source == "agent:pre_approval_review":
                raise RuntimeError("modelo de revisão fora do ar")
            return await super().complete(
                requested_model=requested_model, params=params, source=source
            )

    engine = _FailingReviewEngine(
        [_tool_call_response("call1", "write_file", {"path": "bar.py", "content": "x = 1\n"})]
    )
    compilado = build_graph(engine, ctx).compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "t-second-opinion-fail"}}

    entrada = _initial_state("t-second-opinion-fail")
    async for _ in compilado.astream(entrada, config=config, stream_mode="updates"):
        pass

    estado_pausado = await compilado.aget_state(config)
    payload = _interrupt_payload(estado_pausado)
    pendente = payload["actions"][0]
    assert pendente["review"]["verdict"] == "unavailable"


async def test_second_opinion_disabled_by_default_adds_no_review_note(ctx, tmp_path):
    ctx.approval_policy = ApprovalPolicy()  # second_opinion=False, o default
    engine = FakeRouterEngine(
        [_tool_call_response("call1", "write_file", {"path": "bar.py", "content": "x = 1\n"})]
    )
    compilado = build_graph(engine, ctx).compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "t-no-second-opinion"}}

    entrada = _initial_state("t-no-second-opinion")
    async for _ in compilado.astream(entrada, config=config, stream_mode="updates"):
        pass

    estado_pausado = await compilado.aget_state(config)
    payload = _interrupt_payload(estado_pausado)
    pendente = payload["actions"][0]
    assert "review" not in pendente
    # Só 1 chamada ao engine (a de think()) — nenhuma chamada extra de
    # revisão quando a feature está desligada.
    assert engine.chamadas == 1


async def test_second_opinion_skipped_for_exec_tools(ctx):
    # run_command não tem diff — a revisão automática não roda pra EXEC,
    # mesmo com second_opinion ligado.
    ctx.approval_policy = ApprovalPolicy(second_opinion=True)
    engine = FakeRouterEngine(
        [_tool_call_response("call1", "run_command", {"command": "npm test"})]
    )
    compilado = build_graph(engine, ctx).compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "t-second-opinion-exec"}}

    entrada = _initial_state("t-second-opinion-exec")
    async for _ in compilado.astream(entrada, config=config, stream_mode="updates"):
        pass

    estado_pausado = await compilado.aget_state(config)
    payload = _interrupt_payload(estado_pausado)
    pendente = payload["actions"][0]
    assert "review" not in pendente
    assert engine.chamadas == 1
