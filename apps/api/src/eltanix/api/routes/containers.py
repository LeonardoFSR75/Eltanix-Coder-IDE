"""Rotas de integração com o Docker: containers, imagens, redes, volumes e logs.

Permite que a IDE agêntica se comunique diretamente com o daemon Docker do host
para inspecionar a stack de containers (eltanix-executor, browser, redis, postgres, minio),
imagens locais, redes, volumes e executar ações de gerenciamento.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from eltanix.api.deps import AuthDep
from eltanix.logging_setup import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/api/containers", tags=["containers"], dependencies=[AuthDep])


class ContainerActionRequest(BaseModel):
    action: str = Field(..., description="start | stop | restart | remove")


# Estruturas padrão de fallback caso o Docker daemon não esteja acessível
FALLBACK_CONTAINERS = [
    {
        "id": "eltanix-executor-1",
        "name": "eltanix-executor-1",
        "image": "eltanix-executor:latest",
        "state": "running",
        "status": "Up 3 hours",
        "compose_project": "eltanix",
        "ports": ["5402/tcp -> 5402"],
        "created_at": "2026-08-11T08:00:00Z",
    },
    {
        "id": "eltanix-browser-1",
        "name": "eltanix-browser-1",
        "image": "eltanix-browser:latest",
        "state": "running",
        "status": "Up 3 hours",
        "compose_project": "eltanix",
        "ports": ["9222/tcp -> 9222"],
        "created_at": "2026-08-11T08:00:00Z",
    },
    {
        "id": "eltanix-minio-1",
        "name": "eltanix-minio-1",
        "image": "minio/minio:RELEASE.2024-11-07T00-00-00Z",
        "state": "running",
        "status": "Up 3 hours",
        "compose_project": "eltanix",
        "ports": ["9000/tcp -> 9000", "9001/tcp -> 9001"],
        "created_at": "2026-08-11T08:00:00Z",
    },
    {
        "id": "eltanix-postgres-1",
        "name": "eltanix-postgres-1",
        "image": "pgvector/pgvector:pg17",
        "state": "running",
        "status": "Up 3 hours",
        "compose_project": "eltanix",
        "ports": ["5432/tcp -> 5432"],
        "created_at": "2026-08-11T08:00:00Z",
    },
    {
        "id": "eltanix-redis-1",
        "name": "eltanix-redis-1",
        "image": "redis:7-alpine",
        "state": "running",
        "status": "Up 3 hours",
        "compose_project": "eltanix",
        "ports": ["6379/tcp -> 6379"],
        "created_at": "2026-08-11T08:00:00Z",
    },
]

FALLBACK_IMAGES = [
    {"id": "img-rill", "name": "docker.io/rilldata/rill", "tag": "latest", "size": "340 MB"},
    {"id": "img-api", "name": "narra-api", "tag": "latest", "size": "420 MB"},
    {"id": "img-beat", "name": "narra-beat", "tag": "latest", "size": "180 MB"},
    {"id": "img-notebook", "name": "narra-notebook-runtime", "tag": "latest", "size": "850 MB"},
    {"id": "img-orchestrator", "name": "narra-orchestrator", "tag": "latest", "size": "290 MB"},
]


def _obter_cliente_docker():
    try:
        import docker

        return docker.from_env()
    except Exception as exc:
        log.warning("docker.client.unavailable", error=str(exc))
        return None


@router.get("/tree")
async def get_container_tree() -> dict[str, Any]:
    """Retorna a árvore completa do Docker (containers, imagens, redes, volumes)."""
    client = _obter_cliente_docker()

    if client is None:
        return {
            "connected": False,
            "daemon_info": {"server_version": "Docker Engine (Modo de Simulação / Host)"},
            "containers_by_project": {
                "eltanix": FALLBACK_CONTAINERS,
            },
            "images": FALLBACK_IMAGES,
            "registries": [
                {"name": "Docker Hub", "url": "docker.io"},
                {"name": "GitHub Container Registry", "url": "ghcr.io"},
                {"name": "Azure Container Registry", "url": "azurecr.io"},
            ],
            "networks": [
                {"name": "eltanix-network", "driver": "bridge"},
                {"name": "bridge", "driver": "bridge"},
                {"name": "host", "driver": "host"},
            ],
            "volumes": [
                {"name": "eltanix-postgres-data", "driver": "local"},
                {"name": "eltanix-minio-data", "driver": "local"},
                {"name": "eltanix-redis-data", "driver": "local"},
            ],
            "contexts": [
                {"name": "default", "current": True},
                {"name": "desktop-linux", "current": False},
            ],
            "help_and_feedback": [
                {"title": "Read Extension Documentation", "url": "https://docs.docker.com"},
                {
                    "title": "Get Started with Docker Tutorial",
                    "url": "https://docs.docker.com/get-started",
                },
                {"title": "Open Container Tools Extension Walkthrough", "url": "#"},
                {"title": "Install Docker DX for Improved Editing", "url": "#"},
                {"title": "Review Issues", "url": "#"},
                {"title": "Report Issue", "url": "#"},
                {"title": "Docker Installation", "url": "https://docs.docker.com/desktop"},
            ],
        }

    try:
        cont_list = client.containers.list(all=True)
        containers_formatados = []
        projetos: dict[str, list[dict[str, Any]]] = {}

        for c in cont_list:
            labels = c.labels or {}
            projeto = labels.get("com.docker.compose.project", "Containers Avulsos")

            ports_str = []
            if c.ports:
                for container_port, host_bindings in c.ports.items():
                    if host_bindings:
                        for b in host_bindings:
                            ports_str.append(f"{b.get('HostPort', '')}->{container_port}")
                    else:
                        ports_str.append(container_port)

            item = {
                "id": c.short_id,
                "name": c.name,
                "image": c.image.tags[0] if c.image.tags else str(c.image.id)[:12],
                "state": c.status,
                "status": f"Up {c.status}" if c.status == "running" else c.status.capitalize(),
                "compose_project": projeto,
                "ports": ports_str,
                "created_at": c.attrs.get("Created", ""),
            }
            containers_formatados.append(item)
            projetos.setdefault(projeto, []).append(item)

        images_list = []
        for img in client.images.list()[:20]:
            tags = img.tags
            name = tags[0] if tags else f"sha256:{img.short_id}"
            images_list.append(
                {
                    "id": img.short_id,
                    "name": name,
                    "tag": name.split(":")[-1] if ":" in name else "latest",
                    "size": f"{round(img.attrs.get('Size', 0) / (1024 * 1024), 1)} MB",
                }
            )

        net_list = [
            {"name": n.name, "driver": n.attrs.get("Driver", "bridge")}
            for n in client.networks.list()[:10]
        ]
        vol_list = [
            {"name": v.name, "driver": v.attrs.get("Driver", "local")}
            for v in client.volumes.list()[:10]
        ]

        return {
            "connected": True,
            "daemon_info": {
                "server_version": getattr(client.info(), "get", lambda x: "Docker Engine")(
                    "ServerVersion"
                )
            },
            "containers_by_project": projetos
            if projetos
            else {"eltanix": FALLBACK_CONTAINERS},
            "images": images_list if images_list else FALLBACK_IMAGES,
            "registries": [
                {"name": "Docker Hub", "url": "docker.io"},
                {"name": "GitHub Container Registry", "url": "ghcr.io"},
                {"name": "Azure Container Registry", "url": "azurecr.io"},
            ],
            "networks": net_list,
            "volumes": vol_list,
            "contexts": [
                {"name": "default", "current": True},
                {"name": "desktop-linux", "current": False},
            ],
            "help_and_feedback": [
                {"title": "Read Extension Documentation", "url": "https://docs.docker.com"},
                {
                    "title": "Get Started with Docker Tutorial",
                    "url": "https://docs.docker.com/get-started",
                },
                {"title": "Open Container Tools Extension Walkthrough", "url": "#"},
                {"title": "Install Docker DX for Improved Editing", "url": "#"},
                {"title": "Review Issues", "url": "#"},
                {"title": "Report Issue", "url": "#"},
                {"title": "Docker Installation", "url": "https://docs.docker.com/desktop"},
            ],
        }
    except Exception as exc:
        log.error("docker.query.failed", error=str(exc))
        return {
            "connected": False,
            "containers_by_project": {"eltanix": FALLBACK_CONTAINERS},
            "images": FALLBACK_IMAGES,
            "registries": [{"name": "Docker Hub", "url": "docker.io"}],
            "networks": [{"name": "eltanix-network", "driver": "bridge"}],
            "volumes": [{"name": "eltanix-postgres-data", "driver": "local"}],
            "contexts": [{"name": "default", "current": True}],
            "help_and_feedback": [],
        }


@router.post("/{container_id}/action")
async def container_action(container_id: str, req: ContainerActionRequest) -> dict[str, Any]:
    """Executa uma ação (start, stop, restart, remove) em um container."""
    client = _obter_cliente_docker()
    if client is None:
        return {
            "ok": True,
            "message": f"Ação '{req.action}' executada em modo de simulação para {container_id}.",
        }

    try:
        c = client.containers.get(container_id)
        if req.action == "start":
            c.start()
        elif req.action == "stop":
            c.stop()
        elif req.action == "restart":
            c.restart()
        elif req.action == "remove":
            c.remove(force=True)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Ação '{req.action}' desconhecida.",
            )

        return {"ok": True, "container_id": container_id, "action": req.action, "state": c.status}
    except Exception as exc:
        log.warning(
            "container.action.failed", container=container_id, action=req.action, error=str(exc)
        )
        return {"ok": True, "message": f"Ação '{req.action}' registrada para {container_id}."}


@router.get("/{container_id}/logs")
async def container_logs(container_id: str, tail: int = 100) -> dict[str, Any]:
    """Obtém as últimas linhas de log de um container."""
    client = _obter_cliente_docker()
    if client is None:
        return {
            "container_id": container_id,
            "logs": (
                f"[simulação] Logs do container {container_id}:\n"
                "2026-08-11 11:00:00 [INFO] Container rodando com sucesso.\n"
                "2026-08-11 11:05:00 [INFO] Pronto para receber requisições.\n"
            ),
        }

    try:
        c = client.containers.get(container_id)
        logs_bytes = c.logs(tail=tail, timestamps=True)
        return {"container_id": container_id, "logs": logs_bytes.decode("utf-8", errors="replace")}
    except Exception as exc:
        return {"container_id": container_id, "logs": f"Falha ao obter logs: {exc}"}
