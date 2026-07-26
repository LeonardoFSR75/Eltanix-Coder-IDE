"""Rotas do painel Git do editor.

Diferente das ferramentas Git do agente (que operam no worktree da sessão),
estas operam no **projeto que você está editando** — é o painel de controle de
versão do IDE.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from git import GitCommandError
from pydantic import BaseModel, Field

from sicoobito.api.deps import AuthDep, SettingsDep
from sicoobito.api.routes.workspace import _fs_from_body, project_fs
from sicoobito.logging_setup import get_logger
from sicoobito.workspace import git as git_ops
from sicoobito.workspace.git import GitError, open_repo

log = get_logger(__name__)

router = APIRouter(prefix="/api/git", tags=["git"], dependencies=[AuthDep])


def _erro(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/status")
async def status_(settings: SettingsDep, project: str = Query(min_length=1)) -> dict[str, Any]:
    fs = project_fs(settings, project)
    try:
        estado = await asyncio.to_thread(git_ops.status, fs.root)
    except GitError as exc:
        raise _erro(exc) from exc

    return {
        "branch": estado.branch,
        "head": estado.head[:8],
        "dirty": estado.dirty,
        "files": [{"path": f.path, "status": f.status} for f in estado.files],
    }


@router.get("/diff")
async def diff(
    settings: SettingsDep,
    project: str = Query(min_length=1),
    path: str | None = None,
    staged: bool = False,
) -> dict[str, Any]:
    fs = project_fs(settings, project)
    try:
        saida = await asyncio.to_thread(git_ops.diff, fs.root, staged=staged, path=path)
    except GitError as exc:
        raise _erro(exc) from exc
    return {"diff": saida, "staged": staged, "path": path}


@router.get("/file-versions")
async def file_versions(
    settings: SettingsDep, project: str = Query(min_length=1), path: str = Query(min_length=1)
) -> dict[str, Any]:
    """Conteúdo no HEAD e no disco, para o DiffEditor lado a lado.

    O diff textual do `git diff` serve para ler; para *revisar* dentro do
    editor, o Monaco precisa das duas versões inteiras.
    """
    fs = project_fs(settings, project)

    def _ler() -> tuple[str, str]:
        repo = open_repo(fs.root)
        try:
            original = repo.git.show(f"HEAD:{path}")
        except GitCommandError:
            # Arquivo novo: não existe no HEAD, e o lado esquerdo fica vazio.
            original = ""
        try:
            atual = fs.read(path)
        except (FileNotFoundError, ValueError):
            # Arquivo apagado no disco.
            atual = ""
        return original, atual

    try:
        original, atual = await asyncio.to_thread(_ler)
    except GitError as exc:
        raise _erro(exc) from exc

    return {"path": path, "original": original, "modified": atual}


class StageRequest(BaseModel):
    project: str = Field(min_length=1)
    paths: list[str] = Field(min_length=1)


@router.post("/stage")
async def stage(payload: StageRequest, settings: SettingsDep) -> dict[str, Any]:
    fs = _fs_from_body(settings, payload.project)

    def _stage() -> None:
        repo = open_repo(fs.root)
        repo.git.add("--", *payload.paths)

    try:
        await asyncio.to_thread(_stage)
    except (GitError, GitCommandError) as exc:
        raise _erro(exc) from exc
    return {"staged": payload.paths}


@router.post("/unstage")
async def unstage(payload: StageRequest, settings: SettingsDep) -> dict[str, Any]:
    fs = _fs_from_body(settings, payload.project)

    def _unstage() -> None:
        repo = open_repo(fs.root)
        repo.git.restore("--staged", "--", *payload.paths)

    try:
        await asyncio.to_thread(_unstage)
    except (GitError, GitCommandError) as exc:
        raise _erro(exc) from exc
    return {"unstaged": payload.paths}


class CommitRequest(BaseModel):
    project: str = Field(min_length=1)
    message: str = Field(min_length=1)
    # Vazio commita o que já está no index — o comportamento que quem usa um
    # painel Git espera depois de escolher os arquivos.
    paths: list[str] | None = None


@router.post("/commit")
async def commit(payload: CommitRequest, settings: SettingsDep) -> dict[str, Any]:
    fs = _fs_from_body(settings, payload.project)
    try:
        sha = await asyncio.to_thread(
            git_ops.commit, fs.root, payload.message, paths=payload.paths or None
        )
    except GitError as exc:
        raise _erro(exc) from exc
    return {"sha": sha[:8]}


@router.get("/branches")
async def branches(settings: SettingsDep, project: str = Query(min_length=1)) -> dict[str, Any]:
    fs = project_fs(settings, project)

    def _listar() -> dict[str, Any]:
        repo = open_repo(fs.root)
        try:
            atual = repo.active_branch.name
        except TypeError:
            atual = ""
        return {
            "current": atual,
            "branches": sorted(b.name for b in repo.branches),
        }

    try:
        return await asyncio.to_thread(_listar)
    except GitError as exc:
        raise _erro(exc) from exc


class CheckoutRequest(BaseModel):
    project: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    create: bool = False


@router.post("/checkout")
async def checkout(payload: CheckoutRequest, settings: SettingsDep) -> dict[str, Any]:
    fs = _fs_from_body(settings, payload.project)

    def _trocar() -> str:
        repo = open_repo(fs.root)
        # Trocar de branch com alterações pendentes sobrescreveria trabalho não
        # salvo sem aviso; o painel precisa dizer isso antes.
        if repo.is_dirty(untracked_files=False):
            raise GitError(
                "Há alterações não commitadas. Faça commit ou descarte antes de trocar de branch."
            )
        if payload.create:
            repo.git.checkout("-b", payload.branch)
        else:
            repo.git.checkout(payload.branch)
        return repo.active_branch.name

    try:
        atual = await asyncio.to_thread(_trocar)
    except (GitError, GitCommandError) as exc:
        raise _erro(exc) from exc
    return {"branch": atual}


@router.get("/log")
async def log_(
    settings: SettingsDep, project: str = Query(min_length=1), limit: int = 30
) -> dict[str, Any]:
    fs = project_fs(settings, project)
    try:
        commits = await asyncio.to_thread(git_ops.log_recent, fs.root, limit)
    except GitError as exc:
        raise _erro(exc) from exc
    return {"commits": commits}


class DiscardRequest(BaseModel):
    project: str = Field(min_length=1)
    paths: list[str] = Field(min_length=1)


@router.post("/discard")
async def discard(payload: DiscardRequest, settings: SettingsDep) -> dict[str, Any]:
    """Descarta alterações locais. Operação destrutiva: a UI precisa confirmar."""
    fs = _fs_from_body(settings, payload.project)

    def _descartar() -> None:
        repo = open_repo(fs.root)
        repo.git.checkout("--", *payload.paths)

    try:
        await asyncio.to_thread(_descartar)
    except (GitError, GitCommandError) as exc:
        raise _erro(exc) from exc
    log.info("git.discard", project=payload.project, paths=len(payload.paths))
    return {"discarded": payload.paths}
