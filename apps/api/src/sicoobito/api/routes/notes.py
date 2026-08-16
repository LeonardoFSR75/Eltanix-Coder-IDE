"""Rotas de notas (Segundo Cérebro)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from sicoobito.api.deps import AuthDep
from sicoobito.audit.service import AuditService
from sicoobito.notes.service import NoteService
from sicoobito.workspace.projects import ProjectError

router = APIRouter(prefix="/api/notes", tags=["notes"], dependencies=[AuthDep])


def _service(request: Request) -> NoteService:
    service: NoteService | None = getattr(request.app.state, "notes", None)
    if service is None:  # pragma: no cover - só ocorre se o lifespan falhar
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Serviço de notas indisponível."
        )
    return service


def _audit(request: Request) -> AuditService | None:
    return getattr(request.app.state, "audit", None)


def _view(note: Any) -> dict[str, Any]:
    return {
        "id": str(note.id),
        "project_slug": note.project_slug,
        "title": note.title,
        "content": note.content,
        "tags": note.tags,
        "links": note.links,
        "created_at": note.created_at.isoformat(),
        "updated_at": note.updated_at.isoformat(),
    }


class NoteIn(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    content: str = Field(default="")
    tags: list[str] = Field(default_factory=list)
    project: str | None = Field(default=None, description="Slug do projeto — vazio = nota global")


@router.get("")
async def list_notes(request: Request, project: str | None = Query(default=None)) -> dict[str, Any]:
    notes = await _service(request).list_all(project_slug=project)
    return {"notes": [_view(n) for n in notes]}


@router.post("")
async def create_note(payload: NoteIn, request: Request) -> dict[str, Any]:
    try:
        note = await _service(request).create(
            title=payload.title,
            content=payload.content,
            tags=payload.tags,
            project_slug=payload.project,
        )
    except ProjectError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if audit := _audit(request):
        await audit.record(
            actor="usuário", module="SecondBrain", action="Nota criada", details=note.title
        )
    return _view(note)


@router.get("/{note_id}")
async def get_note(note_id: uuid.UUID, request: Request) -> dict[str, Any]:
    note = await _service(request).get(note_id)
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nota não encontrada.")
    return _view(note)


@router.put("/{note_id}")
async def update_note(note_id: uuid.UUID, payload: NoteIn, request: Request) -> dict[str, Any]:
    note = await _service(request).update(
        note_id, title=payload.title, content=payload.content, tags=payload.tags
    )
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nota não encontrada.")
    return _view(note)


@router.delete("/{note_id}")
async def delete_note(note_id: uuid.UUID, request: Request) -> dict[str, Any]:
    note = await _service(request).get(note_id)
    deleted = await _service(request).delete(note_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nota não encontrada.")
    if audit := _audit(request):
        await audit.record(
            actor="usuário",
            module="SecondBrain",
            action="Nota removida",
            details=note.title if note else str(note_id),
            risk_level="medium",
        )
    return {"deleted": True}


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=8, ge=1, le=50)
    project: str | None = Field(default=None)


@router.post("/search")
async def search_notes(payload: SearchRequest, request: Request) -> dict[str, Any]:
    hits = await _service(request).search(
        payload.query, limit=payload.limit, project_slug=payload.project
    )
    return {
        "query": payload.query,
        "hits": [
            {
                "note_id": h.note_id,
                "title": h.title,
                "chunk_index": h.chunk_index,
                "content": h.content,
                "token_count": h.token_count,
                "score": round(h.score, 6),
                "vector_rank": h.vector_rank,
                "text_rank": h.text_rank,
            }
            for h in hits
        ],
    }
