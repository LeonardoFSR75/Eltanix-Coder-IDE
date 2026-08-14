"""Cliente do serviço executor.

Substitui o acesso direto ao daemon do Docker (ver ADR 0002). A interface
pública é a mesma de antes — `Sandbox.exec()`, `SandboxManager.acquire()` — para
que as ferramentas do agente não saibam quem executa de fato.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx

from sicoobito.logging_setup import get_logger
from sicoobito.sandbox.container import ExecResult, SandboxError, SandboxUnavailableError

log = get_logger(__name__)

_TIMEOUT_MARGEM = 30.0


@dataclass(slots=True)
class ExecutorConfig:
    base_url: str
    token: str = ""
    ttl_seconds: int = 3600
    # Default de `run_command` quando o modelo não passa `timeout` explícito.
    # Antes ficava hardcoded em 300 aqui dentro, ignorando
    # `SANDBOX_TIMEOUT_SECONDS` — que só valia no modo local (`SandboxConfig`,
    # `sandbox/container.py`). Em produção (`EXECUTOR_URL` setado, ADR 0002)
    # o valor da env var não tinha efeito nenhum sobre o timeout real.
    timeout_seconds: int = 300


class RemoteSandbox:
    """Um sandbox operado pelo executor."""

    def __init__(
        self,
        session_id: str,
        workspace: Path,
        config: ExecutorConfig,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.session_id = session_id
        self.workspace = workspace
        self.config = config
        self._client = client
        self.created_at = 0.0
        self._started = False

    @property
    def running(self) -> bool:
        return self._started

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.token}"} if self.config.token else {}

    async def _get_client(self, timeout_seconds: float = 120.0) -> tuple[httpx.AsyncClient, bool]:
        if self._client is not None and not self._client.is_closed:
            return self._client, False
        return httpx.AsyncClient(timeout=timeout_seconds), True

    async def start(self) -> str:
        canonical = self.workspace
        cur = self.workspace.resolve()
        while cur != cur.parent:
            if cur.name == "worktrees" and cur.parent.name == ".sicoobito":
                canonical = cur.parent.parent
                break
            cur = cur.parent

        env_mounts: dict[str, str] = {}
        for env_dir in [".venv", "node_modules", "vendor"]:
            if (canonical / env_dir).exists():
                env_mounts[env_dir] = (canonical / env_dir).as_posix()
            elif (self.workspace / env_dir).exists():
                env_mounts[env_dir] = (self.workspace / env_dir).as_posix()

        payload = {
            "session_id": self.session_id,
            # O caminho vai como este processo o enxerga; o executor traduz para
            # o equivalente no host, que é o que o daemon do Docker entende.
            "workspace": self.workspace.as_posix(),
            "env_mounts": env_mounts,
            # Sem `image`/`network` de propósito: o executor recusa aceitá-los
            # do chamador (ver services/executor/app.py) — imagem e rede do
            # sandbox são fixadas só pela env var do próprio executor (ADR 0002).
        }
        client, is_owned = await self._get_client(timeout_seconds=120.0)
        try:
            resposta = await client.post(
                f"{self.config.base_url}/sandboxes", json=payload, headers=self._headers()
            )
        except httpx.HTTPError as exc:
            raise SandboxUnavailableError(
                f"executor inacessível em {self.config.base_url}: {exc}"
            ) from exc
        finally:
            if is_owned:
                await client.aclose()

        if resposta.status_code >= 400:
            raise SandboxError(f"executor recusou criar o sandbox: {resposta.text[:300]}")

        dados = resposta.json()
        self._started = True
        self.created_at = time.time()
        log.info(
            "sandbox.started",
            session=self.session_id,
            reused=dados.get("reused"),
            via="executor",
        )
        return dados.get("id", "")

    async def exec(
        self,
        command: str,
        *,
        timeout: int | None = None,  # noqa: ASYNC109 - ver Sandbox.exec
        workdir: str | None = None,
    ) -> ExecResult:
        if not self._started:
            await self.start()

        limite = timeout or self.config.timeout_seconds
        payload = {"command": command, "timeout": limite, "workdir": workdir}
        inicio = time.perf_counter()

        client, is_owned = await self._get_client(timeout_seconds=limite + _TIMEOUT_MARGEM)
        try:
            resposta = await client.post(
                f"{self.config.base_url}/sandboxes/{self.session_id}/exec",
                json=payload,
                headers=self._headers(),
                timeout=limite + _TIMEOUT_MARGEM,
            )
        except httpx.TimeoutException:
            duracao = int((time.perf_counter() - inicio) * 1000)
            return ExecResult(
                exit_code=124,
                stdout="",
                stderr=f"Comando excedeu {limite}s e foi interrompido.",
                duration_ms=duracao,
                timed_out=True,
            )
        except httpx.HTTPError as exc:
            raise SandboxError(f"falha ao falar com o executor: {exc}") from exc
        finally:
            if is_owned:
                await client.aclose()

        if resposta.status_code >= 400:
            raise SandboxError(f"executor retornou erro: {resposta.text[:300]}")

        dados = resposta.json()
        return ExecResult(
            exit_code=dados.get("exit_code", -1),
            stdout=dados.get("stdout", ""),
            stderr=dados.get("stderr", ""),
            duration_ms=dados.get("duration_ms", 0),
            timed_out=dados.get("timed_out", False),
        )

    async def put_file(self, relative_path: str, content: str) -> None:
        """Escreve pelo próprio filesystem: o workspace é montado nos dois lados."""
        destino = self.workspace / relative_path.lstrip("/")
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(content, encoding="utf-8", newline="")

    async def stop(self, *, remove: bool = True) -> None:
        if not self._started:
            return
        self._started = False
        client, is_owned = await self._get_client(timeout_seconds=60.0)
        try:
            await client.delete(
                f"{self.config.base_url}/sandboxes/{self.session_id}",
                headers=self._headers(),
                timeout=60.0,
            )
        except httpx.HTTPError as exc:
            log.warning("sandbox.stop.failed", session=self.session_id, error=str(exc))
        finally:
            if is_owned:
                await client.aclose()
        log.info("sandbox.stopped", session=self.session_id)


class ExecutorSandboxManager:
    """Mesma interface do SandboxManager local, apoiada no executor."""

    def __init__(self, config: ExecutorConfig) -> None:
        self._config = config
        self._sandboxes: dict[str, RemoteSandbox] = {}
        self._http_client: httpx.AsyncClient | None = None

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(60.0, connect=10.0),
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
            )
        return self._http_client

    def new_session_id(self) -> str:
        return uuid.uuid4().hex[:12]

    async def acquire(self, session_id: str, workspace: Path) -> RemoteSandbox:
        sandbox = self._sandboxes.get(session_id)
        if sandbox is None:
            sandbox = RemoteSandbox(
                session_id, workspace, self._config, client=self._get_http_client()
            )
            self._sandboxes[session_id] = sandbox
        await sandbox.start()
        return sandbox

    def get(self, session_id: str) -> RemoteSandbox | None:
        return self._sandboxes.get(session_id)

    async def release(self, session_id: str) -> None:
        sandbox = self._sandboxes.pop(session_id, None)
        if sandbox is not None:
            await sandbox.stop()

    async def reap_expired(self) -> int:
        agora = time.time()
        expirados = [
            sid
            for sid, sandbox in self._sandboxes.items()
            if sandbox.created_at and agora - sandbox.created_at > self._config.ttl_seconds
        ]
        for sid in expirados:
            await self.release(sid)
        return len(expirados)

    async def reap_orphans(self) -> int:
        """Pede ao executor que descarte tudo que este processo não conhece."""
        headers = {"Authorization": f"Bearer {self._config.token}"} if self._config.token else {}
        client = self._get_http_client()
        try:
            resposta = await client.post(
                f"{self._config.base_url}/sandboxes/reap",
                json=list(self._sandboxes),
                headers=headers,
                timeout=60.0,
            )
        except httpx.HTTPError as exc:
            log.debug("sandbox.reap_orphans.unavailable", error=str(exc))
            return 0
        if resposta.status_code >= 400:
            return 0
        removidos = resposta.json().get("removed", 0)
        if removidos:
            log.info("sandbox.orphans.removed", count=removidos)
        return removidos

    async def run_reaper(self, interval_seconds: int = 300) -> None:
        import asyncio

        while True:
            try:
                await asyncio.sleep(interval_seconds)
                await self.reap_expired()
                await self.reap_orphans()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("sandbox.reaper.iteration_failed", error=str(exc))

    async def shutdown(self) -> None:
        for sid in list(self._sandboxes):
            await self.release(sid)
        if self._http_client is not None and not self._http_client.is_closed:
            await self._http_client.aclose()
