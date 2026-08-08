"""Rotas do painel Git do editor.

Diferente das ferramentas Git do agente (que operam no worktree da sessão),
estas operam no **projeto que você está editando** — é o painel de controle de
versão do IDE.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from git import GitCommandError
from pydantic import BaseModel, Field

from sicoobito.api.deps import AuthDep, SettingsDep
from sicoobito.api.routes.workspace import _fs_from_body, project_fs
from sicoobito.logging_setup import get_logger
from sicoobito.workspace import git as git_ops
from sicoobito.workspace.git import GitError, open_repo

log = get_logger(__name__)

router = APIRouter(prefix="/api/git", tags=["git"], dependencies=[AuthDep])

# Cache de blame por (path, sha do HEAD) — só faz sentido para revisões que não
# mudam mais (HEAD apontando para o commit já registrado na chave); revisão
# explícita de outro commit também é imutável e cacheável pelo próprio sha.
_BLAME_CACHE_PREFIX = "git:blame"
_BLAME_CACHE_TTL_SECONDS = 3600

_BRANCH_PATTERN = re.compile(r"^[a-zA-Z0-9._/-]+$")


def validate_branch_name(branch: str) -> str:
    limpo = branch.strip()
    if not limpo or limpo.startswith("-") or not _BRANCH_PATTERN.match(limpo):
        raise GitError(f"Nome de branch inválido: {branch!r}")
    return limpo


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
    valid_path = fs.relative(fs.resolve(path)) if path else None
    try:
        saida = await asyncio.to_thread(git_ops.diff, fs.root, staged=staged, path=valid_path)
    except GitError as exc:
        raise _erro(exc) from exc
    return {"diff": saida, "staged": staged, "path": valid_path}


@router.get("/file-versions")
async def file_versions(
    settings: SettingsDep, project: str = Query(min_length=1), path: str = Query(min_length=1)
) -> dict[str, Any]:
    """Conteúdo no HEAD e no disco, para o DiffEditor lado a lado.

    O diff textual do `git diff` serve para ler; para *revisar* dentro do
    editor, o Monaco precisa das duas versões inteiras.
    """
    fs = project_fs(settings, project)
    try:
        rel_path = fs.relative(fs.resolve(path))
    except Exception as exc:
        raise _erro(exc) from exc

    def _ler() -> tuple[str, str]:
        repo = open_repo(fs.root)
        try:
            original = repo.git.show(f"HEAD:{rel_path}")
        except GitCommandError:
            # Arquivo novo: não existe no HEAD, e o lado esquerdo fica vazio.
            original = ""
        try:
            atual = fs.read(rel_path)
        except (FileNotFoundError, ValueError):
            # Arquivo apagado no disco.
            atual = ""
        return original, atual

    try:
        original, atual = await asyncio.to_thread(_ler)
    except GitError as exc:
        raise _erro(exc) from exc

    return {"path": rel_path, "original": original, "modified": atual}


class StageRequest(BaseModel):
    project: str = Field(min_length=1)
    paths: list[str] = Field(min_length=1)


@router.post("/stage")
async def stage(payload: StageRequest, settings: SettingsDep) -> dict[str, Any]:
    fs = _fs_from_body(settings, payload.project)
    try:
        valid_paths = [fs.relative(fs.resolve(p)) for p in payload.paths]
    except Exception as exc:
        raise _erro(exc) from exc

    def _stage() -> None:
        repo = open_repo(fs.root)
        repo.git.add("--", *valid_paths)

    try:
        await asyncio.to_thread(_stage)
    except (GitError, GitCommandError) as exc:
        raise _erro(exc) from exc
    return {"staged": valid_paths}


@router.post("/unstage")
async def unstage(payload: StageRequest, settings: SettingsDep) -> dict[str, Any]:
    fs = _fs_from_body(settings, payload.project)
    try:
        valid_paths = [fs.relative(fs.resolve(p)) for p in payload.paths]
    except Exception as exc:
        raise _erro(exc) from exc

    def _unstage() -> None:
        repo = open_repo(fs.root)
        repo.git.restore("--staged", "--", *valid_paths)

    try:
        await asyncio.to_thread(_unstage)
    except (GitError, GitCommandError) as exc:
        raise _erro(exc) from exc
    return {"unstaged": valid_paths}


class CommitRequest(BaseModel):
    project: str = Field(min_length=1)
    message: str = Field(min_length=1)
    # Vazio commita o que já está no index — o comportamento que quem usa um
    # painel Git espera depois de escolher os arquivos.
    paths: list[str] | None = None


@router.post("/commit")
async def commit(payload: CommitRequest, settings: SettingsDep) -> dict[str, Any]:
    fs = _fs_from_body(settings, payload.project)
    valid_paths = (
        [fs.relative(fs.resolve(p)) for p in payload.paths] if payload.paths else None
    )
    try:
        sha = await asyncio.to_thread(
            git_ops.commit, fs.root, payload.message, paths=valid_paths
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
    try:
        branch = validate_branch_name(payload.branch)
    except GitError as exc:
        raise _erro(exc) from exc

    def _trocar() -> str:
        repo = open_repo(fs.root)
        # Trocar de branch com alterações pendentes sobrescreveria trabalho não
        # salvo sem aviso; o painel precisa dizer isso antes.
        if repo.is_dirty(untracked_files=False):
            raise GitError(
                "Há alterações não commitadas. Faça commit ou descarte antes de trocar de branch."
            )
        if payload.create:
            repo.git.checkout("-b", branch, "--")
        else:
            repo.git.checkout(branch, "--")
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


@router.get("/blame")
async def blame(
    request: Request,
    settings: SettingsDep,
    project: str = Query(min_length=1),
    path: str = Query(min_length=1),
    rev: str = "HEAD",
) -> dict[str, Any]:
    fs = project_fs(settings, project)
    try:
        rel_path = fs.relative(fs.resolve(path))
    except Exception as exc:
        raise _erro(exc) from exc

    def _head_sha() -> str:
        repo = open_repo(fs.root)
        return repo.head.commit.hexsha if repo.head.is_valid() else ""

    try:
        head_sha = await asyncio.to_thread(_head_sha)
    except GitError as exc:
        raise _erro(exc) from exc

    # Só cacheia quando a revisão pedida é imutável: HEAD (chaveado pelo sha
    # atual, então um novo commit muda a chave sozinho) ou um sha explícito.
    cacheavel = rev == "HEAD" or rev == head_sha
    redis = getattr(request.app.state, "redis", None)
    chave = f"{_BLAME_CACHE_PREFIX}:{fs.root.as_posix()}:{head_sha}:{rel_path}"

    if redis is not None and cacheavel:
        try:
            bruto = await redis.get(chave)
            if bruto:
                return {"path": rel_path, "hunks": json.loads(bruto)}
        except Exception as exc:
            log.warning("git.blame.cache_unavailable", error=str(exc))

    try:
        hunks = await asyncio.to_thread(git_ops.blame, fs.root, rel_path, rev)
    except GitError as exc:
        raise _erro(exc) from exc

    payload = [
        {
            "start_line": h.start_line,
            "end_line": h.end_line,
            "sha": h.sha,
            "author": h.author,
            "date": h.date,
            "message": h.message,
        }
        for h in hunks
    ]

    if redis is not None and cacheavel:
        try:
            await redis.set(chave, json.dumps(payload), ex=_BLAME_CACHE_TTL_SECONDS)
        except Exception as exc:
            log.warning("git.blame.cache_unavailable", error=str(exc))

    return {"path": rel_path, "hunks": payload}


@router.get("/co-change")
async def co_change(
    settings: SettingsDep,
    project: str = Query(min_length=1),
    path: str = Query(min_length=1),
    limit: int = 50,
) -> dict[str, Any]:
    """Quais outros arquivos costumam mudar junto com este, pelo histórico recente."""
    fs = project_fs(settings, project)
    try:
        rel_path = fs.relative(fs.resolve(path))
    except Exception as exc:
        raise _erro(exc) from exc

    try:
        entradas = await asyncio.to_thread(git_ops.co_change, fs.root, rel_path, limit)
    except GitError as exc:
        raise _erro(exc) from exc

    return {
        "path": rel_path,
        "co_changed": [{"path": e.path, "count": e.count} for e in entradas],
    }


class DiscardRequest(BaseModel):
    project: str = Field(min_length=1)
    paths: list[str] = Field(min_length=1)


@router.post("/discard")
async def discard(payload: DiscardRequest, settings: SettingsDep) -> dict[str, Any]:
    """Descarta alterações locais. Operação destrutiva: a UI precisa confirmar."""
    fs = _fs_from_body(settings, payload.project)
    try:
        valid_paths = [fs.relative(fs.resolve(p)) for p in payload.paths]
    except Exception as exc:
        raise _erro(exc) from exc

    def _descartar() -> None:
        repo = open_repo(fs.root)
        repo.git.checkout("--", *valid_paths)

    try:
        await asyncio.to_thread(_descartar)
    except (GitError, GitCommandError) as exc:
        raise _erro(exc) from exc
    log.info("git.discard", project=payload.project, paths=len(valid_paths))
    return {"discarded": valid_paths}
