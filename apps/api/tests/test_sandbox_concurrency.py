"""`sandbox/concurrency.py` (Horizonte 3 — fila local de concorrência de sandbox).

Unitário puro: sem Docker, sem executor, só a máquina de fila FIFO em asyncio.
"""

from __future__ import annotations

import asyncio

from sicoobito.sandbox.concurrency import SandboxConcurrencyGate


async def test_acquire_under_max_returns_immediately():
    gate = SandboxConcurrencyGate(max_concurrent=2)
    await gate.acquire("a")
    await gate.acquire("b")
    assert gate.snapshot() == {"active": 2, "max_concurrent": 2, "waiting": []}


async def test_acquire_beyond_max_blocks_until_release():
    gate = SandboxConcurrencyGate(max_concurrent=1)
    await gate.acquire("a")

    task = asyncio.create_task(gate.acquire("b"))
    await asyncio.sleep(0)  # deixa a task rodar até bloquear no `event.wait()`
    assert not task.done()
    snap = gate.snapshot()
    assert snap["active"] == 1
    assert snap["waiting"] == [{"session_id": "b", "position": 1}]

    await gate.release("a")
    await asyncio.wait_for(task, timeout=1)
    assert gate.snapshot() == {"active": 1, "max_concurrent": 1, "waiting": []}


async def test_fifo_order_promotes_first_waiter_first():
    gate = SandboxConcurrencyGate(max_concurrent=1)
    await gate.acquire("a")

    task_b = asyncio.create_task(gate.acquire("b"))
    await asyncio.sleep(0)
    task_c = asyncio.create_task(gate.acquire("c"))
    await asyncio.sleep(0)
    assert gate.snapshot()["waiting"] == [
        {"session_id": "b", "position": 1},
        {"session_id": "c", "position": 2},
    ]

    await gate.release("a")
    await asyncio.wait_for(task_b, timeout=1)
    assert not task_c.done()
    assert gate.snapshot()["waiting"] == [{"session_id": "c", "position": 1}]

    await gate.release("b")
    await asyncio.wait_for(task_c, timeout=1)
    assert gate.snapshot() == {"active": 1, "max_concurrent": 1, "waiting": []}


async def test_acquire_is_idempotent_for_already_active_session():
    gate = SandboxConcurrencyGate(max_concurrent=1)
    await gate.acquire("a")
    # Segunda chamada para a mesma sessão (reconexão) não deve consumir
    # outra vaga nem bloquear, mesmo com o teto em 1.
    await asyncio.wait_for(gate.acquire("a"), timeout=1)
    assert gate.snapshot()["active"] == 1


async def test_release_of_unknown_session_is_a_noop():
    gate = SandboxConcurrencyGate(max_concurrent=2)
    await gate.release("nunca-adquirida")
    assert gate.snapshot() == {"active": 0, "max_concurrent": 2, "waiting": []}


async def test_cancelling_a_waiter_removes_it_from_the_queue():
    gate = SandboxConcurrencyGate(max_concurrent=1)
    await gate.acquire("a")

    task_b = asyncio.create_task(gate.acquire("b"))
    await asyncio.sleep(0)
    assert gate.snapshot()["waiting"] == [{"session_id": "b", "position": 1}]

    task_b.cancel()
    import contextlib

    with contextlib.suppress(asyncio.CancelledError):
        await task_b

    # A vaga não vazou: liberar "a" ainda deixa a fila vazia e o gate utilizável.
    assert gate.snapshot() == {"active": 1, "max_concurrent": 1, "waiting": []}
    await gate.release("a")
    assert gate.snapshot() == {"active": 0, "max_concurrent": 1, "waiting": []}


async def test_max_concurrent_is_floored_to_at_least_one():
    gate = SandboxConcurrencyGate(max_concurrent=0)
    assert gate.snapshot()["max_concurrent"] == 1
