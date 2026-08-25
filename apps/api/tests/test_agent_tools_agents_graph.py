"""Ferramentas de orquestração multiagente (`agent/tools/agents_graph.py`):
classificação de risco, teto de fork-bomb, e o caminho fail-closed sem
coordenador (ver ADR 0004).
"""

from __future__ import annotations

import pytest

from eltanix.agent.coordinator import AgentCoordinator
from eltanix.agent.tools import RiskClass, ToolContext, registry
from eltanix.agent.tools.agents_graph import (
    agent_finish as _agent_finish_tool,
)
from eltanix.agent.tools.agents_graph import (
    send_message_to_agent as _send_message_tool,
)
from eltanix.agent.tools.agents_graph import (
    spawn_agent as _spawn_agent_tool,
)
from eltanix.agent.tools.agents_graph import (
    stop_agent as _stop_agent_tool,
)
from eltanix.agent.tools.agents_graph import (
    view_agent_graph as _view_agent_graph_tool,
)
from eltanix.agent.tools.agents_graph import (
    wait_for_agents as _wait_for_agents_tool,
)
from eltanix.workspace.fs import WorkspaceFS

spawn_agent = _spawn_agent_tool.handler
view_agent_graph = _view_agent_graph_tool.handler
send_message_to_agent = _send_message_tool.handler
wait_for_agents = _wait_for_agents_tool.handler
agent_finish = _agent_finish_tool.handler
stop_agent = _stop_agent_tool.handler


class _FakeRedis:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.sets: dict[str, set[str]] = {}
        self.lists: dict[str, list[str]] = {}
        self.strings: dict[str, str] = {}

    def pipeline(self):
        return _FakePipeline(self)

    async def hset(self, name, key=None, value=None, mapping=None):
        self.hashes.setdefault(name, {})
        if mapping:
            self.hashes[name].update(mapping)
        if key is not None:
            self.hashes[name][key] = value
        return 1

    async def hget(self, name, key):
        return self.hashes.get(name, {}).get(key)

    async def hgetall(self, name):
        return dict(self.hashes.get(name, {}))

    async def expire(self, name, ttl):
        return True

    async def sadd(self, name, *values):
        self.sets.setdefault(name, set()).update(values)
        return len(values)

    async def smembers(self, name):
        return set(self.sets.get(name, set()))

    async def exists(self, name):
        return int(
            name in self.hashes or name in self.sets or name in self.lists or name in self.strings
        )

    async def rpush(self, name, value):
        self.lists.setdefault(name, []).append(value)
        return len(self.lists[name])

    async def lpop(self, name, count=None):
        itens = self.lists.get(name, [])
        if not itens:
            return None
        if count is None:
            return itens.pop(0)
        retirados, self.lists[name] = itens[:count], itens[count:]
        return retirados or None

    async def blpop(self, keys, timeout):  # noqa: ASYNC109 - espelha a assinatura real do redis-py
        for chave in keys:
            itens = self.lists.get(chave, [])
            if itens:
                return chave, itens.pop(0)
        return None

    async def set(self, name, value, ex=None):
        self.strings[name] = value
        return True


class _FakePipeline:
    def __init__(self, redis: _FakeRedis) -> None:
        self._redis = redis
        self._ops: list[tuple] = []

    def hset(self, *args, **kwargs):
        self._ops.append(("hset", args, kwargs))
        return self

    def expire(self, *args, **kwargs):
        self._ops.append(("expire", args, kwargs))
        return self

    def sadd(self, *args, **kwargs):
        self._ops.append(("sadd", args, kwargs))
        return self

    async def execute(self):
        resultados = []
        for nome, args, kwargs in self._ops:
            resultados.append(await getattr(self._redis, nome)(*args, **kwargs))
        self._ops = []
        return resultados


@pytest.fixture
def coordinator():
    return AgentCoordinator(_FakeRedis(), ttl_seconds=60)


@pytest.fixture
def ctx(tmp_path, coordinator):
    return ToolContext(
        session_id="pai",
        workspace_root=tmp_path,
        fs=WorkspaceFS(tmp_path),
        coordinator=coordinator,
        max_spawn_depth=3,
        max_children_per_agent=4,
        max_wait_seconds=300.0,
    )


def _ctx_sem_coordenador(tmp_path):
    return ToolContext(session_id="pai", workspace_root=tmp_path, fs=WorkspaceFS(tmp_path))


# ── Classificação de risco ──────────────────────────────────────────────────


def test_spawn_agent_and_stop_agent_require_approval():
    for nome in ("spawn_agent", "stop_agent"):
        ferramenta = registry.get(nome)
        assert ferramenta is not None
        assert ferramenta.risk is RiskClass.WRITE
        assert ferramenta.risk.requires_approval is True


def test_coordination_tools_are_read():
    for nome in (
        "view_agent_graph",
        "send_message_to_agent",
        "wait_for_agents",
        "agent_finish",
    ):
        ferramenta = registry.get(nome)
        assert ferramenta is not None
        assert ferramenta.risk is RiskClass.READ
        assert ferramenta.risk.requires_approval is False


# ── spawn_agent ──────────────────────────────────────────────────────────────


async def test_spawn_agent_fails_without_coordinator(tmp_path):
    resultado = await spawn_agent(_ctx_sem_coordenador(tmp_path), {"task": "x"})
    assert resultado.ok is False
    assert "indisponível" in resultado.content.lower()


async def test_spawn_agent_requires_task(ctx):
    async def _spawn(**kwargs):
        raise AssertionError("não deveria ser chamado sem task")

    ctx.spawn_child_agent = _spawn
    resultado = await spawn_agent(ctx, {})
    assert resultado.ok is False


async def test_spawn_agent_calls_closure_and_returns_child_id(ctx):
    chamadas = []

    async def _spawn(*, task, display_name, specialization_prompt=None):
        chamadas.append((task, display_name, specialization_prompt))
        return "filho-123"

    ctx.spawn_child_agent = _spawn
    resultado = await spawn_agent(ctx, {"task": "investigar bug X"})
    assert resultado.ok is True
    assert resultado.data["child_session_id"] == "filho-123"
    assert chamadas == [("investigar bug X", "investigar bug X", None)]


class _FakeSkill:
    def __init__(self, *, system_prompt: str, enabled: bool = True) -> None:
        self.system_prompt = system_prompt
        self.enabled = enabled


class _FakeSkillsService:
    def __init__(self, skills: dict[str, _FakeSkill]) -> None:
        self._skills = skills

    async def get_by_name(self, name: str) -> _FakeSkill | None:
        return self._skills.get(name)


async def test_spawn_agent_with_skill_name_passes_specialization_prompt(ctx):
    ctx.skills = _FakeSkillsService(
        {"revisor-python": _FakeSkill(system_prompt="Você revisa código Python com rigor.")}
    )
    chamadas = []

    async def _spawn(*, task, display_name, specialization_prompt=None):
        chamadas.append(specialization_prompt)
        return "filho-123"

    ctx.spawn_child_agent = _spawn
    resultado = await spawn_agent(
        ctx, {"task": "revisar PR #42", "skill_name": "revisor-python"}
    )
    assert resultado.ok is True
    assert chamadas == ["Você revisa código Python com rigor."]


async def test_spawn_agent_fails_for_unknown_skill_name(ctx):
    ctx.skills = _FakeSkillsService({})

    async def _spawn(**kwargs):
        raise AssertionError("não deveria ser chamado — skill desconhecida")

    ctx.spawn_child_agent = _spawn
    resultado = await spawn_agent(ctx, {"task": "x", "skill_name": "nao-existe"})
    assert resultado.ok is False
    assert "desconhecida" in resultado.content.lower()


async def test_spawn_agent_fails_for_disabled_skill(ctx):
    ctx.skills = _FakeSkillsService(
        {"skill-desabilitada": _FakeSkill(system_prompt="x", enabled=False)}
    )

    async def _spawn(**kwargs):
        raise AssertionError("não deveria ser chamado — skill desabilitada")

    ctx.spawn_child_agent = _spawn
    resultado = await spawn_agent(ctx, {"task": "x", "skill_name": "skill-desabilitada"})
    assert resultado.ok is False
    assert "desabilitada" in resultado.content.lower()


async def test_spawn_agent_fails_when_skills_service_unavailable(ctx):
    ctx.skills = None

    async def _spawn(**kwargs):
        raise AssertionError("não deveria ser chamado — skills indisponíveis")

    ctx.spawn_child_agent = _spawn
    resultado = await spawn_agent(ctx, {"task": "x", "skill_name": "qualquer"})
    assert resultado.ok is False
    assert "indisponíveis" in resultado.content.lower()


async def test_spawn_agent_refuses_beyond_max_depth(ctx):
    ctx.max_spawn_depth = 0  # já na profundidade máxima (raiz conta como 0)

    async def _spawn(**kwargs):
        raise AssertionError("não deveria ser chamado — profundidade máxima atingida")

    ctx.spawn_child_agent = _spawn
    resultado = await spawn_agent(ctx, {"task": "x"})
    assert resultado.ok is False
    assert "profundidade" in resultado.content.lower()


async def test_spawn_agent_refuses_beyond_max_children(ctx):
    ctx.max_children_per_agent = 1
    await ctx.coordinator.register(session_id="pai", display_name="Pai", parent_id=None, depth=0)
    await ctx.coordinator.register(
        session_id="filho-ja-existente", display_name="F1", parent_id="pai", depth=1
    )

    async def _spawn(**kwargs):
        raise AssertionError("não deveria ser chamado — limite já atingido")

    ctx.spawn_child_agent = _spawn
    resultado = await spawn_agent(ctx, {"task": "mais um"})
    assert resultado.ok is False
    assert "limite" in resultado.content.lower()


# ── view_agent_graph ─────────────────────────────────────────────────────────


async def test_view_agent_graph_fails_without_coordinator(tmp_path):
    resultado = await view_agent_graph(_ctx_sem_coordenador(tmp_path), {})
    assert resultado.ok is False


async def test_view_agent_graph_renders_tree(ctx):
    await ctx.coordinator.register(session_id="pai", display_name="Pai", parent_id=None, depth=0)
    await ctx.coordinator.register(
        session_id="filho", display_name="Filho", parent_id="pai", depth=1
    )

    resultado = await view_agent_graph(ctx, {})
    assert resultado.ok is True
    assert "Pai" in resultado.content
    assert "Filho" in resultado.content
    assert "← você" in resultado.content


# ── send_message_to_agent ───────────────────────────────────────────────────


async def test_send_message_fails_without_coordinator(tmp_path):
    resultado = await send_message_to_agent(
        _ctx_sem_coordenador(tmp_path), {"target_agent_id": "x", "message": "oi"}
    )
    assert resultado.ok is False


async def test_send_message_refuses_self(ctx):
    resultado = await send_message_to_agent(ctx, {"target_agent_id": "pai", "message": "oi"})
    assert resultado.ok is False
    assert "si mesmo" in resultado.content.lower()


async def test_send_message_fails_for_unknown_target(ctx):
    resultado = await send_message_to_agent(
        ctx, {"target_agent_id": "nao-existe", "message": "oi"}
    )
    assert resultado.ok is False


async def test_send_message_wakes_target(ctx):
    await ctx.coordinator.register(session_id="pai", display_name="Pai", parent_id=None, depth=0)
    await ctx.coordinator.register(
        session_id="filho", display_name="Filho", parent_id="pai", depth=1
    )

    acordados = []

    async def _wake(target_session_id):
        acordados.append(target_session_id)
        return True

    ctx.wake_agent = _wake
    resultado = await send_message_to_agent(ctx, {"target_agent_id": "filho", "message": "oi"})
    assert resultado.ok is True
    assert acordados == ["filho"]

    mensagens = await ctx.coordinator.consume_pending("filho")
    assert mensagens[0]["content"] == "oi"


# ── wait_for_agents ──────────────────────────────────────────────────────────


async def test_wait_for_agents_fails_without_coordinator(tmp_path):
    resultado = await wait_for_agents(_ctx_sem_coordenador(tmp_path), {})
    assert resultado.ok is False


async def test_wait_for_agents_caps_timeout_at_server_max(ctx, monkeypatch):
    ctx.max_wait_seconds = 1.0
    capturado = {}

    async def _fake_wait(session_id, *, timeout_seconds):
        capturado["timeout"] = timeout_seconds
        return []

    monkeypatch.setattr(ctx.coordinator, "wait_for_message", _fake_wait)
    await wait_for_agents(ctx, {"timeout_seconds": 9999})
    assert capturado["timeout"] == 1.0


async def test_wait_for_agents_returns_messages(ctx):
    await ctx.coordinator.register(session_id="pai", display_name="Pai", parent_id=None, depth=0)
    await ctx.coordinator.send(from_id="filho", to_id="pai", content="terminei")

    resultado = await wait_for_agents(ctx, {"timeout_seconds": 1})
    assert resultado.ok is True
    assert len(resultado.data["messages"]) == 1
    assert "terminei" in resultado.content


# ── agent_finish ─────────────────────────────────────────────────────────────


async def test_agent_finish_without_parent(ctx):
    resultado = await agent_finish(ctx, {"result_summary": "feito"})
    assert resultado.ok is True
    assert resultado.data["finished"] is True
    assert "feito" in resultado.content


async def test_agent_finish_reports_to_parent_and_wakes_it(ctx):
    ctx.session_id = "filho"
    ctx.parent_session_id = "pai"
    await ctx.coordinator.register(session_id="pai", display_name="Pai", parent_id=None, depth=0)
    await ctx.coordinator.register(
        session_id="filho", display_name="Filho", parent_id="pai", depth=1
    )

    acordados = []

    async def _wake(target_session_id):
        acordados.append(target_session_id)
        return True

    ctx.wake_agent = _wake
    resultado = await agent_finish(ctx, {"result_summary": "encontrei o bug em x.py"})
    assert resultado.ok is True
    assert resultado.data["reported_to_parent"] is True
    assert acordados == ["pai"]

    mensagens = await ctx.coordinator.consume_pending("pai")
    assert "encontrei o bug" in mensagens[0]["content"]


# ── stop_agent ───────────────────────────────────────────────────────────────


async def test_stop_agent_fails_without_coordinator(tmp_path):
    resultado = await stop_agent(_ctx_sem_coordenador(tmp_path), {"target_agent_id": "x"})
    assert resultado.ok is False


async def test_stop_agent_refuses_self(ctx):
    resultado = await stop_agent(ctx, {"target_agent_id": "pai"})
    assert resultado.ok is False


async def test_stop_agent_marks_target_stopped(ctx):
    await ctx.coordinator.register(
        session_id="filho", display_name="Filho", parent_id=None, depth=0
    )
    resultado = await stop_agent(ctx, {"target_agent_id": "filho", "reason": "saiu do rumo"})
    assert resultado.ok is True
    assert await ctx.coordinator.is_stopped("filho") is True
