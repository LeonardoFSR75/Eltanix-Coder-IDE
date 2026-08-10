"""Ferramenta de verificação visual — o agente abre um navegador de verdade.

Uma ferramenta composta para todas as ações (`browser_action`), no mesmo
espírito de `run_command` ser uma ferramenta só para todo comando de shell:
navegar, clicar, digitar e tirar screenshot são passos do mesmo fluxo de
verificação, não capacidades separadas que o modelo precisaria descobrir uma
a uma.

É `RiskClass.EXEC` de propósito: uma URL vem do modelo, e um modelo
manipulado por conteúdo externo (issue, README, saída de comando — ver
`read_issue` em vcs.py) poderia tentar navegar para um destino controlado por
quem escreveu aquele conteúdo. A aprovação humana é a mesma barreira que já
existe para `run_command`.
"""

from __future__ import annotations

from typing import Any

from sicoobito.agent.tools.base import RiskClass, ToolContext, ToolResult, tool
from sicoobito.browser.client import BrowserError, BrowserUnavailableError

_ACTIONS = {"navigate", "click", "type", "screenshot", "content"}


def _summarize(args: dict[str, Any]) -> str:
    acao = args.get("action", "?")
    if acao == "navigate":
        return f"navegador: abrir {args.get('url')}"
    if acao == "click":
        alvo = args.get("selector") or f"({args.get('x')}, {args.get('y')})"
        return f"navegador: clicar em {alvo}"
    if acao == "type":
        return f"navegador: digitar em {args.get('selector')}"
    if acao == "screenshot":
        return "navegador: tirar screenshot"
    if acao == "content":
        return "navegador: ler texto da página"
    return f"navegador: {acao}"


@tool(
    name="browser_action",
    description=(
        "Controla um navegador de verdade para verificar visualmente uma aplicação web "
        "rodando (a própria interface do SicoobitoCode, por exemplo). Ações: `navigate` "
        "(abrir uma URL http(s)), `click` (por `selector` CSS ou por `x`/`y`), `type` "
        "(preencher um campo por `selector`), `screenshot` (captura a tela atual) e "
        "`content` (texto visível da página). Use depois de `run_command` subir um "
        "servidor — o navegador roda num serviço isolado que só alcança a própria "
        "aplicação, nunca a internet."
    ),
    risk=RiskClass.EXEC,
    parameters={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": sorted(_ACTIONS)},
            "url": {
                "type": "string",
                "description": "Obrigatório para `navigate`; precisa ser http(s)",
            },
            "selector": {"type": "string", "description": "Seletor CSS, para `click`/`type`"},
            "x": {
                "type": "number",
                "description": "Coordenada X, alternativa a `selector` em `click`",
            },
            "y": {
                "type": "number",
                "description": "Coordenada Y, alternativa a `selector` em `click`",
            },
            "text": {"type": "string", "description": "Texto a digitar, para `type`"},
        },
        "required": ["action"],
    },
    summarize=_summarize,
)
async def browser_action(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    if ctx.browser is None:
        return ToolResult.failure(
            "Navegador indisponível — o serviço de verificação visual (BROWSER_URL) não "
            "está configurado nesta instância."
        )

    acao = args.get("action")
    if acao not in _ACTIONS:
        return ToolResult.failure(f"Ação desconhecida: {acao!r}. Use uma de {sorted(_ACTIONS)}.")

    if acao == "navigate" and not str(args.get("url", "")).startswith(("http://", "https://")):
        return ToolResult.failure("`navigate` exige `url` começando com http:// ou https://.")
    if acao == "click" and not args.get("selector") and args.get("x") is None:
        return ToolResult.failure("`click` exige `selector` ou `x`/`y`.")
    if acao == "type" and (not args.get("selector") or args.get("text") is None):
        return ToolResult.failure("`type` exige `selector` e `text`.")

    try:
        resultado = await ctx.browser.action(
            {
                "action": acao,
                "url": args.get("url"),
                "selector": args.get("selector"),
                "x": args.get("x"),
                "y": args.get("y"),
                "text": args.get("text"),
            }
        )
    except BrowserUnavailableError as exc:
        return ToolResult.failure(str(exc))
    except BrowserError as exc:
        return ToolResult.failure(f"ação de navegador falhou: {exc}")

    if acao == "screenshot":
        imagem = resultado.get("image_base64", "")
        return ToolResult(
            ok=True,
            content=f"Screenshot capturado ({len(imagem)} chars base64).",
            data={"image_base64": imagem, "url": resultado.get("url")},
        )
    if acao == "navigate":
        url_str = resultado.get("url")
        title_str = resultado.get("title")
        status_code = resultado.get("status")
        return ToolResult(
            ok=True,
            content=f"Aberto {url_str} — título: {title_str!r}, status {status_code}.",
            data=resultado,
        )
    if acao == "content":
        texto = resultado.get("text", "")
        return ToolResult(ok=True, content=texto, data={"text": texto})

    return ToolResult(ok=True, content=f"{acao} concluído.", data=resultado)
