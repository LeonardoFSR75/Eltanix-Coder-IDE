"""Cache semântico de respostas — complementa o cache exato de
`optimizer/cache.py` com correspondência por similaridade de embedding.

Regra de segurança central, não um detalhe de threshold: **nunca** roda
quando a chamada tem `tools` — é uma instrução executável, e um falso
positivo devolveria o `tool_call` ERRADO (arquivo/comando trocado), pior que
simplesmente não ter cache. Também nunca roda para fontes cujo veredito
funciona como sinal de autorização (`Settings.semantic_cache_excluded_sources`,
ex. revisão de código) — um veredito velho pra um diff diferente é o mesmo
risco. Desligado por padrão (`Settings.semantic_cache_enabled`).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from novaai_studio.db.session import session_scope
from novaai_studio.logging_setup import get_logger
from novaai_studio.optimizer import semantic_cache_store
from novaai_studio.optimizer.cache import CachedResponse, ResponseCache

log = get_logger(__name__)

EmbedFn = Callable[..., Awaitable[Any]]


def _extract_query_text(messages: list[dict[str, Any]]) -> str:
    """Última mensagem de usuário — é o que varia entre chamadas quase
    idênticas; o system prompt (maior bloco, mas compartilhado entre
    chamadas) não discrimina nada."""
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            partes = [item.get("text", "") for item in content if isinstance(item, dict)]
            return "\n".join(parte for parte in partes if parte)
    return ""


class SemanticCache:
    def __init__(
        self,
        *,
        redis_cache: ResponseCache,
        enabled: bool,
        embedding_profile: str,
        max_cosine_distance: float,
        ttl_seconds: int,
        excluded_sources: list[str],
    ) -> None:
        self._redis_cache = redis_cache
        self._enabled = enabled
        self._embedding_profile = embedding_profile
        self._max_cosine_distance = max_cosine_distance
        self._ttl_seconds = ttl_seconds
        self._excluded_sources = set(excluded_sources)
        self._embed_fn: EmbedFn | None = None

    def set_embed_fn(self, embed_fn: EmbedFn) -> None:
        """Ligação em duas fases: `SemanticCache` precisa chamar
        `RouterEngine.embed()`, mas é uma dependência do próprio
        `RouterEngine` — ver `main.py::lifespan` para a ordem de construção."""
        self._embed_fn = embed_fn

    def _is_eligible(self, prepared: dict[str, Any], source: str) -> bool:
        if not self._enabled or self._embed_fn is None:
            return False
        if prepared.get("tools"):
            return False
        return source not in self._excluded_sources

    async def _embed_text(self, text: str) -> list[float] | None:
        assert self._embed_fn is not None  # só chamado depois de _is_eligible
        try:
            resultado = await self._embed_fn(
                requested_model=self._embedding_profile,
                inputs=[text],
                source="semantic_cache",
            )
        except Exception as exc:
            # Falha ao gerar embedding degrada pra "sem cache semântico", nunca
            # bloqueia ou quebra a chamada real que está em andamento.
            log.warning("semantic_cache.embed_failed", error=str(exc)[:200])
            return None
        data = resultado.payload.get("data") or []
        if not data:
            return None
        return data[0].get("embedding")

    async def lookup(
        self, model_id: str, prepared: dict[str, Any], *, source: str
    ) -> CachedResponse | None:
        if not self._is_eligible(prepared, source):
            return None

        texto = _extract_query_text(list(prepared.get("messages") or []))
        if not texto:
            return None

        embedding = await self._embed_text(texto)
        if embedding is None:
            return None

        try:
            async with session_scope() as session:
                chave = await semantic_cache_store.find_nearest(
                    session,
                    model_id=model_id,
                    embedding=embedding,
                    max_distance=self._max_cosine_distance,
                )
        except Exception as exc:
            log.warning("semantic_cache.lookup_failed", error=str(exc)[:200])
            return None

        if chave is None:
            return None
        return await self._redis_cache.get_by_key(chave)

    async def record(
        self, model_id: str, prepared: dict[str, Any], redis_cache_key: str, *, source: str
    ) -> None:
        """Chamado só depois de um sucesso real do provedor, junto com
        `ResponseCache.set()` — nunca antes, para não indexar uma resposta
        que pode ainda falhar no meio do caminho."""
        if not self._is_eligible(prepared, source):
            return

        texto = _extract_query_text(list(prepared.get("messages") or []))
        if not texto:
            return

        embedding = await self._embed_text(texto)
        if embedding is None:
            return

        expira_em = datetime.now(UTC) + timedelta(seconds=self._ttl_seconds)
        try:
            async with session_scope() as session:
                await semantic_cache_store.insert(
                    session,
                    model_id=model_id,
                    redis_cache_key=redis_cache_key,
                    embedding=embedding,
                    expires_at=expira_em,
                )
        except Exception as exc:
            log.warning("semantic_cache.record_failed", error=str(exc)[:200])
