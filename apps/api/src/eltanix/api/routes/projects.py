"""Rotas de gestão centralizada de projetos."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import string
import sys
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eltanix.api.deps import AdminDep, AuthDep
from eltanix.audit.service import AuditService
from eltanix.auth import store as auth_store
from eltanix.auth.rbac import ROLE_RANK, require_role_by_slug
from eltanix.config import get_settings
from eltanix.db.models import ProjectRecord
from eltanix.db.session import session_scope
from eltanix.logging_setup import get_logger
from eltanix.workspace.projects import (
    ProjectError,
    _branch_of,
    get_project_summary,
    resolve,
    sync_projects_db,
    validate_name,
)
from eltanix.workspace.projects import (
    list_projects as list_disk_projects,
)

log = get_logger(__name__)

router = APIRouter(prefix="/api/projects", tags=["projects"], dependencies=[AuthDep])

# Referências fortes para as tasks de provisionamento de ambiente disparadas em
# segundo plano por `create_project` — sem isto, `asyncio` pode coletar a task
# antes dela terminar (mesmo padrão de `telemetry/tracer.py::TraceRecorder`).
_env_provision_tasks: set[asyncio.Task[None]] = set()


def _audit(request: Request) -> AuditService | None:
    return getattr(request.app.state, "audit", None)


async def _provision_env_background(target_path: Path, language: str | None, slug: str) -> None:
    """Provisiona `.venv`/`node_modules`/etc. sem bloquear `POST /projects` — ver
    o comentário no chamador. Falha aqui é sempre não-fatal: o pior caso é o
    ambiente ficar pendente até o próximo prewarm ou até a IDE ser aberta."""
    try:
        from eltanix.api.routes.packages import ensure_project_env

        await ensure_project_env(target_path, language)
    except Exception as exc:
        log.warning("projects.auto_env.failed", slug=slug, error=str(exc)[:200])


def _projects_root(request: Request) -> Path:
    raiz = getattr(request.app.state, "projects_root", None) or get_settings().projects_root
    if isinstance(raiz, Path):
        return raiz
    if raiz:
        return Path(str(raiz))
    return Path(".")


class ProjectCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="")
    language: str | None = Field(
        default=None,
        description="Linguagem/ecossistema do projeto: python, nodejs, typescript, go, rust, php",
    )
    git_url: str | None = Field(default=None)
    init_git: bool = Field(default=True, description="Inicializa repositório Git automaticamente")
    create_github_repo: bool = Field(
        default=False, description="Cria repositório remoto PRIVADO no GitHub automaticamente"
    )
    budget_limit_usd: float | None = Field(default=None)
    settings: dict[str, Any] = Field(default_factory=dict)


class OpenPathIn(BaseModel):
    path: str = Field(min_length=1, description="Caminho absoluto de qualquer pasta do SO")


class BrowsePathIn(BaseModel):
    path: str | None = Field(default=None, description="Caminho a explorar — vazio lista unidades/raízes do sistema")


class InspectPathIn(BaseModel):
    path: str = Field(min_length=1, description="Caminho a inspecionar")


def _list_system_roots(projects_root: Path) -> list[dict[str, Any]]:
    roots: list[dict[str, Any]] = []
    if projects_root.exists():
        roots.append({
            "name": f"⚡ Raiz de Projetos ({projects_root.name})",
            "path": str(projects_root),
            "icon": "projects",
            "type": "projects_root",
        })
    user_home = Path.home()
    roots.append({
        "name": f"🏠 Pasta do Usuário ({user_home.name})",
        "path": str(user_home),
        "icon": "home",
        "type": "home",
    })
    docs = user_home / "Documents"
    if docs.exists():
        roots.append({
            "name": "📁 Documentos",
            "path": str(docs),
            "icon": "docs",
            "type": "special",
        })
    if sys.platform == "win32":
        for letter in string.ascii_uppercase:
            drive = Path(f"{letter}:\\")
            if drive.exists():
                roots.append({
                    "name": f"💽 Disco Local ({letter}:)",
                    "path": str(drive),
                    "icon": "drive",
                    "type": "drive",
                })
    else:
        roots.append({
            "name": "💽 Raiz do Sistema (/)",
            "path": "/",
            "icon": "drive",
            "type": "drive",
        })
    return roots


def _resolve_user_path(raw_path: str, projects_root: Path) -> Path:
    """Resolve qualquer caminho informado pelo usuário com suporte a:
    1. Nome simples de pasta ou subcaminho, sob a raiz de projetos (ex: 'Sorteador' -> projects_root / 'Sorteador')
    2. Caminhos absolutos do host Windows (ex: 'C:\\Users\\...\\Projetos\\Sorteador') mapeados para /projects
    3. Caminhos diretos do container / SO (ex: '/projects/Sorteador', 'D:\\work\\outro-projeto')

    Esta função alimenta `open-path` (que vincula a pasta devolvida como
    projeto) e `browse`/`inspect` — por isso NÃO tem um passo de "se nada
    bateu, tenta achar uma pasta com esse *nome* em `projects_root`": isso já
    existiu aqui e causava vinculação silenciosa da pasta errada sempre que o
    caminho pedido não resolvia (ex.: o seletor nativo do browser, que só
    consegue entregar o NOME da pasta escolhida — nunca o caminho completo —
    fazia todo `/projects/<nome-coincidente>` existente "vencer" no lugar da
    pasta que o usuário via na tela; ver `LinkProjectModal.tsx`)."""
    clean = (raw_path or "").strip().strip("'\"")
    if not clean:
        return projects_root

    # 1. Se for apenas o nome da pasta ou subcaminho sob a raiz de projetos.
    # `..` seria "resolvido" para fora de `projects_root` por `.resolve()`
    # sozinho — o `is_relative_to` abaixo é o que garante que este passo só
    # aceita algo realmente dentro da raiz, nunca uma fuga por travessia.
    candidate_in_root = (projects_root / clean).resolve()
    if (
        candidate_in_root.exists()
        and candidate_in_root.is_dir()
        and candidate_in_root.is_relative_to(projects_root.resolve())
    ):
        return candidate_in_root

    # 2. Tradução de caminhos Windows (se estiver rodando dentro do container Docker)
    norm = clean.replace("\\", "/")
    projects_root_host = os.environ.get("PROJECTS_ROOT_HOST", "")
    if projects_root_host:
        host_norm = projects_root_host.replace("\\", "/").rstrip("/")
        if norm.lower().startswith(host_norm.lower()):
            rel_part = norm[len(host_norm):].lstrip("/")
            target = (projects_root / rel_part).resolve()
            if target.exists() and target.is_relative_to(projects_root.resolve()):
                return target

    # 3. Resolução direta pelo filesystem do sistema operacional
    try:
        direct = Path(clean).expanduser().resolve()
        if direct.exists():
            return direct
    except Exception:
        pass

    return candidate_in_root



class ProjectUpdateIn(BaseModel):
    name: str | None = Field(default=None)
    description: str | None = Field(default=None)
    git_url: str | None = Field(default=None)
    budget_limit_usd: float | None = Field(default=None)
    settings: dict[str, Any] | None = Field(default=None)


@router.get("")
async def list_projects(request: Request) -> dict[str, Any]:
    """Lista todos os projetos cadastrados no Postgres (auto-sincronizados com PROJECTS_ROOT)."""
    projects_root = _projects_root(request)
    try:
        async with session_scope() as session:
            records = await sync_projects_db(session, projects_root)
            # Canal de serviço e admin da instância veem tudo (mesmo bypass de
            # `auth/rbac.py`); um usuário convidado comum só vê projeto onde é
            # `project_member` — sem isso, RBAC restringiria escrita mas
            # continuaria vazando a existência de todo projeto na listagem.
            if not (
                getattr(request.state, "is_service", False)
                or getattr(request.state, "is_admin", False)
            ):
                user_id = getattr(request.state, "user_id", None)
                if user_id is not None:
                    member_ids = set(
                        await auth_store.list_member_project_ids(session, user_id=user_id)
                    )
                    records = [r for r in records if r.id in member_ids]
            items = [
                {
                    "id": str(r.id),
                    "slug": r.slug,
                    "name": r.name,
                    "description": r.description,
                    "local_path": r.local_path,
                    "git_url": r.git_url,
                    "default_branch": r.default_branch,
                    "budget_limit_usd": float(r.budget_limit_usd)
                    if r.budget_limit_usd is not None
                    else None,
                    "settings": r.settings,
                    "created_at": r.created_at.isoformat(),
                    "updated_at": r.updated_at.isoformat(),
                }
                for r in records
            ]
        return {"projects": items}
    except Exception as exc:
        log.warning("projects.db.unavailable", error=str(exc))
        disk_projects = list_disk_projects(projects_root)
        items = [
            {
                "id": p.slug or p.name,
                "slug": p.slug or p.name,
                "name": p.name,
                "description": p.description,
                "local_path": str(p.path),
                "git_url": None,
                "default_branch": p.branch or "main",
                "budget_limit_usd": None,
                "settings": {},
            }
            for p in disk_projects
        ]
        return {"projects": items}


@router.post("")
async def create_project(payload: ProjectCreateIn, request: Request) -> dict[str, Any]:
    """Cadastra um novo projeto e cria a pasta correspondente sob PROJECTS_ROOT."""
    projects_root = _projects_root(request)
    try:
        slug = validate_name(payload.name)
    except ProjectError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        ) from err

    target_path = projects_root / slug

    if not target_path.exists():
        target_path.mkdir(parents=True, exist_ok=True)

    # Disparado em segundo plano, não aguardado: criar o venv/ambiente pode levar
    # dezenas de segundos (mount de bind do Windows é lento para muitos arquivos
    # pequenos), e `POST /{slug}/prewarm` já refaz esta mesma chamada quando o
    # usuário abre o projeto na IDE — bloquear a criação do projeto nisso é
    # latência pura sem ganho duradouro. `ensure_venv`/`ensure_node_env` etc. já
    # são idempotentes (checam se o ambiente existe antes de recriar).
    _task = asyncio.create_task(_provision_env_background(target_path, payload.language, slug))
    _env_provision_tasks.add(_task)
    _task.add_done_callback(_env_provision_tasks.discard)

    effective_git_url = payload.git_url

    if payload.init_git and not (target_path / ".git").exists():
        try:
            from git import Repo

            repo = Repo.init(target_path)
            try:
                gitignore_path = target_path / ".gitignore"
                if not gitignore_path.exists():
                    gitignore_path.write_text(
                        ".eltanix/\nnode_modules/\n__pycache__/\n", encoding="utf-8"
                    )
                repo.index.add([str(gitignore_path.relative_to(target_path))])
                repo.index.commit("Initial commit")
            except Exception as exc:
                log.warning("git.initial_commit.failed", path=str(target_path), error=str(exc))

            if payload.create_github_repo and not effective_git_url:
                try:
                    from eltanix.workspace.github import GitHubClient, resolve_token

                    settings = get_settings()
                    token = await resolve_token(settings.github_token)
                    if token:
                        gh = GitHubClient(token)
                        repo_data = await gh.create_repository(
                            name=slug,
                            description=payload.description,
                            private=True,
                        )
                        effective_git_url = repo_data.get("clone_url") or repo_data.get("html_url")
                except Exception as exc:
                    log.warning("github.private_repo.create_failed", slug=slug, error=str(exc))

            if effective_git_url:
                try:
                    repo.create_remote("origin", effective_git_url)
                except Exception as exc:
                    log.warning("git.remote.create_failed", path=str(target_path), error=str(exc))
        except Exception as exc:
            log.warning("git.init.failed", path=str(target_path), error=str(exc))

    try:
        async with session_scope() as session:
            stmt = select(ProjectRecord).where(ProjectRecord.slug == slug)
            rec = (await session.execute(stmt)).scalar_one_or_none()
            user_id = getattr(request.state, "user_id", None)
            if not rec:
                rec = ProjectRecord(
                    slug=slug,
                    name=payload.name,
                    description=payload.description,
                    local_path=str(target_path),
                    git_url=effective_git_url,
                    budget_limit_usd=payload.budget_limit_usd,
                    settings=payload.settings,
                )
                session.add(rec)
                await session.flush()
                # Quem cria vira dono — sem isto, o próprio criador ficaria
                # sem `project_member` e cairia no "sem acesso" do enforcement
                # (`require_role_by_slug`) na primeira operação de escrita.
                # Ausente para o canal de serviço (`user_id is None`): não é
                # "membro" de projeto nenhum, já tem bypass total.
                if user_id is not None:
                    await auth_store.add_member(
                        session, project_id=rec.id, user_id=user_id, role="owner"
                    )
            else:
                # POST é upsert-por-slug: sem esta checagem, um `editor` (ou
                # qualquer autenticado, hoje) reenviando o mesmo nome
                # reescreveria metadado de um projeto que não é dono — e essa
                # rota fica fora do PATCH normal (`update_project` abaixo), que
                # já teria barrado o mesmo autor.
                await require_role_by_slug(session, request, project_slug=slug, min_role="editor")
                rec.name = payload.name
                rec.description = payload.description
                rec.git_url = effective_git_url
                rec.budget_limit_usd = payload.budget_limit_usd
                rec.settings = payload.settings

            await session.flush()
            await session.refresh(rec)

            budget_limit = float(rec.budget_limit_usd) if rec.budget_limit_usd is not None else None
            res = {
                "id": str(rec.id),
                "slug": rec.slug,
                "name": rec.name,
                "description": rec.description,
                "local_path": rec.local_path,
                "git_url": rec.git_url,
                "budget_limit_usd": budget_limit,
                "settings": rec.settings,
            }
    except HTTPException:
        # `require_role_by_slug` levanta 403 acima — sem este re-raise, o
        # `except Exception` genérico logo abaixo (pensado só para Postgres
        # fora do ar) a engoliria e devolveria 200 com o fallback em disco,
        # deixando RBAC sem efeito nenhum aqui.
        raise
    except Exception as exc:
        log.warning("projects.db.unavailable", error=str(exc))
        res = {
            "id": slug,
            "slug": slug,
            "name": payload.name,
            "description": payload.description,
            "local_path": str(target_path),
            "git_url": payload.git_url,
            "budget_limit_usd": payload.budget_limit_usd,
            "settings": payload.settings,
        }

    if audit := _audit(request):
        try:
            await audit.record(
                actor="user",
                module="projects",
                action="create",
                details=f"Projeto cadastrado: {slug}",
                metadata={"slug": slug, "git_url": payload.git_url},
                project_slug=slug,
            )
        except Exception as exc:
            log.warning("projects.audit.failed", error=str(exc))

    return res


def _reject_filesystem_root(alvo: Path) -> None:
    """`PathGuard.allow()` (chamado logo abaixo) ADICIONA `alvo` à allowlist
    global do processo — não é uma validação, é uma concessão permanente de
    acesso a tudo dentro dele. Autorizar a raiz de um drive (`C:\\`), `/` ou a
    pasta do usuário inteira faria esse `allow()` liberar o disco todo (ou o
    `$HOME` todo) pro resto da vida do processo. `AdminDep` no router já
    restringe quem chega aqui a dono da instância / canal de serviço; isto é
    a segunda camada, que barra o alvo mais perigoso mesmo vindo de um admin
    legítimo por engano."""
    if alvo.parent == alvo:  # raiz de filesystem: "/" ou "C:\\"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Não é permitido vincular a raiz de um disco ou do sistema de arquivos.",
        )
    if alvo == Path.home().resolve():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Não é permitido vincular a pasta inteira do usuário — escolha uma subpasta.",
        )


@router.post("/open-path", dependencies=[AdminDep])
async def open_absolute_path(payload: OpenPathIn, request: Request) -> dict[str, Any]:
    """Abre e autoriza qualquer pasta do SO como projeto — fora de PROJECTS_ROOT.

    Diferente de `create_project`, o caminho não precisa estar sob PROJECTS_ROOT:
    a fronteira de segurança aqui é o `PathGuard` (autorização explícita por
    caminho), não `resolve()`. O registro em `ProjectRecord` é o que faz essa
    pasta aparecer na Central de Projetos depois de aberta.

    Restrita a `AdminDep` (dono da instância / canal de serviço): o
    `PathGuard.allow()` abaixo concede acesso de leitura a QUALQUER caminho do
    host para o processo inteiro, não só para quem pediu — não é algo que uma
    sessão comum (`viewer`/`editor`) deveria poder disparar.
    """
    from eltanix.workspace.inspector import ProjectInspector
    from eltanix.workspace.path_guard import default_path_guard

    projects_root = _projects_root(request)
    alvo = await asyncio.to_thread(lambda: _resolve_user_path(payload.path, projects_root))
    if not alvo.exists() or not alvo.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Caminho não encontrado ou não é diretório: {payload.path}",
        )
    _reject_filesystem_root(alvo)

    default_path_guard.allow(alvo)

    inspector = ProjectInspector()
    sig = inspector.inspect(alvo)

    try:
        slug = validate_name(alvo.name)
    except ProjectError:
        slug = re.sub(r"[^A-Za-z0-9._-]", "-", alvo.name).strip("-") or "projeto"

    async with session_scope() as session:
        stmt = select(ProjectRecord).where(ProjectRecord.slug == slug)
        rec = (await session.execute(stmt)).scalar_one_or_none()
        if rec and rec.local_path != str(alvo):
            # Slug já usado por outro caminho — sufixa para não colidir.
            base_slug, suffix = slug, 2
            while rec and rec.local_path != str(alvo):
                slug = f"{base_slug}-{suffix}"
                stmt = select(ProjectRecord).where(ProjectRecord.slug == slug)
                rec = (await session.execute(stmt)).scalar_one_or_none()
                suffix += 1

        if not rec:
            rec = ProjectRecord(
                slug=slug,
                name=sig.name,
                description=sig.executive_summary or "",
                local_path=str(alvo),
                default_branch="main",
            )
            session.add(rec)
            await session.flush()
            user_id = getattr(request.state, "user_id", None)
            if user_id is not None:
                await auth_store.add_member(
                    session, project_id=rec.id, user_id=user_id, role="owner"
                )
        else:
            rec.name = sig.name
            rec.local_path = str(alvo)

        await session.flush()

    if audit := _audit(request):
        try:
            await audit.record(
                actor="user",
                module="projects",
                action="open_path",
                details=f"Pasta aberta como projeto: {alvo}",
                metadata={"slug": slug, "path": str(alvo)},
                project_slug=slug,
            )
        except Exception as exc:
            log.warning("projects.audit.failed", error=str(exc))

    return {
        "slug": slug,
        "name": sig.name,
        "path": sig.path,
        "primary_language": sig.primary_language,
        "frameworks": sig.frameworks,
        "build_system": sig.build_system,
        "has_docker": sig.has_docker,
        "has_git": sig.has_git,
        "has_ci_cd": sig.has_ci_cd,
        "summary": sig.executive_summary,
    }


@router.post("/inspect-path", dependencies=[AdminDep])
async def inspect_path(payload: InspectPathIn, request: Request) -> dict[str, Any]:
    """Inspeciona metadados, stack e resumo executivo de qualquer pasta antes
    de vincular. Restrita a `AdminDep`: lê arquivos (`package.json`,
    manifestos etc.) de qualquer diretório do host que o admin apontar, o
    mesmo raio de alcance de `/open-path` — ver o comentário lá."""
    from eltanix.workspace.inspector import ProjectInspector

    projects_root = _projects_root(request)
    alvo = await asyncio.to_thread(lambda: _resolve_user_path(payload.path, projects_root))
    if not alvo.exists() or not alvo.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Caminho não encontrado ou não é diretório: {payload.path}",
        )

    inspector = ProjectInspector()
    sig = inspector.inspect(alvo)
    return {
        "name": sig.name,
        "path": sig.path,
        "primary_language": sig.primary_language,
        "frameworks": sig.frameworks,
        "build_system": sig.build_system,
        "has_docker": sig.has_docker,
        "has_git": sig.has_git,
        "has_ci_cd": sig.has_ci_cd,
        "summary": sig.executive_summary,
    }


@router.post("/filesystem/browse", dependencies=[AdminDep])
async def browse_filesystem(payload: BrowsePathIn, request: Request) -> dict[str, Any]:
    """Lista pastas e raízes do sistema de arquivos para o explorador visual
    de projetos. Restrita a `AdminDep`: `_list_system_roots` devolve de
    propósito TODA letra de drive (Windows) ou `/` (Unix), e a listagem em si
    enumera o conteúdo de qualquer diretório do host — uma sessão comum não
    deveria conseguir varrer o disco inteiro pela IDE."""
    projects_root = _projects_root(request)
    roots = _list_system_roots(projects_root)

    # Se nenhum caminho foi informado, inicia explorando a Raiz de Projetos
    raw_path = payload.path.strip() if payload.path and payload.path.strip() else str(projects_root)
    alvo = await asyncio.to_thread(lambda: _resolve_user_path(raw_path, projects_root))

    if not alvo.exists() or not alvo.is_dir():
        alvo = projects_root if projects_root.exists() else Path.home()

    breadcrumbs: list[dict[str, str]] = []
    curr = alvo
    while curr != curr.parent:
        breadcrumbs.append({"name": curr.name or str(curr), "path": str(curr)})
        curr = curr.parent
    breadcrumbs.append({"name": curr.name or str(curr), "path": str(curr)})
    breadcrumbs.reverse()

    parent_path = str(alvo.parent) if alvo.parent != alvo else None

    ignorar = {
        "$RECYCLE.BIN",
        "System Volume Information",
        "node_modules",
        ".git",
        ".venv",
        "__pycache__",
        ".eltanix",
        ".next",
        "dist",
        "build",
    }

    def _scan() -> list[dict[str, Any]]:
        res = []
        for item in sorted(alvo.iterdir(), key=lambda p: p.name.lower()):
            try:
                if item.is_dir() and item.name not in ignorar and not item.name.startswith("."):
                    has_git = (item / ".git").exists()
                    has_pkg = (item / "package.json").exists()
                    has_py = (item / "pyproject.toml").exists() or (item / "requirements.txt").exists()
                    res.append({
                        "name": item.name,
                        "path": str(item),
                        "has_git": has_git,
                        "is_project": bool(has_git or has_pkg or has_py),
                    })
            except (PermissionError, OSError):
                continue
        return res

    try:
        dirs = await asyncio.to_thread(_scan)
    except (PermissionError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Sem permissão para ler o diretório: {exc}",
        ) from exc

    return {
        "current_path": str(alvo),
        "parent_path": parent_path,
        "breadcrumbs": breadcrumbs,
        "roots": roots,
        "directories": dirs[:120],
        # Sem isto o cliente não tinha como saber que a lista foi cortada —
        # uma pasta com mais de 120 subpastas escondia o resto em silêncio.
        "truncated": len(dirs) > 120,
        "total_directories": len(dirs),
    }



@router.get("/{slug}/summary")
async def get_summary(slug: str, request: Request) -> dict[str, Any]:
    """Retorna a visão geral 360° do projeto (IDE, Git, Custos, Notas, Graphify, etc.)."""
    # Fora do `try/except Exception` logo abaixo de propósito: esse bloco tem
    # fallback para leitura direta em disco quando o Postgres está fora do ar,
    # e um `except Exception` genérico ali engoliria o 403 do RBAC junto.
    async with session_scope() as session:
        await require_role_by_slug(session, request, project_slug=slug, min_role="viewer")

    projects_root = _projects_root(request)
    try:
        async with session_scope() as session:
            summary = await get_project_summary(session, slug, projects_root)
            return {
                "slug": summary.slug,
                "name": summary.name,
                "description": summary.description,
                "local_path": summary.local_path,
                "git_url": summary.git_url,
                "is_git": summary.is_git,
                "branch": summary.branch,
                "budget_limit_usd": summary.budget_limit_usd,
                "total_cost_usd": summary.total_cost_usd,
                "total_tokens": summary.total_tokens,
                "notes_count": summary.notes_count,
                "documents_count": summary.documents_count,
                "graph_nodes_count": summary.graph_nodes_count,
                "graph_edges_count": summary.graph_edges_count,
                "audit_events_count": summary.audit_events_count,
                "active_sessions_count": summary.active_sessions_count,
                "recent_commits": summary.recent_commits,
                "settings": summary.settings,
            }
    except Exception as exc:
        log.warning("projects.summary.fallback", slug=slug, error=str(exc))
        try:
            target_path = resolve(projects_root, slug)
            is_git = (target_path / ".git").exists()
            branch = _branch_of(target_path) if is_git else None
            return {
                "slug": target_path.name,
                "name": target_path.name,
                "description": f"Projeto local em {target_path.name}",
                "local_path": str(target_path),
                "git_url": None,
                "is_git": is_git,
                "branch": branch,
                "budget_limit_usd": None,
                "total_cost_usd": 0.0,
                "total_tokens": 0,
                "notes_count": 0,
                "documents_count": 0,
                "graph_nodes_count": 0,
                "graph_edges_count": 0,
                "audit_events_count": 0,
                "active_sessions_count": 0,
                "recent_commits": [],
                "settings": {},
            }
        except ProjectError as err:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(err)) from err


@router.patch("/{slug}")
async def update_project(slug: str, payload: ProjectUpdateIn, request: Request) -> dict[str, Any]:
    """Atualiza metadados e limites do projeto."""
    try:
        slug_valido = validate_name(slug)
    except ProjectError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err)) from err

    async with session_scope() as session:
        await require_role_by_slug(session, request, project_slug=slug_valido, min_role="editor")
        stmt = select(ProjectRecord).where(ProjectRecord.slug == slug_valido)
        rec = (await session.execute(stmt)).scalar_one_or_none()
        if not rec:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Projeto {slug} não encontrado."
            )

        if payload.name is not None:
            rec.name = payload.name
        if payload.description is not None:
            rec.description = payload.description
        if payload.git_url is not None:
            rec.git_url = payload.git_url
        if payload.budget_limit_usd is not None:
            rec.budget_limit_usd = payload.budget_limit_usd
        if payload.settings is not None:
            rec.settings = payload.settings

        await session.flush()
        await session.refresh(rec)

        budget_limit = float(rec.budget_limit_usd) if rec.budget_limit_usd is not None else None
        res = {
            "slug": rec.slug,
            "name": rec.name,
            "description": rec.description,
            "git_url": rec.git_url,
            "budget_limit_usd": budget_limit,
            "settings": rec.settings,
        }

    if audit := _audit(request):
        try:
            await audit.record(
                actor="user",
                module="projects",
                action="update",
                details=f"Projeto atualizado: {slug_valido}",
                metadata={"slug": slug_valido},
                project_slug=slug_valido,
            )
        except Exception as exc:
            log.warning("projects.audit.failed", error=str(exc))

    return res


@router.delete("/{slug}")
async def delete_project(slug: str, request: Request, delete_files: bool = False) -> dict[str, Any]:
    """Remove o registro do projeto no banco de dados (e opcionalmente no disco)."""
    try:
        slug_valido = validate_name(slug)
    except ProjectError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err)) from err

    projects_root = _projects_root(request)

    async with session_scope() as session:
        await require_role_by_slug(session, request, project_slug=slug_valido, min_role="owner")
        rec = (
            await session.execute(select(ProjectRecord).where(ProjectRecord.slug == slug_valido))
        ).scalar_one_or_none()
        if rec:
            await session.delete(rec)

    if delete_files:
        try:
            target_path = resolve(projects_root, slug_valido)
            shutil.rmtree(target_path, ignore_errors=True)
        except ProjectError:
            pass

    if audit := _audit(request):
        try:
            await audit.record(
                actor="user",
                module="projects",
                action="delete",
                details=f"Projeto removido: {slug_valido} (arquivos_apagados={delete_files})",
                metadata={"slug": slug_valido, "delete_files": delete_files},
                project_slug=slug_valido,
            )
        except Exception as exc:
            log.warning("projects.audit.failed", error=str(exc))

    return {"status": "ok", "slug": slug_valido, "files_deleted": delete_files}


@router.post("/{slug}/prewarm")
async def prewarm_project(slug: str, request: Request) -> dict[str, Any]:
    """Pré-aquece o sandbox e o ecossistema do projeto (ambiente, container e Playwright)."""
    projects_root = _projects_root(request)
    try:
        slug_valido = validate_name(slug)
        workspace_root = resolve(projects_root, slug_valido)
    except ProjectError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err)) from err

    async with session_scope() as session:
        await require_role_by_slug(session, request, project_slug=slug_valido, min_role="viewer")

    # 1. Garante o ambiente de pacotes do projeto (.venv, etc.)
    try:
        from eltanix.api.routes.packages import ensure_project_env

        await ensure_project_env(workspace_root)
    except Exception as exc:
        log.warning("projects.prewarm.env_failed", slug=slug_valido, error=str(exc))

    runner = getattr(request.app.state, "agent_runner", None)
    if runner is None:
        return {"status": "ok", "slug": slug_valido, "sandbox_ready": False}

    # 2. Reutiliza ou cria uma sessão pré-aquecida para a IDE
    sessao_ativa = None
    for s in runner._sessions.values():
        if s.workspace_root == workspace_root and s.sandbox_available:
            sessao_ativa = s
            break

    if sessao_ativa is None:
        try:
            sessao_ativa = await runner.create_session(
                task="Sessão Pré-aquecida da IDE",
                workspace_root=workspace_root,
                mode="auto",
            )
        except Exception as exc:
            log.warning("projects.prewarm.session_failed", slug=slug_valido, error=str(exc))

    is_web = getattr(sessao_ativa, "is_web_app", False) if sessao_ativa else False
    web_prewarmed = getattr(sessao_ativa, "web_prewarmed", False) if sessao_ativa else False
    session_id = sessao_ativa.session_id if sessao_ativa else None

    if sessao_ativa and is_web and not web_prewarmed:
        try:
            web_prewarmed = await runner.prewarm_web_app(sessao_ativa.session_id, force=True)
        except Exception as exc:
            log.warning("projects.prewarm.web_failed", session=session_id, error=str(exc))

    return {
        "status": "ok",
        "slug": slug_valido,
        "session_id": session_id,
        "sandbox_ready": bool(sessao_ativa and sessao_ativa.sandbox_available),
        "is_web_app": is_web,
        "web_prewarmed": web_prewarmed,
    }


class MemberIn(BaseModel):
    user_id: uuid.UUID
    role: str = Field(default="viewer", description="viewer, editor ou owner")


async def _get_project_record_or_404(session: AsyncSession, slug: str) -> ProjectRecord:
    stmt = select(ProjectRecord).where(ProjectRecord.slug == slug)
    rec = (await session.execute(stmt)).scalar_one_or_none()
    if not rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Projeto {slug} não encontrado."
        )
    return rec


@router.get("/{slug}/members")
async def list_members(slug: str, request: Request) -> dict[str, Any]:
    async with session_scope() as session:
        await require_role_by_slug(session, request, project_slug=slug, min_role="viewer")
        rec = await _get_project_record_or_404(session, slug)
        members = await auth_store.list_members(session, project_id=rec.id)
        return {
            "members": [
                {"user_id": str(m.user_id), "role": m.role, "created_at": m.created_at.isoformat()}
                for m in members
            ]
        }


@router.post("/{slug}/members")
async def add_member(slug: str, payload: MemberIn, request: Request) -> dict[str, Any]:
    """Convite/mudança de papel — só `owner` do projeto (ou admin da instância)
    gerencia quem mais tem acesso, mesma fronteira de `delete_project`."""
    if payload.role not in ROLE_RANK:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Papel inválido: {payload.role!r}"
        )
    async with session_scope() as session:
        await require_role_by_slug(session, request, project_slug=slug, min_role="owner")
        rec = await _get_project_record_or_404(session, slug)
        member = await auth_store.add_member(
            session, project_id=rec.id, user_id=payload.user_id, role=payload.role
        )

    if audit := _audit(request):
        try:
            await audit.record(
                actor="user",
                module="projects",
                action="member_add",
                details=f"{payload.user_id} -> {payload.role}",
                metadata={"slug": slug, "user_id": str(payload.user_id), "role": payload.role},
                project_slug=slug,
                risk_level="medium",
            )
        except Exception as exc:
            log.warning("projects.audit.failed", error=str(exc))

    return {"user_id": str(member.user_id), "role": member.role}


@router.delete("/{slug}/members/{user_id}")
async def remove_member(slug: str, user_id: uuid.UUID, request: Request) -> dict[str, Any]:
    async with session_scope() as session:
        await require_role_by_slug(session, request, project_slug=slug, min_role="owner")
        rec = await _get_project_record_or_404(session, slug)
        removed = await auth_store.remove_member(session, project_id=rec.id, user_id=user_id)

    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Membro não encontrado.")

    if audit := _audit(request):
        try:
            await audit.record(
                actor="user",
                module="projects",
                action="member_remove",
                details=str(user_id),
                metadata={"slug": slug, "user_id": str(user_id)},
                project_slug=slug,
                risk_level="medium",
            )
        except Exception as exc:
            log.warning("projects.audit.failed", error=str(exc))

    return {"removed": True}
