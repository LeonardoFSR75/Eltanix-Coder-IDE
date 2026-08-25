"""Cache exato de respostas em Redis.

A economia mais barata que existe: sessões de codificação repetem o mesmo prompt
o tempo todo (o mesmo arquivo relido, o mesmo erro reenviado, o mesmo comando
tentado de novo). Um acerto aqui custa zero token e zero latência de provedor.

Duas decisões deliberadas:

- Só cacheia requisições determinísticas (`temperature` 0 ou ausente) por padrão.
  Cachear temperatura alta transforma variação pedida em repetição silenciosa.
- A chave inclui o **modelo resolvido**, não o perfil. Dois modelos diferentes
  respondendo ao mesmo prompt são respostas diferentes, e misturá-las tornaria
  a métrica de custo por modelo mentirosa.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis

from eltanix.logging_setup import get_logger

log = get_logger(__name__)

_PREFIX = "eltanix:cache:chat"


@dataclass(slots=True)
class CachedResponse:
    payload: dict[str, Any]
    prompt_tokens: int
    completion_tokens: int
    model_id: str

    @property
    def tokens_saved(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class ResponseCache:
    def __init__(
        self,
        redis: Redis | None,
        *,
        enabled: bool = True,
        ttl_seconds: int = 3600,
        only_deterministic: bool = True,
    ) -> None:
        self._redis = redis
        self._enabled = enabled and redis is not None
        self._ttl = ttl_seconds
        self._only_deterministic = only_deterministic

    @property
    def enabled(self) -> bool:
        return self._enabled

    def is_cacheable(self, params: dict[str, Any]) -> bool:
        if not self._enabled:
            return False
        if not self._only_deterministic:
            return True
        temperature = params.get("temperature")
        top_p = params.get("top_p")
        deterministic_temp = temperature is None or float(temperature) == 0.0
        deterministic_top_p = top_p is None or float(top_p) == 1.0
        return deterministic_temp and deterministic_top_p

    def key(self, model_id: str, params: dict[str, Any]) -> str:
        # `sort_keys` + `default=str` deixam a chave estável entre processos e
        # tolerante a objetos pydantic que apareçam em `tools`.
        material = {
            "model": model_id,
            "messages": params.get("messages"),
            "tools": params.get("tools"),
            "tool_choice": params.get("tool_choice"),
            "temperature": params.get("temperature"),
            "top_p": params.get("top_p"),
            "max_tokens": params.get("max_tokens"),
            "response_format": params.get("response_format"),
            "stop": params.get("stop"),
        }
        blob = json.dumps(material, sort_keys=True, default=str, ensure_ascii=False)
        digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
        return f"{_PREFIX}:{digest}"

    async def get(self, model_id: str, params: dict[str, Any]) -> CachedResponse | None:
        if not self.is_cacheable(params):
            return None
        try:
            raw = await self._redis.get(self.key(model_id, params))  # type: ignore[union-attr]
        except Exception as exc:
            log.warning("cache.redis.unavailable", error=str(exc))
            return None
        if not raw:
            return None
        try:
            stored = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return CachedResponse(
            payload=stored["payload"],
            prompt_tokens=stored.get("prompt_tokens", 0),
            completion_tokens=stored.get("completion_tokens", 0),
            model_id=stored.get("model_id", model_id),
        )

    async def get_by_key(self, key: str) -> CachedResponse | None:
        """Busca direta por uma chave já conhecida — usada pelo cache
        semântico (`optimizer/semantic_cache.py`), que descobre a chave via
        similaridade de embedding em vez de recomputar o hash exato. Não
        passa por `is_cacheable`: se a linha existe em `cached_response_embedding`,
        já foi gravada como cacheável no momento original."""
        if not self._enabled:
            return None
        try:
            raw = await self._redis.get(key)  # type: ignore[union-attr]
        except Exception as exc:
            log.warning("cache.redis.unavailable", error=str(exc))
            return None
        if not raw:
            return None
        try:
            stored = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return CachedResponse(
            payload=stored["payload"],
            prompt_tokens=stored.get("prompt_tokens", 0),
            completion_tokens=stored.get("completion_tokens", 0),
            model_id=stored.get("model_id", ""),
        )

    async def set(
        self,
        model_id: str,
        params: dict[str, Any],
        payload: dict[str, Any],
        *,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        if not self.is_cacheable(params):
            return
        stored = json.dumps(
            {
                "payload": payload,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "model_id": model_id,
            },
            default=str,
        )
        try:
            await self._redis.set(self.key(model_id, params), stored, ex=self._ttl)  # type: ignore[union-attr]
        except Exception as exc:
            log.warning("cache.redis.unavailable", error=str(exc))

    async def clear(self) -> int:
        """Remove todas as entradas de cache de chat. Retorna quantas apagou."""
        if self._redis is None:
            return 0
        removed = 0
        try:
            async for key in self._redis.scan_iter(match=f"{_PREFIX}:*", count=500):
                await self._redis.delete(key)
                removed += 1
        except Exception as exc:
            log.warning("cache.redis.unavailable", error=str(exc))
        return removed
