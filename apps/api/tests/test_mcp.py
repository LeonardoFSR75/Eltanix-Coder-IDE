"""MCP: classificação de risco de tools remotas e degradação de conexão.

Ferramentas MCP nascem WRITE por padrão (`docs/adr` + `CLAUDE.md`) — só viram
READ se o servidor for explicitamente marcado `trust_annotations: true` *e* a
tool anunciar `read_only_hint: true`. É o único lugar do invariante 3 (RiskClass)
que decide risco a partir de um sinal que vem de fora do processo, e não tinha
nenhum teste cobrindo isso.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from eltanix.agent.tools.base import RiskClass, ToolRegistry
from eltanix.config import Settings
from eltanix.mcp.client import MCPServerConnection
from eltanix.mcp.config import MCPServerConfig
from eltanix.mcp.manager import MCPManager, _classify_risk


def _cfg(
    *,
    trust_annotations: bool = False,
    name: str = "srv",
    tool_overrides: dict[str, str] | None = None,
) -> MCPServerConfig:
    return MCPServerConfig(
        name=name,
        transport="stdio",
        command="qualquer-coisa",
        trust_annotations=trust_annotations,
        tool_overrides=tool_overrides or {},
    )


def _tool(*, read_only_hint: bool | None, annotations_present: bool = True):
    annotations = SimpleNamespace(read_only_hint=read_only_hint) if annotations_present else None
    return SimpleNamespace(
        name="do_thing",
        description="faz algo",
        input_schema={"type": "object", "properties": {}},
        annotations=annotations,
    )


# ── _classify_risk ───────────────────────────────────────────────────────────


def test_untrusted_server_is_always_write_even_with_read_only_hint():
    # Servidor não confiado: mesmo anunciando read_only_hint=True, o hint não
    # é garantia (spec do MCP) — a config precisa opt-in explícito.
    cfg = _cfg(trust_annotations=False)
    tool = _tool(read_only_hint=True)
    assert _classify_risk(cfg, tool) is RiskClass.WRITE


def test_trusted_server_without_annotations_is_write():
    cfg = _cfg(trust_annotations=True)
    tool = _tool(read_only_hint=None, annotations_present=False)
    assert _classify_risk(cfg, tool) is RiskClass.WRITE


def test_trusted_server_with_read_only_hint_false_is_write():
    cfg = _cfg(trust_annotations=True)
    tool = _tool(read_only_hint=False)
    assert _classify_risk(cfg, tool) is RiskClass.WRITE


def test_trusted_server_with_read_only_hint_true_is_read():
    cfg = _cfg(trust_annotations=True)
    tool = _tool(read_only_hint=True)
    assert _classify_risk(cfg, tool) is RiskClass.READ


# ── _classify_risk: override por ferramenta ─────────────────────────────────


def test_tool_override_read_wins_over_untrusted_server():
    # Servidor não confiado, mas usuário revisou UMA tool específica e decidiu
    # confiar nela — override tem precedência sobre trust_annotations.
    cfg = _cfg(trust_annotations=False, tool_overrides={"do_thing": "read"})
    tool = _tool(read_only_hint=None, annotations_present=False)
    assert _classify_risk(cfg, tool) is RiskClass.READ


def test_tool_override_write_wins_over_trusted_server_with_read_only_hint():
    # Servidor confiado com hint read-only, mas o usuário forçou essa tool
    # específica a continuar WRITE — override vence o caminho normal.
    cfg = _cfg(trust_annotations=True, tool_overrides={"do_thing": "write"})
    tool = _tool(read_only_hint=True)
    assert _classify_risk(cfg, tool) is RiskClass.WRITE


def test_tool_override_only_affects_the_named_tool():
    # Override de uma tool não deve vazar para outra tool do mesmo servidor.
    cfg = _cfg(trust_annotations=False, tool_overrides={"outra_tool": "read"})
    tool = _tool(read_only_hint=True)
    assert _classify_risk(cfg, tool) is RiskClass.WRITE


# ── MCPServerConnection: status e degradação ────────────────────────────────


def test_disabled_server_starts_disabled_without_connecting():
    cfg = MCPServerConfig(name="off", transport="stdio", command="x", enabled=False)
    conn = MCPServerConnection(cfg)
    assert conn.status == "disabled"


async def test_disabled_server_connect_is_a_noop():
    cfg = MCPServerConfig(name="off", transport="stdio", command="x", enabled=False)
    conn = MCPServerConnection(cfg)
    await conn.connect()
    assert conn.status == "disabled"
    assert conn.tools == []


async def test_invalid_command_marks_only_that_server_as_error():
    # Comando inexistente: a conexão deve falhar sozinha, sem propagar exceção
    # para quem chamou `connect()` — é exatamente a regra de degradação
    # graciosa do CLAUDE.md ("MCP com comando inválido só marca aquele
    # servidor como erro, os outros continuam").
    cfg = MCPServerConfig(
        name="quebrado",
        transport="stdio",
        command="este-comando-nao-existe-em-lugar-nenhum-xyz",
    )
    conn = MCPServerConnection(cfg)
    await asyncio.wait_for(conn.connect(), timeout=15)
    assert conn.status == "error"
    assert conn.error is not None
    assert conn.tools == []


async def test_call_tool_without_connection_fails_without_raising():
    cfg = _cfg()
    conn = MCPServerConnection(cfg)
    ok, text = await conn.call_tool("qualquer", {})
    assert ok is False
    assert "quebrado" not in text  # sanity: não é o teste anterior vazando estado
    assert conn.config.name in text


# ── MCPManager.register_tools ────────────────────────────────────────────────


def test_register_tools_skips_connections_that_are_not_connected(monkeypatch):
    settings = Settings()
    manager = MCPManager(settings)

    conectado = SimpleNamespace(
        status="connected",
        config=_cfg(name="ok", trust_annotations=False),
        tools=[_tool(read_only_hint=True)],
    )
    com_erro = SimpleNamespace(
        status="error",
        config=_cfg(name="quebrado"),
        tools=[_tool(read_only_hint=True)],
    )
    manager._connections = {"ok": conectado, "quebrado": com_erro}

    registry = ToolRegistry()
    manager.register_tools(registry)

    nomes = {t.name for t in registry.all()}
    assert "mcp__ok__do_thing" in nomes
    assert "mcp__quebrado__do_thing" not in nomes


def test_register_tools_applies_classified_risk(monkeypatch):
    settings = Settings()
    manager = MCPManager(settings)

    # trust_annotations=False -> WRITE mesmo com read_only_hint=True, e a tool
    # registrada precisa refletir essa classificação (não algo fixo/errado).
    conectado = SimpleNamespace(
        status="connected",
        config=_cfg(name="ok", trust_annotations=False),
        tools=[_tool(read_only_hint=True)],
    )
    manager._connections = {"ok": conectado}

    registry = ToolRegistry()
    manager.register_tools(registry)

    ferramenta = registry.get("mcp__ok__do_thing")
    assert ferramenta is not None
    assert ferramenta.risk is RiskClass.WRITE
    assert ferramenta.risk.requires_approval is True
