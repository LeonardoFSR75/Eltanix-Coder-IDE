"""Ferramenta do agente para classificar risco de prompt/texto."""

from __future__ import annotations

from typing import Any

from eltanix.agent.tools.base import RiskClass, ToolContext, ToolResult, tool


@tool(
    name="analyze_prompt_risk",
    description=(
        "Analisa texto de prompt ou mensagem em busca de risco de segurança, jailbreak, "
        "exfiltração ou abuso do agente. Leitura apenas — não altera estado."
    ),
    risk=RiskClass.READ,
    parameters={
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": (
                    "Texto em claro a ser classificado. "
                    "Pode ser um prompt, mensagem ou instrução do usuário."
                ),
            }
        },
        "required": ["text"],
    },
    summarize=lambda a: f"analisar risco: {a.get('text', '')[:80]}",
)
async def analyze_prompt_risk(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    if ctx.security is None:
        return ToolResult.failure("Serviço de segurança indisponível para esta sessão.")

    text = str(args.get("text") or "").strip()
    if not text:
        return ToolResult.failure("Informe um texto para análise de risco.")

    try:
        result = ctx.security.analyze(text)
        if ctx.audit is not None:
            try:
                await ctx.audit.record(
                    actor="agente",
                    module="Security",
                    action="Análise de prompt com SecureBERT",
                    details=(
                        f"classificação={result.get('classification')} score={result.get('score')}"
                    ),
                    risk_level="medium"
                    if result.get("classification") in {"suspicious", "unsafe"}
                    else "low",
                    status="success",
                    session_id=ctx.session_id,
                    project_slug=ctx.project_slug or None,
                    metadata={
                        "provider": result.get("provider"),
                        "available": result.get("available"),
                        "mode": result.get("mode"),
                        "reasons": result.get("reasons", []),
                        "length": len(text),
                    },
                )
            except Exception:
                pass
    except Exception as exc:  # pragma: no cover - falha resistente
        if ctx.audit is not None:
            try:
                await ctx.audit.record(
                    actor="agente",
                    module="Security",
                    action="Falha de análise de prompt com SecureBERT",
                    details=str(exc)[:200],
                    risk_level="medium",
                    status="error",
                    session_id=ctx.session_id,
                    project_slug=ctx.project_slug or None,
                    metadata={"input_length": len(text)},
                )
            except Exception:
                pass
        return ToolResult.failure(f"Falha na análise de risco: {exc}")

    return ToolResult(
        ok=True,
        content=(
            f"classificação={result.get('classification')} "
            f"score={result.get('score')} provider={result.get('provider')}"
        ),
        data=result,
    )


@tool(
    name="mcp_security_scan",
    description=(
        "Escaneia servidores ou ferramentas MCP com o Cisco AI Defense MCP Scanner "
        "em busca de injeções de prompt, exfiltração de dados, vulnerabilidades e "
        "anomalias de comportamento. Leitura apenas — não altera estado."
    ),
    risk=RiskClass.READ,
    parameters={
        "type": "object",
        "properties": {
            "server_name": {
                "type": "string",
                "description": (
                    "Nome do servidor MCP cadastrado para auditar "
                    "(opcional se quiser escanear todos)."
                ),
            },
            "analyzers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Lista de analisadores ('yara', 'llm'). Padrão: ['yara'].",
            },
        },
    },
    summarize=lambda a: f"scan MCP: {a.get('server_name') or 'todos'}",
)
async def mcp_security_scan(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    from eltanix.config import get_settings
    from eltanix.mcp import config_editor
    from eltanix.mcp.config import MCPServerConfig
    from eltanix.mcp.scanner import MCPScannerService

    settings = get_settings()
    scanner = MCPScannerService(settings)
    server_name = str(args.get("server_name") or "").strip()
    analyzers = args.get("analyzers") or ["yara"]

    try:
        data = config_editor.load(settings.mcp_config_file)
        servers = data.get("servers", [])
        if server_name:
            target = next((s for s in servers if s.get("name") == server_name), None)
            if not target:
                return ToolResult.failure(
                    f"Servidor MCP '{server_name}' não encontrado na configuração."
                )
            cfg = MCPServerConfig.model_validate(target)
            res = await scanner.scan_server(cfg, analyzers=analyzers)
            return ToolResult(
                ok=res.status != "error",
                content=(
                    f"Servidor '{server_name}': status={res.status}, "
                    f"achados={res.findings_count}, ferramentas={res.tools_scanned}"
                ),
                data=res.to_dict(),
            )
        else:
            results = []
            for s in servers:
                cfg = MCPServerConfig.model_validate(s)
                res = await scanner.scan_server(cfg, analyzers=analyzers)
                results.append(res.to_dict())
            return ToolResult(
                ok=True,
                content=f"Escaneamento de {len(results)} servidores concluído.",
                data={"results": results},
            )
    except Exception as exc:
        return ToolResult.failure(f"Falha ao executar scanner MCP: {exc}")
