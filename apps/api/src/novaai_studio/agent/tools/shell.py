"""Execução de comandos — sempre dentro do sandbox.

A saída de comando é o maior desperdício de token de uma sessão agêntica: uma
suíte de testes despeja milhares de linhas das quais interessam a última dezena
e as que contêm falha. O truncamento aqui é cabeça + falhas + cauda, não um
corte cego no início.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from novaai_studio.agent.tools.base import RiskClass, ToolContext, ToolResult, tool
from novaai_studio.sandbox.container import SandboxError

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


def project_venv_prefix(workspace_root: str | Path | None) -> str:
    """Força a execução a usar o venv montado no sandbox do projeto garantindo os
    caminhos padrão do Linux."""
    if not workspace_root:
        return ""

    root = Path(workspace_root)
    canonical = root
    cur = root.resolve()
    while cur != cur.parent:
        if cur.name == "worktrees" and cur.parent.name == ".novaai_studio":
            canonical = cur.parent.parent
            break
        cur = cur.parent

    if not (root / ".venv").exists() and not (canonical / ".venv").exists():
        return ""

    paths = (
        "/tmp/novaai_studio_bootstrap:"
        "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:"
        "/workspace/.venv/bin:/workspace/.venv/Scripts:/workspace/node_modules/.bin:$PATH"
    )
    pythonpaths = (
        "/tmp/novaai_studio_bootstrap:"
        "/workspace:"
        "/workspace/.venv/lib/python3.12/site-packages:"
        "/workspace/.venv/lib/python3.11/site-packages:"
        "/workspace/.venv/lib/python3.10/site-packages:"
        "/workspace/.venv/Lib/site-packages:"
        "/workspace/.venv/lib/site-packages:$PYTHONPATH"
    )
    return (
        f"export VIRTUAL_ENV='/workspace/.venv'; "
        f"export PATH='{paths}'; "
        f"export PYTHONPATH='{pythonpaths}'; "
    )


def _run_command_status(resultado: ToolResult) -> str:
    """`run_command` sempre devolve `ok=True` de propósito (comando que falha
    é informação pro modelo decidir o próximo passo, não uma falha da
    ferramenta em si) — sem isto, telemetria/observabilidade (`_telemetry_status`
    em `agent/graph.py`) mostraria todo `pip install` sem rede como
    `status="ok"` em `/api/telemetry/recent`, escondendo a falha real."""
    dados = resultado.data or {}
    if dados.get("timed_out") or dados.get("exit_code") not in (0, None):
        return "error"
    return "ok" if resultado.ok else "error"


@tool(
    name="run_command",
    description=(
        "Executa um comando de shell no sandbox, na raiz do workspace. "
        "O sandbox NÃO tem acesso à rede: pip install/npm install/curl/download "
        "sempre falham por resolução de DNS — não tente instalar pacotes novos, "
        "use só a biblioteca padrão ou o que já está instalado. É descartado ao "
        "fim da sessão. Use para rodar testes, linters e build."
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
    status_from_result=_run_command_status,
)
async def run_command(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    if ctx.sandbox is None and getattr(ctx, "sandboxes", None) is not None:
        try:
            ctx.sandbox = await ctx.sandboxes.acquire(ctx.session_id, ctx.workspace_root)
        except Exception:
            pass

    if ctx.sandbox is None:
        return ToolResult.failure(
            "Sandbox indisponível — o Docker precisa estar rodando para executar comandos."
        )

    comando = args["command"].strip()
    prefixo_venv = project_venv_prefix(getattr(ctx, "workspace_root", None))
    if prefixo_venv and not comando.startswith(("export ", "source ", "cd ", "VIRTUAL_ENV=")):
        comando = f"{prefixo_venv}{comando}"

    partes = comando.split()
    primeiro = partes[0] if partes else ""
    extensoes_estaticas = (".html", ".htm", ".css", ".json", ".txt", ".md", ".png", ".jpg", ".svg")
    eh_arquivo_estatico = any(primeiro.lower().endswith(ext) for ext in extensoes_estaticas) or any(
        primeiro.lower().startswith("./") and primeiro.lower().endswith(ext)
        for ext in extensoes_estaticas
    )
    if eh_arquivo_estatico:
        return ToolResult(
            ok=True,
            content=(
                f"[saída 126]\n"
                f"ERRO DE COMANDO: '{primeiro}' é um arquivo estático de dados e não um "
                f"binário executável.\n"
                f"Para testar ou servir um arquivo HTML/Web no sandbox, utilize "
                f"'python -m http.server' ou a ferramenta 'browser_action'."
            ),
            data={"command": comando, "exit_code": 126, "duration_ms": 0, "timed_out": False},
        )

    # Interceptação de instalações de pacotes via shell em sandbox sem rede:
    cmd_lower = comando.lower()
    partes_lower = [p.lower() for p in partes]
    eh_comando_pacote = (
        "pip install" in cmd_lower
        or "pip3 install" in cmd_lower
        or ("pip" in partes_lower and "install" in partes_lower)
        or "npm install" in cmd_lower
        or "npm i " in cmd_lower
        or "yarn add" in cmd_lower
        or "pnpm add" in cmd_lower
        or "go get" in cmd_lower
        or "go install" in cmd_lower
        or "cargo add" in cmd_lower
        or "composer require" in cmd_lower
    )
    network_enabled = getattr(getattr(ctx, "sandbox", None), "config", None) and getattr(
        ctx.sandbox.config, "network_enabled", False
    )

    if eh_comando_pacote and not network_enabled:
        return ToolResult(
            ok=True,
            content=(
                "[saída 1 em 0ms]\n"
                "ERRO DE AMBIENTE: O sandbox do NovaAI Studio está isolado da rede por segurança.\n"
                "Comandos de instalação de pacotes (pip, npm, go get, cargo add, composer "
                "require) falham no shell do container.\n"
                "Para instalar pacotes e dependências no ambiente do projeto de forma "
                "persistente, utilize a ferramenta 'manage_packages' "
                "(ex.: manage_packages(action='install', package='nome_do_pacote')) "
                "ou a aba 'Pacotes' da IDE."
            ),
            data={"command": comando, "exit_code": 1, "duration_ms": 0, "timed_out": False},
        )

    # Interceptação de servidores contínuos (Flask, Uvicorn, Next.js, etc.):
    # Servidores bloqueiam o sandbox se executados em foreground. Gerencia liberação
    # prévia de portas ocupadas, execução em segundo plano e health check do socket.
    eh_servidor_provavel = any(
        srv in cmd_lower
        for srv in [
            "flask run",
            "uvicorn",
            "http.server",
            "gunicorn",
            "streamlit run",
            "npm run dev",
            "npm start",
            "next dev",
            "vite",
        ]
    ) or any(
        cmd_lower.startswith(p) or f" {p}" in cmd_lower
        for p in [
            "python app.py",
            "python3 app.py",
            "python server.py",
            "python3 server.py",
            "node server.js",
            "node app.js",
            "node index.js",
        ]
    )
    eh_comando_pontual = any(
        t in cmd_lower
        for t in [
            "pytest",
            "unittest",
            "test_",
            "_test",
            "check",
            "lint",
            "build",
            "-c",
            "--help",
            "-h",
            "-v",
            "--version",
            "cat ",
            "ls ",
            "grep ",
        ]
    )

    if eh_servidor_provavel and not eh_comando_pontual:
        # Detecta porta alvo
        porta_alvo = 5000
        if "8000" in comando or "uvicorn" in cmd_lower:
            porta_alvo = 8000
        elif "3000" in comando or "next" in cmd_lower:
            porta_alvo = 3000
        elif "5173" in comando or "vite" in cmd_lower:
            porta_alvo = 5173
        elif "8501" in comando or "streamlit" in cmd_lower:
            porta_alvo = 8501

        # Limpa sufixos de backgrounding adicionados pelo modelo (ex: & sleep 2)
        cmd_limpo = re.sub(r"\s*&\s*sleep\s+\d+", "", comando).strip().rstrip("&").strip()
        # Escapa aspas simples no comando para envolver em bash -c '...'
        cmd_escapado = cmd_limpo.replace("'", "'\"'\"'")
        comando = (
            f"fuser -k {porta_alvo}/tcp >/dev/null 2>&1 || true; "
            f"sleep 0.2; "
            f"nohup bash -c '{cmd_escapado}' > /tmp/novaai_studio_server.log 2>&1 & "
            f"for i in $(seq 1 20); do "
            f"(echo > /dev/tcp/127.0.0.1/{porta_alvo}) >/dev/null 2>&1 && break || sleep 0.3; "
            f"done; "
            f"sleep 0.3; "
            f"cat /tmp/novaai_studio_server.log"
        )

    try:
        resultado = await ctx.sandbox.exec(comando, timeout=args.get("timeout"))
    except SandboxError as exc:
        return ToolResult.failure(str(exc))

    # Normaliza saídas de kill / pkill (código 143 é normal ao encerrar processo)
    if ("pkill" in cmd_lower or "kill" in cmd_lower) and resultado.exit_code == 143:
        resultado.exit_code = 0

    corpo = summarize_output(resultado.stdout)
    if resultado.stderr.strip():
        corpo += f"\n\n--- stderr ---\n{summarize_output(resultado.stderr)}"

    erro_de_rede = (
        "Temporary failure in name resolution" in corpo or "No matching distribution found" in corpo
    )
    erro_de_modulo_ausente = any(
        m in corpo
        for m in [
            "ModuleNotFoundError",
            "Cannot find module",
            "could not import",
            "unresolved import",
            "Class ",
            "Fatal error",
        ]
    )
    if erro_de_rede:
        corpo += (
            "\n\n💡 DICA DE PACOTES: O sandbox de comando não tem acesso à rede. "
            "Para instalar pacotes no projeto, utilize a ferramenta 'manage_packages' "
            "(action='install', package='...')."
        )
    elif erro_de_modulo_ausente:
        corpo += (
            "\n\n💡 DICA DE PACOTES: O pacote/módulo importado não está instalado no "
            "projeto. Utilize a ferramenta 'manage_packages' "
            "(ex.: manage_packages(action='install', package='nome_do_pacote')) "
            "para instalá-lo no ambiente do projeto (Python, Node.js, Go, Rust, PHP)."
        )

    estado = "sucesso" if resultado.ok else f"saída {resultado.exit_code}"
    dica_timeout = ""
    if resultado.timed_out:
        estado = "tempo esgotado"
        dica_timeout = (
            "\n\nDICA: o comando não retornou sozinho dentro do tempo limite — "
            "provavelmente é um servidor ou processo de longa duração. Rode em "
            "background (ex.: `comando & sleep 2` ou "
            "`nohup comando > saida.log 2>&1 & sleep 2`) "
            "para dar tempo do servidor inicializar a porta antes de testar com "
            "`browser_action` ou `curl`."
        )

    return ToolResult(
        # Comando que falha não é falha da ferramenta: o modelo precisa do
        # resultado para decidir o próximo passo, então `ok=True`.
        ok=True,
        content=f"[{estado} em {resultado.duration_ms}ms]\n{corpo}{dica_timeout}",
        data={
            "command": comando,
            "exit_code": resultado.exit_code,
            "duration_ms": resultado.duration_ms,
            "timed_out": resultado.timed_out,
        },
    )
