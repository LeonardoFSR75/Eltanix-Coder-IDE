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
import time
from contextlib import asynccontextmanager, suppress
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

TOKEN = os.getenv("BROWSER_TOKEN", "")
SESSION_TTL_SECONDS = int(os.getenv("BROWSER_SESSION_TTL_SECONDS", "1800"))
REAP_INTERVAL_SECONDS = int(os.getenv("BROWSER_REAP_INTERVAL_SECONDS", "300"))

_playwright: Any | None = None
_browser: Any | None = None
_pages: dict[str, Any] = {}
_last_used: dict[str, float] = {}


async def _reap_loop() -> None:
    while True:
        await asyncio.sleep(REAP_INTERVAL_SECONDS)
        agora = time.time()
        expiradas = [sid for sid, ultimo in _last_used.items() if agora - ultimo > SESSION_TTL_SECONDS]
        for sid in expiradas:
            page = _pages.pop(sid, None)
            _last_used.pop(sid, None)
            if page is not None and not page.is_closed():
                await page.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    reaper = asyncio.create_task(_reap_loop())
    try:
        yield
    finally:
        reaper.cancel()
        with suppress(asyncio.CancelledError):
            await reaper
        for page in _pages.values():
            if not page.is_closed():
                await page.close()
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
    page = await browser.new_page()
    _pages[session_id] = page
    _last_used[session_id] = time.time()
    return page


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "sessions": len(_pages), "browser_launched": _browser is not None}


class CreateSessionRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)


@app.post("/sessions", dependencies=[Auth])
async def create_session(payload: CreateSessionRequest) -> dict[str, Any]:
    await _get_page(payload.session_id)
    return {"session_id": payload.session_id, "created": True}


from urllib.parse import urlparse

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
                    candidatos.append(parsed._replace(netloc=f"{host_gateway}:{port}").geturl())
                else:
                    candidatos.append(parsed._replace(netloc=sandbox_host).geturl())
                    candidatos.append(parsed._replace(netloc=host_gateway).geturl())
                urls_to_try = [*candidatos, alvo_url]

            resposta = None
            ultimo_erro = None
            for tentativa_url in urls_to_try:
                try:
                    resposta = await page.goto(
                        tentativa_url, timeout=payload.timeout_ms, wait_until="domcontentloaded"
                    )
                    ultimo_erro = None
                    break
                except Exception as exc:  # noqa: BLE001
                    ultimo_erro = exc

            if ultimo_erro is not None:
                raise ultimo_erro

            return {
                "ok": True,
                "url": page.url,
                "title": await page.title(),
                "status": resposta.status if resposta else None,
                "duration_ms": int((time.perf_counter() - inicio) * 1000),
            }

        if payload.action == "click":
            if payload.selector:
                await page.click(payload.selector, timeout=payload.timeout_ms)
            elif payload.x is not None and payload.y is not None:
                await page.mouse.click(payload.x, payload.y)
            else:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="informe selector ou x/y")
            return {"ok": True, "duration_ms": int((time.perf_counter() - inicio) * 1000)}

        if payload.action == "type":
            if not payload.selector or payload.text is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="type exige selector e text")
            await page.fill(payload.selector, payload.text, timeout=payload.timeout_ms)
            return {"ok": True, "duration_ms": int((time.perf_counter() - inicio) * 1000)}

        if payload.action == "screenshot":
            png = await page.screenshot(timeout=payload.timeout_ms)
            return {
                "ok": True,
                "image_base64": base64.b64encode(png).decode("ascii"),
                "url": page.url,
                "duration_ms": int((time.perf_counter() - inicio) * 1000),
            }

        if payload.action == "content":
            texto = await page.inner_text("body")
            return {
                "ok": True,
                "text": texto[:20_000],
                "duration_ms": int((time.perf_counter() - inicio) * 1000),
            }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"ação falhou: {exc}"
        ) from exc

    raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"ação desconhecida: {payload.action}")


@app.delete("/sessions/{session_id}", dependencies=[Auth])
async def close_session(session_id: str) -> dict[str, Any]:
    page = _pages.pop(session_id, None)
    _last_used.pop(session_id, None)
    closed = False
    if page is not None and not page.is_closed():
        await page.close()
        closed = True
    return {"closed": closed}
