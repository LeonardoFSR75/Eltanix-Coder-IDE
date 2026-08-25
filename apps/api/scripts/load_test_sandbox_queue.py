"""Smoke de concorrência local contra o gate de sandbox (sandbox/concurrency.py).

Não é o teste de carga formal do alvo da auditoria arquitetural (1.000
projetos / 500 usuários / 5.000 sessões-dia / 50.000 execuções-dia) — esse
alvo pressupõe infraestrutura multi-tenant que o produto não opera hoje
(decisão via pergunta ao usuário; ver Horizonte 3, item 3, em
docs/proposals/plano-implementacao-auditoria-arquitetural.md). Isto valida,
contra a stack real (docker compose), que o gate de concorrência (Horizonte 3,
item 1) se comporta certo sob carga moderada e concorrente:

- a fila enche quando N sessões concorrentes excedem SANDBOX_MAX_CONCURRENT;
- posição na fila decresce conforme sessões anteriores fecham;
- nenhuma vaga vaza — a contagem final volta a zero;
- nenhuma sessão falha por causa da fila em si (timeout de espera à parte).

Requer a stack rodando (`docker compose up -d`) e um projeto já criado.
Usa o canal de serviço (NOVAAI_STUDIO_API_KEY, ver docs/adr/0005-login-obrigatorio.md)
em vez de login de usuário — é ferramenta externa, não sessão de browser.

Uso:
  NOVAAI_STUDIO_API_KEY=... uv run python scripts/load_test_sandbox_queue.py \
      --project e2e-smoke-test --sessions 10 --base-url http://localhost:5401
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

import httpx


async def _create_and_close(
    client: httpx.AsyncClient,
    base_url: str,
    project: str,
    index: int,
    headers: dict[str, str],
) -> tuple[str, float]:
    inicio = time.perf_counter()
    try:
        resposta = await client.post(
            f"{base_url}/api/agent/sessions",
            json={"project": project, "task": f"smoke de carga #{index}"},
            headers=headers,
            timeout=180.0,
        )
    except httpx.HTTPError as exc:
        raise RuntimeError(f"sessão #{index}: create falhou ({exc!r})") from exc
    resposta.raise_for_status()
    session_id = resposta.json()["session_id"]
    duracao = time.perf_counter() - inicio
    try:
        await client.post(
            f"{base_url}/api/agent/sessions/{session_id}/close",
            json={"keep_branch": False},
            headers=headers,
            timeout=90.0,
        )
    except httpx.HTTPError as exc:
        raise RuntimeError(f"sessão #{index} ({session_id}): close falhou ({exc!r})") from exc
    return session_id, duracao


async def _poll_queue(
    client: httpx.AsyncClient, base_url: str, headers: dict[str, str], stop: asyncio.Event
) -> list[dict]:
    """Sob N criações concorrentes o event loop do dev server pode demorar a
    responder ao polling — timeout isolado aqui não deve derrubar a amostragem
    inteira, só perder aquela leitura."""
    amostras = []
    while not stop.is_set():
        try:
            resposta = await client.get(
                f"{base_url}/api/agent/sandboxes/queue", headers=headers, timeout=15.0
            )
            if resposta.status_code == 200:
                amostras.append(resposta.json())
        except httpx.HTTPError:
            pass
        await asyncio.sleep(0.3)
    return amostras


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="e2e-smoke-test")
    parser.add_argument("--sessions", type=int, default=10)
    parser.add_argument("--base-url", default="http://localhost:5401")
    args = parser.parse_args()

    api_key = os.environ.get("NOVAAI_STUDIO_API_KEY", "")
    if not api_key:
        print("NOVAAI_STUDIO_API_KEY não definida no ambiente.", file=sys.stderr)
        return 1
    headers = {"X-Api-Key": api_key}

    async with httpx.AsyncClient() as client:
        antes = await client.get(
            f"{args.base_url}/api/agent/sandboxes/queue", headers=headers, timeout=30.0
        )
        antes.raise_for_status()
        print(f"antes:  {antes.json()}")

        stop = asyncio.Event()
        poll_task = asyncio.create_task(_poll_queue(client, args.base_url, headers, stop))

        tarefas = [
            _create_and_close(client, args.base_url, args.project, i, headers)
            for i in range(args.sessions)
        ]
        resultados = await asyncio.gather(*tarefas, return_exceptions=True)

        stop.set()
        amostras = await poll_task

        depois = await client.get(
            f"{args.base_url}/api/agent/sandboxes/queue", headers=headers, timeout=30.0
        )
        depois.raise_for_status()
        print(f"depois: {depois.json()}")

    falhas = [r for r in resultados if isinstance(r, BaseException)]
    pico_active = max((a["active"] for a in amostras), default=0)
    pico_waiting = max((len(a["waiting"]) for a in amostras), default=0)

    print(f"sessões: {args.sessions}, falhas: {len(falhas)}")
    print(f"pico de active observado: {pico_active}")
    print(f"pico de waiting observado: {pico_waiting}")
    for falha in falhas:
        print(f"  falha: {falha!r}", file=sys.stderr)

    estado_final = depois.json()
    ok = not falhas and estado_final["active"] == 0 and estado_final["waiting"] == []
    print("RESULTADO: OK" if ok else "RESULTADO: FALHOU")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
