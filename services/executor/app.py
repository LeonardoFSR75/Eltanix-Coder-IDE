"""Executor: o único serviço com acesso ao daemon do Docker.

Por que ele existe separado da API (ver `docs/adr/0002`): montar o
`docker.sock` num processo dá a quem o alcançar poder equivalente a root no
host. A API atende requisições de usuário, monta prompts e executa código
escrito por um modelo — é justamente onde esse poder não pode estar.

Aqui a superfície é deliberadamente pequena: criar sandbox, executar comando,
destruir, listar. Nada de caminho arbitrário, nada de opção de container vinda
de fora. As restrições de segurança do container são fixadas neste arquivo e o
chamador não consegue afrouxá-las.
"""

from __future__ import annotations

import asyncio
import hmac
import os
import shlex
import time
from typing import Annotated, Any

import docker
from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

WORKDIR = "/workspace"
LABEL = "sicoobito.session"

TOKEN = os.getenv("EXECUTOR_TOKEN", "")
# Os dois lados do mesmo diretório: o caminho que a API enxerga dentro do seu
# container, e o caminho equivalente no host. O daemon do Docker resolve bind
# mounts contra o host, então sem esta tradução o volume apontaria para o vazio.
PROJECTS_ROOT_CONTAINER = os.getenv("PROJECTS_ROOT_CONTAINER", "/projects").rstrip("/")
PROJECTS_ROOT_HOST = os.getenv("PROJECTS_ROOT_HOST", "").rstrip("/\\")

DEFAULT_IMAGE = os.getenv("SANDBOX_IMAGE", "python:3.12-slim")
DEFAULT_MEMORY = os.getenv("SANDBOX_MEMORY", "2g")
NETWORK_ENABLED = os.getenv("SANDBOX_NETWORK", "false").lower() in {"1", "true", "yes"}
PIDS_LIMIT = int(os.getenv("SANDBOX_PIDS_LIMIT", "512"))
CPU_QUOTA = int(os.getenv("SANDBOX_CPU_QUOTA", "100000"))

app = FastAPI(title="SicoobitoCode Executor", version="1.0.0")
_client: docker.DockerClient | None = None


def client() -> docker.DockerClient:
    global _client
    if _client is None:
        _client = docker.from_env()
    return _client


def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    """O executor só aceita chamadas da API, nunca do browser."""
    if not TOKEN:
        return
    presented = ""
    if authorization:
        scheme, _, valor = authorization.partition(" ")
        presented = valor.strip() if scheme.lower() == "bearer" else authorization.strip()
    if not presented or not hmac.compare_digest(presented, TOKEN):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token inválido")


Auth = Depends(require_token)


def to_host_path(container_path: str) -> str:
    """Traduz um caminho visto pela API para o caminho equivalente no host."""
    normalizado = container_path.replace("\\", "/").rstrip("/")
    if not PROJECTS_ROOT_HOST:
        return normalizado
    if not normalizado.startswith(PROJECTS_ROOT_CONTAINER):
        # Recusar é melhor que montar algo inesperado: um caminho fora da raiz
        # de projetos só chega aqui por engano ou por tentativa de abuso.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"caminho fora de {PROJECTS_ROOT_CONTAINER}: {container_path}",
        )
    resto = normalizado[len(PROJECTS_ROOT_CONTAINER) :].lstrip("/")
    separador = "\\" if "\\" in PROJECTS_ROOT_HOST or ":" in PROJECTS_ROOT_HOST[:2] else "/"
    if not resto:
        return PROJECTS_ROOT_HOST
    return f"{PROJECTS_ROOT_HOST}{separador}{resto.replace('/', separador)}"


class CreateRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    # Caminho do workspace **como a API o enxerga**; traduzido aqui.
    workspace: str
    image: str | None = None
    network: bool | None = None


class ExecRequest(BaseModel):
    command: str
    timeout: int = Field(default=300, ge=1, le=3600)
    workdir: str | None = None


@app.get("/health")
async def health() -> dict[str, Any]:
    try:
        client().ping()
        docker_ok = True
        erro = None
    except Exception as exc:  # noqa: BLE001
        docker_ok = False
        erro = str(exc)
    return {
        "status": "ok" if docker_ok else "degraded",
        "docker": docker_ok,
        "error": erro,
        "projects_root_container": PROJECTS_ROOT_CONTAINER,
        "projects_root_host": PROJECTS_ROOT_HOST,
        "network_enabled": NETWORK_ENABLED,
    }


@app.post("/sandboxes", dependencies=[Auth])
async def create_sandbox(payload: CreateRequest) -> dict[str, Any]:
    nome = f"sicoobito-{payload.session_id}"
    host_path = to_host_path(payload.workspace)

    existentes = client().containers.list(all=True, filters={"name": nome})
    if existentes:
        container = existentes[0]
        if container.status != "running":
            container.start()
        return {"id": container.id, "name": nome, "reused": True}

    rede = NETWORK_ENABLED if payload.network is None else payload.network
    try:
        container = client().containers.run(
            payload.image or DEFAULT_IMAGE,
            # Mantém o container vivo entre execuções da mesma sessão, em vez
            # de pagar o custo de subir um por comando.
            command=["sleep", "infinity"],
            name=nome,
            detach=True,
            working_dir=WORKDIR,
            volumes={host_path: {"bind": WORKDIR, "mode": "rw"}},
            network_mode="bridge" if rede else "none",
            mem_limit=DEFAULT_MEMORY,
            cpu_quota=CPU_QUOTA,
            pids_limit=PIDS_LIMIT,
            user="1000:1000",
            environment={"HOME": "/tmp", "PYTHONDONTWRITEBYTECODE": "1"},
            labels={LABEL: payload.session_id},
            privileged=False,
            security_opt=["no-new-privileges:true"],
            cap_drop=["ALL"],
            auto_remove=False,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"falha ao criar sandbox: {exc}"
        ) from exc

    return {"id": container.id, "name": nome, "reused": False, "host_path": host_path}


@app.post("/sandboxes/{session_id}/exec", dependencies=[Auth])
async def exec_command(session_id: str, payload: ExecRequest) -> dict[str, Any]:
    nome = f"sicoobito-{session_id}"
    try:
        container = client().containers.get(nome)
    except docker.errors.NotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"sandbox {session_id} não existe"
        ) from exc

    inicio = time.perf_counter()

    # `exec_create`/`exec_start`/`exec_inspect` são chamadas síncronas e
    # bloqueantes do docker-py. Rodá-las direto na coroutine travaria o único
    # event loop do processo (uvicorn sobe sem `--workers`) até o comando
    # terminar, derrubando /health e todas as outras sessões junto. Por isso
    # a chamada vai para uma thread do pool via `asyncio.to_thread`, com o
    # mesmo padrão usado em `Sandbox.exec` (apps/api/src/sicoobito/sandbox/container.py).
    def _run() -> tuple[int, bytes, bytes]:
        handle = client().api.exec_create(
            container.id,
            ["sh", "-c", payload.command],
            workdir=payload.workdir or WORKDIR,
            stdout=True,
            stderr=True,
            user="1000:1000",
        )
        saida = client().api.exec_start(handle["Id"], demux=True)
        info = client().api.exec_inspect(handle["Id"])
        stdout, stderr = saida if isinstance(saida, tuple) else (saida, b"")
        return info.get("ExitCode", -1), stdout or b"", stderr or b""

    try:
        exit_code, stdout, stderr = await asyncio.wait_for(
            asyncio.to_thread(_run), timeout=payload.timeout
        )
    except TimeoutError:
        return {
            "exit_code": 124,
            "stdout": "",
            "stderr": f"Comando excedeu {payload.timeout}s e foi interrompido.",
            "duration_ms": int((time.perf_counter() - inicio) * 1000),
            "timed_out": True,
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"falha ao executar: {exc}"
        ) from exc

    return {
        "exit_code": exit_code,
        "stdout": stdout.decode("utf-8", "replace"),
        "stderr": stderr.decode("utf-8", "replace"),
        "duration_ms": int((time.perf_counter() - inicio) * 1000),
        "timed_out": False,
    }


@app.delete("/sandboxes/{session_id}", dependencies=[Auth])
async def destroy_sandbox(session_id: str) -> dict[str, Any]:
    nome = f"sicoobito-{session_id}"
    try:
        container = client().containers.get(nome)
    except docker.errors.NotFound:
        return {"removed": False, "reason": "não existia"}
    container.remove(force=True)
    return {"removed": True}


@app.get("/sandboxes", dependencies=[Auth])
async def list_sandboxes() -> dict[str, Any]:
    containers = client().containers.list(all=True, filters={"label": LABEL})
    return {
        "sandboxes": [
            {
                "session_id": c.labels.get(LABEL, ""),
                "name": c.name,
                "status": c.status,
                "created": c.attrs.get("Created"),
            }
            for c in containers
        ]
    }


@app.post("/sandboxes/reap", dependencies=[Auth])
async def reap(keep: list[str] | None = None) -> dict[str, Any]:
    """Remove sandboxes que a API não reconhece mais.

    Um `kill -9` na API deixaria containers vivos indefinidamente; ela informa
    quais sessões ainda existem e o resto cai.
    """
    manter = set(keep or [])
    removidos = 0
    for container in client().containers.list(all=True, filters={"label": LABEL}):
        if container.labels.get(LABEL, "") in manter:
            continue
        try:
            container.remove(force=True)
            removidos += 1
        except Exception:  # noqa: BLE001, S110 - limpeza é best-effort
            pass
    return {"removed": removidos}


def quote(valor: str) -> str:
    return shlex.quote(valor)
