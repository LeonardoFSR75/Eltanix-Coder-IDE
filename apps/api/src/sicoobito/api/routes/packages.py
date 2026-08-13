"""Rotas para gestão de pacotes e dependências persistentes do projeto."""

from __future__ import annotations

import asyncio
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from sicoobito.api.deps import AuthDep
from sicoobito.config import get_settings
from sicoobito.logging_setup import get_logger
from sicoobito.workspace.projects import resolve

log = get_logger(__name__)

router = APIRouter(
    prefix="/api/projects/{slug}/packages", tags=["packages"], dependencies=[AuthDep]
)


def _projects_root(request: Request) -> Path:
    return getattr(request.app.state, "projects_root", None) or get_settings().projects_root


def get_venv_path(project_path: Path) -> Path:
    return project_path / ".venv"


def get_python_executable(venv_path: Path) -> Path:
    if sys.platform == "win32":
        candidates = [
            venv_path / "Scripts" / "python.exe",
            venv_path / "Scripts" / "python",
            venv_path / "python.exe",
            venv_path / "bin" / "python.exe",
        ]
    else:
        candidates = [
            venv_path / "bin" / "python",
            venv_path / "bin" / "python3",
            venv_path / "bin" / "python.exe",
        ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    if sys.platform == "win32":
        return venv_path / "Scripts" / "python.exe"
    return venv_path / "bin" / "python"


def get_pip_executable(venv_path: Path) -> Path:
    if sys.platform == "win32":
        candidates = [
            venv_path / "Scripts" / "pip.exe",
            venv_path / "Scripts" / "pip",
            venv_path / "pip.exe",
            venv_path / "bin" / "pip.exe",
        ]
    else:
        candidates = [
            venv_path / "bin" / "pip",
            venv_path / "bin" / "pip3",
            venv_path / "bin" / "pip.exe",
        ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    if sys.platform == "win32":
        return venv_path / "Scripts" / "pip.exe"
    return venv_path / "bin" / "pip"


DEFAULT_BASE_PACKAGES = ["setuptools", "wheel"]


def detect_ecosystem(project_path: Path, requested_lang: str | None = None) -> str:
    if requested_lang:
        lang = requested_lang.lower().strip()
        if lang in {"node", "nodejs", "js", "typescript", "ts"}:
            return "nodejs"
        if lang in {"go", "golang"}:
            return "go"
        if lang in {"rust", "rs"}:
            return "rust"
        if lang in {"php"}:
            return "php"
        if lang in {"python", "py"}:
            return "python"

    if (project_path / "package.json").exists() or (project_path / "tsconfig.json").exists():
        return "nodejs"
    if (project_path / "go.mod").exists():
        return "go"
    if (project_path / "Cargo.toml").exists():
        return "rust"
    if (project_path / "composer.json").exists():
        return "php"

    # Verificação por extensões de arquivo
    try:
        for child in project_path.iterdir():
            if child.is_file():
                ext = child.suffix.lower()
                if ext in {".ts", ".js", ".jsx", ".tsx"}:
                    return "nodejs"
                if ext == ".go":
                    return "go"
                if ext == ".rs":
                    return "rust"
                if ext == ".php":
                    return "php"
    except Exception:
        pass

    return "python"


def get_manifest_name(ecosystem: str) -> str:
    mapping = {
        "nodejs": "package.json",
        "go": "go.mod",
        "rust": "Cargo.toml",
        "php": "composer.json",
        "python": "requirements.txt",
    }
    return mapping.get(ecosystem, "requirements.txt")


async def ensure_node_env(project_path: Path) -> Path:
    pkg_json = project_path / "package.json"
    if not pkg_json.exists():
        clean_name = re.sub(r"[^a-z0-9_-]", "", project_path.name.lower()) or "project"
        pkg_json.write_text(
            f'{{\n  "name": "{clean_name}",\n  "version": "1.0.0",\n  "private": true,\n'
            '  "dependencies": {},\n  "devDependencies": {}\n}\n',
            encoding="utf-8",
        )
    node_modules = project_path / "node_modules"
    if not node_modules.exists():
        import shutil
        npm_bin = shutil.which("npm")
        if npm_bin:
            try:
                proc = await asyncio.create_subprocess_exec(
                    npm_bin,
                    "install",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(project_path),
                )
                await asyncio.wait_for(proc.communicate(), timeout=120)
            except Exception as exc:
                log.warning(
                    "packages.node_env.install_failed",
                    project=project_path.name,
                    error=str(exc),
                )
    return project_path


async def ensure_go_env(project_path: Path) -> Path:
    go_mod = project_path / "go.mod"
    if not go_mod.exists():
        mod_name = re.sub(r"[^a-z0-9_.-]", "", project_path.name.lower()) or "app"
        go_mod.write_text(f"module {mod_name}\n\ngo 1.22\n", encoding="utf-8")
    import shutil
    go_bin = shutil.which("go")
    if go_bin:
        try:
            proc = await asyncio.create_subprocess_exec(
                go_bin,
                "mod",
                "tidy",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(project_path),
            )
            await asyncio.wait_for(proc.communicate(), timeout=60)
        except Exception as exc:
            log.warning("packages.go_env.tidy_failed", project=project_path.name, error=str(exc))
    return project_path


async def ensure_rust_env(project_path: Path) -> Path:
    cargo_toml = project_path / "Cargo.toml"
    if not cargo_toml.exists():
        pkg_name = re.sub(r"[^a-z0-9_-]", "_", project_path.name.lower()) or "app"
        cargo_toml.write_text(
            f'[package]\nname = "{pkg_name}"\nversion = "0.1.0"\nedition = "2021"\n\n'
            "[dependencies]\n",
            encoding="utf-8",
        )
    return project_path


async def ensure_php_env(project_path: Path) -> Path:
    composer_json = project_path / "composer.json"
    if not composer_json.exists():
        pkg_name = f"app/{re.sub(r'[^a-z0-9_-]', '', project_path.name.lower()) or 'project'}"
        composer_json.write_text(
            f'{{\n  "name": "{pkg_name}",\n  "require": {{}}\n}}\n', encoding="utf-8"
        )
    return project_path


async def ensure_project_env(project_path: Path, lang: str | None = None) -> Path:
    eco = detect_ecosystem(project_path, lang)
    if eco == "nodejs":
        return await ensure_node_env(project_path)
    elif eco == "go":
        return await ensure_go_env(project_path)
    elif eco == "rust":
        return await ensure_rust_env(project_path)
    elif eco == "php":
        return await ensure_php_env(project_path)
    else:
        return await ensure_venv(project_path)


async def ensure_venv(project_path: Path, install_base: bool = True) -> Path:
    venv_path = get_venv_path(project_path)
    py_exe = get_python_executable(venv_path)

    need_create = not py_exe.exists()
    if not need_create:
        try:
            proc_check = await asyncio.create_subprocess_exec(
                str(py_exe),
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, _ = await asyncio.wait_for(proc_check.communicate(), timeout=5)
            if proc_check.returncode != 0:
                need_create = True
        except Exception:
            need_create = True

    if need_create:
        log.info("packages.venv.creating", project=project_path.name)
        cmd = [sys.executable, "-m", "venv", "--clear", str(venv_path)]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(project_path),
        )
        try:
            _stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        except TimeoutError:
            proc.kill()
            raise RuntimeError("Timeout ao criar o ambiente virtual (.venv).") from None
        if proc.returncode != 0:
            raise RuntimeError(f"Falha ao criar venv no projeto: {stderr.decode(errors='ignore')}")

        py_exe = get_python_executable(venv_path)

        if install_base and py_exe.exists():
            try:
                log.info("packages.venv.base_install", project=project_path.name)
                cmd_base = [
                    str(py_exe), "-m", "pip", "install", "--upgrade", "pip", *DEFAULT_BASE_PACKAGES
                ]
                proc_base = await asyncio.create_subprocess_exec(
                    *cmd_base,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(project_path),
                )
                await asyncio.wait_for(proc_base.communicate(), timeout=120)
            except Exception as exc:
                log.warning(
                    "packages.venv.base_install_failed",
                    project=project_path.name,
                    error=str(exc),
                )

    req_file = project_path / "requirements.txt"
    if not req_file.exists():
        try:
            req_file.write_text("# Dependências do projeto\n", encoding="utf-8")
        except Exception:
            pass

    return venv_path


def normalize_python_package_name(pkg_name: str) -> str:
    return pkg_name.strip().lower().replace("_", "-")


def parse_requirements_txt(project_path: Path) -> dict[str, str]:
    req_file = project_path / "requirements.txt"
    if not req_file.exists():
        return {}

    result = {}
    lines = req_file.read_text(encoding="utf-8", errors="ignore").splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^([a-zA-Z0-9_\-\.]+)(?:([=><~!]=?)(.+))?$", line)
        if match:
            pkg_name = normalize_python_package_name(match.group(1))
            spec = line
            result[pkg_name] = spec
    return result


def sync_requirements_file(
    project_path: Path, pkg_name: str, version: str | None = None, remove: bool = False
) -> str:
    req_file = project_path / "requirements.txt"
    lines: list[str] = []
    if req_file.exists():
        lines = req_file.read_text(encoding="utf-8", errors="ignore").splitlines()

    canon_target = normalize_python_package_name(pkg_name)
    new_lines: list[str] = []
    found = False

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue

        match = re.match(r"^([a-zA-Z0-9_\-\.]+)", stripped)
        if match:
            norm_name = normalize_python_package_name(match.group(1))
            if norm_name == canon_target:
                found = True
                if remove:
                    continue
                else:
                    new_line = f"{canon_target}=={version}" if version else canon_target
                    new_lines.append(new_line)
                    continue
        new_lines.append(line)

    if not remove and not found:
        new_line = f"{canon_target}=={version}" if version else canon_target
        new_lines.append(new_line)

    content = "\n".join(new_lines).strip() + "\n"
    req_file.write_text(content, encoding="utf-8")
    return content


def export_requirements_from_venv(project_path: Path) -> str:
    """Exporta o estado real do ambiente virtual para requirements.txt."""
    req_file = project_path / "requirements.txt"
    venv_path = get_venv_path(project_path)
    py_exe = get_python_executable(venv_path)

    if not py_exe.exists():
        content = "# Dependências do projeto\n"
        req_file.write_text(content, encoding="utf-8")
        return content

    proc = subprocess.run(
        [str(py_exe), "-m", "pip", "freeze"],
        capture_output=True,
        text=True,
        cwd=str(project_path),
        check=False,
    )

    content = proc.stdout.strip()
    if not content:
        content = "# Dependências do projeto\n"
    else:
        content = content + "\n"

    req_file.write_text(content, encoding="utf-8")
    return content


class InstallPackageIn(BaseModel):
    package: str = Field(
        min_length=1, description="Nome do pacote ou especificação (ex: pytest, lodash, gin)"
    )
    save_requirements: bool = Field(
        default=True, description="Atualiza o manifesto automaticamente"
    )


class UninstallPackageIn(BaseModel):
    package: str = Field(min_length=1, description="Nome do pacote a desinstalar")
    save_requirements: bool = Field(
        default=True, description="Remove do manifesto automaticamente"
    )


@router.get("")
async def get_project_packages(slug: str, request: Request) -> dict[str, Any]:
    """Lista todos os pacotes instalados no ambiente persistente do projeto e o
    conteúdo do manifesto."""
    projects_root = _projects_root(request)
    try:
        project_path = resolve(projects_root, slug)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    eco = detect_ecosystem(project_path)
    manifest_name = get_manifest_name(eco)

    try:
        await ensure_project_env(project_path)
    except Exception as exc:
        log.warning("packages.ensure_env.failed", slug=slug, error=str(exc))

    installed_packages: list[dict[str, str]] = []
    venv_path = get_venv_path(project_path)
    py_exe = get_python_executable(venv_path)

    if eco == "nodejs":
        pkg_json = project_path / "package.json"
        if pkg_json.exists():
            try:
                import json
                data = json.loads(pkg_json.read_text(encoding="utf-8", errors="ignore"))
                deps = data.get("dependencies", {})
                dev_deps = data.get("devDependencies", {})
                for k, v in {**deps, **dev_deps}.items():
                    installed_packages.append({"name": k, "version": str(v)})
            except Exception as exc:
                log.warning("packages.nodejs.parse_failed", error=str(exc))
    elif eco == "go":
        go_mod = project_path / "go.mod"
        if go_mod.exists():
            for line in go_mod.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                match = re.match(r"^([a-zA-Z0-9_\-\.\/]+)\s+(v[0-9\.\-]+)", line)
                if match:
                    installed_packages.append({"name": match.group(1), "version": match.group(2)})
    elif eco == "rust":
        cargo_toml = project_path / "Cargo.toml"
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
        if composer_json.exists():
            try:
                import json
                data = json.loads(composer_json.read_text(encoding="utf-8", errors="ignore"))
                reqs = data.get("require", {})
                for k, v in reqs.items():
                    if k != "php":
                        installed_packages.append({"name": k, "version": str(v)})
            except Exception as exc:
                log.warning("packages.php.parse_failed", error=str(exc))
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
                        {"name": p["name"], "version": p["version"]}
                        for p in raw_pkgs
                    ]
            except Exception as exc:
                log.warning("packages.list.failed", slug=slug, error=str(exc))

    manifest_file = project_path / manifest_name
    manifest_content = (
        manifest_file.read_text(encoding="utf-8", errors="ignore")
        if manifest_file.exists()
        else ""
    )
    req_map = (
        parse_requirements_txt(project_path)
        if eco == "python"
        else {p["name"]: p["version"] for p in installed_packages}
    )

    return {
        "project": slug,
        "ecosystem": eco,
        "manifest_file": manifest_name,
        "venv_exists": py_exe.exists() if eco == "python" else manifest_file.exists(),
        "venv_path": str(venv_path) if eco == "python" else str(project_path),
        "installed_count": len(installed_packages),
        "packages": installed_packages,
        "requirements_exists": manifest_file.exists(),
        "requirements_content": manifest_content,
        "requirements_map": req_map,
    }


@router.post("/install")
async def install_project_package(
    slug: str, payload: InstallPackageIn, request: Request
) -> dict[str, Any]:
    """Instala um pacote no ambiente do projeto e atualiza o manifesto."""
    projects_root = _projects_root(request)
    try:
        project_path = resolve(projects_root, slug)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    eco = detect_ecosystem(project_path)
    manifest_name = get_manifest_name(eco)
    import shutil

    if eco == "nodejs":
        await ensure_node_env(project_path)
        npm_bin = shutil.which("npm")
        if not npm_bin:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="npm não encontrado no ambiente servidor.",
            )
        cmd = [npm_bin, "install", payload.package]
    elif eco == "go":
        await ensure_go_env(project_path)
        go_bin = shutil.which("go")
        if not go_bin:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="go CLI não encontrado no ambiente servidor.",
            )
        cmd = [go_bin, "get", payload.package]
    elif eco == "rust":
        await ensure_rust_env(project_path)
        cargo_bin = shutil.which("cargo")
        if not cargo_bin:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="cargo não encontrado no ambiente servidor.",
            )
        cmd = [cargo_bin, "add", payload.package]
    elif eco == "php":
        await ensure_php_env(project_path)
        composer_bin = shutil.which("composer")
        if not composer_bin:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="composer não encontrado no ambiente servidor.",
            )
        cmd = [composer_bin, "require", payload.package]
    else:
        venv_path = await ensure_venv(project_path)
        py_exe = get_python_executable(venv_path)
        cmd = [str(py_exe), "-m", "pip", "install", payload.package]

    log.info("packages.install.start", slug=slug, package=payload.package, eco=eco)

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
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Tempo limite excedido ao instalar o pacote '{payload.package}'.",
        ) from None

    if proc.returncode != 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Falha ao instalar pacote '{payload.package}': "
                f"{stderr.decode(errors='ignore')}"
            ),
        )

    pkg_clean = re.split(r"[=><~!]", payload.package)[0].strip()
    pkg_clean = normalize_python_package_name(pkg_clean)
    manifest_file = project_path / manifest_name
    manifest_content = (
        manifest_file.read_text(encoding="utf-8", errors="ignore")
        if manifest_file.exists()
        else ""
    )

    if eco == "python" and payload.save_requirements:
        manifest_content = export_requirements_from_venv(project_path)

    return {
        "ok": True,
        "package": pkg_clean,
        "ecosystem": eco,
        "manifest_file": manifest_name,
        "version": None,
        "requirements_updated": payload.save_requirements,
        "requirements_content": manifest_content,
        "stdout": stdout.decode(errors="ignore"),
    }


@router.delete("/uninstall")
async def uninstall_project_package(
    slug: str, payload: UninstallPackageIn, request: Request
) -> dict[str, Any]:
    """Desinstala um pacote do ambiente do projeto e atualiza o manifesto."""
    projects_root = _projects_root(request)
    try:
        project_path = resolve(projects_root, slug)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    eco = detect_ecosystem(project_path)
    manifest_name = get_manifest_name(eco)
    import shutil

    if eco == "nodejs":
        npm_bin = shutil.which("npm")
        if not npm_bin:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="npm não encontrado."
            )
        cmd = [npm_bin, "uninstall", payload.package]
    elif eco == "go":
        go_bin = shutil.which("go")
        if not go_bin:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="go CLI não encontrado."
            )
        cmd = [go_bin, "mod", "edit", f"-droprequire={payload.package}"]
    elif eco == "rust":
        cargo_bin = shutil.which("cargo")
        if not cargo_bin:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="cargo não encontrado."
            )
        cmd = [cargo_bin, "remove", payload.package]
    elif eco == "php":
        composer_bin = shutil.which("composer")
        if not composer_bin:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="composer não encontrado."
            )
        cmd = [composer_bin, "remove", payload.package]
    else:
        venv_path = get_venv_path(project_path)
        py_exe = get_python_executable(venv_path)
        if not py_exe.exists():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Ambiente virtual não existe."
            )
        cmd = [str(py_exe), "-m", "pip", "uninstall", "-y", payload.package]

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
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Tempo limite excedido ao desinstalar '{payload.package}'.",
        ) from None

    if proc.returncode != 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Falha ao desinstalar '{payload.package}': {stderr.decode(errors='ignore')}",
        )

    manifest_file = project_path / manifest_name
    manifest_content = ""
    if eco == "python" and payload.save_requirements:
        manifest_content = export_requirements_from_venv(project_path)
    elif manifest_file.exists():
        manifest_content = manifest_file.read_text(encoding="utf-8", errors="ignore")

    return {
        "ok": True,
        "package": payload.package,
        "ecosystem": eco,
        "manifest_file": manifest_name,
        "requirements_updated": payload.save_requirements,
        "requirements_content": manifest_content,
        "stdout": stdout.decode(errors="ignore"),
    }


@router.post("/sync")
async def sync_project_requirements(slug: str, request: Request) -> dict[str, Any]:
    """Sincroniza as dependências do ambiente a partir do arquivo manifesto."""
    projects_root = _projects_root(request)
    try:
        project_path = resolve(projects_root, slug)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    eco = detect_ecosystem(project_path)
    manifest_name = get_manifest_name(eco)
    manifest_file = project_path / manifest_name
    import shutil

    if not manifest_file.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Arquivo {manifest_name} não encontrado.",
        )

    if eco == "nodejs":
        npm_bin = shutil.which("npm")
        if not npm_bin:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="npm não encontrado."
            )
        cmd = [npm_bin, "install"]
    elif eco == "go":
        go_bin = shutil.which("go")
        if not go_bin:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="go CLI não encontrado."
            )
        cmd = [go_bin, "mod", "download"]
    elif eco == "rust":
        cargo_bin = shutil.which("cargo")
        if not cargo_bin:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="cargo não encontrado."
            )
        cmd = [cargo_bin, "check"]
    elif eco == "php":
        composer_bin = shutil.which("composer")
        if not composer_bin:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="composer não encontrado."
            )
        cmd = [composer_bin, "install"]
    else:
        venv_path = await ensure_venv(project_path)
        py_exe = get_python_executable(venv_path)
        if not py_exe.exists():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ambiente virtual não foi criado corretamente.",
            )

        manifest_content = export_requirements_from_venv(project_path)
        return {
            "ok": True,
            "ecosystem": eco,
            "manifest_file": manifest_name,
            "message": "requirements.txt sincronizado a partir do ambiente virtual do projeto",
            "stdout": manifest_content,
        }

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
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Tempo limite excedido ao sincronizar {manifest_name}.",
        ) from None

    if proc.returncode != 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Falha ao sincronizar {manifest_name}: {stderr.decode(errors='ignore')}",
        )

    return {
        "ok": True,
        "ecosystem": eco,
        "manifest_file": manifest_name,
        "message": f"Ambiente sincronizado com sucesso a partir do {manifest_name}",
        "stdout": stdout.decode(errors="ignore"),
    }

