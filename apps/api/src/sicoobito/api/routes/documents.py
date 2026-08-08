"""Rotas de documentos (RAG): upload, ingestão e busca.

O upload não passa pelo gateway do Next (`apps/web/app/api/gateway/...`),
que lê o corpo como texto e corromperia um PDF binário. O fluxo é: o cliente
pede uma URL pré-assinada aqui, sobe o arquivo direto para o MinIO, e só então
confirma — ponto em que a ingestão (extração, fatiamento, embedding) é
agendada como tarefa de fundo.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from sicoobito.api.deps import AuthDep, SettingsDep
from sicoobito.audit.service import AuditService
from sicoobito.db.session import session_scope
from sicoobito.documents import store
from sicoobito.documents.service import DocumentService
from sicoobito.logging_setup import get_logger
from sicoobito.storage.blob import BlobStore

router = APIRouter(prefix="/api/documents", tags=["documents"], dependencies=[AuthDep])

log = get_logger(__name__)

_ALLOWED_CONTENT_TYPES = {"application/pdf"}


def _service(request: Request) -> DocumentService:
    service: DocumentService | None = getattr(request.app.state, "documents", None)
    if service is None:  # pragma: no cover - só ocorre se o lifespan falhar
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Serviço de documentos indisponível.",
        )
    return service


def _blob(request: Request) -> BlobStore:
    blob: BlobStore | None = getattr(request.app.state, "blob", None)
    if blob is None:  # pragma: no cover - só ocorre se o lifespan falhar
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Armazenamento indisponível."
        )
    return blob


def _audit(request: Request) -> AuditService | None:
    return getattr(request.app.state, "audit", None)


class UploadUrlRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=512)
    content_type: str
    size_bytes: int = Field(gt=0)
    project: str | None = Field(default=None, description="Slug do projeto — vazio = global")


@router.post("/upload-url")
async def request_upload_url(
    payload: UploadUrlRequest, request: Request, settings: SettingsDep
) -> dict[str, Any]:
    if payload.content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tipo não suportado: {payload.content_type}. Aceito: PDF.",
        )
    max_bytes = settings.documents_max_upload_mb * 1024 * 1024
    if payload.size_bytes > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Arquivo maior que o limite de {settings.documents_max_upload_mb}MB.",
        )

    blob = _blob(request)
    object_key = f"{uuid.uuid4()}/{payload.filename}"

    async with session_scope() as session:
        document = await store.create_document(
            session,
            filename=payload.filename,
            content_type=payload.content_type,
            size_bytes=payload.size_bytes,
            bucket=blob.bucket,
            object_key=object_key,
            project_slug=payload.project,
        )
        document_id = document.id

    upload_url = await blob.presigned_put_url(object_key)
    return {"document_id": str(document_id), "upload_url": upload_url}


@router.post("/{document_id}/confirm")
async def confirm_upload(
    document_id: uuid.UUID, request: Request, background_tasks: BackgroundTasks
) -> dict[str, Any]:
    blob = _blob(request)
    service = _service(request)

    async with session_scope() as session:
        document = await store.get_document(session, document_id)
        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Documento não encontrado."
            )
        object_key = document.minio_object

    if not await blob.object_exists(object_key):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Upload ainda não chegou ao armazenamento. Tente novamente em instantes.",
        )

    async with session_scope() as session:
        await store.set_status(session, document_id, status="processing")

    background_tasks.add_task(service.ingest, document_id)

    if audit := _audit(request):
        await audit.record(
            actor="usuário",
            module="RAG",
            action="Upload de documento confirmado",
            details=f"document_id={document_id}",
        )

    return {"document_id": str(document_id), "status": "processing"}


@router.get("")
async def list_documents(project: str | None = Query(default=None)) -> dict[str, Any]:
    async with session_scope() as session:
        documents = await store.list_documents(session, project_slug=project)

    return {
        "documents": [
            {
                "id": str(d.id),
                "project_slug": d.project_slug,
                "filename": d.filename,
                "content_type": d.content_type,
                "size_bytes": d.size_bytes,
                "page_count": d.page_count,
                "chunk_count": d.chunk_count,
                "status": d.status,
                "error": d.error,
                "uploaded_at": d.uploaded_at.isoformat(),
                "indexed_at": d.indexed_at.isoformat() if d.indexed_at else None,
            }
            for d in documents
        ]
    }


@router.get("/{document_id}")
async def get_document(document_id: uuid.UUID) -> dict[str, Any]:
    async with session_scope() as session:
        document = await store.get_document(session, document_id)

    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Documento não encontrado."
        )

    return {
        "id": str(document.id),
        "project_slug": document.project_slug,
        "filename": document.filename,
        "content_type": document.content_type,
        "size_bytes": document.size_bytes,
        "page_count": document.page_count,
        "chunk_count": document.chunk_count,
        "status": document.status,
        "error": document.error,
        "uploaded_at": document.uploaded_at.isoformat(),
        "indexed_at": document.indexed_at.isoformat() if document.indexed_at else None,
    }


@router.delete("/{document_id}")
async def delete_document(document_id: uuid.UUID, request: Request) -> dict[str, Any]:
    blob = _blob(request)

    async with session_scope() as session:
        document = await store.get_document(session, document_id)
        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Documento não encontrado."
            )
        object_key = document.minio_object
        filename = document.filename
        await store.delete_document(session, document_id)

    try:
        await blob.remove_object(object_key)
    except Exception as exc:
        # Linha do banco já caiu; um objeto órfão no bucket não é motivo para
        # devolver erro a uma exclusão que, do ponto de vista do usuário, já
        # aconteceu. Loga para o órfão ser rastreável, sem propagar.
        log.warning("documents.blob_delete_failed", object_key=object_key, error=str(exc)[:200])

    if audit := _audit(request):
        await audit.record(
            actor="usuário",
            module="RAG",
            action="Documento removido",
            details=filename,
            risk_level="medium",
        )

    return {"deleted": True}


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=8, ge=1, le=50)
    project: str | None = Field(default=None)


@router.post("/search")
async def search_documents(payload: SearchRequest, request: Request) -> dict[str, Any]:
    hits = await _service(request).search(
        payload.query, limit=payload.limit, project_slug=payload.project
    )
    return {
        "query": payload.query,
        "hits": [
            {
                "document_id": h.document_id,
                "filename": h.filename,
                "chunk_index": h.chunk_index,
                "page_number": h.page_number,
                "content": h.content,
                "token_count": h.token_count,
                "score": round(h.score, 6),
                "vector_rank": h.vector_rank,
                "text_rank": h.text_rank,
            }
            for h in hits
        ],
    }
