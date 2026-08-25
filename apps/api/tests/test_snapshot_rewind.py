"""Checkpoints/rewind de sessão (Fase 8 do upgrade do agente).

Duas coisas para provar, sem precisar de Postgres de verdade — mesmo truque
de `test_graph_integration.py`: `MemorySaver` implementa a mesma interface de
`BaseCheckpointSaver` que `AsyncPostgresSaver`, então `aget_state_history`/
`aupdate_state` funcionam idêntico nos dois.

1. `agent/graph.py::act()` grava um snapshot do conteúdo "antes" sempre que
   uma ferramenta WRITE roda, com a iteração certa (`test_graph_integration`
   já cobre RiskClass/aprovação — aqui só a gravação em si).
2. `AgentRunner.list_checkpoints`/`rewind_to` (chamados como função solta
   sobre um "self" falso — só usam `self._compiled_graph`/`self.snapshots`,
   então não precisam do `AgentRunner` real com todas as dependências
   pesadas do construtor) truncam o grafo e revertem arquivos corretamente.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver

from novaai_studio.agent.approval_policy import ApprovalPolicy, EditPathRule
from novaai_studio.agent.graph import build_graph
from novaai_studio.agent.runner import AgentRunner, AgentSession
from novaai_studio.agent.tools import ToolContext
from novaai_studio.workspace.fs import WorkspaceFS


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


def _finished_response(texto: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": texto, "tool_calls": None}}]}


class FakeRouterEngine:
    def __init__(self, respostas: list[dict]) -> None:
        self._respostas = list(respostas)

    async def complete(
        self, *, requested_model, params, source, project_slug=None, session_id=None
    ):
        return _FakeResult(payload=self._respostas.pop(0))


def _initial_state(session_id: str) -> dict:
    return {
        "messages": [{"role": "user", "content": "escreva a.py"}],
        "session_id": session_id,
        "mode": "agent",
        "iterations": 0,
        "max_iterations": 25,
        "finished": False,
        "files_changed": [],
        "total_cost_usd": 0.0,
        "total_tokens": 0,
    }


class _FakeSnapshotService:
    """Mesma semântica de `agent/snapshot_store.py::SnapshotService`
    (a versão real depende de Postgres para o `DISTINCT ON`), guardada em
    memória — o bastante para provar que `act()`/`rewind_to` chamam esta
    interface com os argumentos certos e reagem certo ao resultado."""

    def __init__(self) -> None:
        self.records: list[dict] = []

    async def record(self, *, session_id, iteration, path, content_before) -> None:
        self.records.append(
            {
                "session_id": session_id,
                "iteration": iteration,
                "path": path,
                "content_before": content_before,
            }
        )

    async def restore_targets(self, *, session_id, after_iteration):
        por_path: dict[str, dict] = {}
        for r in sorted(self.records, key=lambda r: r["iteration"]):
            if r["session_id"] != session_id or r["iteration"] <= after_iteration:
                continue
            por_path.setdefault(r["path"], r)
        return [
            type("FakeSnapshot", (), {"path": r["path"], "content_before": r["content_before"]})()
            for r in por_path.values()
        ]


@pytest.fixture
def ctx(tmp_path):
    return ToolContext(
        session_id="t-rewind",
        workspace_root=tmp_path,
        fs=WorkspaceFS(tmp_path),
        approval_policy=ApprovalPolicy(
            rules=[EditPathRule(tools=["write_file"], path_glob="*.py", max_changed_lines=200)]
        ),
    )


class _FakeRunner:
    """Só o suficiente de `AgentRunner` para `list_checkpoints`/`rewind_to`
    funcionarem — os dois métodos só tocam `self._compiled_graph(session)` e
    `self.snapshots`, então montar o `AgentRunner` de verdade (engine, sandbox,
    indexer...) seria peso morto para este teste."""

    _iteration_checkpoints = staticmethod(AgentRunner._iteration_checkpoints)

    def __init__(self, compilado, snapshots) -> None:
        self._compilado = compilado
        self.snapshots = snapshots

    async def _compiled_graph(self, session):
        return self._compilado


def _session(tmp_path: Path, ctx: ToolContext) -> AgentSession:
    return AgentSession(
        session_id=ctx.session_id,
        workspace_root=tmp_path,
        worktree_path=tmp_path,
        branch="",
        base_branch="main",
        mode="agent",
        task="escreva a.py",
        context=ctx,
    )


class TestActRecordsSnapshotBeforeWrite:
    async def test_records_content_before_write_file(self, ctx, tmp_path):
        ctx.snapshots = _FakeSnapshotService()
        # newline="" evita a tradução de "\n" para "\r\n" do modo texto no
        # Windows — sem isso o conteúdo gravado no disco (e lido de volta
        # pela ferramenta) não bate byte a byte com o literal do teste.
        (tmp_path / "a.py").write_text("v0\n", encoding="utf-8", newline="")

        engine = FakeRouterEngine(
            [
                _tool_call_response("call1", "write_file", {"path": "a.py", "content": "v1\n"}),
                _finished_response("pronto"),
            ]
        )
        compilado = build_graph(engine, ctx).compile(checkpointer=MemorySaver())
        config = {"configurable": {"thread_id": "t-snapshot"}}
        async for _ in compilado.astream(
            _initial_state("t-snapshot"), config=config, stream_mode="updates"
        ):
            pass

        assert len(ctx.snapshots.records) == 1
        gravado = ctx.snapshots.records[0]
        assert gravado["path"] == "a.py"
        assert gravado["content_before"] == "v0\n"
        assert gravado["iteration"] == 1

    async def test_no_snapshot_for_read_tools(self, ctx, tmp_path):
        ctx.snapshots = _FakeSnapshotService()
        (tmp_path / "a.py").write_text("v0\n", encoding="utf-8")

        engine = FakeRouterEngine(
            [
                _tool_call_response("call1", "read_file", {"path": "a.py"}),
                _finished_response("pronto"),
            ]
        )
        compilado = build_graph(engine, ctx).compile(checkpointer=MemorySaver())
        config = {"configurable": {"thread_id": "t-no-snapshot"}}
        async for _ in compilado.astream(
            _initial_state("t-no-snapshot"), config=config, stream_mode="updates"
        ):
            pass

        assert ctx.snapshots.records == []

    async def test_no_crash_without_snapshots_service(self, ctx, tmp_path):
        # ctx.snapshots continua None (default) — act() precisa rodar a
        # ferramenta normalmente mesmo sem serviço de snapshot configurado.
        engine = FakeRouterEngine(
            [
                _tool_call_response("call1", "write_file", {"path": "a.py", "content": "v1\n"}),
                _finished_response("pronto"),
            ]
        )
        compilado = build_graph(engine, ctx).compile(checkpointer=MemorySaver())
        config = {"configurable": {"thread_id": "t-sem-snapshot-service"}}
        async for _ in compilado.astream(
            _initial_state("t-sem-snapshot-service"), config=config, stream_mode="updates"
        ):
            pass

        assert (tmp_path / "a.py").read_text(encoding="utf-8") == "v1\n"


class TestListAndRewind:
    async def _run_two_turns(self, ctx, tmp_path):
        engine = FakeRouterEngine(
            [
                _tool_call_response("call1", "write_file", {"path": "a.py", "content": "v1\n"}),
                _finished_response("turno 1 pronto"),
                _tool_call_response("call2", "write_file", {"path": "a.py", "content": "v2\n"}),
                _finished_response("turno 2 pronto"),
            ]
        )
        compilado = build_graph(engine, ctx).compile(checkpointer=MemorySaver())
        config = {"configurable": {"thread_id": ctx.session_id}}

        async for _ in compilado.astream(
            _initial_state(ctx.session_id), config=config, stream_mode="updates"
        ):
            pass
        # Segundo turno: nova mensagem do usuário, retomando do checkpoint
        # existente (mesmo mecanismo que `AgentRunner.stream_run` usa para
        # continuar uma sessão já iniciada).
        async for _ in compilado.astream(
            {"messages": [{"role": "user", "content": "agora mude para v2"}], "finished": False},
            config=config,
            stream_mode="updates",
        ):
            pass
        return compilado

    async def test_list_checkpoints_returns_one_per_iteration(self, ctx, tmp_path):
        ctx.snapshots = _FakeSnapshotService()
        compilado = await self._run_two_turns(ctx, tmp_path)
        runner = _FakeRunner(compilado, ctx.snapshots)
        sessao = _session(tmp_path, ctx)

        pontos = await AgentRunner.list_checkpoints(runner, sessao)

        # `iterations` sobe uma vez por chamada a think() — 4 chamadas no
        # total (turno 1: tool-call + finish; turno 2: idem) mais o
        # checkpoint inicial (iteration=0, antes de qualquer think()).
        iteracoes = [p["iteration"] for p in pontos]
        assert iteracoes == [0, 1, 2, 3, 4], "cronológico, um por chamada a think()"

        por_iteracao = {p["iteration"]: p for p in pontos}
        # iteration=2: think() que encerrou o turno 1 ("turno 1 pronto",
        # sem tool_calls) — precisa aparecer como finalizado mesmo depois
        # do turno 2 já ter começado (é o bug que `_iteration_checkpoints`
        # corrige: sem o filtro de "última mensagem não é de usuário", a
        # fusão da mensagem do turno 2 rouba este checkpoint e zera `finished`).
        assert por_iteracao[2]["summary"] == "turno 1 pronto"
        assert por_iteracao[2]["finished"] is True
        # iteration=4: think() que encerrou o turno 2 — idem, fim de sessão.
        assert por_iteracao[4]["summary"] == "turno 2 pronto"
        assert por_iteracao[4]["finished"] is True
        # iteration=1/3: checkpoints pós-act() (escrita rodou, mas o
        # assistente ainda não respondeu nada com conteúdo) — não finalizados.
        assert por_iteracao[1]["finished"] is False
        assert por_iteracao[3]["finished"] is False

    async def test_rewind_restores_file_and_truncates_messages(self, ctx, tmp_path):
        ctx.snapshots = _FakeSnapshotService()
        compilado = await self._run_two_turns(ctx, tmp_path)
        assert (tmp_path / "a.py").read_text(encoding="utf-8") == "v2\n"

        runner = _FakeRunner(compilado, ctx.snapshots)
        sessao = _session(tmp_path, ctx)

        # iteration=2 é o fim do turno 1 (think() respondeu "turno 1 pronto",
        # sem tool_calls) — o ponto que um usuário clicaria em "restaurar
        # aqui" para desfazer o turno 2 inteiro, incluindo a segunda escrita
        # E a mensagem de usuário que pediu essa segunda escrita.
        resultado = await AgentRunner.rewind_to(runner, sessao, iteration=2)

        assert resultado["iteration"] == 2
        assert resultado["files_restored"] == ["a.py"]
        assert (tmp_path / "a.py").read_text(encoding="utf-8") == "v1\n"

        config = {"configurable": {"thread_id": ctx.session_id}}
        estado = await compilado.aget_state(config)
        assert estado.values["iterations"] == 2
        mensagens = estado.values["messages"]
        assert [m.get("role") for m in mensagens] == ["user", "assistant", "tool", "assistant"]
        assert mensagens[-1]["content"] == "turno 1 pronto"
        # A mensagem do usuário que abriu o turno 2 ("agora mude para v2")
        # precisa ter sido descartada pelo rewind, não só a resposta dela —
        # é exatamente o que quebrava antes do fix em `_iteration_checkpoints`.
        assert all("v2" not in (m.get("content") or "") for m in mensagens)

    async def test_rewind_unknown_iteration_raises(self, ctx, tmp_path):
        ctx.snapshots = _FakeSnapshotService()
        compilado = await self._run_two_turns(ctx, tmp_path)
        runner = _FakeRunner(compilado, ctx.snapshots)
        sessao = _session(tmp_path, ctx)

        with pytest.raises(ValueError):
            await AgentRunner.rewind_to(runner, sessao, iteration=99)

    async def test_rewind_without_checkpointer_raises_runtime_error(self, ctx, tmp_path):
        compilado = build_graph(FakeRouterEngine([]), ctx).compile()  # sem checkpointer
        runner = _FakeRunner(compilado, None)
        sessao = _session(tmp_path, ctx)

        with pytest.raises(RuntimeError):
            await AgentRunner.rewind_to(runner, sessao, iteration=1)

    async def test_list_checkpoints_empty_without_checkpointer(self, ctx, tmp_path):
        compilado = build_graph(FakeRouterEngine([]), ctx).compile()
        runner = _FakeRunner(compilado, None)
        sessao = _session(tmp_path, ctx)

        assert await AgentRunner.list_checkpoints(runner, sessao) == []
