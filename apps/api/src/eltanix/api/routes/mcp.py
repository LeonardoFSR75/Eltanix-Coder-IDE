"""Rotas de servidores MCP — cadastro, status ao vivo e recarga sem restart."""

from __future__ import annotations

import os
import re
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field, model_validator

from eltanix.agent.tools import registry
from eltanix.api.deps import AuthDep, SettingsDep
from eltanix.audit.service import AuditService
from eltanix.logging_setup import get_logger
from eltanix.mcp import config_editor
from eltanix.mcp.config import MCPServerConfig, load_catalog
from eltanix.mcp.manager import MCPManager
from eltanix.mcp.scanner import MCPScannerService
from eltanix.router import env_editor

log = get_logger(__name__)

router = APIRouter(prefix="/api/mcp", tags=["mcp"], dependencies=[AuthDep])

_ENV_VAR_UNSAFE_RE = re.compile(r"[^A-Z0-9_]")


def _sanitize_env_var_part(value: str) -> str:
    sanitized = _ENV_VAR_UNSAFE_RE.sub("_", value.upper())
    return f"_{sanitized}" if not sanitized or sanitized[0].isdigit() else sanitized


def _env_var_name(server_name: str, key: str) -> str:
    return f"MCP_{_sanitize_env_var_part(server_name)}_{_sanitize_env_var_part(key)}"


def _colliding_server_name(name: str, existing_names: list[str]) -> str | None:
    """Nomes de servidor distintos (ex. "my-server" e "my.server") sanitizam
    para a mesma variável de ambiente — sem checar isso, salvar o segundo
    sobrescreveria em `.env` o segredo referenciado pelo placeholder do
    primeiro, que passaria a autenticar com a credencial errada sem aviso
    nenhum."""
    sanitized = _sanitize_env_var_part(name)
    for existing in existing_names:
        if existing != name and _sanitize_env_var_part(existing) == sanitized:
            return existing
    return None


def _externalize_secrets(entry: dict[str, Any], settings: SettingsDep) -> dict[str, Any]:
    """`env`/`headers` de servidor MCP nunca ficam em texto puro em `mcp.yaml`
    (arquivo versionado no git) — o valor real vai para `.env` (não
    versionado) e o yaml guarda só a referência `${VAR}`, mesmo padrão que
    `providers.yaml` já usa para credenciais de LLM (ver `mcp/config.py::_expand_env`)."""
    entry = dict(entry)
    name = entry.get("name", "")
    env_updates: dict[str, str] = {}

    def _placeholderize(mapping: dict[str, str] | None) -> dict[str, str]:
        result: dict[str, str] = {}
        for key, value in (mapping or {}).items():
            if not value or (value.startswith("${") and value.endswith("}")):
                result[key] = value
                continue
            var_name = _env_var_name(name, key)
            env_updates[var_name] = value
            result[key] = f"${{{var_name}}}"
        return result

    if entry.get("env"):
        entry["env"] = _placeholderize(entry["env"])
    if entry.get("headers"):
        entry["headers"] = _placeholderize(entry["headers"])

    if env_updates:
        # Efeito imediato (o processo atual já enxerga a var) — persistência
        # em disco é best-effort, igual ao resto da tela de configuração.
        os.environ.update(env_updates)
        try:
            env_editor.write_values(settings.env_file_path, env_updates)
        except Exception as exc:  # persistência é best-effort
            log.warning("mcp.server.secret_persist_failed", server=name, error=str(exc)[:200])

    return entry


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


@router.get("/catalog")
async def catalog(settings: SettingsDep) -> dict[str, Any]:
    return {"templates": [t.model_dump() for t in load_catalog(settings.mcp_catalog_file)]}


@router.post("/servers")
async def create_server(
    payload: MCPServerIn, request: Request, settings: SettingsDep
) -> dict[str, Any]:
    data = config_editor.load(settings.mcp_config_file)
    existing_names = [s.get("name", "") for s in data["servers"]]
    if colliding := _colliding_server_name(payload.name, existing_names):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"nome de servidor colide com {colliding!r} depois de sanitizado para "
                "variável de ambiente — escolha um nome que não dependa só de "
                "pontuação para se distinguir"
            ),
        )
    entry = _externalize_secrets(payload.model_dump(), settings)
    try:
        config_editor.append_server(data, entry)
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
    existing_names = [s.get("name", "") for s in data["servers"] if s.get("name") != name]
    if colliding := _colliding_server_name(payload.name, existing_names):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"nome de servidor colide com {colliding!r} depois de sanitizado para "
                "variável de ambiente — escolha um nome que não dependa só de "
                "pontuação para se distinguir"
            ),
        )
    entry = _externalize_secrets(payload.model_dump(), settings)
    try:
        config_editor.update_server(data, name, entry)
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


class ToolOverrideIn(BaseModel):
    risk: Literal["read", "write"] | None = None


@router.put("/servers/{name}/tools/{tool_name}/override")
async def set_tool_override(
    name: str,
    tool_name: str,
    payload: ToolOverrideIn,
    request: Request,
    settings: SettingsDep,
) -> dict[str, Any]:
    data = config_editor.load(settings.mcp_config_file)
    try:
        config_editor.set_tool_override(data, name, tool_name, payload.risk)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    config_editor.dump(settings.mcp_config_file, data)

    servers = await _reload_and_list(request, settings)
    if audit := _audit(request):
        await audit.record(
            actor="usuário",
            module="MCP",
            action="Override de risco de ferramenta MCP",
            details=f"{name}/{tool_name} -> {payload.risk or 'padrão'}",
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


@router.get("/scanner/status")
async def scanner_status(settings: SettingsDep) -> dict[str, Any]:
    """Retorna a disponibilidade do scanner de segurança Cisco MCP Scanner."""
    scanner = MCPScannerService(settings)
    return await scanner.check_health()


class ScanRequestIn(BaseModel):
    analyzers: list[str] = Field(default_factory=lambda: ["yara"])


@router.post("/scan")
async def scan_all_servers(
    payload: ScanRequestIn, request: Request, settings: SettingsDep
) -> dict[str, Any]:
    """Escaneia todos os servidores MCP configurados."""
    scanner = MCPScannerService(settings)
    data = config_editor.load(settings.mcp_config_file)
    results: list[dict[str, Any]] = []

    for raw_server in data.get("servers", []):
        try:
            cfg = MCPServerConfig.model_validate(raw_server)
            res = await scanner.scan_server(cfg, analyzers=payload.analyzers)
            results.append(res.to_dict())
        except Exception as exc:
            results.append(
                {
                    "server_name": raw_server.get("name", "desconhecido"),
                    "status": "error",
                    "tools_scanned": 0,
                    "findings_count": 0,
                    "findings": [],
                    "error": str(exc),
                }
            )

    return {"results": results}


@router.post("/servers/{name}/scan")
async def scan_single_server(
    name: str, payload: ScanRequestIn, request: Request, settings: SettingsDep
) -> dict[str, Any]:
    """Escaneia um servidor MCP específico por nome."""
    scanner = MCPScannerService(settings)
    data = config_editor.load(settings.mcp_config_file)
    try:
        raw_server = next(s for s in data.get("servers", []) if s.get("name") == name)
    except StopIteration as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"servidor não encontrado: {name}",
        ) from exc

    cfg = MCPServerConfig.model_validate(raw_server)
    res = await scanner.scan_server(cfg, analyzers=payload.analyzers)
    return {"result": res.to_dict()}
