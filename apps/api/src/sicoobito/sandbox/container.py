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

from sicoobito.logging_setup import get_logger

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
        except Exception:  # noqa: BLE001
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
        self._container = None
        self._client = None
        self.created_at = 0.0

    @property
    def container_name(self) -> str:
        return f"sicoobito-{self.session_id}"

    @property
    def running(self) -> bool:
        return self._container is not None

    async def start(self) -> str:
        if self._container is not None:
            return self._container.id

        self._client = await asyncio.to_thread(_docker_client)

        # Sessão retomada depois de um reload: reaproveita o container.
        existing = await asyncio.to_thread(
            lambda: self._client.containers.list(
                all=True, filters={"name": self.container_name}
            )
        )
        if existing:
            container = existing[0]
            if container.status != "running":
                await asyncio.to_thread(container.start)
            self._container = container
            log.info("sandbox.reused", session=self.session_id, container=container.short_id)
            return container.id

        try:
            container = await asyncio.to_thread(
                lambda: self._client.containers.run(
                    self.config.image,
                    # `sleep infinity` mantém o container vivo para receber
                    # vários `exec` na mesma sessão, em vez de subir um
                    # container por comando.
                    command=["sleep", "infinity"],
                    name=self.container_name,
                    detach=True,
                    working_dir=WORKDIR,
                    volumes={str(self.workspace): {"bind": WORKDIR, "mode": "rw"}},
                    network_mode="bridge" if self.config.network_enabled else "none",
                    mem_limit=self.config.memory_limit,
                    cpu_quota=self.config.cpu_quota,
                    pids_limit=self.config.pids_limit,
                    # Não-root: o estrago de um comando ruim fica contido.
                    user="1000:1000",
                    environment={
                        "HOME": "/tmp",
                        "PYTHONDONTWRITEBYTECODE": "1",
                        **self.config.env,
                    },
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
        return container.id

    async def exec(
        self,
        command: str,
        *,
        timeout: int | None = None,  # noqa: ASYNC109 - ver docstring
        workdir: str | None = None,
    ) -> ExecResult:
        """Executa um comando dentro do container.

        O `timeout` é parâmetro em vez de responsabilidade do chamador porque o
        estouro precisa virar `ExecResult(timed_out=True)` — uma observação que
        o modelo lê e usa para decidir o próximo passo. Um `CancelledError`
        propagado abortaria o turno inteiro em vez de informar o agente.
        """
        if self._container is None:
            await self.start()

        timeout = timeout or self.config.timeout_seconds
        started = time.perf_counter()

        # `sh -c` para aceitar pipe e redirecionamento, que é o que o modelo
        # naturalmente escreve. A contenção vem do container, não da sintaxe.
        argv = ["sh", "-c", command]

        def _run() -> tuple[int, bytes, bytes]:
            handle = self._client.api.exec_create(
                self._container.id,
                argv,
                workdir=workdir or WORKDIR,
                stdout=True,
                stderr=True,
                user="1000:1000",
            )
            output = self._client.api.exec_start(handle["Id"], demux=True)
            info = self._client.api.exec_inspect(handle["Id"])
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
                stderr=f"Comando excedeu {timeout}s e foi interrompido.",
                duration_ms=duration,
                timed_out=True,
            )
        except Exception as exc:
            raise SandboxError(f"falha ao executar no sandbox: {exc}") from exc

        duration = int((time.perf_counter() - started) * 1000)
        result = ExecResult(
            exit_code=exit_code,
            stdout=stdout.decode("utf-8", "replace"),
            stderr=stderr.decode("utf-8", "replace"),
            duration_ms=duration,
        )
        log.info(
            "sandbox.exec",
            session=self.session_id,
            command=command[:120],
            exit_code=result.exit_code,
            duration_ms=duration,
        )
        return result

    async def put_file(self, relative_path: str, content: str) -> None:
        """Escreve um arquivo dentro do container sem passar pelo shell.

        Evita ter de escapar o conteúdo dentro de um `echo`, que quebra com
        aspas, crase e quebra de linha.
        """
        if self._container is None:
            await self.start()

        data = content.encode("utf-8")
        buffer = BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            info = tarfile.TarInfo(name=relative_path.lstrip("/"))
            info.size = len(data)
            info.mtime = int(time.time())
            archive.addfile(info, BytesIO(data))
        buffer.seek(0)

        await asyncio.to_thread(
            lambda: self._container.put_archive(WORKDIR, buffer.getvalue())
        )

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

    def new_session_id(self) -> str:
        return uuid.uuid4().hex[:12]

    async def acquire(self, session_id: str, workspace: Path) -> Sandbox:
        sandbox = self._sandboxes.get(session_id)
        if sandbox is None:
            sandbox = Sandbox(session_id, workspace, self._config)
            self._sandboxes[session_id] = sandbox
        await sandbox.start()
        return sandbox

    def get(self, session_id: str) -> Sandbox | None:
        return self._sandboxes.get(session_id)

    async def release(self, session_id: str) -> None:
        sandbox = self._sandboxes.pop(session_id, None)
        if sandbox is not None:
            await sandbox.stop()

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

    async def shutdown(self) -> None:
        for session in list(self._sandboxes):
            await self.release(session)

    @staticmethod
    def quote(value: str) -> str:
        """Escapa um valor para uso seguro dentro de um comando de shell."""
        return shlex.quote(value)
