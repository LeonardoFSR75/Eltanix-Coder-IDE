"""Sandbox de execução: um container efêmero por sessão do agente.

Isto é fronteira de segurança, não conveniência. O agente executa comandos que
um modelo escreveu, sobre um repositório que pode conter instruções hostis em
README, issue ou dependência. As restrições abaixo existem cada uma por um
motivo concreto:

- **sem rede por padrão** — impede exfiltrar o código para fora e impede baixar
  e executar algo de origem desconhecida. Instalar dependência é uma decisão
  explícita, não um efeito colateral de rodar teste.
- **só o workspace montado** — o resto do disco não existe para o container.
- **usuário não-root** — limita o estrago dentro do próprio container.
- **limites de CPU, memória e PIDs** — um laço infinito ou fork bomb do modelo
  não pode derrubar a máquina do desenvolvedor.
- **`docker.sock` nunca montado** — acesso ao socket do Docker é equivalente a
  root no host, e anularia tudo acima.
"""

from __future__ import annotations

import asyncio
import shlex
import tarfile
import time
import uuid
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

from sicoobito.logging_setup import get_logger
from sicoobito.sandbox.concurrency import SandboxConcurrencyGate

log = get_logger(__name__)

DEFAULT_IMAGE = "python:3.12-slim"
WORKDIR = "/workspace"
LABEL = "sicoobito.session"


class SandboxError(RuntimeError):
    pass


class SandboxUnavailableError(SandboxError):
    """Docker não está acessível."""


@dataclass(slots=True)
class SandboxConfig:
    image: str = DEFAULT_IMAGE
    memory_limit: str = "2g"
    cpu_quota: int = 100_000  # 1 CPU (período padrão de 100ms)
    pids_limit: int = 512
    network_enabled: bool = False
    timeout_seconds: int = 300
    # TTL do container ocioso; o reaper derruba o que passar disso.
    ttl_seconds: int = 3600
    env: dict[str, str] = field(default_factory=dict)
    # Teto de sandboxes ativos ao mesmo tempo neste host (ver sandbox/concurrency.py).
    max_concurrent: int = 6


@dataclass(slots=True)
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


_cached_docker_client = None


def _docker_client():
    global _cached_docker_client
    if _cached_docker_client is not None:
        try:
            _cached_docker_client.ping()
            return _cached_docker_client
        except Exception:
            _cached_docker_client = None

    try:
        import docker

        client = docker.from_env()
        client.ping()
        _cached_docker_client = client
        return client
    except Exception as exc:
        raise SandboxUnavailableError(
            f"Docker não está acessível: {exc}. Inicie o Docker Desktop."
        ) from exc


class Sandbox:
    """Ciclo de vida de um container de sessão."""

    def __init__(self, session_id: str, workspace: Path, config: SandboxConfig | None = None):
        self.session_id = session_id
        self.workspace = workspace.resolve()
        self.config = config or SandboxConfig()
        self._container: Any | None = None
        self._client: Any | None = None
        self.created_at = 0.0

    @property
    def container_name(self) -> str:
        return f"sicoobito-{self.session_id}"

    @property
    def running(self) -> bool:
        return self._container is not None

    async def start(self) -> str:
        if self._container is not None:
            return str(self._container.id)

        self._client = await asyncio.to_thread(_docker_client)
        client = self._client
        assert client is not None

        # Sessão retomada depois de um reload: reaproveita o container.
        existing = await asyncio.to_thread(
            lambda: client.containers.list(all=True, filters={"name": self.container_name})
        )
        if existing:
            container = existing[0]
            if container.status != "running":
                await asyncio.to_thread(container.start)
            self._container = container
            log.info("sandbox.reused", session=self.session_id, container=container.short_id)
            return str(container.id)

        # As flags de segurança abaixo (user, cap_drop, security_opt, privileged,
        # mem/cpu/pids limit) espelham as mesmas restrições em
        # services/executor/app.py::create_sandbox — este é o caminho local/dev
        # (ADR 0002), aquele é o serviço isolado de produção. Mudou uma flag
        # aqui, mude a mesma lá.
        # Monta /workspace e mapeia diretamente .venv, node_modules e vendor caso existam no projeto
        vols: dict[str, dict[str, str]] = {str(self.workspace): {"bind": WORKDIR, "mode": "rw"}}
        canonical_project = self.workspace
        cur = self.workspace.resolve()
        while cur != cur.parent:
            if cur.name == "worktrees" and cur.parent.name == ".sicoobito":
                canonical_project = cur.parent.parent
                break
            cur = cur.parent

        for env_dir, bind_target in [
            (".venv", f"{WORKDIR}/.venv"),
            ("node_modules", f"{WORKDIR}/node_modules"),
            ("vendor", f"{WORKDIR}/vendor"),
        ]:
            ws_dir = self.workspace / env_dir
            canon_dir = canonical_project / env_dir
            src_path = ws_dir if ws_dir.exists() else canon_dir
            if src_path.exists() and not src_path.is_symlink():
                vols[str(src_path.resolve())] = {"bind": bind_target, "mode": "rw"}
            elif canon_dir.exists() and not canon_dir.is_symlink():
                vols[str(canon_dir.resolve())] = {"bind": bind_target, "mode": "rw"}

        default_env = {
            "HOME": "/tmp",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_INPUT": "1",
            "PIP_RETRIES": "0",
            "PIP_DEFAULT_TIMEOUT": "2",
            "VIRTUAL_ENV": "/workspace/.venv",
            "PYTHONPATH": (
                "/workspace:"
                "/workspace/.venv/lib/python3.12/site-packages:"
                "/workspace/.venv/lib/python3.11/site-packages:"
                "/workspace/.venv/lib/python3.10/site-packages:"
                "/workspace/.venv/Lib/site-packages:"
                "/workspace/.venv/lib/site-packages"
            ),
            "PATH": (
                "/usr/local/sbin:/usr/local/bin:"
                "/usr/sbin:/usr/bin:/sbin:/bin:"
                "/workspace/.venv/bin:/workspace/.venv/Scripts:"
                "/workspace/node_modules/.bin"
            ),
            **self.config.env,
        }

        # Conecta o sandbox na rede interna browser_net para que o serviço browser
        # consiga inspecionar a aplicação web sem liberar acesso à internet pública.
        sandbox_network = "bridge" if self.config.network_enabled else "none"
        if not self.config.network_enabled:
            try:
                for net in client.networks.list():
                    if net.name in ("browser_net", "sicoobito_browser_net") or (
                        net.name and net.name.endswith("_browser_net")
                    ):
                        sandbox_network = net.name
                        break
            except Exception:
                pass

        try:
            container = await asyncio.to_thread(
                lambda: client.containers.run(
                    self.config.image,
                    # `sleep infinity` mantém o container vivo para receber
                    # vários `exec` na mesma sessão, em vez de subir um
                    # container por comando.
                    command=["sleep", "infinity"],
                    name=self.container_name,
                    detach=True,
                    working_dir=WORKDIR,
                    volumes=vols,
                    network_mode=sandbox_network,
                    mem_limit=self.config.memory_limit,
                    cpu_quota=self.config.cpu_quota,
                    pids_limit=self.config.pids_limit,
                    # Não-root: o estrago de um comando ruim fica contido.
                    user="1000:1000",
                    environment=default_env,
                    labels={LABEL: self.session_id},
                    # Sem privilégio extra e sem escalada via setuid.
                    privileged=False,
                    security_opt=["no-new-privileges:true"],
                    cap_drop=["ALL"],
                    auto_remove=False,
                )
            )
        except Exception as exc:
            raise SandboxError(f"não foi possível iniciar o sandbox: {exc}") from exc

        self._container = container
        self.created_at = time.time()
        log.info(
            "sandbox.started",
            session=self.session_id,
            container=container.short_id,
            image=self.config.image,
            network=self.config.network_enabled,
        )
        return str(container.id)

    async def exec(
        self,
        command: str,
        *,
        timeout: int | None = None,  # noqa: ASYNC109 - ver docstring
        workdir: str | None = None,
    ) -> ExecResult:
        """Executa um comando dentro do container vivo da sessão.

        `timeout` é aplicado no `asyncio.wait_for`, não como parâmetro do
        Docker: o daemon do Docker não tem timeout nativo no `exec_create`
        nem no `exec_start`, e se um comando travar (ex. `sleep infinity`,
        servidor web sem `&`), quem cancela a espera é o loop do Python.
        """
        if self._container is None:
            await self.start()

        client = self._client
        container = self._container
        if client is None or container is None:
            raise SandboxError("sandbox não foi iniciado")

        timeout = timeout or self.config.timeout_seconds
        started = time.perf_counter()

        # `sh -c` para aceitar pipe e redirecionamento, que é o que o modelo
        # naturalmente escreve. A contenção vem do container, não da sintaxe.
        argv = ["sh", "-c", command]

        exec_env = [
            "HOME=/tmp",
            "PYTHONDONTWRITEBYTECODE=1",
            "PIP_DISABLE_PIP_VERSION_CHECK=1",
            "VIRTUAL_ENV=/workspace/.venv",
            "PYTHONPATH=/workspace:/workspace/.venv/lib/python3.12/site-packages:/workspace/.venv/lib/python3.11/site-packages:/workspace/.venv/lib/python3.10/site-packages:/workspace/.venv/Lib/site-packages:/workspace/.venv/lib/site-packages",
            "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/workspace/.venv/bin:/workspace/.venv/Scripts:/workspace/node_modules/.bin",
        ]

        def _run() -> tuple[int, bytes, bytes]:
            handle = client.api.exec_create(
                container.id,
                argv,
                workdir=workdir or WORKDIR,
                stdout=True,
                stderr=True,
                user="1000:1000",
                environment=exec_env,
            )
            output = client.api.exec_start(handle["Id"], demux=True)
            info = client.api.exec_inspect(handle["Id"])
            stdout, stderr = output if isinstance(output, tuple) else (output, b"")
            return info.get("ExitCode", -1), stdout or b"", stderr or b""

        try:
            exit_code, stdout, stderr = await asyncio.wait_for(
                asyncio.to_thread(_run), timeout=timeout
            )
        except TimeoutError:
            duration = int((time.perf_counter() - started) * 1000)
            log.warning("sandbox.exec.timeout", session=self.session_id, command=command[:120])
            return ExecResult(
                exit_code=124,
                stdout="",
                stderr=f"tempo limite esgotado ({timeout}s)",
                duration_ms=duration,
                timed_out=True,
            )

        duration = int((time.perf_counter() - started) * 1000)
        return ExecResult(
            exit_code=exit_code,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
            duration_ms=duration,
            timed_out=False,
        )

    async def write_file(self, relative_path: str, content: str) -> None:
        """Cria/sobrescreve um arquivo dentro do container usando `put_archive`.

        Evita rodar `cat <<'EOF'` via shell para não ter problema de escape de
        aspas ou estouro de tamanho de argumento de linha de comando.
        """
        if self._container is None:
            await self.start()
        container = self._container
        if container is None:
            raise SandboxError("sandbox não foi iniciado")

        data = content.encode("utf-8")
        buffer = BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            info = tarfile.TarInfo(name=relative_path.lstrip("/"))
            info.size = len(data)
            info.mtime = int(time.time())
            archive.addfile(info, BytesIO(data))
        buffer.seek(0)

        await asyncio.to_thread(lambda: container.put_archive(WORKDIR, buffer.getvalue()))

    async def stop(self, *, remove: bool = True) -> None:
        if self._container is None:
            return
        container = self._container
        self._container = None
        try:
            await asyncio.to_thread(lambda: container.stop(timeout=5))
            if remove:
                await asyncio.to_thread(container.remove)
        except Exception as exc:
            log.warning("sandbox.stop.failed", session=self.session_id, error=str(exc))
        log.info("sandbox.stopped", session=self.session_id)


class SandboxManager:
    """Registro dos sandboxes ativos, com limpeza dos que passaram do TTL."""

    def __init__(self, config: SandboxConfig | None = None) -> None:
        self._config = config or SandboxConfig()
        self._sandboxes: dict[str, Sandbox] = {}
        self._gate = SandboxConcurrencyGate(self._config.max_concurrent)

    def new_session_id(self) -> str:
        return uuid.uuid4().hex[:12]

    async def acquire(self, session_id: str, workspace: Path) -> Sandbox:
        sandbox = self._sandboxes.get(session_id)
        if sandbox is not None:
            await sandbox.start()
            return sandbox

        # Sessão nova de verdade: passa pela fila antes de criar container —
        # reconexão (branch acima) não compete por vaga de novo.
        await self._gate.acquire(session_id)
        sandbox = Sandbox(session_id, workspace, self._config)
        self._sandboxes[session_id] = sandbox
        try:
            await sandbox.start()
        except Exception:
            self._sandboxes.pop(session_id, None)
            await self._gate.release(session_id)
            raise
        return sandbox

    def get(self, session_id: str) -> Sandbox | None:
        return self._sandboxes.get(session_id)

    async def release(self, session_id: str) -> None:
        sandbox = self._sandboxes.pop(session_id, None)
        if sandbox is not None:
            await sandbox.stop()
        await self._gate.release(session_id)

    def queue_status(self) -> dict[str, Any]:
        return self._gate.snapshot()

    async def reap_expired(self) -> int:
        """Derruba containers ociosos além do TTL."""
        now = time.time()
        expired = [
            session
            for session, sandbox in self._sandboxes.items()
            if sandbox.created_at and now - sandbox.created_at > self._config.ttl_seconds
        ]
        for session in expired:
            await self.release(session)
        if expired:
            log.info("sandbox.reaped", count=len(expired))
        return len(expired)

    async def reap_orphans(self) -> int:
        """Remove containers de sessões que este processo não conhece.

        Um `kill -9` no servidor — ou uma queda — impede o desligamento
        ordenado, e os containers ficam consumindo memória até alguém notar.
        Eles não estão em `_sandboxes`, então `reap_expired` nunca os veria; a
        única pista que resta é o label gravado na criação.
        """
        try:
            client = await asyncio.to_thread(_docker_client)
        except SandboxUnavailableError:
            return 0

        try:
            containers = await asyncio.to_thread(
                lambda: client.containers.list(all=True, filters={"label": LABEL})
            )
        except Exception as exc:
            log.warning("sandbox.reap_orphans.failed", error=str(exc))
            return 0

        removidos = 0
        for container in containers:
            session = container.labels.get(LABEL, "")
            if session in self._sandboxes:
                continue
            try:
                await asyncio.to_thread(lambda c=container: c.remove(force=True))
                removidos += 1
                log.info("sandbox.orphan.removed", session=session, container=container.short_id)
            except Exception as exc:
                log.warning("sandbox.orphan.remove_failed", session=session, error=str(exc))
        return removidos

    async def run_reaper(self, interval_seconds: int = 300) -> None:
        """Laço de limpeza. Roda como task de fundo enquanto a app vive."""
        while True:
            try:
                await asyncio.sleep(interval_seconds)
                await self.reap_expired()
                await self.reap_orphans()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("sandbox.reaper.iteration_failed", error=str(exc))

    async def get_stats(self, session_id: str) -> dict[str, Any]:
        return {"session_id": session_id, "status": "unknown", "ports": [], "metrics": {}}

    async def get_server_logs(self, session_id: str, tail: int = 100) -> dict[str, Any]:
        return {"session_id": session_id, "logs": ""}

    async def shutdown(self) -> None:
        for session in list(self._sandboxes):
            await self.release(session)

    @staticmethod
    def quote(value: str) -> str:
        """Escapa um valor para uso seguro dentro de um comando de shell."""
        return shlex.quote(value)
