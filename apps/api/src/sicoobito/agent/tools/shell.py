"""Execução de comandos — sempre dentro do sandbox.

A saída de comando é o maior desperdício de token de uma sessão agêntica: uma
suíte de testes despeja milhares de linhas das quais interessam a última dezena
e as que contêm falha. O truncamento aqui é cabeça + falhas + cauda, não um
corte cego no início.
"""

from __future__ import annotations

import re
from typing import Any

from sicoobito.agent.tools.base import RiskClass, ToolContext, ToolResult, tool
from sicoobito.sandbox.container import SandboxError

HEAD_LINES = 40
TAIL_LINES = 60
MAX_ERROR_LINES = 60

_ERROR_RE = re.compile(
    r"(error|failed|failure|exception|traceback|assert|✗|FAIL|E\s{3})", re.IGNORECASE
)


def summarize_output(text: str, *, head: int = HEAD_LINES, tail: int = TAIL_LINES) -> str:
    """Preserva cabeça, cauda e as linhas que contêm sinal de erro."""
    lines = text.splitlines()
    if len(lines) <= head + tail:
        return text

    cabeca = lines[:head]
    cauda = lines[-tail:]
    meio = lines[head:-tail]
    erros = [linha for linha in meio if _ERROR_RE.search(linha)][:MAX_ERROR_LINES]

    partes = ["\n".join(cabeca)]
    if erros:
        partes.append(f"\n... [{len(meio)} linhas omitidas; linhas com erro preservadas] ...\n")
        partes.append("\n".join(erros))
    else:
        partes.append(f"\n... [{len(meio)} linhas omitidas] ...\n")
    partes.append("\n".join(cauda))
    return "\n".join(partes)


@tool(
    name="run_command",
    description=(
        "Executa um comando de shell no sandbox, na raiz do workspace. "
        "O sandbox não tem acesso à rede por padrão e é descartado ao fim da "
        "sessão. Use para rodar testes, linters e build."
    ),
    risk=RiskClass.EXEC,
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Comando completo, ex.: 'pytest -q'"},
            "timeout": {"type": "integer", "description": "Segundos até interromper; padrão 300"},
        },
        "required": ["command"],
    },
    summarize=lambda a: f"executar: {a.get('command')}",
)
async def run_command(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    if ctx.sandbox is None:
        return ToolResult.failure(
            "Sandbox indisponível — o Docker precisa estar rodando para executar comandos."
        )

    comando = args["command"].strip()
    partes = comando.split()
    primeiro = partes[0] if partes else ""
    extensoes_estaticas = (".html", ".htm", ".css", ".json", ".txt", ".md", ".png", ".jpg", ".svg")
    if any(primeiro.lower().endswith(ext) for ext in extensoes_estaticas) or any(primeiro.lower().startswith("./") and primeiro.lower().endswith(ext) for ext in extensoes_estaticas):
        return ToolResult(
            ok=True,
            content=(
                f"[saída 126]\n"
                f"ERRO DE COMANDO: '{primeiro}' é um arquivo estático de dados e não um binário executável.\n"
                f"Para testar ou servir um arquivo HTML/Web no sandbox, utilize 'python -m http.server' ou a ferramenta 'browser_action'."
            ),
            data={"command": comando, "exit_code": 126, "duration_ms": 0, "timed_out": False},
        )

    try:
        resultado = await ctx.sandbox.exec(comando, timeout=args.get("timeout"))
    except SandboxError as exc:
        return ToolResult.failure(str(exc))


    corpo = summarize_output(resultado.stdout)
    if resultado.stderr.strip():
        corpo += f"\n\n--- stderr ---\n{summarize_output(resultado.stderr)}"

    estado = "sucesso" if resultado.ok else f"saída {resultado.exit_code}"
    if resultado.timed_out:
        estado = "tempo esgotado"

    return ToolResult(
        # Comando que falha não é falha da ferramenta: o modelo precisa do
        # resultado para decidir o próximo passo, então `ok=True`.
        ok=True,
        content=f"[{estado} em {resultado.duration_ms}ms]\n{corpo}",
        data={
            "command": comando,
            "exit_code": resultado.exit_code,
            "duration_ms": resultado.duration_ms,
            "timed_out": resultado.timed_out,
        },
    )
