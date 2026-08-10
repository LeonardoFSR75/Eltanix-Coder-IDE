"""`run_headless_burst`: drena um `stream_run()` até o fim sem SSE e traduz o
desfecho pro `AgentCoordinator` — os 3 casos (completou, pausou em interrupt,
levantou exceção) são a garantia central de que um agente filho sem UI
observando nunca fica num estado ambíguo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from sicoobito.agent.coordinator import AgentCoordinator
from sicoobito.agent.headless import run_headless_burst


@dataclass
class _FakeSession:
    session_id: str


class _FakeRunner:
    def __init__(self, eventos: list[dict[str, Any]] | None = None, *, erro: Exception | None = None):
        self._eventos = eventos or []
        self._erro = erro
        self.chamadas: list[dict[str, Any]] = []

    async def stream_run(self, session, *, resume=None, message=None):
        self.chamadas.append({"session_id": session.session_id, "resume": resume, "message": message})
        if self._erro is not None:
            raise self._erro
        for evento in self._eventos:
            yield evento


class _FakeRedis:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}

    def pipeline(self):
        raise NotImplementedError("headless burst só usa set_status, não pipeline")

    async def hset(self, name, key=None, value=None, mapping=None):
        self.hashes.setdefault(name, {})
        if mapping:
            self.hashes[name].update(mapping)
        if key is not None:
            self.hashes[name][key] = value
        return 1

    async def hget(self, name, key):
        return self.hashes.get(name, {}).get(key)

    async def expire(self, name, ttl):
        return True


@pytest.fixture
def coordinator():
    return AgentCoordinator(_FakeRedis(), ttl_seconds=60)


async def test_burst_completes_normally(coordinator):
    runner = _FakeRunner(eventos=[{"node": "think", "update": {}}, {"node": "act", "update": {}}])
    sessao = _FakeSession(session_id="filho1")

    await run_headless_burst(runner, coordinator, sessao)

    status = await coordinator._redis.hget(coordinator._key("filho1", "meta"), "status")
    assert status == "completed"
    assert runner.chamadas == [{"session_id": "filho1", "resume": None, "message": None}]


async def test_burst_pauses_at_interrupt(coordinator):
    runner = _FakeRunner(
        eventos=[{"node": "think", "update": {}}, {"node": "interrupt", "update": {"actions": []}}]
    )
    sessao = _FakeSession(session_id="filho2")

    await run_headless_burst(runner, coordinator, sessao)

    status = await coordinator._redis.hget(coordinator._key("filho2", "meta"), "status")
    assert status == "waiting_approval"


async def test_burst_failure_is_caught_and_marked_failed(coordinator):
    runner = _FakeRunner(erro=RuntimeError("boom"))
    sessao = _FakeSession(session_id="filho3")

    await run_headless_burst(runner, coordinator, sessao)  # não deve lançar

    status = await coordinator._redis.hget(coordinator._key("filho3", "meta"), "status")
    assert status == "failed"


async def test_burst_passes_resume_and_message_through(coordinator):
    runner = _FakeRunner(eventos=[])
    sessao = _FakeSession(session_id="filho4")

    await run_headless_burst(runner, coordinator, sessao, resume={"call1": True}, message="oi")

    assert runner.chamadas == [
        {"session_id": "filho4", "resume": {"call1": True}, "message": "oi"}
    ]
