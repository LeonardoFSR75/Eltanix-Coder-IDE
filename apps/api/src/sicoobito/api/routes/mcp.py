"""Rotas de servidores MCP — cadastro, status ao vivo e recarga sem restart."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field, model_validator

from sicoobito.agent.tools import registry
from sicoobito.api.deps import AuthDep, SettingsDep
from sicoobito.audit.service import AuditService
from sicoobito.mcp import config_editor
from sicoobito.mcp.manager import MCPManager

router = APIRouter(prefix="/api/mcp", tags=["mcp"], dependencies=[AuthDep])


def _manager(request: Request) -> MCPManager:
    manager: MCPManager | None = getattr(request.app.state, "mcp_manager", None)
    if manager is None:  # pragma: no cover - só ocorre se o lifespan falhar
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Gerenciador MCP indisponível."
        )
    return manager


def _audit(request: Request) -> AuditService | None:
    return getattr(request.app.state, "audit", None)


class MCPServerIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    transport: Literal["stdio", "http"]
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    trust_annotations: bool = False

    @model_validator(mode="after")
    def _valida_campos_por_transporte(self) -> MCPServerIn:
        if self.transport == "stdio" and not self.command:
            raise ValueError("transporte stdio exige 'command'")
        if self.transport == "http" and not self.url:
            raise ValueError("transporte http exige 'url'")
        return self


async def _reload_and_list(request: Request, settings: SettingsDep) -> list[dict[str, Any]]:
    manager = _manager(request)
    await manager.reload(registry)
    return manager.list_status()


@router.get("/servers")
async def list_servers(request: Request) -> dict[str, Any]:
    return {"servers": _manager(request).list_status()}


@router.post("/servers")
async def create_server(
    payload: MCPServerIn, request: Request, settings: SettingsDep
) -> dict[str, Any]:
    data = config_editor.load(settings.mcp_config_file)
    try:
        config_editor.append_server(data, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    config_editor.dump(settings.mcp_config_file, data)

    servers = await _reload_and_list(request, settings)
    if audit := _audit(request):
        await audit.record(
            actor="usuário",
            module="MCP",
            action="Servidor MCP criado",
            details=f"{payload.name} ({payload.transport})",
        )
    return {"servers": servers}


@router.put("/servers/{name}")
async def update_server(
    name: str, payload: MCPServerIn, request: Request, settings: SettingsDep
) -> dict[str, Any]:
    data = config_editor.load(settings.mcp_config_file)
    try:
        config_editor.update_server(data, name, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    config_editor.dump(settings.mcp_config_file, data)

    servers = await _reload_and_list(request, settings)
    if audit := _audit(request):
        await audit.record(
            actor="usuário", module="MCP", action="Servidor MCP atualizado", details=name
        )
    return {"servers": servers}


@router.post("/servers/{name}/toggle")
async def toggle_server(name: str, request: Request, settings: SettingsDep) -> dict[str, Any]:
    data = config_editor.load(settings.mcp_config_file)
    try:
        current = next(s for s in data["servers"] if s.get("name") == name)
        config_editor.set_enabled(data, name, not current.get("enabled", True))
    except (KeyError, StopIteration) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"servidor não encontrado: {name}"
        ) from exc
    config_editor.dump(settings.mcp_config_file, data)

    servers = await _reload_and_list(request, settings)
    if audit := _audit(request):
        await audit.record(
            actor="usuário",
            module="MCP",
            action="Servidor MCP habilitado/desabilitado",
            details=name,
        )
    return {"servers": servers}


@router.delete("/servers/{name}")
async def delete_server(name: str, request: Request, settings: SettingsDep) -> dict[str, Any]:
    data = config_editor.load(settings.mcp_config_file)
    try:
        config_editor.delete_server(data, name)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    config_editor.dump(settings.mcp_config_file, data)

    servers = await _reload_and_list(request, settings)
    if audit := _audit(request):
        await audit.record(
            actor="usuário",
            module="MCP",
            action="Servidor MCP removido",
            details=name,
            risk_level="medium",
        )
    return {"servers": servers}
