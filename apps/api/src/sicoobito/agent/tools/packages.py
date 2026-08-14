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


def _packages_risk(args: dict[str, Any]) -> RiskClass:
    action = (args.get("action") or "list").strip().lower()
    if action == "list":
        return RiskClass.READ
    return RiskClass.WRITE


@tool(
    name="manage_packages",
    description=(
        "Gerencia os pacotes Python no ambiente (.venv) e no requirements.txt do projeto. "
        "Use para instalar pacotes ('install'), desinstalar ('uninstall'), listar "
        "pacotes instalados ('list') ou sincronizar o ambiente ('sync'). Como o sandbox "
        "de comando não tem acesso à rede, esta é a ferramenta correta para adicionar "
        "dependências ao projeto."
    ),
    risk=_packages_risk,
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
                "description": (
                    "Nome do pacote ou especificação (ex: 'pandas', 'requests>=2.28.0') "
                    "(obrigatório em install/uninstall)"
                ),
            },
            "save_requirements": {
                "type": "boolean",
                "description": (
                    "Se True (padrão), atualiza automaticamente o arquivo requirements.txt "
                    "do projeto"
                ),
            },
        },
        "required": ["action"],
    },
    summarize=(
        lambda a: f"gerenciar pacotes ({a.get('action')}, pacote={a.get('package') or 'N/A'})"
    ),
)
async def manage_packages(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    import shutil

    from sicoobito.api.routes.packages import (
        detect_ecosystem,
        ensure_project_env,
        ensure_venv,
        get_manifest_name,
        get_python_executable,
        get_venv_path,
        parse_requirements_txt,
        sync_requirements_file,
    )

    action = args.get("action", "list")
    package = (args.get("package") or "").strip()
    save_requirements = args.get("save_requirements", True)

    project_path = Path(ctx.workspace_root)
    canonical_root = project_path
    if getattr(ctx, "project_root", None):
        canonical_root = Path(ctx.project_root)
    else:
        cur = project_path.resolve()  # noqa: ASYNC240
        while cur != cur.parent:
            if cur.name == "worktrees" and cur.parent.name == ".sicoobito":
                canonical_root = cur.parent.parent
                break
            cur = cur.parent
    project_display_name = ctx.project_slug or canonical_root.name

    # Garante que ambientes persistentes (.venv, node_modules) do projeto
    # canônico estejam disponíveis no worktree
    if (
        canonical_root != project_path
        and not (project_path / ".venv").exists()
        and (canonical_root / ".venv").exists()
    ):
        try:
            from sicoobito.workspace.git import _link_or_share_env

            _link_or_share_env(canonical_root, project_path)
        except Exception as exc:
            log.warning("manage_packages.link_env_failed", error=str(exc))

    eco = detect_ecosystem(project_path)
    if (
        eco == "python"
        and not (project_path / "requirements.txt").exists()
        and (canonical_root / "requirements.txt").exists()
    ):
        eco = detect_ecosystem(canonical_root)
    manifest_name = get_manifest_name(eco)

    if action == "list":
        installed_packages: list[dict[str, str]] = []
        venv_path = get_venv_path(project_path)
        if not venv_path.exists() and (canonical_root / ".venv").exists():
            venv_path = get_venv_path(canonical_root)
        py_exe = get_python_executable(venv_path)

        if eco == "nodejs":
            pkg_json = project_path / "package.json"
            if not pkg_json.exists() and (canonical_root / "package.json").exists():
                pkg_json = canonical_root / "package.json"
            if pkg_json.exists():
                try:
                    import json

                    data = json.loads(pkg_json.read_text(encoding="utf-8", errors="ignore"))
                    deps = data.get("dependencies", {})
                    dev_deps = data.get("devDependencies", {})
                    for k, v in {**deps, **dev_deps}.items():
                        installed_packages.append({"name": k, "version": str(v)})
                except Exception as exc:
                    log.warning("manage_packages.node_parse.failed", error=str(exc))
        elif eco == "go":
            go_mod = project_path / "go.mod"
            if not go_mod.exists() and (canonical_root / "go.mod").exists():
                go_mod = canonical_root / "go.mod"
            if go_mod.exists():
                import re

                for line in go_mod.read_text(encoding="utf-8", errors="ignore").splitlines():
                    line = line.strip()
                    match = re.match(r"^([a-zA-Z0-9_\-\.\/]+)\s+(v[0-9\.\-]+)", line)
                    if match:
                        installed_packages.append(
                            {"name": match.group(1), "version": match.group(2)}
                        )
        elif eco == "rust":
            cargo_toml = project_path / "Cargo.toml"
            if not cargo_toml.exists() and (canonical_root / "Cargo.toml").exists():
                cargo_toml = canonical_root / "Cargo.toml"
            if cargo_toml.exists():
                in_deps = False
                for line in cargo_toml.read_text(encoding="utf-8", errors="ignore").splitlines():
                    stripped = line.strip()
                    if stripped.startswith("["):
                        in_deps = "dependencies" in stripped.lower()
                        continue
                    if in_deps and "=" in stripped:
                        parts = stripped.split("=", 1)
                        k = parts[0].strip()
                        v = parts[1].strip().strip('"').strip("'")
                        installed_packages.append({"name": k, "version": v})
        elif eco == "php":
            composer_json = project_path / "composer.json"
            if not composer_json.exists() and (canonical_root / "composer.json").exists():
                composer_json = canonical_root / "composer.json"
            if composer_json.exists():
                try:
                    import json

                    data = json.loads(composer_json.read_text(encoding="utf-8", errors="ignore"))
                    reqs = data.get("require", {})
                    for k, v in reqs.items():
                        if k != "php":
                            installed_packages.append({"name": k, "version": str(v)})
                except Exception as exc:
                    log.warning("manage_packages.php_parse.failed", error=str(exc))
        else:
            if py_exe.exists():
                cmd = [str(py_exe), "-m", "pip", "list", "--format=json"]
                try:
                    proc = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=str(project_path),
                    )
                    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
                    if proc.returncode == 0:
                        import json

                        raw_pkgs = json.loads(stdout.decode(errors="ignore"))
                        installed_packages = [
                            {"name": p["name"], "version": p["version"]} for p in raw_pkgs
                        ]
                except Exception as exc:
                    log.warning("manage_packages.list.failed", error=str(exc))

        manifest_file = project_path / manifest_name
        if not manifest_file.exists() and (canonical_root / manifest_name).exists():
            manifest_file = canonical_root / manifest_name
        req_map = (
            parse_requirements_txt(project_path)
            if eco == "python" and (project_path / "requirements.txt").exists()
            else (
                parse_requirements_txt(canonical_root)
                if eco == "python" and (canonical_root / "requirements.txt").exists()
                else {p["name"]: p["version"] for p in installed_packages}
            )
        )
        req_content = (
            manifest_file.read_text(encoding="utf-8", errors="ignore")
            if manifest_file.exists()
            else ""
        )

        count = len(installed_packages)
        content_str = (
            f"=== Pacotes do Projeto ({project_display_name}) ===\n"
            f"Ecossistema: {eco.upper()} | Manifesto: {manifest_name}\n"
            f"Total de Pacotes Instalados: {count}\n"
        )
        if installed_packages:
            amostra = ", ".join(f"{p['name']}=={p['version']}" for p in installed_packages[:15])
            content_str += f"Instalados (primeiros 15): {amostra}\n"

        ctx.session_state.packages_checked = True

        return ToolResult(
            ok=True,
            content=content_str,
            data={
                "ecosystem": eco,
                "manifest_file": manifest_name,
                "installed_count": count,
                "packages": installed_packages,
                "requirements_exists": manifest_file.exists(),
                "requirements_content": req_content,
                "requirements_map": req_map,
            },
        )

    elif action == "install":
        if not package:
            return ToolResult.failure("O nome do pacote é obrigatório para a ação 'install'.")

        try:
            await ensure_project_env(project_path)
        except Exception as exc:
            return ToolResult.failure(f"Falha ao preparar ambiente do projeto: {exc}")

        if eco == "nodejs":
            npm_bin = shutil.which("npm")
            if not npm_bin:
                return ToolResult.failure("npm não encontrado no sistema.")
            cmd = [npm_bin, "install", package]
        elif eco == "go":
            go_bin = shutil.which("go")
            if not go_bin:
                return ToolResult.failure("go CLI não encontrado no sistema.")
            cmd = [go_bin, "get", package]
        elif eco == "rust":
            cargo_bin = shutil.which("cargo")
            if not cargo_bin:
                return ToolResult.failure("cargo não encontrado no sistema.")
            cmd = [cargo_bin, "add", package]
        elif eco == "php":
            composer_bin = shutil.which("composer")
            if not composer_bin:
                return ToolResult.failure("composer não encontrado no sistema.")
            cmd = [composer_bin, "require", package]
        else:
            venv_path = get_venv_path(project_path)
            py_exe = get_python_executable(venv_path)
            cmd = [str(py_exe), "-m", "pip", "install", package]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(project_path),
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        except TimeoutError:
            proc.kill()
            return ToolResult.failure(f"Tempo limite excedido ao instalar o pacote '{package}'.")

        if proc.returncode != 0:
            return ToolResult.failure(
                f"Falha ao instalar pacote '{package}': {stderr.decode(errors='ignore')}"
            )

        import re

        pkg_clean = re.split(r"[=><~!]", package)[0].strip()
        pkg_clean = pkg_clean.lower().replace("_", "-")
        installed_version = None
        req_content = ""

        if eco == "python" and save_requirements:
            cmd_show = [str(py_exe), "-m", "pip", "show", pkg_clean]
            proc_show = await asyncio.create_subprocess_exec(
                *cmd_show,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(project_path),
            )
            try:
                stdout_show, _ = await asyncio.wait_for(proc_show.communicate(), timeout=30)
                if proc_show.returncode == 0:
                    for line in stdout_show.decode(errors="ignore").splitlines():
                        if line.startswith("Version:"):
                            installed_version = line.split(":", 1)[1].strip()
                            break
            except Exception:
                pass
            req_content = sync_requirements_file(
                project_path, pkg_clean, installed_version, remove=False
            )
            if canonical_root != project_path and (canonical_root / "requirements.txt").exists():
                sync_requirements_file(canonical_root, pkg_clean, installed_version, remove=False)
        else:
            manifest_file = project_path / manifest_name
            if not manifest_file.exists() and (canonical_root / manifest_name).exists():
                manifest_file = canonical_root / manifest_name
            if manifest_file.exists():
                req_content = manifest_file.read_text(encoding="utf-8", errors="ignore")

        ver_str = f"=={installed_version}" if installed_version else ""
        return ToolResult(
            ok=True,
            content=(
                f"Pacote '{pkg_clean}{ver_str}' instalado com sucesso no ambiente "
                f"{eco.upper()} do projeto."
                + (f" O {manifest_name} foi atualizado." if save_requirements else "")
            ),
            data={
                "package": pkg_clean,
                "ecosystem": eco,
                "manifest_file": manifest_name,
                "version": installed_version,
                "requirements_updated": save_requirements,
                "requirements_content": req_content,
                "stdout": stdout.decode(errors="ignore"),
            },
        )

    elif action == "uninstall":
        if not package:
            return ToolResult.failure("O nome do pacote é obrigatório para a ação 'uninstall'.")

        if eco == "nodejs":
            npm_bin = shutil.which("npm")
            if not npm_bin:
                return ToolResult.failure("npm não encontrado.")
            cmd = [npm_bin, "uninstall", package]
        elif eco == "go":
            go_bin = shutil.which("go")
            if not go_bin:
                return ToolResult.failure("go CLI não encontrado.")
            cmd = [go_bin, "mod", "edit", f"-droprequire={package}"]
        elif eco == "rust":
            cargo_bin = shutil.which("cargo")
            if not cargo_bin:
                return ToolResult.failure("cargo não encontrado.")
            cmd = [cargo_bin, "remove", package]
        elif eco == "php":
            composer_bin = shutil.which("composer")
            if not composer_bin:
                return ToolResult.failure("composer não encontrado.")
            cmd = [composer_bin, "remove", package]
        else:
            venv_path = get_venv_path(project_path)
            if not venv_path.exists() and (canonical_root / ".venv").exists():
                venv_path = get_venv_path(canonical_root)
            py_exe = get_python_executable(venv_path)
            if not py_exe.exists():
                return ToolResult.failure("Ambiente virtual (.venv) do projeto não existe.")
            cmd = [str(py_exe), "-m", "pip", "uninstall", "-y", package]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(project_path),
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        except TimeoutError:
            proc.kill()
            return ToolResult.failure(f"Tempo limite excedido ao desinstalar '{package}'.")

        if proc.returncode != 0:
            return ToolResult.failure(
                f"Falha ao desinstalar '{package}': {stderr.decode(errors='ignore')}"
            )

        manifest_file = project_path / manifest_name
        if not manifest_file.exists() and (canonical_root / manifest_name).exists():
            manifest_file = canonical_root / manifest_name
        req_content = ""
        if eco == "python" and save_requirements:
            req_content = sync_requirements_file(project_path, package, remove=True)
            if canonical_root != project_path and (canonical_root / "requirements.txt").exists():
                sync_requirements_file(canonical_root, package, remove=True)
        elif manifest_file.exists():
            req_content = manifest_file.read_text(encoding="utf-8", errors="ignore")

        return ToolResult(
            ok=True,
            content=f"Pacote '{package}' desinstalado com sucesso."
            + (f" Removido do {manifest_name}." if save_requirements else ""),
            data={
                "package": package,
                "ecosystem": eco,
                "manifest_file": manifest_name,
                "requirements_updated": save_requirements,
                "requirements_content": req_content,
                "stdout": stdout.decode(errors="ignore"),
            },
        )

    elif action == "sync":
        manifest_file = project_path / manifest_name
        if not manifest_file.exists():
            return ToolResult.failure(f"Arquivo {manifest_name} não encontrado no projeto.")

        try:
            await ensure_project_env(project_path)
        except Exception as exc:
            return ToolResult.failure(f"Falha ao preparar ambiente do projeto: {exc}")

        if eco == "nodejs":
            npm_bin = shutil.which("npm")
            if not npm_bin:
                return ToolResult.failure("npm não encontrado.")
            cmd = [npm_bin, "install"]
        elif eco == "go":
            go_bin = shutil.which("go")
            if not go_bin:
                return ToolResult.failure("go CLI não encontrado.")
            cmd = [go_bin, "mod", "download"]
        elif eco == "rust":
            cargo_bin = shutil.which("cargo")
            if not cargo_bin:
                return ToolResult.failure("cargo não encontrado.")
            cmd = [cargo_bin, "check"]
        elif eco == "php":
            composer_bin = shutil.which("composer")
            if not composer_bin:
                return ToolResult.failure("composer não encontrado.")
            cmd = [composer_bin, "install"]
        else:
            venv_path = await ensure_venv(project_path)
            py_exe = get_python_executable(venv_path)
            cmd = [str(py_exe), "-m", "pip", "install", "-r", str(manifest_file)]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(project_path),
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        except TimeoutError:
            proc.kill()
            return ToolResult.failure(f"Tempo limite excedido ao sincronizar {manifest_name}.")

        if proc.returncode != 0:
            return ToolResult.failure(
                f"Falha ao sincronizar {manifest_name}: {stderr.decode(errors='ignore')}"
            )

        return ToolResult(
            ok=True,
            content=(
                f"Ambiente {eco.upper()} do projeto sincronizado com sucesso com o {manifest_name}."
            ),
            data={"stdout": stdout.decode(errors="ignore")},
        )

    return ToolResult.failure(f"Ação desconhecida: {action}")
