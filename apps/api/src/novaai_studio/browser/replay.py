"""Persistência de replay de sessão do navegador (Fase 4b).

`services/browser` não alcança `minio` (rede `browser_net`, ver
docker-compose.yml e o docstring de `services/browser/app.py`) — devolve
trace.zip/vídeo como bytes no corpo do `DELETE /sessions/{id}`
(`BrowserClient.stop()`), e é aqui, do lado de `api` (que já tem
`BlobStore`), que os bytes viram objetos no bucket existente de documentos.

O índice de sessões recentes fica no Redis — mesmo espírito de "falha
degrada, não derruba" do CLAUDE.md: é cache/atalho de navegação para achar
replays recentes, não registro de auditoria, então some sozinho (TTL) sem
Postgres/migração nova, e o índice inteiro é opcional (sem Redis, o replay
ainda sobe pro MinIO — só não aparece na lista de "sessões recentes").

Escopo é por `session_id`, não por projeto: nenhum dos dois chamadores atuais
(`api/routes/browser.py` para o painel manual, `agent/runner.py` para sessões
do agente) tem um identificador de projeto barato o suficiente para valer a
pena encanar aqui — `project` é best-effort (nome do diretório de workspace
para sessões de agente, `None` para o painel).
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from contextlib import suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sicoobito.logging_setup import get_logger

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from sicoobito.storage.blob import BlobStore

log = get_logger(__name__)

_KEY_PREFIX = "browser-sessions"
_REDIS_HASH_PREFIX = "browser:replay:"
_REDIS_INDEX_KEY = "browser:replays"
_REDIS_TTL_SECONDS = 7 * 24 * 3600
_MAX_INDEXED = 200

# Sinal de curta duração (não registro de auditoria — por isso um TTL curto,
# ao contrário do índice de replay de 7 dias acima): quando o reaper TTL de
# `services/browser` descarta uma sessão com trace/vídeo em andamento, os
# bytes já foram jogados fora ali mesmo (aquele serviço não alcança o MinIO,
# ver docstring do módulo) — sem isto, a próxima consulta a
# `GET /replays/{id}` via 404 fica indistinguível de "nunca existiu".
_REDIS_EXPIRED_PREFIX = "browser:replay-expired:"
_REDIS_EXPIRED_TTL_SECONDS = 24 * 3600

# Blobs recém-enviados ficam de fora da varredura de órfãos por esta margem —
# `store_replay` sobe os bytes ANTES de indexar no Redis (linhas abaixo),
# então uma sessão pega no meio dessa janela pareceria "sem índice" sem
# realmente estar órfã.
_PURGE_GRACE_SECONDS = 3600


async def store_replay(
    *,
    blob: BlobStore | None,
    redis: Redis | None,
    session_id: str,
    project: str | None,
    payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Sobe trace/vídeo pro MinIO e indexa no Redis. `None` em qualquer
    argumento essencial (blob indisponível, sessão sem trace/vídeo) é um
    retorno normal, não erro — replay é conveniência opcional."""
    if blob is None or not payload:
        return None
    trace_b64 = payload.get("trace_base64")
    video_b64 = payload.get("video_base64")
    if not trace_b64 and not video_b64:
        return None

    started_at = payload.get("started_at") or time.time()
    prefixo = f"{_KEY_PREFIX}/{session_id}/{int(started_at)}"
    trace_key = f"{prefixo}/trace.zip"
    video_key = f"{prefixo}/video.webm"

    try:
        if trace_b64:
            await blob.put_object(trace_key, base64.b64decode(trace_b64), "application/zip")
        if video_b64:
            await blob.put_object(video_key, base64.b64decode(video_b64), "video/webm")
    except Exception as exc:
        log.warning("browser.replay.upload_failed", session=session_id, error=str(exc))
        return None

    metadata: dict[str, Any] = {
        "session_id": session_id,
        "project": project,
        "started_at": started_at,
        "duration_ms": payload.get("duration_ms"),
        "actions": payload.get("actions") or [],
        # Fase 4c: log de rede da sessão, timestamps na mesma base de
        # `actions` — permite ao Replay tab mostrar as requisições feitas
        # perto do instante de cada marcador clicado.
        "network": payload.get("network") or [],
        "trace_key": trace_key if trace_b64 else None,
        "video_key": video_key if video_b64 else None,
    }

    if redis is not None:
        try:
            await redis.set(
                f"{_REDIS_HASH_PREFIX}{session_id}",
                json.dumps(metadata, ensure_ascii=False),
                ex=_REDIS_TTL_SECONDS,
            )
            await redis.zadd(_REDIS_INDEX_KEY, {session_id: started_at})
            # Mantém só as N sessões mais recentes na lista — o resto continua
            # no MinIO, só sai do índice de "replays recentes".
            await redis.zremrangebyrank(_REDIS_INDEX_KEY, 0, -(_MAX_INDEXED + 1))
        except Exception as exc:
            log.warning("browser.replay.index_failed", session=session_id, error=str(exc))

    return metadata


async def list_recent_replays(redis: Redis | None, *, limit: int = 30) -> list[dict[str, Any]]:
    if redis is None:
        return []
    try:
        session_ids = await redis.zrevrange(_REDIS_INDEX_KEY, 0, max(limit - 1, 0))
        if not session_ids:
            return []
        chaves = [f"{_REDIS_HASH_PREFIX}{sid}" for sid in session_ids]
        brutos = await redis.mget(chaves)
    except Exception as exc:
        log.warning("browser.replay.list_failed", error=str(exc))
        return []
    resultado: list[dict[str, Any]] = []
    for bruto in brutos:
        if not bruto:
            continue
        with suppress(Exception):
            entrada = json.loads(bruto)
            entrada.pop("actions", None)  # listas completas só na rota de detalhe
            entrada.pop("network", None)
            resultado.append(entrada)
    return resultado


async def get_replay(redis: Redis | None, session_id: str) -> dict[str, Any] | None:
    if redis is None:
        return None
    try:
        bruto = await redis.get(f"{_REDIS_HASH_PREFIX}{session_id}")
    except Exception as exc:
        log.warning("browser.replay.get_failed", session=session_id, error=str(exc))
        return None
    if not bruto:
        return None
    try:
        return json.loads(bruto)
    except Exception:
        return None


async def mark_replay_expired(redis: Redis | None, session_id: str) -> None:
    """Registra que o replay desta sessão foi perdido por TTL — ver
    `_REDIS_EXPIRED_PREFIX` acima. Chamado pelos dois pontos que fecham uma
    sessão de navegador (`api/routes/browser.py` para o painel manual,
    `agent/runner.py::AgentRunner.close_session` para o agente) quando
    `BrowserClient.stop()` volta com `expired_by_ttl=True` e sem bytes."""
    if redis is None:
        return
    with suppress(Exception):
        await redis.set(
            f"{_REDIS_EXPIRED_PREFIX}{session_id}", "1", ex=_REDIS_EXPIRED_TTL_SECONDS
        )


async def was_replay_expired(redis: Redis | None, session_id: str) -> bool:
    if redis is None:
        return False
    try:
        return bool(await redis.get(f"{_REDIS_EXPIRED_PREFIX}{session_id}"))
    except Exception as exc:
        log.warning("browser.replay.expired_check_failed", session=session_id, error=str(exc))
        return False


async def purge_orphaned_replay_blobs(*, blob: BlobStore | None, redis: Redis | None) -> int:
    """Remove do MinIO trace.zip/video.webm cujo índice Redis (TTL de 7 dias,
    `_REDIS_HASH_PREFIX`) já expirou — `store_replay` sobe os bytes mas nunca
    os apaga sozinho (o índice é só um atalho de navegação, ver docstring do
    módulo), então sem isto o bucket cresce para sempre. Roda periodicamente
    via `run_replay_purge_reaper`, nunca de dentro de `services/browser`
    (aquele serviço não alcança o MinIO — invariante da rede `browser_net`).

    Degrada, não derruba: `blob`/`redis` indisponível ou qualquer falha
    pontual só faz este ciclo remover menos, nunca lançar. Retorna quantos
    objetos foram removidos."""
    if blob is None or redis is None:
        return 0
    try:
        objetos = await blob.list_object_keys(f"{_KEY_PREFIX}/")
    except Exception as exc:
        log.warning("browser.replay.purge_list_failed", error=str(exc))
        return 0

    agora = datetime.now(UTC)
    por_sessao: dict[str, list[str]] = {}
    for chave, modificado_em in objetos:
        # `browser-sessions/<session_id>/<started_at>/trace.zip` (ou
        # `video.webm`) — ver `store_replay` abaixo para o formato da chave.
        partes = chave.split("/")
        if len(partes) < 2:
            continue
        idade_segundos = (agora - modificado_em).total_seconds() if modificado_em else None
        if idade_segundos is not None and idade_segundos < _PURGE_GRACE_SECONDS:
            continue  # upload recente demais — pode ainda não estar indexado
        por_sessao.setdefault(partes[1], []).append(chave)

    removidos = 0
    for session_id, chaves_sessao in por_sessao.items():
        try:
            ainda_indexado = await redis.exists(f"{_REDIS_HASH_PREFIX}{session_id}")
        except Exception as exc:
            log.warning("browser.replay.purge_check_failed", session=session_id, error=str(exc))
            continue
        if ainda_indexado:
            continue
        for chave in chaves_sessao:
            with suppress(Exception):
                await blob.remove_object(chave)
                removidos += 1
    return removidos


async def run_replay_purge_reaper(
    *, blob: BlobStore | None, redis: Redis | None, interval_seconds: int = 6 * 3600
) -> None:
    """Laço de limpeza periódica, mesmo padrão de
    `AuthService.run_session_purge_reaper`."""
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            removidos = await purge_orphaned_replay_blobs(blob=blob, redis=redis)
            if removidos:
                log.info("browser.replay.purge_completed", removed=removidos)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("browser.replay.purge_reaper_iteration_failed", error=str(exc)[:200])
