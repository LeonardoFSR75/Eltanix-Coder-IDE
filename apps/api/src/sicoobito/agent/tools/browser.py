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

    if acao == "navigate":
        url_raw = str(args.get("url", ""))
        if not url_raw.startswith(("http://", "https://")):
            return ToolResult.failure("`navigate` exige `url` começando com http:// ou https://.")
        from urllib.parse import urlparse

        parsed = urlparse(url_raw)
        hostname = (parsed.hostname or "").lower()
        if (
            hostname not in {"localhost", "127.0.0.1", "0.0.0.0", "web", "api"}
            and not hostname.startswith("sicoobito-")
        ):
            return ToolResult(
                ok=True,
                content=(
                    "AVISO DE AMBIENTE: O navegador do SicoobitoCode é isolado da rede pública e "
                    "é destinado EXCLUSIVAMENTE para testar e inspecionar a aplicação web local "
                    "no sandbox (ex.: http://localhost:5000).\n"
                    f"Ele não navega em sites externos da internet como '{hostname}'.\n"
                    "Para consultar extensões, convenções ou templates do ecossistema (como Vue, "
                    "React, etc.), utilize as ferramentas `list_skills` e `load_skill` ou consulte "
                    "os arquivos locais do projeto."
                ),
                data={"url": url_raw, "blocked": True},
            )
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
        msg = f"ação de navegador falhou: {exc}"
        if "ERR_CONNECTION_REFUSED" in msg or "Connection refused" in msg:
            msg += (
                "\n\n💡 DICA DE NAVEGADOR: A conexão com o servidor foi recusada. "
                "Certifique-se de que o servidor web foi iniciado no sandbox "
                "(ex: `python app.py & sleep 2` ou `python -m http.server 5000 & sleep 2`), "
                "que esteja escutando na interface correta (ex: 0.0.0.0 ou 127.0.0.1) "
                "e aguarde a porta abrir antes de navegar."
            )
        return ToolResult.failure(msg)

    erros_console = resultado.get("console_errors") or []
    erros_pagina = resultado.get("page_errors") or []
    aviso_erros = ""
    if erros_pagina or erros_console:
        linhas: list[str] = ["\n\n⚠️ AVISO: Erros detectados na página/console do navegador:"]
        for p_err in erros_pagina[:5]:
            linhas.append(f"  - [PAGE ERROR] {p_err}")
        for c_err in erros_console[:5]:
            linhas.append(f"  - {c_err}")
        aviso_erros = "\n".join(linhas)

    if acao == "screenshot":
        imagem = resultado.get("image_base64", "")
        return ToolResult(
            ok=True,
            content=f"Screenshot capturado ({len(imagem)} chars base64).{aviso_erros}",
            data={**resultado, "image_base64": imagem, "url": resultado.get("url")},
        )
    if acao == "navigate":
        url_str = resultado.get("url")
        title_str = resultado.get("title")
        status_code = resultado.get("status")
        return ToolResult(
            ok=True,
            content=(
                f"Aberto {url_str} — título: {title_str!r}, status {status_code}.{aviso_erros}"
            ),
            data=resultado,
        )
    if acao == "content":
        texto = resultado.get("text", "")
        return ToolResult(ok=True, content=f"{texto}{aviso_erros}", data=resultado)

    return ToolResult(ok=True, content=f"{acao} concluído.{aviso_erros}", data=resultado)
