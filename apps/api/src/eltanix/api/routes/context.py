"""Rotas de indexação e busca de contexto."""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select

from eltanix.api._client_disconnect import await_or_abandon_on_disconnect
from eltanix.api.deps import AuthDep, EngineDep, SettingsDep
from eltanix.auth.rbac import require_role_by_slug
from eltanix.context import completions as completion_engine
from eltanix.context import store as context_store
from eltanix.context.indexer import ContextIndexer
from eltanix.context.repomap import DEFAULT_TOKEN_BUDGET, build_repo_map
from eltanix.db.models import CompletionEvent
from eltanix.db.session import session_scope
from eltanix.logging_setup import get_logger
from eltanix.workspace import projects as project_ops
from eltanix.workspace.projects import ProjectError

log = get_logger(__name__)

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


async def _check_project_access(request: Request, project: str, min_role: str) -> None:
    async with session_scope() as session:
        await require_role_by_slug(session, request, project_slug=project, min_role=min_role)


class IndexRequest(BaseModel):
    project: str
    # `force` reindexa tudo, ignorando o hash. Útil depois de trocar o modelo de
    # embedding, quando os vetores antigos deixam de ser comparáveis.
    force: bool = False


@router.post("/index")
async def index_workspace(
    payload: IndexRequest, request: Request, settings: SettingsDep
) -> dict[str, Any]:
    await _check_project_access(request, payload.project, min_role="editor")
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
    await _check_project_access(request, payload.project, min_role="viewer")
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
    await _check_project_access(request, project, min_role="viewer")
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
    await _check_project_access(request, project, min_role="viewer")
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
        await require_role_by_slug(session, request, project_slug=project, min_role="viewer")
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


# ── Autocompletar inline / ghost text (Onda 1.1, ADR 0014) ──────────────────

# Timeout duro do lado do servidor. Além disso a sugestão já nasceu velha — o
# usuário digitou mais e o ghost text não serve mais para aquele cursor.
_COMPLETION_HARD_TIMEOUT_S = 2.0


async def _guard_completion_rate(request: Request, limit: int) -> None:
    """`INCR`+`expire` por ator numa janela de 60 s (mesmo padrão do Cmd+K em
    `agent.py::_guard_inline_edit_rate`). Ghost text dispara muito mais, daí o
    teto mais alto. Redis fora → não limita (degrada, não derruba)."""
    redis = getattr(request.app.state, "redis", None)
    if redis is None:
        return
    ator = getattr(request.state, "actor", "unknown")
    try:
        pipe = redis.pipeline()
        pipe.incr(f"context:completion:ratelimit:{ator}")
        pipe.expire(f"context:completion:ratelimit:{ator}", 60)
        count, _ = await pipe.execute()
    except Exception as exc:  # degradação intencional: Redis fora não barra o editor
        log.warning("context.completion.ratelimit_redis_failed", error=str(exc)[:200])
        return
    if int(count) > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Muitas requisições de autocompletar em sequência; aguarde um instante.",
        )


class CompletionRequest(BaseModel):
    project: str = Field(min_length=1)
    path: str = Field(min_length=1)
    # Prefixo (até o cursor) e sufixo (depois). O teto largo aqui só rejeita
    # payload absurdo; `completions.clamp_context` corta para 4000/2000 chars
    # colados no cursor antes de ir ao modelo.
    prefix: str = Field(default="", max_length=20_000)
    suffix: str = Field(default="", max_length=20_000)
    language: str | None = Field(default=None, max_length=64)


@router.post("/completions")
async def completions(
    payload: CompletionRequest,
    request: Request,
    settings: SettingsDep,
    engine: EngineDep,
) -> Any:
    """Uma sugestão de autocompletar inline na posição do cursor (ADR 0014).

    READ-only: nunca escreve arquivo, não passa por `ApprovalPolicy` — a
    inserção só acontece no cliente quando o humano aperta `Tab`. Toda falha
    (kill switch, modelo fora, timeout, resposta vazia) degrada para `204 No
    Content`: ghost text falha em silêncio, nunca com um erro visível no
    editor.
    """
    if not settings.ide_inline_completions_enabled:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    if not payload.prefix.strip() and not payload.suffix.strip():
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    await _guard_completion_rate(request, settings.ide_completion_max_per_minute)
    await _check_project_access(request, payload.project, min_role="viewer")

    messages = completion_engine.build_messages(
        prefix=payload.prefix,
        suffix=payload.suffix,
        path=payload.path,
        language=payload.language,
    )
    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(
            await_or_abandon_on_disconnect(
                request,
                engine.complete(
                    requested_model=settings.ide_completion_profile,
                    params={
                        "messages": messages,
                        "temperature": 0,
                        "max_tokens": completion_engine.MAX_TOKENS,
                    },
                    source="ide:completion",
                ),
            ),
            timeout=_COMPLETION_HARD_TIMEOUT_S,
        )
    except asyncio.CancelledError:
        # Cliente digitou de novo e abortou a request — nada a devolver.
        raise
    except Exception as exc:
        # Timeout duro, modelo fora, circuito aberto — ghost text degrada em
        # silêncio (204), nunca um erro visível no editor.
        log.warning("context.completion.unavailable", error=str(exc)[:200])
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    text = completion_engine.extract_completion(
        result.payload, prefix=payload.prefix, suffix=payload.suffix
    )
    if not text:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return {
        "completion": text,
        "suggestion_id": uuid.uuid4().hex,
        "model": result.model_id,
        "cached": result.cache_hit,
        "latency_ms": int((time.perf_counter() - started) * 1000),
    }


class CompletionOutcome(BaseModel):
    suggestion_id: str = Field(min_length=1, max_length=64)
    outcome: Literal["accepted", "rejected", "ignored"]
    project: str | None = Field(default=None, max_length=128)
    language: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=128)
    shown_ms: int | None = Field(default=None, ge=0, le=3_600_000)
    latency_ms: int | None = Field(default=None, ge=0, le=3_600_000)
    chars_suggested: int = Field(default=0, ge=0, le=100_000)
    chars_accepted: int = Field(default=0, ge=0, le=100_000)


@router.post("/completions/outcome", status_code=status.HTTP_202_ACCEPTED)
async def completion_outcome(payload: CompletionOutcome, request: Request) -> dict[str, Any]:
    """Desfecho de uma sugestão (`accepted`/`rejected`/`ignored`) — o número que
    diz se o autocompletar presta. Best-effort: nunca falha o editor por causa
    de telemetria de aceitação. Não grava prefixo/sufixo, só contagens."""
    ator = getattr(request.state, "actor", None)
    try:
        async with session_scope() as session:
            session.add(
                CompletionEvent(
                    suggestion_id=payload.suggestion_id,
                    actor=ator,
                    project_slug=payload.project,
                    language=payload.language,
                    model=payload.model,
                    outcome=payload.outcome,
                    shown_ms=payload.shown_ms,
                    latency_ms=payload.latency_ms,
                    chars_suggested=payload.chars_suggested,
                    chars_accepted=payload.chars_accepted,
                )
            )
    except Exception as exc:  # telemetria best-effort
        log.warning("context.completion.outcome_persist_failed", error=str(exc)[:200])
    return {"ok": True}


@router.get("/completions/stats")
async def completion_stats(
    request: Request, days: int = Query(default=7, ge=1, le=90)
) -> dict[str, Any]:
    """Taxa de aceitação do autocompletar, derivada de `completion_event`."""
    since = datetime.now(UTC) - timedelta(days=days)
    _accepted = func.coalesce(
        func.sum(case((CompletionEvent.outcome == "accepted", 1), else_=0)), 0
    )
    async with session_scope() as session:
        total, accepted, ignored, rejected, sug_chars, acc_chars, avg_latency, avg_shown = (
            await session.execute(
                select(
                    func.count(CompletionEvent.id),
                    _accepted,
                    func.coalesce(
                        func.sum(case((CompletionEvent.outcome == "ignored", 1), else_=0)), 0
                    ),
                    func.coalesce(
                        func.sum(case((CompletionEvent.outcome == "rejected", 1), else_=0)), 0
                    ),
                    func.coalesce(func.sum(CompletionEvent.chars_suggested), 0),
                    func.coalesce(func.sum(CompletionEvent.chars_accepted), 0),
                    func.avg(CompletionEvent.latency_ms),
                    func.avg(CompletionEvent.shown_ms),
                ).where(CompletionEvent.created_at >= since)
            )
        ).one()

        by_lang = (
            await session.execute(
                select(
                    CompletionEvent.language,
                    func.count(CompletionEvent.id),
                    _accepted,
                )
                .where(CompletionEvent.created_at >= since)
                .group_by(CompletionEvent.language)
                .order_by(func.count(CompletionEvent.id).desc())
            )
        ).all()

    total = int(total)
    sug_chars = int(sug_chars)
    return {
        "window_days": days,
        "suggestions": total,
        "accepted": int(accepted),
        "ignored": int(ignored),
        "rejected": int(rejected),
        "acceptance_rate": round(int(accepted) / total, 4) if total else 0.0,
        "chars_suggested": sug_chars,
        "chars_accepted": int(acc_chars),
        "char_acceptance_rate": round(int(acc_chars) / sug_chars, 4) if sug_chars else 0.0,
        "avg_latency_ms": int(avg_latency) if avg_latency is not None else None,
        "avg_shown_ms": int(avg_shown) if avg_shown is not None else None,
        "by_language": [
            {
                "language": lang,
                "suggestions": int(count),
                "accepted": int(acc),
                "acceptance_rate": round(int(acc) / int(count), 4) if count else 0.0,
            }
            for lang, count, acc in by_lang
        ],
    }
