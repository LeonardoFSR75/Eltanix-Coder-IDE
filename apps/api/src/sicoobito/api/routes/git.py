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
from sicoobito.router import env_editor
from sicoobito.workspace import git as git_ops
from sicoobito.workspace.git import GitError, get_git_user_config, open_repo, update_git_user_config
from sicoobito.workspace.github import GitHubClient, GitHubError, _token_from_cli, resolve_token

log = get_logger(__name__)

router = APIRouter(prefix="/api/git", tags=["git"], dependencies=[AuthDep])

# Cache de blame por (path, sha do HEAD) — só faz sentido para revisões que não
# mudam mais (HEAD apontando para o commit já registrado na chave); revisão
# explícita de outro commit também é imutável e cacheável pelo próprio sha.
_BLAME_CACHE_PREFIX = "git:blame"
_BLAME_CACHE_TTL_SECONDS = 3600

_BRANCH_PATTERN = re.compile(r"^[a-zA-Z0-9._/-]+$")
_REV_PATTERN = re.compile(r"^[a-zA-Z0-9._/^~@:{}-]+$")


def validate_branch_name(branch: str) -> str:
    limpo = branch.strip()
    if not limpo or limpo.startswith("-") or not _BRANCH_PATTERN.match(limpo):
        raise GitError(f"Nome de branch inválido: {branch!r}")
    return limpo


def validate_rev(rev: str) -> str:
    """Recusa qualquer coisa que comece com `-` — GitPython só bloqueia
    `--output`/`-o` da lista de opções perigosas de `git blame`, não
    `--contents=<arquivo>`, que permite ler um caminho arbitrário do host
    passado como se fosse uma revisão."""
    limpo = (rev or "").strip()
    if not limpo or limpo.startswith("-") or not _REV_PATTERN.match(limpo):
        raise GitError(f"Revisão git inválida: {rev!r}")
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
    valid_paths = [fs.relative(fs.resolve(p)) for p in payload.paths] if payload.paths else None
    try:
        sha = await asyncio.to_thread(git_ops.commit, fs.root, payload.message, paths=valid_paths)
    except GitError as exc:
        raise _erro(exc) from exc
    return {"sha": sha[:8]}


@router.get("/branches")
async def branches(settings: SettingsDep, project: str = Query(min_length=1)) -> dict[str, Any]:
    fs = project_fs(settings, project)

    def _listar() -> dict[str, Any]:
        repo = open_repo(fs.root)
        atual = "main"
        try:
            atual = repo.active_branch.name
        except Exception:
            atual = "main"

        lista_branches: list[str] = []
        try:
            # Filtra branches internas de worktrees do agente (sicoobito/*) da listagem da interface
            lista_branches = sorted(
                b.name
                for b in repo.branches
                if not b.name.startswith("sicoobito/") or b.name == atual
            )
        except Exception:
            lista_branches = []

        if not lista_branches and atual:
            lista_branches = [atual]

        return {
            "current": atual,
            "branches": lista_branches,
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
        try:
            if payload.create:
                repo.git.checkout("-b", branch, "--")
            else:
                repo.git.checkout(branch, "--")
        except GitCommandError as exc:
            msg = str(exc)
            if "already used by worktree" in msg:
                raise GitError(
                    f"A branch '{branch}' está em uso ativo pelo agente. "
                    "Encerre a sessão do agente para alternar para esta branch."
                ) from exc
            err_detail = exc.stderr.strip() if hasattr(exc, "stderr") and exc.stderr else str(exc)
            raise GitError(f"Falha ao alternar para a branch '{branch}': {err_detail}") from exc

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
        rev = validate_rev(rev)
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


# ── Configurações de Conta Git e GitHub ──────────────────────────────────────


class GitConfigUpdateRequest(BaseModel):
    user_name: str | None = None
    user_email: str | None = None
    default_branch: str | None = None
    autocrlf: str | None = None
    gpg_sign: bool | None = None
    signing_key: str | None = None
    scope: str = Field(default="global", pattern="^(global|local)$")
    project: str | None = None


@router.get("/config")
async def get_git_config(
    settings: SettingsDep, project: str | None = Query(default=None)
) -> dict[str, Any]:
    """Retorna configurações do Git local/global e chaves SSH ativas."""
    root = project_fs(settings, project).root if project else None
    try:
        cfg = await asyncio.to_thread(get_git_user_config, root)
    except Exception as exc:
        raise _erro(exc) from exc
    return cfg


@router.put("/config")
async def update_git_config(
    payload: GitConfigUpdateRequest, settings: SettingsDep
) -> dict[str, Any]:
    """Atualiza configurações de usuário do Git (`user.name`, `user.email`, etc.)."""
    root = project_fs(settings, payload.project).root if payload.project else None
    try:
        cfg = await asyncio.to_thread(
            update_git_user_config,
            user_name=payload.user_name,
            user_email=payload.user_email,
            default_branch=payload.default_branch,
            autocrlf=payload.autocrlf,
            gpg_sign=payload.gpg_sign,
            signing_key=payload.signing_key,
            scope=payload.scope,
            root=root,
        )
    except GitError as exc:
        raise _erro(exc) from exc
    return cfg


class GitHubConfigUpdateRequest(BaseModel):
    github_token: str = Field(default="")


class GitHubTokenTestRequest(BaseModel):
    token: str = Field(min_length=1)


@router.get("/github/config")
async def get_github_config(settings: SettingsDep) -> dict[str, Any]:
    """Status e dados do perfil GitHub associado ao token atual."""
    raw_token = settings.github_token
    token = resolve_token(raw_token)

    token_source = "settings" if raw_token else ("gh_cli" if _token_from_cli() else "none")

    if not token:
        return {
            "status": "not_configured",
            "token_configured": False,
            "token_source": token_source,
            "error": "Nenhum token do GitHub configurado.",
            "user": None,
        }

    try:
        client = GitHubClient(token)
        user_info = await client.whoami()
        masked = f"{token[:4]}...{token[-4:]}" if len(token) > 8 else "***"
        return {
            "status": "authenticated",
            "token_configured": bool(raw_token),
            "token_source": token_source,
            "masked_token": masked,
            "user": {
                "login": user_info.get("login"),
                "name": user_info.get("name"),
                "email": user_info.get("email"),
                "avatar_url": user_info.get("avatar_url"),
                "html_url": user_info.get("html_url"),
                "bio": user_info.get("bio"),
                "public_repos": user_info.get("public_repos"),
                "total_private_repos": user_info.get("total_private_repos"),
                "created_at": user_info.get("created_at"),
            },
        }
    except GitHubError as exc:
        return {
            "status": "error",
            "token_configured": bool(raw_token),
            "token_source": token_source,
            "error": str(exc),
            "user": None,
        }


@router.post("/github/config/test")
async def test_github_token(payload: GitHubTokenTestRequest) -> dict[str, Any]:
    """Testa um token PAT do GitHub em tempo real sem salvá-lo."""
    try:
        client = GitHubClient(payload.token.strip())
        user_info = await client.whoami()
        return {
            "valid": True,
            "user": {
                "login": user_info.get("login"),
                "name": user_info.get("name"),
                "email": user_info.get("email"),
                "avatar_url": user_info.get("avatar_url"),
                "html_url": user_info.get("html_url"),
                "bio": user_info.get("bio"),
                "public_repos": user_info.get("public_repos"),
            },
        }
    except GitHubError as exc:
        return {"valid": False, "error": str(exc), "user": None}


@router.put("/github/config")
async def update_github_config(
    payload: GitHubConfigUpdateRequest, settings: SettingsDep
) -> dict[str, Any]:
    """Salva o token do GitHub no arquivo `.env` e atualiza a configuração ativa."""
    token_str = payload.github_token.strip()
    settings.github_token = token_str

    try:
        env_editor.write_values(settings.env_file_path, {"GITHUB_TOKEN": token_str})
    except Exception as exc:
        log.warning("git.github.persist_failed", error=str(exc))

    return await get_github_config(settings)
