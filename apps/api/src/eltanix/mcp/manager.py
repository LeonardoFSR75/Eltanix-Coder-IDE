"""Gerencia o ciclo de vida de todas as conexões MCP e sua exposição como
ferramentas do agente.

Cada ferramenta remota vira um `Tool` local, montado uma vez no startup (ou
em `reload()`) como *closure* sobre a conexão certa — por isso não precisa de
campo novo em `ToolContext`: o handler já sabe com qual servidor falar.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from eltanix.agent.tools.base import RiskClass, Tool, ToolContext, ToolRegistry, ToolResult
from eltanix.config import Settings
from eltanix.logging_setup import get_logger
from eltanix.mcp.client import MCPServerConnection
from eltanix.mcp.config import MCPServerConfig, load_mcp_servers

log = get_logger(__name__)

MAX_OUTPUT_CHARS = 24_000


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    metade = limit // 2
    omitido = len(text) - limit
    return f"{text[:metade]}\n\n... [{omitido} caracteres omitidos no meio] ...\n\n{text[-metade:]}"


def _tool_name(server: str, tool: str) -> str:
    # Mesma convenção `mcp__<server>__<tool>` de clientes MCP já conhecidos —
    # evita colisão entre servidores e com as ferramentas nativas.
    return f"mcp__{server}__{tool}"


def _classify_risk(server_cfg: MCPServerConfig, tool: Any) -> RiskClass:
    # Precedência: override explícito da tool > trust_annotations+read_only_hint > WRITE.
    override = server_cfg.tool_overrides.get(tool.name)
    if override == "read":
        return RiskClass.READ
    if override == "write":
        return RiskClass.WRITE
    if server_cfg.trust_annotations and tool.annotations and tool.annotations.read_only_hint:
        return RiskClass.READ
    return RiskClass.WRITE


class MCPManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._connections: dict[str, MCPServerConnection] = {}
        self._registered_names: list[str] = []

    async def connect_all(self) -> None:
        configs = load_mcp_servers(self.settings.mcp_config_file)
        for cfg in configs:
            connection = MCPServerConnection(cfg)
            await connection.connect()
            self._connections[cfg.name] = connection

    async def disconnect_all(self) -> None:
        for connection in self._connections.values():
            await connection.disconnect()
        self._connections.clear()

    def register_tools(self, registry: ToolRegistry) -> None:
        for name in self._registered_names:
            registry.unregister(name)
        self._registered_names = []

        for connection in self._connections.values():
            if connection.status != "connected":
                continue
            for remote_tool in connection.tools:
                local_name = _tool_name(connection.config.name, remote_tool.name)
                risk = _classify_risk(connection.config, remote_tool)

                def _make_handler(conn: MCPServerConnection, tool_name: str):
                    async def _handler(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
                        ok, text = await conn.call_tool(tool_name, args)
                        return ToolResult(ok=ok, content=_truncate(text))

                    return _handler

                def _make_summarize(display_name: str) -> Callable[[dict[str, Any]], str]:
                    def _summarize(a: dict[str, Any]) -> str:
                        pares = ", ".join(f"{k}={v!r}" for k, v in (a or {}).items())
                        return f"{display_name}({pares})"[:200]

                    return _summarize

                try:
                    registry.register(
                        Tool(
                            name=local_name,
                            description=(
                                f"[MCP · {connection.config.name}] "
                                f"{remote_tool.description or remote_tool.name}"
                            ),
                            risk=risk,
                            parameters=remote_tool.input_schema
                            or {"type": "object", "properties": {}},
                            handler=_make_handler(connection, remote_tool.name),
                            summarize=_make_summarize(local_name),
                        )
                    )
                    self._registered_names.append(local_name)
                except ValueError as exc:
                    log.warning("mcp.tool.register_failed", tool=local_name, error=str(exc))

    async def reload(self, registry: ToolRegistry) -> None:
        await self.disconnect_all()
        await self.connect_all()
        self.register_tools(registry)

    def list_status(self) -> list[dict[str, Any]]:
        configs = load_mcp_servers(self.settings.mcp_config_file)
        out: list[dict[str, Any]] = []
        for cfg in configs:
            connection = self._connections.get(cfg.name)
            out.append(
                {
                    "name": cfg.name,
                    "transport": cfg.transport,
                    "enabled": cfg.enabled,
                    "trust_annotations": cfg.trust_annotations,
                    "command": cfg.command,
                    "args": cfg.args,
                    "url": cfg.url,
                    "status": connection.status if connection else "disabled",
                    "error": connection.error if connection else None,
                    "tools_count": len(connection.tools) if connection else 0,
                    "tools": [
                        {
                            "name": remote_tool.name,
                            "local_name": _tool_name(cfg.name, remote_tool.name),
                            "risk": str(_classify_risk(cfg, remote_tool)),
                            "override": cfg.tool_overrides.get(remote_tool.name),
                        }
                        for remote_tool in connection.tools
                    ]
                    if connection
                    else [],
                }
            )
        return out
