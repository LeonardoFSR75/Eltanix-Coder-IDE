"""Rotas de indexação e busca de contexto."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from sicoobito.api.deps import AuthDep, SettingsDep
from sicoobito.context.indexer import ContextIndexer
from sicoobito.context.repomap import DEFAULT_TOKEN_BUDGET, build_repo_map

router = APIRouter(prefix="/api/context", tags=["context"], dependencies=[AuthDep])


def _indexer(request: Request) -> ContextIndexer:
    indexer: ContextIndexer | None = getattr(request.app.state, "indexer", None)
    if indexer is None:  # pragma: no cover - só ocorre se o lifespan falhar
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Indexador não inicializado."
        )
    return indexer


def _resolve_root(settings: SettingsDep, requested: str | None) -> Path:
    """Resolve a raiz do workspace.

    Sem `WORKSPACE_ROOT` configurado, aceitar um caminho arbitrário do corpo da
    requisição deixaria qualquer diretório da máquina indexável por quem
    alcançasse a API. Com ele configurado, o caminho pedido precisa estar dentro.
    """
    configured = settings.workspace_root

    if requested is None:
        if configured is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Defina WORKSPACE_ROOT ou informe `path` explicitamente.",
            )
        return Path(configured).resolve()

    candidate = Path(requested).expanduser().resolve()
    if configured is not None:
        root = Path(configured).resolve()
        if not candidate.is_relative_to(root):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Caminho fora de WORKSPACE_ROOT ({root}).",
            )
    return candidate


class IndexRequest(BaseModel):
    path: str | None = None
    # `force` reindexa tudo, ignorando o hash. Útil depois de trocar o modelo de
    # embedding, quando os vetores antigos deixam de ser comparáveis.
    force: bool = False


@router.post("/index")
async def index_workspace(
    payload: IndexRequest, request: Request, settings: SettingsDep
) -> dict[str, Any]:
    root = _resolve_root(settings, payload.path)
    report = await _indexer(request).index_workspace(root, force=payload.force)
    return {
        "workspace": report.workspace,
        "scanned": report.scanned,
        "indexed": report.indexed,
        "skipped_unchanged": report.skipped_unchanged,
        "removed": report.removed,
        "chunks": report.chunks,
        "embedded": report.embedded,
        "embedding_failures": report.embedding_failures,
        "duration_ms": report.duration_ms,
        "errors": report.errors,
    }


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    path: str | None = None
    limit: int = Field(default=12, ge=1, le=50)
    path_prefix: str | None = None
    # O conteúdo completo do chunk é grande; por padrão devolvemos só o
    # suficiente para o humano decidir se quer abrir.
    include_content: bool = True


@router.post("/search")
async def search(
    payload: SearchRequest, request: Request, settings: SettingsDep
) -> dict[str, Any]:
    root = _resolve_root(settings, payload.path)
    hits = await _indexer(request).search(
        root=root, query=payload.query, limit=payload.limit, path_prefix=payload.path_prefix
    )
    return {
        "query": payload.query,
        "hits": [
            {
                "path": hit.path,
                "citation": hit.citation,
                "symbol": hit.symbol,
                "parent": hit.parent,
                "kind": hit.kind,
                "start_line": hit.start_line,
                "end_line": hit.end_line,
                "language": hit.language,
                "token_count": hit.token_count,
                "score": round(hit.score, 6),
                "vector_rank": hit.vector_rank,
                "text_rank": hit.text_rank,
                "content": hit.content if payload.include_content else None,
            }
            for hit in hits
        ],
    }


@router.get("/status")
async def status_(
    request: Request, settings: SettingsDep, path: str | None = None
) -> dict[str, Any]:
    root = _resolve_root(settings, path)
    stats = await _indexer(request).stats(root)
    return {"workspace": str(root), **stats}


@router.get("/repomap")
async def repomap(
    request: Request,
    settings: SettingsDep,
    path: str | None = None,
    token_budget: int = Query(default=DEFAULT_TOKEN_BUDGET, ge=200, le=32000),
) -> dict[str, Any]:
    root = _resolve_root(settings, path)
    workspace = _indexer(request).workspace_key(root)
    return await build_repo_map(workspace, token_budget=token_budget)
