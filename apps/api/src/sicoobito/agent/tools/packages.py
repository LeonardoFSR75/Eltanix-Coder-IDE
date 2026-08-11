"""Ferramenta de gestão de pacotes e dependências do projeto para o agente.

Permite ao agente consultar, instalar, desinstalar e sincronizar pacotes Python
no ambiente `.venv` persistente do projeto e no `requirements.txt`, utilizando a
camada de pacotes da IDE (que possui acesso à rede no servidor host), contornando
o isolamento de rede do sandbox de execução de comandos.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from sicoobito.agent.tools.base import RiskClass, ToolContext, ToolResult, tool
from sicoobito.logging_setup import get_logger

log = get_logger(__name__)


@tool(
    name="manage_packages",
    description=(
        "Gerencia os pacotes Python no ambiente (.venv) e no requirements.txt do projeto. "
        "Use para instalar pacotes ('install'), desinstalar ('uninstall'), listar "
        "pacotes instalados ('list') ou sincronizar o ambiente ('sync'). Como o sandbox "
        "de comando não tem acesso à rede, esta é a ferramenta correta para adicionar "
        "dependências ao projeto."
    ),
    risk=RiskClass.WRITE,
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["install", "uninstall", "list", "sync"],
                "description": "Ação a realizar: install, uninstall, list ou sync",
            },
            "package": {
                "type": "string",
                "description": "Nome do pacote ou especificação (ex: 'pandas', 'requests>=2.28.0') (obrigatório em install/uninstall)",
            },
            "save_requirements": {
                "type": "boolean",
                "description": "Se True (padrão), atualiza automaticamente o arquivo requirements.txt do projeto",
            },
        },
        "required": ["action"],
    },
    summarize=lambda a: f"gerenciar pacotes ({a.get('action')}, pacote={a.get('package') or 'N/A'})",
)
async def manage_packages(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    from sicoobito.api.routes.packages import (
        ensure_venv,
        get_pip_executable,
        get_python_executable,
        get_venv_path,
        parse_requirements_txt,
        sync_requirements_file,
    )

    action = args.get("action", "list")
    package = (args.get("package") or "").strip()
    save_requirements = args.get("save_requirements", True)

    project_path = Path(ctx.workspace_root)

    if action == "list":
        venv_path = get_venv_path(project_path)
        py_exe = get_python_executable(venv_path)
        pip_exe = get_pip_executable(venv_path)
        installed_packages: list[dict[str, str]] = []

        if py_exe.exists() and pip_exe.exists():
            cmd = [str(pip_exe), "list", "--format=json"]
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(project_path),
                )
                stdout, _ = await proc.communicate()
                if proc.returncode == 0:
                    import json
                    raw_pkgs = json.loads(stdout.decode(errors="ignore"))
                    installed_packages = [
                        {"name": p["name"], "version": p["version"]} for p in raw_pkgs
                    ]
            except Exception as exc:
                log.warning("manage_packages.list.failed", error=str(exc))

        req_map = parse_requirements_txt(project_path)
        req_file = project_path / "requirements.txt"
        req_content = req_file.read_text(encoding="utf-8", errors="ignore") if req_file.exists() else ""

        count = len(installed_packages)
        content_str = (
            f"=== Pacotes do Projeto ({project_path.name}) ===\n"
            f"Ambiente Virtual (.venv): {'Existente' if py_exe.exists() else 'Não criado'}\n"
            f"Total de Pacotes Instalados: {count}\n"
            f"requirements.txt: {'Sim' if req_file.exists() else 'Não'}\n"
        )
        if installed_packages:
            amostra = ", ".join(f"{p['name']}=={p['version']}" for p in installed_packages[:15])
            content_str += f"Instalados (primeiros 15): {amostra}\n"

        return ToolResult(
            ok=True,
            content=content_str,
            data={
                "installed_count": count,
                "packages": installed_packages,
                "requirements_exists": req_file.exists(),
                "requirements_content": req_content,
                "requirements_map": req_map,
            },
        )

    elif action == "install":
        if not package:
            return ToolResult.failure("O nome do pacote é obrigatório para a ação 'install'.")

        try:
            venv_path = await ensure_venv(project_path)
        except Exception as exc:
            return ToolResult.failure(f"Falha ao preparar venv do projeto: {exc}")

        pip_exe = get_pip_executable(venv_path)
        cmd = [str(pip_exe), "install", package]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(project_path),
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            return ToolResult.failure(
                f"Falha ao instalar pacote '{package}': {stderr.decode(errors='ignore')}"
            )

        import re
        pkg_clean = re.split(r"[=><~!]", package)[0].strip()
        installed_version = None

        cmd_show = [str(pip_exe), "show", pkg_clean]
        proc_show = await asyncio.create_subprocess_exec(
            *cmd_show,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(project_path),
        )
        stdout_show, _ = await proc_show.communicate()
        if proc_show.returncode == 0:
            for line in stdout_show.decode(errors="ignore").splitlines():
                if line.startswith("Version:"):
                    installed_version = line.split(":", 1)[1].strip()
                    break

        req_content = ""
        if save_requirements:
            req_content = sync_requirements_file(project_path, pkg_clean, installed_version, remove=False)

        ver_str = f"=={installed_version}" if installed_version else ""
        return ToolResult(
            ok=True,
            content=(
                f"Pacote '{pkg_clean}{ver_str}' instalado com sucesso no .venv do projeto."
                + (" O requirements.txt foi atualizado." if save_requirements else "")
            ),
            data={
                "package": pkg_clean,
                "version": installed_version,
                "requirements_updated": save_requirements,
                "requirements_content": req_content,
                "stdout": stdout.decode(errors="ignore"),
            },
        )

    elif action == "uninstall":
        if not package:
            return ToolResult.failure("O nome do pacote é obrigatório para a ação 'uninstall'.")

        venv_path = get_venv_path(project_path)
        pip_exe = get_pip_executable(venv_path)

        if not pip_exe.exists():
            return ToolResult.failure("Ambiente virtual (.venv) do projeto não existe.")

        cmd = [str(pip_exe), "uninstall", "-y", package]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(project_path),
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            return ToolResult.failure(
                f"Falha ao desinstalar '{package}': {stderr.decode(errors='ignore')}"
            )

        req_content = ""
        if save_requirements:
            req_content = sync_requirements_file(project_path, package, remove=True)

        return ToolResult(
            ok=True,
            content=f"Pacote '{package}' desinstalado com sucesso."
            + (" Removido do requirements.txt." if save_requirements else ""),
            data={
                "package": package,
                "requirements_updated": save_requirements,
                "requirements_content": req_content,
                "stdout": stdout.decode(errors="ignore"),
            },
        )

    elif action == "sync":
        req_file = project_path / "requirements.txt"
        if not req_file.exists():
            return ToolResult.failure("Arquivo requirements.txt não encontrado no projeto.")

        try:
            venv_path = await ensure_venv(project_path)
        except Exception as exc:
            return ToolResult.failure(f"Falha ao preparar venv do projeto: {exc}")

        pip_exe = get_pip_executable(venv_path)
        cmd = [str(pip_exe), "install", "-r", str(req_file)]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(project_path),
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            return ToolResult.failure(
                f"Falha ao sincronizar requirements.txt: {stderr.decode(errors='ignore')}"
            )

        return ToolResult(
            ok=True,
            content="Ambiente .venv do projeto sincronizado com sucesso com o requirements.txt.",
            data={"stdout": stdout.decode(errors="ignore")},
        )

    return ToolResult.failure(f"Ação desconhecida: {action}")
