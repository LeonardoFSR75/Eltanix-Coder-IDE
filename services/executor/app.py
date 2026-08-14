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
from pathlib import Path
import posixpath
import shlex
import time
from typing import Annotated, Any

import docker
import docker.errors
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
    normalizado = posixpath.normpath(container_path.replace("\\", "/"))
    root = posixpath.normpath(PROJECTS_ROOT_CONTAINER)

    if not (normalizado == root or normalizado.startswith(root + "/")):
        # Recusar é melhor que montar algo inesperado: um caminho fora da raiz
        # de projetos só chega aqui por engano ou por tentativa de abuso.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"caminho fora de {PROJECTS_ROOT_CONTAINER}: {container_path}",
        )
    if not PROJECTS_ROOT_HOST:
        return normalizado

    resto = normalizado[len(root) :].lstrip("/")
    separador = "\\" if "\\" in PROJECTS_ROOT_HOST or ":" in PROJECTS_ROOT_HOST[:2] else "/"
    if not resto:
        return PROJECTS_ROOT_HOST
    return f"{PROJECTS_ROOT_HOST}{separador}{resto.replace('/', separador)}"


class CreateRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    # Caminho do workspace **como a API o enxerga**; traduzido aqui.
    workspace: str
    env_mounts: dict[str, str] = Field(default_factory=dict)
    # `image`/`network` propositalmente NÃO existem aqui: a imagem e a rede
    # do sandbox são fixadas só por env var deste processo (DEFAULT_IMAGE,
    # NETWORK_ENABLED) — um payload não pode afrouxar o isolamento de rede
    # nem trocar a imagem, mesmo de posse do EXECUTOR_TOKEN (ver docstring
    # do módulo e ADR 0002).


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
        "network_enabled": NETWORK_ENABLED,
    }


_container_cache: dict[str, str] = {}


@app.post("/sandboxes", dependencies=[Auth])
async def create_sandbox(payload: CreateRequest) -> dict[str, Any]:
    nome = f"sicoobito-{payload.session_id}"
    host_path = to_host_path(payload.workspace)

    cid = _container_cache.get(payload.session_id)
    if cid:
        try:
            container = client().containers.get(cid)
            if container.status != "running":
                container.start()
            return {"id": container.id, "name": nome, "reused": True}
        except Exception:  # noqa: BLE001
            _container_cache.pop(payload.session_id, None)

    existentes = client().containers.list(all=True, filters={"name": nome})
    if existentes:
        container = existentes[0]
        if container.status != "running":
            container.start()
        _container_cache[payload.session_id] = str(container.id)
        return {"id": container.id, "name": nome, "reused": True}

    # As flags de segurança abaixo (user, cap_drop, security_opt, privileged,
    # mem/cpu/pids limit) espelham as mesmas restrições em
    # apps/api/src/sicoobito/sandbox/container.py — aquele é o caminho local/dev,
    # este é o serviço isolado de produção (ADR 0002). Mudou uma flag aqui,
    # mude a mesma lá.
    try:
        vols = {host_path: {"bind": WORKDIR, "mode": "rw"}}
        for env_name, container_path in payload.env_mounts.items():
            if env_name in {".venv", "node_modules", "vendor"}:
                host_env_path = to_host_path(container_path)
                vols[host_env_path] = {"bind": f"{WORKDIR}/{env_name}", "mode": "rw"}

        default_env = {
            "HOME": "/tmp",
            "HOST": "0.0.0.0",
            "FLASK_RUN_HOST": "0.0.0.0",
            "UVICORN_HOST": "0.0.0.0",
            "VITE_HOST": "0.0.0.0",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_INPUT": "1",
            "PIP_RETRIES": "0",
            "PIP_DEFAULT_TIMEOUT": "2",
            "VIRTUAL_ENV": "/workspace/.venv",
            "PYTHONPATH": (
                "/tmp/sicoobito_bootstrap:"
                "/workspace:"
                "/workspace/.venv/lib/python3.12/site-packages:"
                "/workspace/.venv/lib/python3.11/site-packages:"
                "/workspace/.venv/lib/python3.10/site-packages:"
                "/workspace/.venv/Lib/site-packages:"
                "/workspace/.venv/lib/site-packages"
            ),
            "PATH": (
                "/tmp/sicoobito_bootstrap:"
                "/usr/local/sbin:/usr/local/bin:"
                "/usr/sbin:/usr/bin:/sbin:/bin:"
                "/workspace/.venv/bin:/workspace/.venv/Scripts:"
                "/workspace/node_modules/.bin"
            ),
        }

        # Conecta o sandbox na rede interna browser_net para que o serviço browser
        # consiga inspecionar a aplicação web sem liberar acesso à internet pública.
        sandbox_network = "bridge" if NETWORK_ENABLED else "none"
        if not NETWORK_ENABLED:
            try:
                for net in client().networks.list():
                    if net.name in ("browser_net", "sicoobito_browser_net") or (
                        net.name and net.name.endswith("_browser_net")
                    ):
                        sandbox_network = net.name
                        break
            except Exception:  # noqa: BLE001
                pass

        container = client().containers.run(
            DEFAULT_IMAGE,
            command=["sleep", "infinity"],
            name=nome,
            detach=True,
            working_dir=WORKDIR,
            volumes=vols,
            network_mode=sandbox_network,
            mem_limit=DEFAULT_MEMORY,
            cpu_quota=CPU_QUOTA,
            pids_limit=PIDS_LIMIT,
            user="1000:1000",
            environment=default_env,
            labels={LABEL: payload.session_id},
            privileged=False,
            security_opt=["no-new-privileges:true"],
            cap_drop=["ALL"],
            auto_remove=False,
        )
        _container_cache[payload.session_id] = str(container.id)

        # Injeta bootstrap: 0.0.0.0 socket bind automático e utilitários pkill, fuser, lsof
        bootstrap_script = r"""
import os, stat
os.makedirs('/tmp/sicoobito_bootstrap', exist_ok=True)
with open('/tmp/sicoobito_bootstrap/sitecustomize.py', 'w') as f:
    f.write('''import socket
_orig_bind = socket.socket.bind
def _sicoobito_bind(self, address):
    if isinstance(address, tuple) and len(address) >= 2:
        if address[0] in ('127.0.0.1', 'localhost'):
            address = ('0.0.0.0', address[1], *address[2:])
    return _orig_bind(self, address)
socket.socket.bind = _sicoobito_bind
''')
with open('/tmp/sicoobito_bootstrap/pkill', 'w') as f:
    f.write('''#!/usr/bin/env python3
import sys, os, signal, glob
pattern = ""
sig = signal.SIGTERM
for arg in sys.argv[1:]:
    if arg.startswith('-') and not arg.startswith('-f'):
        if arg in ('-9', '-KILL'): sig = signal.SIGKILL
    else: pattern = arg
curr = os.getpid()
killed = 0
for p in glob.glob('/proc/[0-9]*'):
    try:
        pid = int(os.path.basename(p))
        if pid in (1, curr): continue
        with open(f'{p}/cmdline', 'r', errors='ignore') as cf:
            cmd = cf.read().replace('\\x00', ' ')
        if pattern and pattern in cmd:
            os.kill(pid, sig)
            killed += 1
    except Exception: pass
sys.exit(0 if killed > 0 else 1)
''')
fuser_code = '''#!/usr/bin/env python3
import sys, os, signal, glob
target_port = None
kill_mode = '-k' in sys.argv or sys.argv[0].endswith('fuser')
for arg in sys.argv[1:]:
    for sub in arg.replace(':', ' ').replace('/', ' ').split():
        if sub.isdigit():
            target_port = int(sub)
            break
hex_port = f"{target_port:04X}" if target_port else None
inodes = set()
try:
    with open('/proc/net/tcp', 'r') as f:
        for line in f.readlines()[1:]:
            parts = line.strip().split()
            if len(parts) >= 10:
                local_addr, inode = parts[1], parts[9]
                if hex_port is None or local_addr.endswith(':' + hex_port):
                    inodes.add(inode)
except Exception: pass
pids = set()
curr = os.getpid()
for p in glob.glob('/proc/[0-9]*'):
    try:
        pid = int(os.path.basename(p))
        if pid in (1, curr): continue
        for fd in glob.glob(f'{p}/fd/*'):
            try:
                link = os.readlink(fd)
                for inode in inodes:
                    if f'[{inode}]' in link: pids.add(pid)
            except Exception: pass
    except Exception: pass
for pid in pids:
    if kill_mode:
        try: os.kill(pid, signal.SIGKILL); print(f"Killed process {pid}")
        except Exception: pass
    else:
        print(pid)
'''
with open('/tmp/sicoobito_bootstrap/fuser', 'w') as f: f.write(fuser_code)
with open('/tmp/sicoobito_bootstrap/lsof', 'w') as f: f.write(fuser_code)
with open('/tmp/sicoobito_bootstrap/netstat', 'w') as f: f.write(fuser_code)
for name in ('pkill', 'fuser', 'lsof', 'netstat'):
    path = f'/tmp/sicoobito_bootstrap/{name}'
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
"""
        try:
            container.exec_run(["python", "-c", bootstrap_script])
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"falha ao criar sandbox: {exc}"
        ) from exc

    return {"id": container.id, "name": nome, "reused": False, "host_path": host_path}


@app.post("/sandboxes/{session_id}/exec", dependencies=[Auth])
async def exec_command(session_id: str, payload: ExecRequest) -> dict[str, Any]:
    nome = f"sicoobito-{session_id}"
    cid = _container_cache.get(session_id)
    if cid is None:
        try:
            container = client().containers.get(nome)
            cid = str(container.id)
            _container_cache[session_id] = cid
        except docker.errors.NotFound as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"sandbox {session_id} não existe"
            ) from exc

    inicio = time.perf_counter()

    exec_env = [
        "HOME=/tmp",
        "PYTHONDONTWRITEBYTECODE=1",
        "PIP_DISABLE_PIP_VERSION_CHECK=1",
        "VIRTUAL_ENV=/workspace/.venv",
        "PYTHONPATH=/workspace:/workspace/.venv/lib/python3.12/site-packages:/workspace/.venv/lib/python3.11/site-packages:/workspace/.venv/lib/python3.10/site-packages:/workspace/.venv/Lib/site-packages:/workspace/.venv/lib/site-packages",
        "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/workspace/.venv/bin:/workspace/.venv/Scripts:/workspace/node_modules/.bin",
    ]

    def _run() -> tuple[int, bytes, bytes]:
        handle = client().api.exec_create(
            cid,
            ["sh", "-c", payload.command],
            workdir=payload.workdir or WORKDIR,
            stdout=True,
            stderr=True,
            user="1000:1000",
            environment=exec_env,
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
    except docker.errors.NotFound as exc:
        _container_cache.pop(session_id, None)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"sandbox {session_id} não existe"
        ) from exc
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
    _container_cache.pop(session_id, None)
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
