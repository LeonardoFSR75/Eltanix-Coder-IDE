"""Rotas de documentos (RAG): upload, ingestão e busca.

O upload não passa pelo gateway do Next (`apps/web/app/api/gateway/...`),
que lê o corpo como texto e corromperia um PDF binário. O fluxo é: o cliente
pede uma URL pré-assinada aqui, sobe o arquivo direto para o MinIO, e só então
confirma — ponto em que a ingestão (extração, fatiamento, embedding) é
agendada como tarefa de fundo.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from novaai_studio.api.deps import AuthDep, SettingsDep
from novaai_studio.audit.service import AuditService
from novaai_studio.auth.rbac import require_role_by_slug
from novaai_studio.db.session import session_scope
from novaai_studio.documents import store
from novaai_studio.documents.service import DocumentService
from novaai_studio.logging_setup import get_logger
from novaai_studio.storage.blob import BlobStore
from novaai_studio.workspace.projects import ProjectError, ensure_project_slug_exists

router = APIRouter(prefix="/api/documents", tags=["documents"], dependencies=[AuthDep])

log = get_logger(__name__)

_ALLOWED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".doc",
    ".docm",
    ".xlsx",
    ".xls",
    ".xlsm",
    ".xlsb",
    ".pptx",
    ".ppt",
    ".ppsx",
    ".odt",
    ".ods",
    ".odp",
    ".rtf",
    ".epub",
    ".csv",
    ".tsv",
    ".txt",
    ".md",
    ".markdown",
}

_ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "application/vnd.ms-word.document.macroEnabled.12",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/vnd.ms-excel.sheet.macroEnabled.12",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.slideshow",
    "application/vnd.oasis.opendocument.text",
    "application/vnd.oasis.opendocument.spreadsheet",
    "application/vnd.oasis.opendocument.presentation",
    "application/rtf",
    "text/rtf",
    "application/epub+zip",
    "text/csv",
    "application/csv",
    "text/tab-separated-values",
    "text/plain",
    "text/markdown",
    "application/octet-stream",
}
_UNSAFE_OBJECT_KEY_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def _safe_object_name(filename: str) -> str:
    """`filename` vira parte literal da chave do objeto no MinIO — sem
    sanitizar, `/`, `..` ou caracteres de controle no nome viram estrutura
    dentro do bucket em vez de um nome de arquivo comum."""
    nome = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    nome = _UNSAFE_OBJECT_KEY_CHARS.sub("_", nome).strip("._") or "documento"
    return nome[:255]


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
    ext = ("." + payload.filename.rsplit(".", 1)[-1].lower()) if "." in payload.filename else ""
    is_valid = payload.content_type in _ALLOWED_CONTENT_TYPES or ext in _ALLOWED_EXTENSIONS
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Formato não suportado: '{payload.filename}' ({payload.content_type}). "
                "Formatos aceitos: PDF, Word (DOCX/DOC), Excel (XLSX/CSV), PowerPoint (PPTX), "
                "OpenDocument (ODT/ODS/ODP), RTF, EPUB e Markdown/Texto."
            ),
        )
    max_bytes = settings.documents_max_upload_mb * 1024 * 1024
    if payload.size_bytes > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Arquivo maior que o limite de {settings.documents_max_upload_mb}MB.",
        )

    blob = _blob(request)
    object_key = f"{uuid.uuid4()}/{_safe_object_name(payload.filename)}"

    async with session_scope() as session:
        await require_role_by_slug(
            session, request, project_slug=payload.project, min_role="editor"
        )
        if payload.project:
            try:
                await ensure_project_slug_exists(session, payload.project)
            except ProjectError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
                ) from exc
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
    document_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    settings: SettingsDep,
) -> dict[str, Any]:
    blob = _blob(request)
    service = _service(request)

    async with session_scope() as session:
        document = await store.get_document(session, document_id)
        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Documento não encontrado."
            )
        await require_role_by_slug(
            session, request, project_slug=document.project_slug, min_role="editor"
        )
        object_key = document.minio_object

    if not await blob.object_exists(object_key):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Upload ainda não chegou ao armazenamento. Tente novamente em instantes.",
        )

    # `size_bytes` foi só o valor declarado pelo cliente ao pedir a URL — o
    # upload em si vai direto para o MinIO, sem passar pela API, então nada
    # até aqui impediu um arquivo maior que o limite configurado. Checa o
    # tamanho real do objeto antes de agendar a extração/embedding.
    max_bytes = settings.documents_max_upload_mb * 1024 * 1024
    tamanho_real = await blob.stat_size(object_key)
    if tamanho_real is not None and tamanho_real > max_bytes:
        try:
            await blob.remove_object(object_key)
        except Exception as exc:
            log.warning(
                "documents.oversized_cleanup_failed", object_key=object_key, error=str(exc)[:200]
            )
        async with session_scope() as session:
            await store.set_status(
                session,
                document_id,
                status="failed",
                error=f"Arquivo enviado ({tamanho_real} bytes) excede o limite de "
                f"{settings.documents_max_upload_mb}MB.",
            )
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Arquivo maior que o limite de {settings.documents_max_upload_mb}MB.",
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
async def list_documents(
    request: Request, project: str | None = Query(default=None)
) -> dict[str, Any]:
    async with session_scope() as session:
        await require_role_by_slug(session, request, project_slug=project, min_role="viewer")
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
async def get_document(document_id: uuid.UUID, request: Request) -> dict[str, Any]:
    async with session_scope() as session:
        document = await store.get_document(session, document_id)
        if document is not None:
            await require_role_by_slug(
                session, request, project_slug=document.project_slug, min_role="viewer"
            )

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
        await require_role_by_slug(
            session, request, project_slug=document.project_slug, min_role="editor"
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
    async with session_scope() as session:
        await require_role_by_slug(
            session, request, project_slug=payload.project, min_role="viewer"
        )
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
