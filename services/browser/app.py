"""Browser: serviço isolado que roda o Chromium headless para a ferramenta
de verificação visual do agente (`browser_action`, ver
`apps/api/src/eltanix/agent/tools/browser.py`).

Por que separado do sandbox de execução (`services/executor`): aquele
sandbox é isolado de rede por padrão (`network_mode=none`) — outras
ferramentas (`run_command`) dependem implicitamente dessa garantia continuar
valendo para todo mundo. Um navegador para verificar UI precisa de rede de
verdade (alcançar o servidor da própria aplicação), então em vez de afrouxar
o sandbox de shell, este serviço tem a SUA PRÓPRIA rede restrita — só alcança
`web`/`api` (ver docker-compose.yml, rede `browser_net` com `internal:
true`), nunca a internet pública, e nunca o `docker.sock` (esse continua
exclusivo do `executor`, ADR 0002).

Uma página por sessão do agente, reaproveitada entre ações — abrir um
Chromium novo a cada clique seria lento e jogaria fora o estado de navegação
(cookies, formulário preenchido) entre uma ação e a próxima.
"""

from __future__ import annotations

import asyncio
import base64
import hmac
import ipaddress
import os
import shutil
import socket
import tempfile
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field

from urllib.parse import urlparse

TOKEN = os.getenv("BROWSER_TOKEN", "")
SESSION_TTL_SECONDS = int(os.getenv("BROWSER_SESSION_TTL_SECONDS", "1800"))
REAP_INTERVAL_SECONDS = int(os.getenv("BROWSER_REAP_INTERVAL_SECONDS", "300"))
# Teto de contextos Chromium/Lightpanda vivos ao mesmo tempo — sem isto, uma
# rajada de sessões (painel + várias sessões de agente) esgota a memória do
# único processo de browser compartilhado, sem nenhum aviso até o container
# cair. Análogo ao `SandboxConcurrencyGate` do lado do executor.
MAX_CONCURRENT_SESSIONS = int(os.getenv("BROWSER_MAX_CONCURRENT_SESSIONS", "20"))

# Trace/vídeo por sessão (Fase 4b) — arquivos passam por disco local antes de
# virar bytes na resposta; `api` é quem de fato sobe pro MinIO (este serviço
# não alcança `minio`, só `web`/`api`, ver docstring do módulo).
VIDEO_ROOT = Path(tempfile.gettempdir()) / "eltanix-browser-videos"
TRACE_ROOT = Path(tempfile.gettempdir()) / "eltanix-browser-traces"
VIDEO_ROOT.mkdir(parents=True, exist_ok=True)
TRACE_ROOT.mkdir(parents=True, exist_ok=True)
# Teto por blob (trace.zip OU video.webm) antes de base64-codificar e devolver
# no corpo JSON do `DELETE /sessions/{id}` — sem isto, uma gravação longa vira
# uma resposta HTTP gigante (base64 já é +33% do tamanho original) que tanto
# `BrowserClient.stop()` quanto `store_replay` precisam segurar inteira em
# memória. Sessões que estourarem o teto perdem só aquele blob (sinalizado em
# `trace_dropped_size_limit`/`video_dropped_size_limit`), não o resto do
# replay (actions/network continuam completos).
MAX_REPLAY_BLOB_BYTES = int(os.getenv("BROWSER_MAX_REPLAY_BLOB_BYTES", str(20 * 1024 * 1024)))

_playwright: Any | None = None
_browser: Any | None = None
_lp_browser: Any | None = None
_session_engine: dict[str, str] = {}
_pages: dict[str, Any] = {}
_contexts: dict[str, Any] = {}
_video_dirs: dict[str, str] = {}
_session_started_at: dict[str, float] = {}
_action_logs: dict[str, list[dict[str, Any]]] = {}
_last_used: dict[str, float] = {}
_console_logs: dict[str, list[str]] = {}
_page_errors: dict[str, list[str]] = {}
_network_logs: dict[str, list[dict[str, Any]]] = {}
_pending_requests: dict[str, dict[Any, float]] = {}
# Lembra qual netloc (host:porta) resolveu por último para cada sessão, para
# tentá-lo primeiro na próxima navegação em vez de sempre reiniciar do
# candidato original (item 8 do plano de robustez do navegador interno).
_last_successful_netloc: dict[str, str] = {}
# Sessões que o `_reap_loop` descartou por TTL enquanto ainda tinham
# trace/vídeo gravado — os bytes já foram jogados fora nesse momento (ver
# docstring de `_finalize_replay`), então isto é só um sinal de curta duração
# (podado depois de 1h) para o próximo `DELETE /sessions/{id}` distinguir
# "nunca houve nada" de "havia algo, mas expirou antes de alguém pedir" —
# item 9 do plano de robustez do navegador interno.
_expired_sessions: dict[str, float] = {}

# Um `asyncio.Lock` por sessão, serializando toda ação sobre a mesma `Page`
# (inclusive a criação do contexto): sem isto, duas requisições concorrentes
# para uma sessão nova podiam ambas ver `_pages.get(session_id) is None`,
# ambas criar um contexto Chromium, e a perdedora da corrida nunca era
# fechada (contexto + diretório de vídeo vazam até o processo cair); duas
# ações concorrentes na MESMA `Page` já criada colidem em comportamento
# indefinido do Playwright (não foi projetado pra ser pilotado por duas
# corrotinas ao mesmo tempo).
_session_locks: dict[str, asyncio.Lock] = {}
_session_locks_guard = asyncio.Lock()


async def _lock_for_session(session_id: str) -> asyncio.Lock:
    async with _session_locks_guard:
        lock = _session_locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            _session_locks[session_id] = lock
        return lock

LIGHTPANDA_CDP_URL = os.getenv("LIGHTPANDA_CDP_URL", "http://lightpanda:9222")


def _log_action(session_id: str, action: str, summary: str) -> None:
    lista = _action_logs.setdefault(session_id, [])
    inicio = _session_started_at.get(session_id, time.time())
    lista.append(
        {
            "t_offset_ms": int((time.time() - inicio) * 1000),
            "action": action,
            "summary": summary[:200],
        }
    )
    if len(lista) > 200:
        lista.pop(0)


async def _finalize_replay(session_id: str) -> dict[str, Any] | None:
    """Encerra a sessão liberando trace.zip + vídeo como bytes — chamado tanto
    pelo fechamento explícito (`DELETE /sessions/{id}`, que quer os bytes para
    subir no MinIO) quanto pela expiração por TTL (`_reap_loop`, que só quer
    liberar os recursos do Chromium e descarta o resultado: sessão expirou por
    inatividade, não há painel nem sessão de agente esperando o replay)."""
    context = _contexts.pop(session_id, None)
    page = _pages.pop(session_id, None)
    video_dir = _video_dirs.pop(session_id, None)
    started = _session_started_at.pop(session_id, None)
    actions = _action_logs.pop(session_id, [])
    network = _network_logs.pop(session_id, [])
    _last_used.pop(session_id, None)
    _console_logs.pop(session_id, None)
    _page_errors.pop(session_id, None)
    _pending_requests.pop(session_id, None)
    _session_engine.pop(session_id, None)
    _last_successful_netloc.pop(session_id, None)
    # Seguro remover mesmo se o chamador atual detém o lock: isto só tira a
    # entrada do dicionário, não invalida o objeto `asyncio.Lock` que ele já
    # segura — o próximo `_lock_for_session` para este `session_id` (uma
    # sessão nova, já que esta acabou de ser finalizada) cria um lock novo.
    _session_locks.pop(session_id, None)

    if context is None:
        return None

    trace_path = TRACE_ROOT / f"{session_id}.zip"
    video_obj = getattr(page, "video", None) if page is not None else None
    resultado: dict[str, Any] | None = None
    try:
        with suppress(Exception):
            await context.tracing.stop(path=str(trace_path))
        with suppress(Exception):
            await context.close()

        video_bytes = None
        if video_obj is not None:
            with suppress(Exception):
                video_file = await video_obj.path()
                video_bytes = Path(video_file).read_bytes()

        trace_bytes = trace_path.read_bytes() if trace_path.exists() else None

        trace_dropped = bool(trace_bytes) and len(trace_bytes) > MAX_REPLAY_BLOB_BYTES
        video_dropped = bool(video_bytes) and len(video_bytes) > MAX_REPLAY_BLOB_BYTES
        if trace_dropped:
            trace_bytes = None
        if video_dropped:
            video_bytes = None

        if trace_bytes or video_bytes or trace_dropped or video_dropped:
            resultado = {
                "started_at": started,
                "duration_ms": int((time.time() - started) * 1000) if started else None,
                "actions": actions,
                "network": network,
                "trace_base64": base64.b64encode(trace_bytes).decode("ascii")
                if trace_bytes
                else None,
                "video_base64": base64.b64encode(video_bytes).decode("ascii")
                if video_bytes
                else None,
                "trace_dropped_size_limit": trace_dropped,
                "video_dropped_size_limit": video_dropped,
            }
    finally:
        with suppress(Exception):
            trace_path.unlink(missing_ok=True)
        if video_dir:
            shutil.rmtree(video_dir, ignore_errors=True)

    return resultado


async def _reap_loop() -> None:
    while True:
        await asyncio.sleep(REAP_INTERVAL_SECONDS)
        agora = time.time()
        expiradas = [
            sid for sid, ultimo in _last_used.items() if agora - ultimo > SESSION_TTL_SECONDS
        ]
        for sid in expiradas:
            with suppress(Exception):
                lock = await _lock_for_session(sid)
                async with lock:
                    resultado = await _finalize_replay(sid)
                if resultado is not None:
                    _expired_sessions[sid] = agora

        # Poda marcadores velhos — sinal de curta duração para o próximo
        # `close_session` consultar, não registro de auditoria (ver
        # `_expired_sessions` acima).
        limite = agora - 3600
        for sid in [s for s, quando in _expired_sessions.items() if quando < limite]:
            _expired_sessions.pop(sid, None)


@asynccontextmanager
async def lifespan(app: FastAPI):
    reaper = asyncio.create_task(_reap_loop())
    try:
        yield
    finally:
        reaper.cancel()
        with suppress(asyncio.CancelledError):
            await reaper
        for context in _contexts.values():
            with suppress(Exception):
                await context.close()
        if _lp_browser is not None:
            with suppress(Exception):
                await _lp_browser.close()
        if _browser is not None:
            with suppress(Exception):
                await _browser.close()
        if _playwright is not None:
            with suppress(Exception):
                await _playwright.stop()


app = FastAPI(title="Eltanix Coder IDE Browser (Dual-Engine)", version="1.1.0", lifespan=lifespan)


async def _get_playwright() -> Any:
    from playwright.async_api import async_playwright

    global _playwright
    if _playwright is None:
        _playwright = await async_playwright().start()
    return _playwright


async def _launch_chromium() -> Any:
    global _browser
    if _browser is not None:
        return _browser
    pw = await _get_playwright()
    _browser = await pw.chromium.launch(headless=True)
    return _browser


async def _connect_lightpanda() -> Any:
    global _lp_browser
    if _lp_browser is not None and _lp_browser.is_connected():
        return _lp_browser
    pw = await _get_playwright()
    cdp_url = LIGHTPANDA_CDP_URL
    if not cdp_url.startswith("ws://") and not cdp_url.startswith("http://"):
        cdp_url = f"http://{cdp_url}"
    _lp_browser = await pw.chromium.connect_over_cdp(cdp_url, timeout=3000)
    return _lp_browser


async def _launch_browser(engine: str = "auto") -> tuple[Any, str]:
    """Retorna (browser, engine_used). Se 'lightpanda' ou 'auto', tenta Lightpanda com fallback seguro para Chromium."""
    if engine in ("lightpanda", "auto"):
        try:
            lp = await _connect_lightpanda()
            return lp, "lightpanda"
        except Exception:
            if engine == "lightpanda":
                pass
    cr = await _launch_chromium()
    return cr, "chromium"


def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    """Só a API fala com este serviço, nunca o browser do usuário — mesmo padrão do executor."""
    if not TOKEN:
        return
    presented = ""
    if authorization:
        scheme, _, valor = authorization.partition(" ")
        presented = valor.strip() if scheme.lower() == "bearer" else authorization.strip()
    if not presented or not hmac.compare_digest(presented, TOKEN):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token inválido")


Auth = Depends(require_token)


async def _get_page(session_id: str, engine: str = "auto") -> tuple[Any, str]:
    """Chame sempre com o lock de `_lock_for_session(session_id)` já
    adquirido pelo chamador — esta função não se protege sozinha (ver
    `_session_locks` acima)."""
    page = _pages.get(session_id)
    if page is not None and not page.is_closed():
        cached_engine = _session_engine.get(session_id, "chromium")
        # Lightpanda é leve mas não sustenta rasterização completa (sem
        # `Page.captureScreenshot` confiável via CDP) — se a sessão já está
        # presa nele e a ação atual pediu explicitamente chromium (hoje só
        # acontece para `screenshot`, ver `_run_action_locked`), falhar aqui
        # com uma mensagem clara em vez de deixar `page.screenshot()` estourar
        # mais abaixo um "ação falhou" genérico que mascara a causa real.
        if engine == "chromium" and cached_engine == "lightpanda":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=(
                    f"sessão '{session_id}' já está usando o motor 'lightpanda' (leve, sem "
                    "suporte a screenshot) — para capturar tela, feche esta sessão "
                    "(DELETE /sessions/{session_id}) e abra outra com engine='chromium' ou 'auto'."
                ),
            )
        _last_used[session_id] = time.time()
        return page, cached_engine

    if session_id not in _contexts and len(_contexts) >= MAX_CONCURRENT_SESSIONS:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"Limite de {MAX_CONCURRENT_SESSIONS} sessões de navegador simultâneas "
                "atingido — feche alguma sessão (painel ou agente) antes de abrir outra."
            ),
        )

    browser, engine_used = await _launch_browser(engine=engine)
    _session_engine[session_id] = engine_used

    video_dir = VIDEO_ROOT / session_id
    video_dir.mkdir(parents=True, exist_ok=True)
    context = await browser.new_context(
        viewport={"width": 1280, "height": 800},
        record_video_dir=str(video_dir) if engine_used == "chromium" else None,
        record_video_size={"width": 1280, "height": 800} if engine_used == "chromium" else None,
    )
    if engine_used == "chromium":
        with suppress(Exception):
            await context.tracing.start(screenshots=True, snapshots=True)

    page = await context.new_page()
    _contexts[session_id] = context
    _video_dirs[session_id] = str(video_dir)
    _session_started_at[session_id] = time.time()
    _pages[session_id] = page
    _last_used[session_id] = time.time()
    _console_logs.setdefault(session_id, [])
    _page_errors.setdefault(session_id, [])
    _network_logs.setdefault(session_id, [])
    _pending_requests.setdefault(session_id, {})
    _action_logs.setdefault(session_id, [])

    def _on_console(msg: Any) -> None:
        try:
            tipo = getattr(msg, "type", "log")
            if tipo in ("error", "warning"):
                texto = getattr(msg, "text", str(msg))
                _console_logs[session_id].append(f"[{tipo.upper()}] {texto}")
                if len(_console_logs[session_id]) > 50:
                    _console_logs[session_id].pop(0)
        except Exception:
            pass

    def _on_pageerror(exc: Any) -> None:
        try:
            _page_errors[session_id].append(str(exc))
            if len(_page_errors[session_id]) > 20:
                _page_errors[session_id].pop(0)
        except Exception:
            pass

    def _on_request(req: Any) -> None:
        try:
            pendentes = _pending_requests[session_id]
            pendentes[req] = time.perf_counter()
            # Requisições penduradas (SSE/long-poll/WS que nunca disparam
            # `response`/`requestfailed`) nunca eram removidas daqui — sem
            # limite, o dict cresce sem parar ao longo de uma sessão longa.
            # Descarta a mais antiga (dict é ordenado por inserção) quando
            # passa do limite, mesmo padrão de poda já usado em
            # `_console_logs`/`_page_errors`/`_network_logs`.
            if len(pendentes) > 200:
                pendentes.pop(next(iter(pendentes)), None)
        except Exception:
            pass

    def _record_response(req: Any, status_code: int | None, tamanho: int | None) -> None:
        inicio = _pending_requests[session_id].pop(req, None)
        duracao_ms = int((time.perf_counter() - inicio) * 1000) if inicio is not None else None
        entradas = _network_logs[session_id]
        session_start = _session_started_at.get(session_id, time.time())
        entradas.append(
            {
                "method": getattr(req, "method", "?"),
                "url": getattr(req, "url", ""),
                "resource_type": getattr(req, "resource_type", None),
                "status": status_code,
                "duration_ms": duracao_ms,
                "size_bytes": tamanho,
                # Fase 4c: permite correlacionar cada requisição com o marcador
                # da timeline de replay mais próximo (mesma base de tempo que
                # `_log_action`, relativa ao início da sessão).
                "t_offset_ms": int((time.time() - session_start) * 1000),
            }
        )
        if len(entradas) > 50:
            entradas.pop(0)

    def _on_response(resp: Any) -> None:
        try:
            tamanho = None
            with suppress(Exception):
                headers = resp.headers
                comprimento = headers.get("content-length") if headers else None
                tamanho = int(comprimento) if comprimento is not None else None
            _record_response(resp.request, getattr(resp, "status", None), tamanho)
        except Exception:
            pass

    def _on_requestfailed(req: Any) -> None:
        try:
            _record_response(req, None, None)
        except Exception:
            pass

    try:
        page.on("console", _on_console)
        page.on("pageerror", _on_pageerror)
        page.on("request", _on_request)
        page.on("response", _on_response)
        page.on("requestfailed", _on_requestfailed)
    except Exception:
        pass

    return page, engine_used


def _check_lightpanda_sync(cdp_url: str) -> bool:
    """Chamada bloqueante (`urllib.request`) — só é segura fora do event
    loop, ver o `asyncio.to_thread` em `health()` abaixo."""
    import urllib.request

    try:
        with urllib.request.urlopen(f"{cdp_url}/json/version", timeout=1.0) as resp:
            return resp.status == 200
    except Exception:
        return False


@app.get("/health")
async def health() -> dict[str, Any]:
    lp_ok = False
    if _lp_browser is not None and _lp_browser.is_connected():
        lp_ok = True
    else:
        # Docker consulta este endpoint a cada `SESSION_TTL_SECONDS`/3 (ver
        # healthcheck no docker-compose.yml) — antes, `urllib.request.urlopen`
        # síncrono aqui bloqueava o event loop inteiro (até 1s de timeout) a
        # cada poll, travando toda requisição concorrente nesse intervalo.
        cdp_url = LIGHTPANDA_CDP_URL.replace("ws://", "http://")
        lp_ok = await asyncio.to_thread(_check_lightpanda_sync, cdp_url)

    return {
        "status": "ok",
        "sessions": len(_contexts),
        "chromium_launched": _browser is not None,
        "lightpanda_available": lp_ok,
        "engines_supported": ["chromium", "lightpanda"],
    }


class CreateSessionRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    engine: Literal["auto", "lightpanda", "chromium"] = "auto"


@app.post("/sessions", dependencies=[Auth])
async def create_session(payload: CreateSessionRequest) -> dict[str, Any]:
    lock = await _lock_for_session(payload.session_id)
    async with lock:
        _page, engine_used = await _get_page(payload.session_id, engine=payload.engine)
    return {"session_id": payload.session_id, "created": True, "engine_used": engine_used}


ALLOWED_SCHEMES = ("http://", "https://")

# Hosts de metadados cloud / link-local — nunca são um alvo legítimo,
# independente de quem pediu a navegação. Cópia sincronizada (não
# importada) de `eltanix.security.url_safety.BLOCKED_HOSTNAMES`: este
# serviço roda isolado num container mínimo (ver Dockerfile — não instala o
# pacote `eltanix` de propósito, para manter a menor superfície possível
# numa rede que já é a mais permissiva do sistema) — ver o addendum do ADR
# 0007 para o porquê da duplicação ser intencional.
BLOCKED_HOSTS = {
    "169.254.169.254",
    "metadata.google.internal",
    "instance-data",
}

# `localhost`/`127.0.0.1`/`0.0.0.0` são o gatilho legítimo da substituição
# de candidatos logo abaixo em `run_action` (sessão panel-* tenta
# `eltanix-<sid>`/`host.docker.internal` como fallback) — nunca devem ser
# bloqueados aqui, mesmo sendo tecnicamente loopback/reservado.
_LOOPBACK_TRIGGERS = {"localhost", "127.0.0.1", "0.0.0.0"}

# Hosts de infraestrutura Docker que nenhuma sessão deveria alcançar
# diretamente por URL explícita (nem painel, nem agente) — `browser_net` não
# lhes dá rota mesmo, mas rejeitar cedo dá um erro claro em vez de um
# timeout de conexão confuso.
_INFRA_HOSTS_ALWAYS_BLOCKED = {"executor", "redis", "minio", "postgres", "mcp-scanner"}

# Hosts Docker-internos que só sessões de AGENTE podem alcançar diretamente
# (a allowlist correspondente vive em
# `eltanix.agent.tools.browser::is_agent_local_test_target`) — sessões do
# PAINEL MANUAL (`panel-*`) nunca devem, porque o resultado é renderizado
# num `<iframe>` do navegador REAL do usuário, fora do Docker, que não
# resolve esses nomes (ver item 2 / `url_is_internal_fallback` abaixo para o
# sinal complementar quando a substituição acontece por baixo dos panos).
_DOCKER_INTERNAL_HOSTS_BLOCKED_FOR_PANEL = {"web", "api", "host.docker.internal"}


def _canonical_ipv4(host: str) -> str | None:
    """IPv4 em codificação alternativa (decimal `2130706433`, octal
    `0177.0.0.1`, hex `0x7f.0.0.1`, curta `127.1`) → forma pontilhada
    canônica; senão `None`. Cópia sincronizada (não importada) de
    `eltanix.security.url_safety.canonical_ipv4` — mesmo motivo da duplicação
    do resto deste bloco (ver docstring de BLOCKED_HOSTS e addendum do ADR
    0007). Sem isto, `http://2130706433/` fura o bloqueio de IP privado."""
    try:
        packed = socket.inet_aton(host)
    except OSError:
        return None
    return socket.inet_ntoa(packed)


def validate_url(url: str | None, *, session_id: str = "") -> None:
    if not url or not url.startswith(ALLOWED_SCHEMES):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="url precisa ser http(s)")
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="url sem hostname válido")

    # Normaliza IPv4 codificado de forma exótica para a checagem de IP
    # privado/reservado lá embaixo enxergar o alvo real.
    hostname = _canonical_ipv4(hostname) or hostname

    if hostname in BLOCKED_HOSTS or hostname.startswith("169.254."):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"Acesso ao host '{hostname}' é restrito por segurança (SSRF).",
        )

    if hostname in _INFRA_HOSTS_ALWAYS_BLOCKED:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"Acesso ao host '{hostname}' é restrito por segurança (SSRF).",
        )

    is_panel = session_id.startswith("panel-")
    if is_panel and (
        hostname in _DOCKER_INTERNAL_HOSTS_BLOCKED_FOR_PANEL
        or hostname.startswith("eltanix-")
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=(
                f"O host '{hostname}' só existe dentro da rede Docker e nunca será alcançável "
                "pelo navegador real do host — o painel manual não navega para ele diretamente. "
                "Digite `localhost:<porta>` (o serviço resolve o alvo correto internamente)."
            ),
        )

    if hostname in _LOOPBACK_TRIGGERS:
        return

    with suppress(ValueError):
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Acesso ao IP privado/reservado '{hostname}' é restrito por segurança (SSRF).",
            )


class ActionRequest(BaseModel):
    action: Literal["navigate", "click", "type", "screenshot", "content"]
    url: str | None = None
    selector: str | None = None
    x: float | None = None
    y: float | None = None
    text: str | None = None
    engine: Literal["auto", "lightpanda", "chromium"] = "auto"
    timeout_ms: int = Field(default=15_000, ge=100, le=60_000)
    # Default `False`: o agente (`agent/tools/browser.py`) navega várias vezes
    # em sequência (DOM-only, click/type/content) sem precisar de imagem a
    # cada passo — forçar rasterização em toda `navigate` anulava a vantagem
    # de leveza do Lightpanda e custava um render completo do Chromium à toa.
    # O painel manual (`api/routes/browser.py`) passa `True` explicitamente.
    capture_screenshot: bool = False


@app.post("/sessions/{session_id}/action", dependencies=[Auth])
async def run_action(session_id: str, payload: ActionRequest) -> dict[str, Any]:
    # Serializa TODA ação desta sessão (inclusive a criação preguiçosa da
    # página) atrás do mesmo lock — ver o comentário em `_session_locks`
    # acima para as duas classes de corrida que isto fecha.
    lock = await _lock_for_session(session_id)
    async with lock:
        return await _run_action_locked(session_id, payload)


async def _run_action_locked(session_id: str, payload: ActionRequest) -> dict[str, Any]:
    # Se a ação for screenshot e o engine for auto, forçamos chromium para rasterização completa
    engine_hint = payload.engine
    if payload.action == "screenshot" and engine_hint == "auto":
        engine_hint = "chromium"

    page, engine_used = await _get_page(session_id, engine=engine_hint)
    inicio = time.perf_counter()

    try:
        if payload.action == "navigate":
            validate_url(payload.url, session_id=session_id)
            alvo_url = payload.url or ""
            parsed = urlparse(alvo_url)
            hostname = (parsed.hostname or "").lower()
            port = parsed.port

            urls_to_try = [alvo_url]
            if hostname in {"localhost", "127.0.0.1", "0.0.0.0"}:
                clean_sid = session_id.removeprefix("panel-")
                sandbox_host = f"eltanix-{clean_sid}"
                host_gateway = os.getenv("HOST_GATEWAY_HOST", "host.docker.internal")

                candidatos: list[str] = []
                if port:
                    candidatos.append(parsed._replace(netloc=f"{sandbox_host}:{port}").geturl())
                    if session_id.startswith("panel-"):
                        candidatos.append(parsed._replace(netloc=f"{host_gateway}:{port}").geturl())
                else:
                    candidatos.append(parsed._replace(netloc=sandbox_host).geturl())
                    if session_id.startswith("panel-"):
                        candidatos.append(parsed._replace(netloc=host_gateway).geturl())

                # Tenta primeiro o candidato que resolveu da última vez nesta
                # sessão, em vez de sempre reiniciar do topo.
                lembrado = _last_successful_netloc.get(session_id)
                if lembrado:
                    candidatos.sort(key=lambda c: urlparse(c).netloc != lembrado)

                urls_to_try = candidatos
            # Só uma URL "de verdade" (não candidato de fallback interno) —
            # nenhuma substituição em jogo, então nunca é fallback interno.
            eh_url_original_unica = urls_to_try == [alvo_url]

            # Limpa logs da sessão anterior para esta nova navegação
            _console_logs[session_id] = []
            _page_errors[session_id] = []
            _network_logs[session_id] = []
            _pending_requests[session_id] = {}

            resposta = None
            ultimo_erro = None
            url_bem_sucedida: str | None = None
            # Orçamento real do chamador (até 60s, `ActionRequest.timeout_ms`)
            # — antes ficava artificialmente limitado a 15s mesmo quando o
            # caller pedia mais.
            limite_tempo = time.perf_counter() + payload.timeout_ms / 1000

            while True:
                for tentativa_url in urls_to_try:
                    try:
                        timeout_tentativa = min(payload.timeout_ms, 5000)
                        resposta = await page.goto(
                            tentativa_url,
                            timeout=timeout_tentativa,
                            wait_until="domcontentloaded",
                        )
                        ultimo_erro = None
                        url_bem_sucedida = tentativa_url
                        break
                    except Exception as exc:  # noqa: BLE001
                        ultimo_erro = exc

                if ultimo_erro is None:
                    break

                if time.perf_counter() >= limite_tempo:
                    break

                err_str = str(ultimo_erro)
                if (
                    "ERR_CONNECTION_REFUSED" in err_str
                    or "ERR_NAME_NOT_RESOLVED" in err_str
                    or "Timeout" in err_str
                ):
                    await asyncio.sleep(0.3)
                else:
                    break

            if ultimo_erro is not None:
                err_msg = str(ultimo_erro)
                if "ERR_CONNECTION_REFUSED" in err_msg:
                    raise HTTPException(
                        status.HTTP_502_BAD_GATEWAY,
                        detail=(
                            f"Conexão recusada ao conectar em {alvo_url} (porta {port or 80}). "
                            f"O servidor web no sandbox ainda não está pronto ou não está escutando na porta {port or 80}."
                        ),
                    )
                raise ultimo_erro

            # Sinaliza explicitamente quando a URL efetivamente carregada é
            # uma substituição Docker-interna (`eltanix-<sid>`/
            # `host.docker.internal`) em vez da URL pedida — sem isto, quem
            # chama (painel manual → iframe "Ao Vivo" no navegador real do
            # usuário) não tinha como saber que recebeu um hostname que só
            # resolve dentro do `browser_net`.
            url_is_internal_fallback = (
                not eh_url_original_unica and url_bem_sucedida is not None and url_bem_sucedida != alvo_url
            )
            if url_is_internal_fallback and url_bem_sucedida:
                _last_successful_netloc[session_id] = urlparse(url_bem_sucedida).netloc

            image_b64 = None
            if payload.capture_screenshot:
                try:
                    png = await page.screenshot(timeout=min(payload.timeout_ms, 5000))
                    image_b64 = base64.b64encode(png).decode("ascii")
                except Exception:  # noqa: BLE001
                    pass

            _log_action(session_id, "navigate", page.url)
            return {
                "ok": True,
                "url": page.url,
                "original_url": alvo_url,
                "url_is_internal_fallback": url_is_internal_fallback,
                "title": await page.title(),
                "status": resposta.status if resposta else None,
                "duration_ms": int((time.perf_counter() - inicio) * 1000),
                "engine_used": engine_used,
                "image_base64": image_b64,
                "console_errors": list(_console_logs.get(session_id, [])),
                "page_errors": list(_page_errors.get(session_id, [])),
            }

        if payload.action == "click":
            if payload.selector:
                await page.click(payload.selector, timeout=payload.timeout_ms)
            elif payload.x is not None and payload.y is not None:
                await page.mouse.click(payload.x, payload.y)
            else:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="informe selector ou x/y")
            _log_action(session_id, "click", payload.selector or f"{payload.x},{payload.y}")
            return {
                "ok": True,
                "engine_used": engine_used,
                "duration_ms": int((time.perf_counter() - inicio) * 1000),
                "console_errors": list(_console_logs.get(session_id, [])),
                "page_errors": list(_page_errors.get(session_id, [])),
            }

        if payload.action == "type":
            if not payload.selector or payload.text is None:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST, detail="type exige selector e text"
                )
            await page.fill(payload.selector, payload.text, timeout=payload.timeout_ms)
            _log_action(session_id, "type", f"{payload.selector}: {payload.text[:50]}")
            return {
                "ok": True,
                "engine_used": engine_used,
                "duration_ms": int((time.perf_counter() - inicio) * 1000),
                "console_errors": list(_console_logs.get(session_id, [])),
                "page_errors": list(_page_errors.get(session_id, [])),
            }

        if payload.action == "screenshot":
            png = await page.screenshot(timeout=payload.timeout_ms)
            _log_action(session_id, "screenshot", page.url)
            return {
                "ok": True,
                "engine_used": engine_used,
                "image_base64": base64.b64encode(png).decode("ascii"),
                "url": page.url,
                "duration_ms": int((time.perf_counter() - inicio) * 1000),
                "console_errors": list(_console_logs.get(session_id, [])),
                "page_errors": list(_page_errors.get(session_id, [])),
            }

        if payload.action == "content":
            texto = await page.inner_text("body")
            _log_action(session_id, "content", page.url)
            return {
                "ok": True,
                "engine_used": engine_used,
                "text": texto[:20_000],
                "duration_ms": int((time.perf_counter() - inicio) * 1000),
                "console_errors": list(_console_logs.get(session_id, [])),
                "page_errors": list(_page_errors.get(session_id, [])),
            }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"ação falhou: {exc}"
        ) from exc

    raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"ação desconhecida: {payload.action}")


@app.get("/sessions/{session_id}/network", dependencies=[Auth])
async def get_network_log(session_id: str) -> dict[str, Any]:
    return {"requests": list(_network_logs.get(session_id, []))}


@app.websocket("/sessions/{session_id}/stream", dependencies=[Auth])
async def stream_screencast(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    lock = await _lock_for_session(session_id)
    async with lock:
        page, _ = await _get_page(session_id, engine="chromium")
    cdp = await page.context.new_cdp_session(page)

    def _on_frame(params: dict[str, Any]) -> None:
        async def _forward() -> None:
            try:
                await websocket.send_json(
                    {"type": "frame", "data": params.get("data"), "ts": time.time()}
                )
            except Exception:
                return
            with suppress(Exception):
                await cdp.send(
                    "Page.screencastFrameAck", {"sessionId": params["sessionId"]}
                )

        asyncio.create_task(_forward())

    cdp.on("Page.screencastFrame", _on_frame)

    try:
        await cdp.send(
            "Page.startScreencast",
            {"format": "jpeg", "quality": 70, "maxWidth": 1280, "maxHeight": 800, "everyNthFrame": 1},
        )
        while True:
            # A conexão só serve para enviar frames; qualquer mensagem do lado
            # da API (inclusive desconexão) é o sinal para encerrar o laço.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        with suppress(Exception):
            await cdp.send("Page.stopScreencast")
        with suppress(Exception):
            await cdp.detach()


@app.delete("/sessions/{session_id}", dependencies=[Auth])
async def close_session(session_id: str) -> dict[str, Any]:
    lock = await _lock_for_session(session_id)
    async with lock:
        tinha_sessao = session_id in _contexts
        replay = await _finalize_replay(session_id) if tinha_sessao else None
    resultado: dict[str, Any] = {"closed": tinha_sessao, **(replay or {})}
    if not tinha_sessao and _expired_sessions.pop(session_id, None) is not None:
        # A sessão não existe mais porque o `_reap_loop` já a descartou por
        # TTL antes deste DELETE chegar — e ela tinha trace/vídeo em
        # andamento quando isso aconteceu (ver `_expired_sessions`). O
        # chamador (`apps/api/src/eltanix/browser/client.py::stop()`)
        # propaga esta flag para marcar o replay como perdido em vez de
        # simplesmente "não havia nada" (item 9 do plano de robustez).
        resultado["expired_by_ttl"] = True
    return resultado
