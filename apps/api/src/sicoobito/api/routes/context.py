"""Rotas de indexação e busca de contexto."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from sicoobito.api.deps import AuthDep, SettingsDep
from sicoobito.context import store as context_store
from sicoobito.context.indexer import ContextIndexer
from sicoobito.context.repomap import DEFAULT_TOKEN_BUDGET, build_repo_map
from sicoobito.db.session import session_scope
from sicoobito.workspace import projects as project_ops
from sicoobito.workspace.projects import ProjectError

router = APIRouter(prefix="/api/context", tags=["context"], dependencies=[AuthDep])


def _indexer(request: Request) -> ContextIndexer:
    indexer: ContextIndexer | None = getattr(request.app.state, "indexer", None)
    if indexer is None:  # pragma: no cover - só ocorre se o lifespan falhar
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Indexador não inicializado."
        )
    return indexer


def _resolve_root(settings: SettingsDep, project: str | None) -> Path:
    """Resolve a raiz do projeto a indexar.

    Só nomes de projeto são aceitos, nunca caminhos: aceitar caminho arbitrário
    do corpo da requisição deixaria qualquer diretório da máquina indexável por
    quem alcançasse a API.
    """
    raiz = settings.effective_projects_root
    if raiz is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Defina PROJECTS_ROOT para indexar projetos.",
        )
    if not project:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Informe o projeto a indexar.",
        )
    try:
        return project_ops.resolve(Path(raiz), project)
    except ProjectError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


class IndexRequest(BaseModel):
    project: str
    # `force` reindexa tudo, ignorando o hash. Útil depois de trocar o modelo de
    # embedding, quando os vetores antigos deixam de ser comparáveis.
    force: bool = False


@router.post("/index")
async def index_workspace(
    payload: IndexRequest, request: Request, settings: SettingsDep
) -> dict[str, Any]:
    root = _resolve_root(settings, payload.project)
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
    project: str
    limit: int = Field(default=12, ge=1, le=50)
    path_prefix: str | None = None
    # O conteúdo completo do chunk é grande; por padrão devolvemos só o
    # suficiente para o humano decidir se quer abrir.
    include_content: bool = True


@router.post("/search")
async def search(payload: SearchRequest, request: Request, settings: SettingsDep) -> dict[str, Any]:
    root = _resolve_root(settings, payload.project)
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
async def status_(request: Request, settings: SettingsDep, project: str) -> dict[str, Any]:
    root = _resolve_root(settings, project)
    stats = await _indexer(request).stats(root)
    return {"workspace": str(root), **stats}


@router.get("/repomap")
async def repomap(
    request: Request,
    settings: SettingsDep,
    project: str,
    token_budget: int = Query(default=DEFAULT_TOKEN_BUDGET, ge=200, le=32000),
) -> dict[str, Any]:
    root = _resolve_root(settings, project)
    workspace = _indexer(request).workspace_key(root)
    return await build_repo_map(workspace, token_budget=token_budget)


@router.get("/graph")
async def graph(
    request: Request,
    settings: SettingsDep,
    project: str,
    path: str = Query(min_length=1),
    symbol: str | None = None,
    line: int | None = None,
) -> dict[str, Any]:
    """Vizinhança de 1 hop de um símbolo no Code Knowledge Graph.

    Sem `symbol`/`line`, devolve o chunk `module` do arquivo (onde vivem os
    imports do topo) — o suficiente para responder "o que este arquivo
    importa" e "quem importa este arquivo" sem apontar para um símbolo.
    """
    root = _resolve_root(settings, project)
    workspace = _indexer(request).workspace_key(root)

    async with session_scope() as session:
        result = await context_store.code_graph(
            session, workspace=workspace, path=path, symbol=symbol, line=line
        )

    if result.chunk is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Nenhum chunk indexado em {path!r}."
        )

    def _node(chunk: Any) -> dict[str, Any]:
        return {
            "path": chunk.path,
            "symbol": chunk.symbol,
            "parent": chunk.parent,
            "kind": chunk.kind,
            "start_line": chunk.start_line,
            "end_line": chunk.end_line,
        }

    return {
        "node": _node(result.chunk),
        "contains": [_node(c) for c in result.contains],
        "contained_by": _node(result.contained_by) if result.contained_by else None,
        "imports": result.imports,
        "imported_by": result.imported_by,
    }
