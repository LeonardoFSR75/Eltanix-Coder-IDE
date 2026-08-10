"""GET /api/agent/sessions/{session_id}/graph — a mesma árvore que a tool
`view_agent_graph` do agente vê (ADR 0004), exposta como rota para o painel
do IDE. `AgentCoordinator` em si já tem cobertura própria em
test_agent_coordinator.py; aqui só a ligação HTTP.
"""

from __future__ import annotations

import asyncio
import os

import pytest
from fastapi.testclient import TestClient

os.environ["SICOOBITO_API_KEY"] = "chave-de-teste"
os.environ["REDIS_URL"] = "redis://localhost:65533/0"

from sicoobito.agent.coordinator import AgentCoordinator
from sicoobito.config import get_settings
from sicoobito.main import create_app

AUTH = {"Authorization": "Bearer chave-de-teste"}


class _FakeRedis:
    """Mesmo estilo mínimo de test_agent_coordinator.py — hash e set bastam
    para register()/graph_snapshot()."""

    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.sets: dict[str, set[str]] = {}

    def pipeline(self):
        return _FakePipeline(self)

    async def hset(self, name, key=None, value=None, mapping=None):
        self.hashes.setdefault(name, {})
        if mapping:
            self.hashes[name].update(mapping)
        if key is not None:
            self.hashes[name][key] = value
        return 1

    async def hgetall(self, name):
        return dict(self.hashes.get(name, {}))

    async def expire(self, name, ttl):
        return True

    async def sadd(self, name, *values):
        self.sets.setdefault(name, set()).update(values)
        return len(values)

    async def smembers(self, name):
        return set(self.sets.get(name, set()))


class _FakePipeline:
    def __init__(self, redis: _FakeRedis) -> None:
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
            resultados.append(await getattr(self._redis, nome)(*args, **kwargs))
        self._ops = []
        return resultados


@pytest.fixture(scope="module")
def client():
    get_settings.cache_clear()
    with TestClient(create_app()) as test_client:
        # Substitui o coordinator real (Redis de verdade ou None) por um
        # apontando pro fake — mesmo princípio de qualquer outra dependência
        # injetada via app.state neste projeto.
        fake_coordinator = AgentCoordinator(_FakeRedis())
        test_client.app.state.agent_coordinator = fake_coordinator
        test_client.fake_coordinator = fake_coordinator
        yield test_client


def test_graph_of_unknown_session_is_empty(client):
    resposta = client.get("/api/agent/sessions/nao-existe/graph", headers=AUTH)
    assert resposta.status_code == 200
    assert resposta.json() == {"agents": []}


def test_graph_returns_parent_and_children(client):
    async def _popular():
        await client.fake_coordinator.register(
            session_id="root", display_name="Raiz", parent_id=None, depth=0
        )
        await client.fake_coordinator.register(
            session_id="filho", display_name="Filho", parent_id="root", depth=1
        )
        await client.fake_coordinator.set_status("filho", "waiting_approval")

    asyncio.run(_popular())

    resposta = client.get("/api/agent/sessions/root/graph", headers=AUTH)
    assert resposta.status_code == 200
    agentes = {a["session_id"]: a for a in resposta.json()["agents"]}
    assert set(agentes) == {"root", "filho"}
    assert agentes["filho"]["parent_id"] == "root"
    assert agentes["filho"]["status"] == "waiting_approval"
    assert agentes["root"]["depth"] == 0


def test_requires_auth(client):
    resposta = client.get("/api/agent/sessions/root/graph")
    assert resposta.status_code == 401
