"""Rotas para gestão de pacotes e dependências persistentes do projeto."""

from __future__ import annotations

import asyncio
import os
import re
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

router = APIRouter(prefix="/api/projects/{slug}/packages", tags=["packages"], dependencies=[AuthDep])


def _projects_root(request: Request) -> Path:
    return getattr(request.app.state, "projects_root", None) or get_settings().projects_root


def get_venv_path(project_path: Path) -> Path:
    return project_path / ".venv"


def get_python_executable(venv_path: Path) -> Path:
    if sys.platform == "win32":
        exe = venv_path / "Scripts" / "python.exe"
        if exe.exists():
            return exe
        return venv_path / "python.exe"
    exe = venv_path / "bin" / "python"
    if exe.exists():
        return exe
    return venv_path / "bin" / "python3"


def get_pip_executable(venv_path: Path) -> Path:
    if sys.platform == "win32":
        exe = venv_path / "Scripts" / "pip.exe"
        if exe.exists():
            return exe
        return venv_path / "pip.exe"
    exe = venv_path / "bin" / "pip"
    if exe.exists():
        return exe
    return venv_path / "bin" / "pip3"


async def ensure_venv(project_path: Path) -> Path:
    venv_path = get_venv_path(project_path)
    py_exe = get_python_executable(venv_path)
    if not py_exe.exists():
        log.info("packages.venv.creating", project=project_path.name)
        cmd = [sys.executable, "-m", "venv", str(venv_path)]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(project_path),
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"Falha ao criar venv no projeto: {stderr.decode()}")
    return venv_path


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
        # ex: pandas==2.2.0 ou requests>=2.0.0
        match = re.match(r"^([a-zA-Z0-9_\-\.]+)(?:([=><~!]=?)(.+))?$", line)
        if match:
            pkg_name = match.group(1).lower()
            spec = line
            result[pkg_name] = spec
    return result


def sync_requirements_file(project_path: Path, pkg_name: str, version: str | None = None, remove: bool = False) -> str:
    req_file = project_path / "requirements.txt"
    lines: list[str] = []
    if req_file.exists():
        lines = req_file.read_text(encoding="utf-8", errors="ignore").splitlines()

    norm_target = pkg_name.lower().replace("_", "-")
    new_lines: list[str] = []
    found = False

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        
        match = re.match(r"^([a-zA-Z0-9_\-\.]+)", stripped)
        if match:
            norm_name = match.group(1).lower().replace("_", "-")
            if norm_name == norm_target:
                found = True
                if remove:
                    continue  # Pula remoção
                else:
                    new_line = f"{pkg_name}=={version}" if version else pkg_name
                    new_lines.append(new_line)
                    continue
        new_lines.append(line)

    if not remove and not found:
        new_line = f"{pkg_name}=={version}" if version else pkg_name
        new_lines.append(new_line)

    content = "\n".join(new_lines).strip() + "\n"
    req_file.write_text(content, encoding="utf-8")
    return content


class InstallPackageIn(BaseModel):
    package: str = Field(min_length=1, description="Nome do pacote ou especificação (ex: pytest, pandas==2.2.0)")
    save_requirements: bool = Field(default=True, description="Atualiza o requirements.txt automaticamente")


class UninstallPackageIn(BaseModel):
    package: str = Field(min_length=1, description="Nome do pacote a desinstalar")
    save_requirements: bool = Field(default=True, description="Remove do requirements.txt automaticamente")


@router.get("")
async def get_project_packages(slug: str, request: Request) -> dict[str, Any]:
    """Lista todos os pacotes instalados no ambiente persistente do projeto e o conteúdo do requirements.txt."""
    projects_root = _projects_root(request)
    try:
        project_path = resolve(projects_root, slug)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

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
                    {"name": p["name"], "version": p["version"]}
                    for p in raw_pkgs
                ]
        except Exception as exc:
            log.warning("packages.list.failed", slug=slug, error=str(exc))

    req_map = parse_requirements_txt(project_path)
    req_file = project_path / "requirements.txt"
    req_content = req_file.read_text(encoding="utf-8", errors="ignore") if req_file.exists() else ""

    return {
        "project": slug,
        "venv_exists": py_exe.exists(),
        "venv_path": str(venv_path),
        "installed_count": len(installed_packages),
        "packages": installed_packages,
        "requirements_exists": req_file.exists(),
        "requirements_content": req_content,
        "requirements_map": req_map,
    }


@router.post("/install")
async def install_project_package(slug: str, payload: InstallPackageIn, request: Request) -> dict[str, Any]:
    """Instala um pacote no .venv persistente do projeto e atualiza o requirements.txt."""
    projects_root = _projects_root(request)
    try:
        project_path = resolve(projects_root, slug)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    venv_path = await ensure_venv(project_path)
    pip_exe = get_pip_executable(venv_path)

    cmd = [str(pip_exe), "install", payload.package]
    log.info("packages.install.start", slug=slug, package=payload.package)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(project_path),
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Falha ao instalar pacote '{payload.package}': {stderr.decode(errors='ignore')}",
        )

    # Identifica versão instalada para sincronizar requirements.txt
    pkg_clean = re.split(r"[=><~!]", payload.package)[0].strip()
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
    if payload.save_requirements:
        req_content = sync_requirements_file(project_path, pkg_clean, installed_version, remove=False)

    return {
        "ok": True,
        "package": pkg_clean,
        "version": installed_version,
        "requirements_updated": payload.save_requirements,
        "requirements_content": req_content,
        "stdout": stdout.decode(errors="ignore"),
    }


@router.delete("/uninstall")
async def uninstall_project_package(slug: str, payload: UninstallPackageIn, request: Request) -> dict[str, Any]:
    """Desinstala um pacote do .venv persistente do projeto e atualiza o requirements.txt."""
    projects_root = _projects_root(request)
    try:
        project_path = resolve(projects_root, slug)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    venv_path = get_venv_path(project_path)
    pip_exe = get_pip_executable(venv_path)

    if not pip_exe.exists():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ambiente virtual não existe.")

    cmd = [str(pip_exe), "uninstall", "-y", payload.package]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(project_path),
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Falha ao desinstalar '{payload.package}': {stderr.decode(errors='ignore')}",
        )

    req_content = ""
    if payload.save_requirements:
        req_content = sync_requirements_file(project_path, payload.package, remove=True)

    return {
        "ok": True,
        "package": payload.package,
        "requirements_updated": payload.save_requirements,
        "requirements_content": req_content,
        "stdout": stdout.decode(errors="ignore"),
    }


@router.post("/sync")
async def sync_project_requirements(slug: str, request: Request) -> dict[str, Any]:
    """Sincroniza o .venv executando pip install -r requirements.txt."""
    projects_root = _projects_root(request)
    try:
        project_path = resolve(projects_root, slug)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    req_file = project_path / "requirements.txt"
    if not req_file.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Arquivo requirements.txt não encontrado.")

    venv_path = await ensure_venv(project_path)
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Falha ao sincronizar requirements.txt: {stderr.decode(errors='ignore')}",
        )

    return {
        "ok": True,
        "message": "Ambiente sincronizado com sucesso a partir do requirements.txt",
        "stdout": stdout.decode(errors="ignore"),
    }
