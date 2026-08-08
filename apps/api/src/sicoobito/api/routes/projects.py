"""Rotas de gestão centralizada de projetos."""

from __future__ import annotations

import shutil
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from sicoobito.api.deps import AuthDep
from sicoobito.audit.service import AuditService
from sicoobito.config import get_settings
from sicoobito.db.models import ProjectRecord
from sicoobito.db.session import session_scope
from sicoobito.logging_setup import get_logger
from sicoobito.workspace.projects import (
    ProjectError,
    _branch_of,
    get_project_summary,
    resolve,
    sync_projects_db,
    validate_name,
)
from sicoobito.workspace.projects import (
    list_projects as list_disk_projects,
)

log = get_logger(__name__)

router = APIRouter(prefix="/api/projects", tags=["projects"], dependencies=[AuthDep])


def _audit(request: Request) -> AuditService | None:
    return getattr(request.app.state, "audit", None)


def _projects_root(request: Request):
    return getattr(request.app.state, "projects_root", None) or get_settings().projects_root


class ProjectCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="")
    git_url: str | None = Field(default=None)
    budget_limit_usd: float | None = Field(default=None)
    settings: dict[str, Any] = Field(default_factory=dict)


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
            items = [
                {
                    "id": str(r.id),
                    "slug": r.slug,
                    "name": r.name,
                    "description": r.description,
                    "local_path": r.local_path,
                    "git_url": r.git_url,
                    "default_branch": r.default_branch,
                    "budget_limit_usd": float(r.budget_limit_usd) if r.budget_limit_usd is not None else None,
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
    slug = validate_name(payload.name)
    target_path = projects_root / slug

    if not target_path.exists():
        target_path.mkdir(parents=True, exist_ok=True)

    async with session_scope() as session:
        stmt = select(ProjectRecord).where(ProjectRecord.slug == slug)
        rec = (await session.execute(stmt)).scalar_one_or_none()
        if not rec:
            rec = ProjectRecord(
                slug=slug,
                name=payload.name,
                description=payload.description,
                local_path=str(target_path),
                git_url=payload.git_url,
                budget_limit_usd=payload.budget_limit_usd,
                settings=payload.settings,
            )
            session.add(rec)
        else:
            rec.name = payload.name
            rec.description = payload.description
            rec.git_url = payload.git_url
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

    if audit := _audit(request):
        await audit.record(
            actor="user",
            module="projects",
            action="create",
            details=f"Projeto cadastrado: {slug}",
            event_metadata={"slug": slug, "git_url": payload.git_url},
            project_slug=slug,
        )

    return res


@router.get("/{slug}/summary")
async def get_summary(slug: str, request: Request) -> dict[str, Any]:
    """Retorna a visão geral 360° do projeto (IDE, Git, Custos, Notas, Graphify, Auditoria, Sessões)."""
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
                "graph_nodes_count": summary.graph_nodes_count,
                "graph_edges_count": summary.graph_edges_count,
                "audit_events_count": summary.audit_events_count,
                "active_sessions_count": summary.active_sessions_count,
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
                "graph_nodes_count": 0,
                "graph_edges_count": 0,
                "audit_events_count": 0,
                "active_sessions_count": 0,
                "settings": {},
            }
        except ProjectError as err:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(err)) from err


@router.patch("/{slug}")
async def update_project(slug: str, payload: ProjectUpdateIn, request: Request) -> dict[str, Any]:
    """Atualiza metadados e limites do projeto."""
    slug_valido = validate_name(slug)
    async with session_scope() as session:
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
        await audit.record(
            actor="user",
            module="projects",
            action="update",
            details=f"Projeto atualizado: {slug_valido}",
            event_metadata={"slug": slug_valido},
            project_slug=slug_valido,
        )

    return res


@router.delete("/{slug}")
async def delete_project(slug: str, request: Request, delete_files: bool = False) -> dict[str, Any]:
    """Remove o registro do projeto no banco de dados (e opcionalmente apaga os arquivos no disk)."""
    slug_valido = validate_name(slug)
    projects_root = _projects_root(request)

    async with session_scope() as session:
        rec = (await session.execute(select(ProjectRecord).where(ProjectRecord.slug == slug_valido))).scalar_one_or_none()
        if rec:
            await session.delete(rec)

    if delete_files:
        try:
            target_path = resolve(projects_root, slug_valido)
            shutil.rmtree(target_path, ignore_errors=True)
        except ProjectError:
            pass

    if audit := _audit(request):
        await audit.record(
            actor="user",
            module="projects",
            action="delete",
            details=f"Projeto removido: {slug_valido} (arquivos_apagados={delete_files})",
            event_metadata={"slug": slug_valido, "delete_files": delete_files},
            project_slug=slug_valido,
        )

    return {"status": "ok", "slug": slug_valido, "files_deleted": delete_files}
