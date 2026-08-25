"""Cliente do serviço browser (Fase 7 — verificação visual do agente).

Mesmo motivo do executor (ADR 0002) na direção oposta: o sandbox de execução
de comando é isolado de rede por padrão (`network_mode=none`) — é uma garantia
que outras ferramentas dependem implicitamente continuar valendo. Um navegador
para verificar UI precisa de rede de verdade (alcançar o servidor da própria
aplicação), então em vez de afrouxar esse sandbox para todo mundo, o serviço
que roda o Chromium é isolado à parte, numa rede própria que só alcança
`web`/`api` (ver docker-compose.yml, rede `browser_net` com `internal: true`)
— nunca a internet pública, nunca o `docker.sock`.
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import httpx

from sicoobito.logging_setup import get_logger

log = get_logger(__name__)

_TIMEOUT_MARGEM = 15.0


class BrowserError(RuntimeError):
    pass


class BrowserUnavailableError(BrowserError):
    pass


@dataclass(slots=True)
class BrowserConfig:
    base_url: str
    token: str = ""


class BrowserClient:
    """Uma página de navegador por sessão do agente, operada pelo serviço browser."""

    def __init__(self, session_id: str, config: BrowserConfig, client: httpx.AsyncClient) -> None:
        self.session_id = session_id
        self.config = config
        self._client = client
        self._started = False

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.token}"} if self.config.token else {}

    async def start(self, engine: str = "auto", *, retries: int = 3) -> None:
        ultimo_erro = None
        for tentativa in range(retries + 1):
            try:
                resposta = await self._client.post(
                    f"{self.config.base_url}/sessions",
                    json={"session_id": self.session_id, "engine": engine},
                    headers=self._headers(),
                    timeout=10.0,
                )
                if resposta.status_code >= 400:
                    raise BrowserError(
                        f"serviço de navegador recusou criar a sessão: {resposta.text[:300]}"
                    )
                self._started = True
                return
            except httpx.HTTPError as exc:
                ultimo_erro = exc
                if tentativa < retries:
                    import asyncio

                    await asyncio.sleep(0.5 * (tentativa + 1))
        raise BrowserUnavailableError(
            f"serviço de navegador inacessível em {self.config.base_url}: {ultimo_erro}"
        ) from ultimo_erro

    create_session = start

    async def action(self, payload: dict[str, Any], *, timeout_ms: int = 15_000) -> dict[str, Any]:
        if not self._started:
            await self.start()

        timeout = (timeout_ms / 1000) + _TIMEOUT_MARGEM
        ultimo_erro = None
        for tentativa in range(3):
            try:
                resposta = await self._client.post(
                    f"{self.config.base_url}/sessions/{self.session_id}/action",
                    json={**payload, "timeout_ms": timeout_ms},
                    headers=self._headers(),
                    timeout=timeout,
                )
                if resposta.status_code >= 400:
                    raise BrowserError(f"serviço de navegador retornou erro: {resposta.text[:300]}")
                return resposta.json()
            except httpx.TimeoutException as exc:
                raise BrowserError(f"ação excedeu {timeout_ms}ms") from exc
            except httpx.HTTPError as exc:
                ultimo_erro = exc
                if tentativa < 2:
                    import asyncio

                    await asyncio.sleep(0.4)
        msg_erro = f"falha ao falar com o serviço de navegador: {ultimo_erro}"
        raise BrowserError(msg_erro) from ultimo_erro

    async def network_log(self) -> list[dict[str, Any]]:
        """Só faz sentido depois de `start()` — sessão sem página não tem log."""
        if not self._started:
            return []
        try:
            resposta = await self._client.get(
                f"{self.config.base_url}/sessions/{self.session_id}/network",
                headers=self._headers(),
                timeout=10.0,
            )
            if resposta.status_code >= 400:
                raise BrowserError(f"serviço de navegador retornou erro: {resposta.text[:300]}")
            return resposta.json().get("requests", [])
        except httpx.HTTPError as exc:
            raise BrowserError(f"falha ao ler log de rede: {exc}") from exc

    async def stop(self, *, force: bool = False) -> dict[str, Any] | None:
        """Por padrão (`force=False`), não faz nada se `_started` for `False`
        — evita um DELETE inútil para sessões que nunca chegaram a usar o
        navegador. Tanto o `AgentRunner` quanto o painel manual do IDE (`api/
        routes/browser.py`) mantêm uma instância por sessão durante toda a
        vida dela, então `_started` reflete de verdade se ESTA sessão chamou
        `start()` — `force=True` fica disponível para quem não tiver essa
        garantia.

        Retorna o corpo da resposta do serviço (Fase 4b: `trace_base64`/
        `video_base64`/`actions`, quando a sessão gravou algo) para quem quiser
        persistir o replay — `None` se não havia sessão para fechar ou a
        chamada falhou (degrada, não derruba: replay é conveniência, não deve
        impedir o encerramento da sessão)."""
        if not self._started and not force:
            return None
        self._started = False
        try:
            resposta = await self._client.delete(
                f"{self.config.base_url}/sessions/{self.session_id}",
                headers=self._headers(),
                timeout=30.0,
            )
            if resposta.status_code < 400:
                with suppress(Exception):
                    return resposta.json()
        except httpx.HTTPError as exc:
            log.warning("browser.stop.failed", session=self.session_id, error=str(exc))
        return None
