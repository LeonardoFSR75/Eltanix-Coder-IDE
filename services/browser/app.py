"""Browser: serviço isolado que roda o Chromium headless para a ferramenta
de verificação visual do agente (`browser_action`, ver
`apps/api/src/sicoobito/agent/tools/browser.py`).

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
import os
import shutil
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

# Trace/vídeo por sessão (Fase 4b) — arquivos passam por disco local antes de
# virar bytes na resposta; `api` é quem de fato sobe pro MinIO (este serviço
# não alcança `minio`, só `web`/`api`, ver docstring do módulo).
VIDEO_ROOT = Path(tempfile.gettempdir()) / "sicoobito-browser-videos"
TRACE_ROOT = Path(tempfile.gettempdir()) / "sicoobito-browser-traces"
VIDEO_ROOT.mkdir(parents=True, exist_ok=True)
TRACE_ROOT.mkdir(parents=True, exist_ok=True)

_playwright: Any | None = None
_browser: Any | None = None
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
    _last_used.pop(session_id, None)
    _console_logs.pop(session_id, None)
    _page_errors.pop(session_id, None)
    _network_logs.pop(session_id, None)
    _pending_requests.pop(session_id, None)

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

        if trace_bytes or video_bytes:
            resultado = {
                "started_at": started,
                "duration_ms": int((time.time() - started) * 1000) if started else None,
                "actions": actions,
                "trace_base64": base64.b64encode(trace_bytes).decode("ascii")
                if trace_bytes
                else None,
                "video_base64": base64.b64encode(video_bytes).decode("ascii")
                if video_bytes
                else None,
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
                await _finalize_replay(sid)


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
        if _browser is not None:
            await _browser.close()
        if _playwright is not None:
            await _playwright.stop()


app = FastAPI(title="SicoobitoCode Browser", version="1.0.0", lifespan=lifespan)


async def _launch_browser() -> Any:
    from playwright.async_api import async_playwright

    global _playwright, _browser
    if _browser is not None:
        return _browser
    pw = await async_playwright().start()
    _playwright = pw
    _browser = await pw.chromium.launch(headless=True)
    return _browser


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


async def _get_page(session_id: str) -> Any:
    page = _pages.get(session_id)
    if page is not None and not page.is_closed():
        _last_used[session_id] = time.time()
        return page
    browser = await _launch_browser()

    video_dir = VIDEO_ROOT / session_id
    video_dir.mkdir(parents=True, exist_ok=True)
    context = await browser.new_context(
        viewport={"width": 1280, "height": 800},
        record_video_dir=str(video_dir),
        record_video_size={"width": 1280, "height": 800},
    )
    # Best-effort: uma sessão sem trace ainda funciona para navegação normal,
    # só perde o replay (`_finalize_replay` degrada sozinho se isto falhar).
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
            _pending_requests[session_id][req] = time.perf_counter()
        except Exception:
            pass

    def _record_response(req: Any, status_code: int | None, tamanho: int | None) -> None:
        inicio = _pending_requests[session_id].pop(req, None)
        duracao_ms = int((time.perf_counter() - inicio) * 1000) if inicio is not None else None
        entradas = _network_logs[session_id]
        entradas.append(
            {
                "method": getattr(req, "method", "?"),
                "url": getattr(req, "url", ""),
                "resource_type": getattr(req, "resource_type", None),
                "status": status_code,
                "duration_ms": duracao_ms,
                "size_bytes": tamanho,
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

    return page


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "sessions": len(_contexts), "browser_launched": _browser is not None}


class CreateSessionRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)


@app.post("/sessions", dependencies=[Auth])
async def create_session(payload: CreateSessionRequest) -> dict[str, Any]:
    await _get_page(payload.session_id)
    return {"session_id": payload.session_id, "created": True}


ALLOWED_SCHEMES = ("http://", "https://")
BLOCKED_HOSTS = {
    "169.254.169.254",
    "metadata.google.internal",
    "instance-data",
}


def validate_url(url: str | None) -> None:
    if not url or not url.startswith(ALLOWED_SCHEMES):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="url precisa ser http(s)")
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if not hostname or hostname in BLOCKED_HOSTS or hostname.startswith("169.254."):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"Acesso ao host '{hostname}' é restrito por segurança (SSRF).",
        )


class ActionRequest(BaseModel):
    action: Literal["navigate", "click", "type", "screenshot", "content"]
    url: str | None = None
    selector: str | None = None
    x: float | None = None
    y: float | None = None
    text: str | None = None
    timeout_ms: int = Field(default=15_000, ge=100, le=60_000)


@app.post("/sessions/{session_id}/action", dependencies=[Auth])
async def run_action(session_id: str, payload: ActionRequest) -> dict[str, Any]:
    page = await _get_page(session_id)
    inicio = time.perf_counter()

    try:
        if payload.action == "navigate":
            validate_url(payload.url)
            alvo_url = payload.url or ""
            parsed = urlparse(alvo_url)
            hostname = (parsed.hostname or "").lower()
            port = parsed.port

            urls_to_try = [alvo_url]
            if hostname in {"localhost", "127.0.0.1", "0.0.0.0"}:
                clean_sid = session_id.removeprefix("panel-")
                sandbox_host = f"sicoobito-{clean_sid}"
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
                urls_to_try = candidatos

            # Limpa logs da sessão anterior para esta nova navegação
            _console_logs[session_id] = []
            _page_errors[session_id] = []
            _network_logs[session_id] = []
            _pending_requests[session_id] = {}

            resposta = None
            ultimo_erro = None
            limite_tempo = time.perf_counter() + min(payload.timeout_ms / 1000, 15.0)

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

            image_b64 = None
            try:
                png = await page.screenshot(timeout=min(payload.timeout_ms, 5000))
                image_b64 = base64.b64encode(png).decode("ascii")
            except Exception:  # noqa: BLE001
                pass

            _log_action(session_id, "navigate", page.url)
            return {
                "ok": True,
                "url": page.url,
                "title": await page.title(),
                "status": resposta.status if resposta else None,
                "duration_ms": int((time.perf_counter() - inicio) * 1000),
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
                "duration_ms": int((time.perf_counter() - inicio) * 1000),
                "console_errors": list(_console_logs.get(session_id, [])),
                "page_errors": list(_page_errors.get(session_id, [])),
            }

        if payload.action == "screenshot":
            png = await page.screenshot(timeout=payload.timeout_ms)
            _log_action(session_id, "screenshot", page.url)
            return {
                "ok": True,
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
    """Screencast CDP ao vivo — só a API fala com isto, nunca o browser do
    usuário direto (mesma garantia de `require_token`, que já validou o
    handshake via `dependencies=[Auth]` antes deste corpo rodar).

    `Page.startScreencast` é uma chamada CDP crua (não faz parte da API alta
    do Playwright) — cada frame chega via evento `Page.screencastFrame` e
    precisa ser confirmado (`Page.screencastFrameAck`) ou o Chromium para de
    mandar frames novos, achando que o consumidor travou.
    """
    await websocket.accept()
    page = await _get_page(session_id)
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
    tinha_sessao = session_id in _contexts
    replay = await _finalize_replay(session_id) if tinha_sessao else None
    return {"closed": tinha_sessao, **(replay or {})}
