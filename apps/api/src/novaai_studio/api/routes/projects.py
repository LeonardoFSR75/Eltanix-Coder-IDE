"""Rotas de gestão centralizada de projetos."""

from __future__ import annotations

import asyncio
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novaai_studio.api.deps import AuthDep
from novaai_studio.audit.service import AuditService
from novaai_studio.auth import store as auth_store
from novaai_studio.auth.rbac import ROLE_RANK, require_role_by_slug
from novaai_studio.config import get_settings
from novaai_studio.db.models import ProjectRecord
from novaai_studio.db.session import session_scope
from novaai_studio.logging_setup import get_logger
from novaai_studio.workspace.projects import (
    ProjectError,
    _branch_of,
    get_project_summary,
    resolve,
    sync_projects_db,
    validate_name,
)
from novaai_studio.workspace.projects import (
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
        from novaai_studio.api.routes.packages import ensure_project_env

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
                        ".novaai_studio/\nnode_modules/\n__pycache__/\n", encoding="utf-8"
                    )
                repo.index.add([str(gitignore_path.relative_to(target_path))])
                repo.index.commit("Initial commit")
            except Exception as exc:
                log.warning("git.initial_commit.failed", path=str(target_path), error=str(exc))

            if payload.create_github_repo and not effective_git_url:
                try:
                    from novaai_studio.workspace.github import GitHubClient, resolve_token

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


@router.post("/open-path")
async def open_absolute_path(payload: OpenPathIn, request: Request) -> dict[str, Any]:
    """Abre e autoriza qualquer pasta do SO como projeto — fora de PROJECTS_ROOT.

    Diferente de `create_project`, o caminho não precisa estar sob PROJECTS_ROOT:
    a fronteira de segurança aqui é o `PathGuard` (autorização explícita por
    caminho), não `resolve()`. O registro em `ProjectRecord` é o que faz essa
    pasta aparecer na Central de Projetos depois de aberta.
    """
    from novaai_studio.workspace.inspector import ProjectInspector
    from novaai_studio.workspace.path_guard import default_path_guard

    alvo = await asyncio.to_thread(lambda: Path(payload.path).resolve())
    if not alvo.exists() or not alvo.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Caminho não encontrado ou não é diretório: {payload.path}",
        )

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
        from novaai_studio.api.routes.packages import ensure_project_env

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
