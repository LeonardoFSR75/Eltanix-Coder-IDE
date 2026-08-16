"""`AgentCoordinator`: registro, mensagens, árvore pai/filho e o caminho
fail-closed (`register()` devolvendo `False`) que `spawn_agent` depende para
recusar orquestração sem Redis — ver ADR 0004.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager

import pytest

from sicoobito.agent import session_store
from sicoobito.agent.coordinator import AgentCoordinator


def _session_id() -> str:
    return uuid.uuid4().hex[:12]


class _FakePipeline:
    def __init__(self, redis: "_FakeRedis") -> None:
        self._redis = redis
        self._ops: list[tuple[str, tuple, dict]] = []

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
            metodo = getattr(self._redis, nome)
            resultados.append(await metodo(*args, **kwargs))
        self._ops = []
        return resultados


class _FakeRedis:
    """Redis assíncrono mínimo o bastante pra exercitar `AgentCoordinator` —
    hash, set, list, string, com TTL só registrado (não expira de verdade)."""

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
            valor = itens.pop(0)
            return valor
        retirados, self.lists[name] = itens[:count], itens[count:]
        return retirados or None

    async def blpop(self, keys, timeout):
        # Sem bloqueio real de propósito: os testes que exercitam mensagem já
        # chegada não precisam de concorrência, e o teste de timeout mede o
        # comportamento do coordinator (retorna [] em vez de lançar), não o
        # tempo real de espera do Redis.
        for chave in keys:
            itens = self.lists.get(chave, [])
            if itens:
                valor = itens.pop(0)
                return chave, valor
        await asyncio.sleep(min(timeout, 0.05))
        return None

    async def set(self, name, value, ex=None):
        self.strings[name] = value
        return True


@pytest.fixture
def redis():
    return _FakeRedis()


@pytest.fixture
def coordinator(redis):
    return AgentCoordinator(redis, ttl_seconds=60)


# ── Fail-closed sem Redis ────────────────────────────────────────────────────


async def test_register_returns_false_without_redis():
    coordinator_sem_redis = AgentCoordinator(None)
    ok = await coordinator_sem_redis.register(
        session_id="s1", display_name="raiz", parent_id=None, depth=0
    )
    assert ok is False


async def test_other_methods_degrade_safely_without_redis():
    coordinator_sem_redis = AgentCoordinator(None)
    assert await coordinator_sem_redis.children_of("s1") == []
    assert await coordinator_sem_redis.depth_of("s1") == 0
    assert await coordinator_sem_redis.graph_snapshot("s1") == []
    assert await coordinator_sem_redis.send(from_id="a", to_id="b", content="oi") is False
    assert await coordinator_sem_redis.consume_pending("s1") == []
    assert await coordinator_sem_redis.wait_for_message("s1", timeout_seconds=0.1) == []
    assert await coordinator_sem_redis.is_stopped("s1") is False
    # não deve lançar
    await coordinator_sem_redis.set_status("s1", "completed")
    await coordinator_sem_redis.request_stop("s1")


# ── Registro e árvore ────────────────────────────────────────────────────────


async def test_register_root_has_no_parent(coordinator):
    ok = await coordinator.register(session_id="root", display_name="Raiz", parent_id=None, depth=0)
    assert ok is True
    assert await coordinator.depth_of("root") == 0
    assert await coordinator.children_of("root") == []


async def test_register_child_appears_in_parent_children(coordinator):
    await coordinator.register(session_id="root", display_name="Raiz", parent_id=None, depth=0)
    await coordinator.register(session_id="filho", display_name="Filho", parent_id="root", depth=1)

    assert await coordinator.children_of("root") == ["filho"]
    assert await coordinator.depth_of("filho") == 1


async def test_graph_snapshot_walks_the_whole_tree(coordinator):
    await coordinator.register(session_id="root", display_name="Raiz", parent_id=None, depth=0)
    await coordinator.register(session_id="filho1", display_name="F1", parent_id="root", depth=1)
    await coordinator.register(session_id="filho2", display_name="F2", parent_id="root", depth=1)
    await coordinator.register(session_id="neto", display_name="N1", parent_id="filho1", depth=2)

    nos = await coordinator.graph_snapshot("root")
    ids = {n.session_id for n in nos}
    assert ids == {"root", "filho1", "filho2", "neto"}

    raiz = next(n for n in nos if n.session_id == "root")
    assert set(raiz.children) == {"filho1", "filho2"}


async def test_graph_snapshot_unknown_root_is_empty(coordinator):
    assert await coordinator.graph_snapshot("nao-existe") == []


# ── Espelho Postgres (fallback quando o Redis está vazio) ──────────────────────
#
# Integração real — usa a fixture `pg_session` (`conftest.py`), pulada por
# padrão sem `DATABASE_URL_TEST`. Mesmo espírito de `test_session_store.py`:
# exercita a reconstrução da árvore a partir de `agent_session` de verdade,
# não de um fake.


async def test_graph_snapshot_falls_back_to_db_when_redis_is_empty(pg_session, monkeypatch):
    raiz_id = _session_id()
    filho_id = _session_id()
    await session_store.create(
        pg_session,
        session_id=raiz_id,
        project="proj",
        task="tarefa raiz",
        mode="agent",
        profile=None,
        branch=None,
        base_branch=None,
    )
    await session_store.create(
        pg_session,
        session_id=filho_id,
        project="proj",
        task="tarefa filho",
        mode="agent",
        profile=None,
        branch=None,
        base_branch=None,
        parent_session_id=raiz_id,
    )
    await pg_session.flush()

    @asynccontextmanager
    async def fake_session_scope():
        yield pg_session

    monkeypatch.setattr("sicoobito.agent.coordinator.session_scope", fake_session_scope)

    coordinator_sem_redis = AgentCoordinator(None)
    nos = await coordinator_sem_redis.graph_snapshot(raiz_id)

    ids = {n.session_id for n in nos}
    assert ids == {raiz_id, filho_id}

    raiz = next(n for n in nos if n.session_id == raiz_id)
    assert raiz.children == [filho_id]
    assert raiz.depth == 0
    assert raiz.parent_id is None

    filho = next(n for n in nos if n.session_id == filho_id)
    assert filho.depth == 1
    assert filho.parent_id == raiz_id
    assert filho.children == []


async def test_graph_snapshot_db_fallback_unknown_root_is_empty(pg_session, monkeypatch):
    @asynccontextmanager
    async def fake_session_scope():
        yield pg_session

    monkeypatch.setattr("sicoobito.agent.coordinator.session_scope", fake_session_scope)

    coordinator_sem_redis = AgentCoordinator(None)
    assert await coordinator_sem_redis.graph_snapshot("nao-existe") == []


# ── Status ───────────────────────────────────────────────────────────────────


async def test_set_status_updates_snapshot(coordinator):
    await coordinator.register(session_id="root", display_name="Raiz", parent_id=None, depth=0)
    await coordinator.set_status("root", "waiting_approval")

    nos = await coordinator.graph_snapshot("root")
    assert nos[0].status == "waiting_approval"


# ── Mensagens ────────────────────────────────────────────────────────────────


async def test_send_to_unknown_target_returns_false(coordinator):
    assert await coordinator.send(from_id="a", to_id="nao-existe", content="oi") is False


async def test_send_and_consume_pending(coordinator):
    await coordinator.register(session_id="root", display_name="Raiz", parent_id=None, depth=0)
    await coordinator.register(session_id="filho", display_name="Filho", parent_id="root", depth=1)

    enviado = await coordinator.send(from_id="filho", to_id="root", content="terminei")
    assert enviado is True

    mensagens = await coordinator.consume_pending("root")
    assert len(mensagens) == 1
    assert mensagens[0]["from"] == "filho"
    assert mensagens[0]["content"] == "terminei"

    # drenado — uma segunda leitura não vê nada de novo
    assert await coordinator.consume_pending("root") == []


async def test_wait_for_message_returns_immediately_when_already_pending(coordinator):
    await coordinator.register(session_id="root", display_name="Raiz", parent_id=None, depth=0)
    await coordinator.send(from_id="x", to_id="root", content="oi")

    mensagens = await coordinator.wait_for_message("root", timeout_seconds=5)
    assert len(mensagens) == 1
    assert mensagens[0]["content"] == "oi"


async def test_wait_for_message_times_out_without_message(coordinator):
    await coordinator.register(session_id="root", display_name="Raiz", parent_id=None, depth=0)
    mensagens = await coordinator.wait_for_message("root", timeout_seconds=0.05)
    assert mensagens == []


# ── Parada graciosa ──────────────────────────────────────────────────────────


async def test_request_stop_and_is_stopped(coordinator):
    await coordinator.register(session_id="root", display_name="Raiz", parent_id=None, depth=0)
    assert await coordinator.is_stopped("root") is False

    await coordinator.request_stop("root")
    assert await coordinator.is_stopped("root") is True
