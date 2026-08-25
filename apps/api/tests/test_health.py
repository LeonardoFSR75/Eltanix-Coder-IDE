"""O caminho de degradação é o que mais importa aqui.

Redis fora não pode derrubar o gateway: sem ele perdemos cache e circuit
breaker, mas o roteamento continua. Estes testes existem porque a primeira
versão fazia exatamente o contrário.
"""

from __future__ import annotations

import pytest

from novaai_studio.router.catalog import Resilience
from novaai_studio.router.health import HealthTracker


@pytest.fixture
def tracker_without_redis():
    return HealthTracker(None, Resilience())


async def test_all_models_available_without_redis(tracker_without_redis):
    assert await tracker_without_redis.is_available("qualquer/modelo") is True


async def test_latency_is_unknown_without_redis(tracker_without_redis):
    assert await tracker_without_redis.latency_p95("qualquer/modelo") is None


async def test_recording_is_a_noop_without_redis(tracker_without_redis):
    await tracker_without_redis.record_success("qualquer/modelo", 120)
    assert await tracker_without_redis.record_failure("qualquer/modelo", reason="x") is False
    await tracker_without_redis.reset("qualquer/modelo")


async def test_snapshot_is_neutral_without_redis(tracker_without_redis):
    snapshot = await tracker_without_redis.snapshot("qualquer/modelo")
    assert snapshot.available is True
    assert snapshot.success_rate == 1.0
    assert snapshot.cooldown_remaining_s == 0


async def test_broken_redis_degrades_instead_of_raising():
    class BrokenRedis:
        async def get(self, *_args, **_kwargs):
            raise ConnectionError("redis caiu")

        async def lrange(self, *_args, **_kwargs):
            raise ConnectionError("redis caiu")

    tracker = HealthTracker(BrokenRedis(), Resilience())  # type: ignore[arg-type]
    assert await tracker.is_available("qualquer/modelo") is True
    assert await tracker.latency_p95("qualquer/modelo") is None
