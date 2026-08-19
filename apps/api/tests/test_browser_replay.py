"""Item 9 do plano de robustez do navegador interno: sinal de replay perdido
por TTL (`mark_replay_expired`/`was_replay_expired`) e limpeza de blobs
órfãos no MinIO (`purge_orphaned_replay_blobs`) — nenhum dos dois tinha
cobertura antes desta mudança.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

from sicoobito.browser.replay import (
    _REDIS_HASH_PREFIX,
    mark_replay_expired,
    purge_orphaned_replay_blobs,
    store_replay,
    was_replay_expired,
)


class _FakeRedis:
    def __init__(self) -> None:
        self.valores: dict[str, str] = {}

    async def set(self, key, value, ex=None):
        self.valores[key] = value
        return True

    async def get(self, key):
        return self.valores.get(key)

    async def exists(self, key):
        return 1 if key in self.valores else 0

    async def zadd(self, key, mapping):
        self.valores.setdefault(f"{key}:zset", {}).update(mapping)
        return len(mapping)

    async def zremrangebyrank(self, key, start, stop):
        return 0


class _FakeBlob:
    def __init__(self, objetos: list[tuple[str, datetime | None]] | None = None) -> None:
        self._objetos = objetos if objetos is not None else []
        self.removidos: list[str] = []
        self.enviados: dict[str, bytes] = {}

    async def list_object_keys(self, prefix: str):
        return [o for o in self._objetos if o[0].startswith(prefix)]

    async def remove_object(self, key: str) -> None:
        self.removidos.append(key)

    async def put_object(self, key: str, data: bytes, content_type: str) -> None:
        self.enviados[key] = data
        self._objetos.append((key, datetime.now(UTC)))

    def envelhecer(self, key: str, quando: datetime) -> None:
        """Reescreve o timestamp de upload de `key` — usado só em teste, para
        simular tempo passando sem precisar de um `time.sleep` de verdade."""
        self._objetos = [(k, quando) if k == key else (k, dt) for k, dt in self._objetos]


async def test_mark_and_check_replay_expired_round_trip():
    redis = _FakeRedis()

    assert await was_replay_expired(redis, "s1") is False
    await mark_replay_expired(redis, "s1")
    assert await was_replay_expired(redis, "s1") is True
    # Sessão diferente não é afetada.
    assert await was_replay_expired(redis, "s2") is False


async def test_was_replay_expired_without_redis_degrades_to_false():
    assert await was_replay_expired(None, "s1") is False


async def test_purge_removes_only_orphaned_and_old_enough_blobs():
    agora = datetime.now(UTC)
    velho = agora - timedelta(hours=2)  # além da margem de segurança (1h)
    recente = agora - timedelta(minutes=5)  # dentro da margem — nunca remover

    blob = _FakeBlob(
        [
            ("browser-sessions/orfa-velha/100/trace.zip", velho),
            ("browser-sessions/orfa-velha/100/video.webm", velho),
            ("browser-sessions/ainda-indexada/200/trace.zip", velho),
            ("browser-sessions/recem-enviada/300/trace.zip", recente),
        ]
    )
    redis = _FakeRedis()
    redis.valores[f"{_REDIS_HASH_PREFIX}ainda-indexada"] = "{}"

    removidos = await purge_orphaned_replay_blobs(blob=blob, redis=redis)

    assert removidos == 2
    assert set(blob.removidos) == {
        "browser-sessions/orfa-velha/100/trace.zip",
        "browser-sessions/orfa-velha/100/video.webm",
    }


async def test_purge_without_blob_or_redis_degrades_to_zero():
    assert await purge_orphaned_replay_blobs(blob=None, redis=_FakeRedis()) == 0
    assert await purge_orphaned_replay_blobs(blob=_FakeBlob([]), redis=None) == 0


async def test_replay_lifecycle_redis_index_expires_blob_remains_until_purged():
    """Item 20b: ciclo de vida completo do cenário que motivou o item 9 —
    `store_replay` sobe o blob normal, o índice Redis (TTL de 7 dias) depois
    expira sozinho (aqui, simulado apagando a chave direto), e o blob fica
    para trás no MinIO até o reaper de `purge_orphaned_replay_blobs` passar
    e limpar. Ao contrário de `test_purge_removes_only_orphaned_and_old_enough_blobs`
    (que monta o estado "órfão" à mão), este teste passa pelo `store_replay`
    de verdade primeiro, provando que as duas metades do ciclo (upload +
    limpeza) concordam sobre onde o objeto fica gravado.
    """
    blob = _FakeBlob()
    redis = _FakeRedis()
    session_id = "s-ciclo-de-vida"

    metadata = await store_replay(
        blob=blob,
        redis=redis,
        session_id=session_id,
        project=None,
        payload={
            "trace_base64": base64.b64encode(b"trace de verdade").decode(),
            "duration_ms": 500,
            "actions": [],
            "network": [],
        },
    )
    assert metadata is not None
    trace_key = metadata["trace_key"]
    assert trace_key in blob.enviados
    assert await redis.exists(f"{_REDIS_HASH_PREFIX}{session_id}") == 1

    # Índice ainda de pé, dentro da margem de segurança — a limpeza não deve
    # tocar no blob recém-enviado.
    removidos_cedo = await purge_orphaned_replay_blobs(blob=blob, redis=redis)
    assert removidos_cedo == 0
    assert trace_key not in blob.removidos

    # TTL de 7 dias do índice expira (simulado apagando a chave) e o upload
    # envelhece além da margem de 1h — agora sim é candidato a órfão.
    del redis.valores[f"{_REDIS_HASH_PREFIX}{session_id}"]
    blob.envelhecer(trace_key, datetime.now(UTC) - timedelta(hours=2))

    removidos = await purge_orphaned_replay_blobs(blob=blob, redis=redis)

    assert removidos == 1
    assert trace_key in blob.removidos
