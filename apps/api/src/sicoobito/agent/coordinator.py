"""Coordenação entre agentes (orquestração multiagente) — status, caixa de
mensagens e árvore pai/filho, com estado no Redis.

Diferente de `router/health.py::HealthTracker` — que degrada pra "tudo
disponível" quando o Redis cai porque o breaker é recuperável a partir do
próximo probe — o estado daqui é a ÚNICA cópia de quem é filho de quem e do
que foi mensageado: não existe fonte de verdade alternativa pra reconstruir
isso. Por isso `spawn_agent` (em `agent/tools/agents_graph.py`) falha fechado
quando `register()` devolve `False` — ver ADR 0004. Os métodos de leitura/
mensagem que seguem (usados por agentes JÁ registrados) continuam degradando
pra um default seguro, porque falhar todos eles barulhentamente no meio de
uma orquestração em andamento deixaria filhos já rodando sem conseguir
chegar em `agent_finish`.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from redis.asyncio import Redis

from sicoobito.logging_setup import get_logger

log = get_logger(__name__)

_PREFIX = "sicoobito:agents"

AgentStatus = Literal[
    "running", "waiting_approval", "waiting_for_message", "completed", "failed", "stopped"
]


@dataclass(slots=True)
class AgentNode:
    session_id: str
    display_name: str
    status: AgentStatus
    parent_id: str | None
    depth: int
    children: list[str] = field(default_factory=list)


class AgentCoordinator:
    def __init__(self, redis: Redis | None, *, ttl_seconds: int = 21_600) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    def _key(self, session_id: str, suffix: str) -> str:
        return f"{_PREFIX}:{session_id}:{suffix}"

    async def _touch(self, session_id: str) -> None:
        """Renova o TTL deslizante de todas as chaves de um agente. Best-effort
        — chamado só depois de uma operação que já teve sucesso."""
        if self._redis is None:
            return
        try:
            pipe = self._redis.pipeline()
            for suffix in ("meta", "inbox", "children", "stop"):
                pipe.expire(self._key(session_id, suffix), self._ttl)
            await pipe.execute()
        except Exception as exc:
            log.warning("agent_coordinator.redis.unavailable", error=str(exc)[:200])

    # ── Registro e árvore pai/filho ─────────────────────────────────────────

    async def register(
        self,
        *,
        session_id: str,
        display_name: str,
        parent_id: str | None,
        depth: int,
    ) -> bool:
        """True se registrado; False se o Redis está indisponível — quem chama
        (o fechamento `spawn_child_agent` em `agent/runner.py`) precisa tratar
        `False` como falha e não criar a sessão filha (fail closed)."""
        if self._redis is None:
            return False
        try:
            pipe = self._redis.pipeline()
            meta_key = self._key(session_id, "meta")
            pipe.hset(
                meta_key,
                mapping={
                    "status": "running",
                    "display_name": display_name,
                    "parent_id": parent_id or "",
                    "depth": str(depth),
                },
            )
            pipe.expire(meta_key, self._ttl)
            if parent_id is not None:
                children_key = self._key(parent_id, "children")
                pipe.sadd(children_key, session_id)
                pipe.expire(children_key, self._ttl)
            await pipe.execute()
            return True
        except Exception as exc:
            log.warning("agent_coordinator.redis.unavailable", error=str(exc)[:200])
            return False

    async def children_of(self, session_id: str) -> list[str]:
        if self._redis is None:
            return []
        try:
            members = await self._redis.smembers(self._key(session_id, "children"))
        except Exception as exc:
            log.warning("agent_coordinator.redis.unavailable", error=str(exc)[:200])
            return []
        return sorted(m.decode() if isinstance(m, bytes) else m for m in members)

    async def depth_of(self, session_id: str) -> int:
        """0 para um agente desconhecido/raiz — nunca lança."""
        if self._redis is None:
            return 0
        try:
            raw = await self._redis.hget(self._key(session_id, "meta"), "depth")
        except Exception as exc:
            log.warning("agent_coordinator.redis.unavailable", error=str(exc)[:200])
            return 0
        if not raw:
            return 0
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    async def graph_snapshot(self, root_session_id: str) -> list[AgentNode]:
        """Percorre a árvore a partir de `root_session_id` (BFS). Devolve []
        se o Redis está indisponível ou a raiz é desconhecida."""
        if self._redis is None:
            return []
        nodes: list[AgentNode] = []
        fila = [root_session_id]
        visitados: set[str] = set()
        try:
            while fila:
                atual = fila.pop(0)
                if atual in visitados:
                    continue
                visitados.add(atual)
                meta = await self._redis.hgetall(self._key(atual, "meta"))
                if not meta:
                    continue
                meta = {
                    (k.decode() if isinstance(k, bytes) else str(k)): (
                        v.decode() if isinstance(v, bytes) else str(v)
                    )
                    for k, v in meta.items()
                }
                filhos = await self.children_of(atual)
                nodes.append(
                    AgentNode(
                        session_id=atual,
                        display_name=str(meta.get("display_name", atual)),
                        status=meta.get("status", "running"),  # type: ignore[arg-type]
                        parent_id=str(meta["parent_id"]) if meta.get("parent_id") else None,
                        depth=int(meta.get("depth", 0) or 0),
                        children=filhos,
                    )
                )
                fila.extend(filhos)
        except Exception as exc:
            log.warning("agent_coordinator.redis.unavailable", error=str(exc)[:200])
            return nodes
        return nodes

    # ── Status ───────────────────────────────────────────────────────────────

    async def set_status(self, session_id: str, status: AgentStatus) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.hset(self._key(session_id, "meta"), "status", status)
            await self._touch(session_id)
        except Exception as exc:
            log.warning("agent_coordinator.redis.unavailable", error=str(exc)[:200])

    # ── Mensagens ────────────────────────────────────────────────────────────

    async def send(self, *, from_id: str, to_id: str, content: str) -> bool:
        """RPUSH na caixa de `to_id`. False se o alvo é desconhecido/expirado
        ou o Redis está indisponível."""
        if self._redis is None:
            return False
        try:
            existe = await self._redis.exists(self._key(to_id, "meta"))
            if not existe:
                return False
            mensagem = json.dumps(
                {
                    "id": f"msg_{uuid.uuid4().hex[:8]}",
                    "from": from_id,
                    "content": content,
                    "ts": time.time(),
                },
                ensure_ascii=False,
            )
            await self._redis.rpush(self._key(to_id, "inbox"), mensagem)
            await self._touch(to_id)
            return True
        except Exception as exc:
            log.warning("agent_coordinator.redis.unavailable", error=str(exc)[:200])
            return False

    async def consume_pending(self, session_id: str) -> list[dict[str, Any]]:
        """Drena a caixa inteira (LPOP em lote) sem bloquear. [] se vazia ou
        indisponível."""
        if self._redis is None:
            return []
        try:
            itens = await self._redis.lpop(self._key(session_id, "inbox"), 1000)
        except Exception as exc:
            log.warning("agent_coordinator.redis.unavailable", error=str(exc)[:200])
            return []
        if not itens:
            return []
        return [
            json.loads(item.decode() if isinstance(item, bytes) else str(item)) for item in itens
        ]

    async def wait_for_message(
        self, session_id: str, *, timeout_seconds: float
    ) -> list[dict[str, Any]]:
        """Bloqueia via BLPOP (nativo do redis-py assíncrono, sem polling) até
        uma mensagem chegar ou o timeout expirar. [] no timeout ou se o Redis
        está indisponível — nunca lança."""
        if self._redis is None:
            return []
        try:
            resultado = await self._redis.blpop(
                [self._key(session_id, "inbox")], timeout=timeout_seconds
            )
        except Exception as exc:
            log.warning("agent_coordinator.redis.unavailable", error=str(exc)[:200])
            return []
        if resultado is None:
            return []
        _chave, valor = resultado
        mensagens = [json.loads(valor)]
        # BLPOP só devolve um item por chamada — drena o resto que possa ter
        # chegado no intervalo, pra não perder mensagens em rajada.
        mensagens.extend(await self.consume_pending(session_id))
        return mensagens

    # ── Parada graciosa ──────────────────────────────────────────────────────

    async def request_stop(self, session_id: str) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.set(self._key(session_id, "stop"), "1", ex=self._ttl)
        except Exception as exc:
            log.warning("agent_coordinator.redis.unavailable", error=str(exc)[:200])

    async def is_stopped(self, session_id: str) -> bool:
        """False (não parado) se indisponível — mesmo espírito de
        `HealthTracker.is_available`: a ausência de sinal não pode virar um
        efeito (aqui, um pedido de parada que nunca chegou não é "parado")."""
        if self._redis is None:
            return False
        try:
            return bool(await self._redis.exists(self._key(session_id, "stop")))
        except Exception as exc:
            log.warning("agent_coordinator.redis.unavailable", error=str(exc)[:200])
            return False
