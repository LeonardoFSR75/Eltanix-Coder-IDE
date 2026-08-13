"""Ferramenta do agente para classificar risco de prompt/texto."""

from __future__ import annotations

from typing import Any

from sicoobito.agent.tools.base import RiskClass, ToolContext, ToolResult, tool


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
                "description": "Texto em claro a ser classificado. Pode ser um prompt, mensagem ou instrução do usuário.",
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
                    details=f"classificação={result.get('classification')} score={result.get('score')}",
                    risk_level="medium" if result.get("classification") in {"suspicious", "unsafe"} else "low",
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
        content=f"classificação={result.get('classification')} score={result.get('score')} provider={result.get('provider')}",
        data=result,
    )
