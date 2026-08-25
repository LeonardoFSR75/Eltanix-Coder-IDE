"""Comandos e listagem por ecossistema — extraído porque `api/routes/packages.py`
(REST, sem worktree) e `agent/tools/packages.py` (ferramenta do agente, com
fallback de worktree→projeto canônico) reimplementavam a mesma cadeia de
if/elif por ecossistema para montar comando e parsear manifesto. As duas
camadas continuam com suas próprias regras de timeout, resolução de caminho e
formato de erro (HTTPException vs ToolResult) — só o que é idêntico nas duas
(qual binário chamar, como ler cada tipo de manifesto) mora aqui.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from pathlib import Path
from typing import Any, Literal

PackageAction = Literal["install", "uninstall", "sync"]

_AUDIT_TIMEOUT_SECONDS = 90


class MissingBinaryError(RuntimeError):
    """O binário do ecossistema (npm/go/cargo/composer) não está no host."""

    def __init__(self, binary: str) -> None:
        self.binary = binary
        super().__init__(f"'{binary}' não encontrado no ambiente servidor.")


def build_ecosystem_command(
    eco: str,
    action: PackageAction,
    *,
    project_path: Path,
    package: str | None,
    py_exe: Path,
) -> list[str]:
    """Monta o argv para `install`/`uninstall`/`sync` no ecossistema dado.
    Levanta `MissingBinaryError` se o CLI necessário não está no PATH do host."""
    if eco == "nodejs":
        npm_bin = shutil.which("npm")
        if not npm_bin:
            raise MissingBinaryError("npm")
        if action == "install":
            return [npm_bin, "install", package or ""]
        if action == "uninstall":
            return [npm_bin, "uninstall", package or ""]
        return [npm_bin, "install"]

    if eco == "go":
        go_bin = shutil.which("go")
        if not go_bin:
            raise MissingBinaryError("go")
        if action == "install":
            return [go_bin, "get", package or ""]
        if action == "uninstall":
            return [go_bin, "mod", "edit", f"-droprequire={package or ''}"]
        return [go_bin, "mod", "download"]

    if eco == "rust":
        cargo_bin = shutil.which("cargo")
        if not cargo_bin:
            raise MissingBinaryError("cargo")
        if action == "install":
            return [cargo_bin, "add", package or ""]
        if action == "uninstall":
            return [cargo_bin, "remove", package or ""]
        return [cargo_bin, "check"]

    if eco == "php":
        composer_bin = shutil.which("composer")
        if not composer_bin:
            raise MissingBinaryError("composer")
        if action == "install":
            return [composer_bin, "require", package or ""]
        if action == "uninstall":
            return [composer_bin, "remove", package or ""]
        return [composer_bin, "install"]

    # python
    if action == "install":
        return [str(py_exe), "-m", "pip", "install", package or ""]
    if action == "uninstall":
        return [str(py_exe), "-m", "pip", "uninstall", "-y", package or ""]
    return [str(py_exe), "-m", "pip", "install", "-r", str(project_path / "requirements.txt")]


def parse_installed_packages(project_path: Path, eco: str) -> list[dict[str, str]]:
    """Lê o manifesto (package.json/go.mod/Cargo.toml/composer.json) para
    nodejs/go/rust/php. Python não tem entrada aqui: sua fonte de verdade é o
    `.venv` (`pip list`), que exige um subprocesso assíncrono — fica a cargo
    de cada chamador (ver `list_python_packages` abaixo)."""
    if eco == "nodejs":
        pkg_json = project_path / "package.json"
        if not pkg_json.exists():
            return []
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            return []
        deps = data.get("dependencies", {})
        dev_deps = data.get("devDependencies", {})
        return [{"name": k, "version": str(v)} for k, v in {**deps, **dev_deps}.items()]

    if eco == "go":
        go_mod = project_path / "go.mod"
        if not go_mod.exists():
            return []
        resultado = []
        for line in go_mod.read_text(encoding="utf-8", errors="ignore").splitlines():
            match = re.match(r"^([a-zA-Z0-9_\-\.\/]+)\s+(v[0-9\.\-]+)", line.strip())
            if match:
                resultado.append({"name": match.group(1), "version": match.group(2)})
        return resultado

    if eco == "rust":
        cargo_toml = project_path / "Cargo.toml"
        if not cargo_toml.exists():
            return []
        resultado = []
        in_deps = False
        for line in cargo_toml.read_text(encoding="utf-8", errors="ignore").splitlines():
            stripped = line.strip()
            if stripped.startswith("["):
                in_deps = "dependencies" in stripped.lower()
                continue
            if in_deps and "=" in stripped:
                k, _, v = stripped.partition("=")
                resultado.append({"name": k.strip(), "version": v.strip().strip('"').strip("'")})
        return resultado

    if eco == "php":
        composer_json = project_path / "composer.json"
        if not composer_json.exists():
            return []
        try:
            data = json.loads(composer_json.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            return []
        reqs = data.get("require", {})
        return [{"name": k, "version": str(v)} for k, v in reqs.items() if k != "php"]

    return []


async def list_python_packages(py_exe: Path, project_path: Path) -> list[dict[str, str]]:
    """`pip list --format=json` no `.venv` do projeto — único caso que precisa
    de subprocesso (os outros ecossistemas leem o manifesto estático)."""
    if not await asyncio.to_thread(py_exe.exists):
        return []
    try:
        proc = await asyncio.create_subprocess_exec(
            str(py_exe),
            "-m",
            "pip",
            "list",
            "--format=json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(project_path),
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode != 0:
            return []
        raw = json.loads(stdout.decode(errors="ignore"))
        return [{"name": p["name"], "version": p["version"]} for p in raw]
    except Exception:
        return []


async def run_dependency_audit(eco: str, project_path: Path, py_exe: Path) -> dict[str, Any]:
    """CVEs conhecidas nas dependências, via `pip-audit` (python) ou `npm audit`
    (nodejs) — os dois ecossistemas com scanner de linha de comando ubíquo. Os
    demais (go/rust/php) exigem uma ferramenta extra nem sempre presente no
    host (govulncheck/cargo-audit/local-php-security-checker); em vez de
    fingir suporte, devolvem `supported: False` explícito."""
    if eco == "python":
        return await _audit_python(project_path, py_exe)
    if eco == "nodejs":
        return await _audit_nodejs(project_path)
    return {"supported": False, "ecosystem": eco, "tool": None, "vulnerabilities": []}


async def _audit_python(project_path: Path, py_exe: Path) -> dict[str, Any]:
    audit_bin = shutil.which("pip-audit")
    if not audit_bin:
        return {
            "supported": True,
            "ecosystem": "python",
            "tool": "pip-audit",
            "tool_available": False,
            "vulnerabilities": [],
            "message": "'pip-audit' não está instalado no host (pip install pip-audit).",
        }

    req_file = project_path / "requirements.txt"
    cmd = [audit_bin, "--format=json"]
    cmd += ["-r", str(req_file)] if req_file.exists() else ["--path", str(py_exe.parent.parent)]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(project_path),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_AUDIT_TIMEOUT_SECONDS)
    except Exception as exc:
        return _audit_error("python", "pip-audit", str(exc))

    try:
        raw = json.loads(stdout.decode(errors="ignore"))
    except json.JSONDecodeError:
        return _audit_error("python", "pip-audit", stderr.decode(errors="ignore")[:500])

    dependencies = raw.get("dependencies", raw) if isinstance(raw, dict) else raw
    vulnerabilidades: list[dict[str, Any]] = []
    for dep in dependencies or []:
        for v in dep.get("vulns", []) or []:
            vulnerabilidades.append(
                {
                    "package": dep.get("name"),
                    "installed_version": dep.get("version"),
                    "id": v.get("id"),
                    "fix_versions": v.get("fix_versions", []),
                    "description": (v.get("description") or "")[:300],
                }
            )
    return {
        "supported": True,
        "ecosystem": "python",
        "tool": "pip-audit",
        "tool_available": True,
        "vulnerabilities": vulnerabilidades,
        "count": len(vulnerabilidades),
    }


async def _audit_nodejs(project_path: Path) -> dict[str, Any]:
    npm_bin = shutil.which("npm")
    if not npm_bin:
        return {
            "supported": True,
            "ecosystem": "nodejs",
            "tool": "npm audit",
            "tool_available": False,
            "vulnerabilities": [],
            "message": "'npm' não está no PATH do host.",
        }

    try:
        proc = await asyncio.create_subprocess_exec(
            npm_bin,
            "audit",
            "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(project_path),
        )
        # `npm audit` sai com código != 0 quando ENCONTRA vulnerabilidades — não é
        # falha de execução, então o retorno não é checado, só o JSON no stdout.
        stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=_AUDIT_TIMEOUT_SECONDS)
    except Exception as exc:
        return _audit_error("nodejs", "npm audit", str(exc))

    try:
        raw = json.loads(stdout.decode(errors="ignore"))
    except json.JSONDecodeError:
        return _audit_error("nodejs", "npm audit", "saída inválida de 'npm audit --json'.")

    vulnerabilidades = [
        {
            "package": nome,
            "severity": info.get("severity"),
            "range": info.get("range"),
            "fix_available": bool(info.get("fixAvailable")),
        }
        for nome, info in (raw.get("vulnerabilities") or {}).items()
        if isinstance(info, dict)
    ]
    return {
        "supported": True,
        "ecosystem": "nodejs",
        "tool": "npm audit",
        "tool_available": True,
        "vulnerabilities": vulnerabilidades,
        "count": len(vulnerabilidades),
    }


def _audit_error(eco: str, tool: str, error: str) -> dict[str, Any]:
    return {
        "supported": True,
        "ecosystem": eco,
        "tool": tool,
        "tool_available": True,
        "vulnerabilities": [],
        "error": error,
    }
