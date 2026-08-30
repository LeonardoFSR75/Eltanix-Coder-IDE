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
from eltanix.api.deps import AdminDep, AuthDep, EngineDep, SettingsDep
from eltanix.auth.rbac import require_role_by_slug
from eltanix.context import completions as completion_engine
from eltanix.context import next_edit as next_edit_engine
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
# Next-edit dispara por edição assentada, não por tecla — cabe esperar mais.
_NEXT_EDIT_HARD_TIMEOUT_S = 4.0


async def _guard_editor_ai_rate(request: Request, *, feature: str, limit: int) -> None:
    """`INCR`+`expire` por ator numa janela de 60 s (mesmo padrão do Cmd+K em
    `agent.py::_guard_inline_edit_rate`). `feature` separa a chave por recurso
    (`completion`, `next_edit`). Redis fora → não limita (degrada, não
    derruba)."""
    redis = getattr(request.app.state, "redis", None)
    if redis is None:
        return
    ator = getattr(request.state, "actor", "unknown")
    key = f"context:{feature}:ratelimit:{ator}"
    try:
        pipe = redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, 60)
        count, _ = await pipe.execute()
    except Exception as exc:  # degradação intencional: Redis fora não barra o editor
        log.warning(
            "context.editor_ai.ratelimit_redis_failed", feature=feature, error=str(exc)[:200]
        )
        return
    if int(count) > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Muitas requisições de IA do editor em sequência; aguarde um instante.",
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

    await _guard_editor_ai_rate(
        request, feature="completion", limit=settings.ide_completion_max_per_minute
    )
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
    # inline (autocompletar, ADR 0014) | next_edit (tab to jump, ADR 0015)
    kind: Literal["inline", "next_edit"] = "inline"
    project: str | None = Field(default=None, max_length=128)
    language: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=128)
    shown_ms: int | None = Field(default=None, ge=0, le=3_600_000)
    latency_ms: int | None = Field(default=None, ge=0, le=3_600_000)
    chars_suggested: int = Field(default=0, ge=0, le=100_000)
    chars_accepted: int = Field(default=0, ge=0, le=100_000)
    # Só do next_edit: distância em linhas do cursor até o trecho previsto.
    jump_lines: int | None = Field(default=None, ge=0, le=1_000_000)


# Não liga a nenhum `Settings.ide_*_max_per_minute` de propósito: cada evento
# de outcome corresponde a UMA sugestão já mostrada (accepted/ignored), então
# está naturalmente limitado pela soma dos tetos de `completion` + `next_edit`
# — isto aqui só é o teto absoluto contra alguém martelando o endpoint com
# `suggestion_id` inventado pra inflar `completion_event` sem nunca ter
# pedido uma sugestão de verdade.
_COMPLETION_OUTCOME_MAX_PER_MINUTE = 200


@router.post("/completions/outcome", status_code=status.HTTP_202_ACCEPTED)
async def completion_outcome(payload: CompletionOutcome, request: Request) -> dict[str, Any]:
    """Desfecho de uma sugestão (`accepted`/`rejected`/`ignored`) — o número que
    diz se o recurso presta. Cobre autocompletar (`kind=inline`) e next-edit
    (`kind=next_edit`). Best-effort: nunca falha o editor por causa de
    telemetria de aceitação. Não grava conteúdo, só contagens."""
    await _guard_editor_ai_rate(
        request, feature="completion_outcome", limit=_COMPLETION_OUTCOME_MAX_PER_MINUTE
    )
    ator = getattr(request.state, "actor", None)
    try:
        async with session_scope() as session:
            session.add(
                CompletionEvent(
                    suggestion_id=payload.suggestion_id,
                    kind=payload.kind,
                    actor=ator,
                    project_slug=payload.project,
                    language=payload.language,
                    model=payload.model,
                    outcome=payload.outcome,
                    shown_ms=payload.shown_ms,
                    latency_ms=payload.latency_ms,
                    chars_suggested=payload.chars_suggested,
                    chars_accepted=payload.chars_accepted,
                    jump_lines=payload.jump_lines,
                )
            )
    except Exception as exc:  # telemetria best-effort
        log.warning("context.completion.outcome_persist_failed", error=str(exc)[:200])
    return {"ok": True}


@router.get("/completions/stats", dependencies=[AdminDep])
async def completion_stats(
    request: Request, days: int = Query(default=7, ge=1, le=90)
) -> dict[str, Any]:
    """Taxa de aceitação do autocompletar, derivada de `completion_event`.

    Agrega TODOS os projetos (não recebe `project` nem filtra por RBAC de
    projeto) — por isso `AdminDep`: sem essa restrição, qualquer sessão
    autenticada em qualquer projeto enxergava a telemetria de aceitação do
    editor da instância inteira."""
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

        by_kind = (
            await session.execute(
                select(
                    CompletionEvent.kind,
                    func.count(CompletionEvent.id),
                    _accepted,
                    func.avg(CompletionEvent.latency_ms),
                )
                .where(CompletionEvent.created_at >= since)
                .group_by(CompletionEvent.kind)
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
        "by_kind": [
            {
                "kind": kind,
                "suggestions": int(count),
                "accepted": int(acc),
                "acceptance_rate": round(int(acc) / int(count), 4) if count else 0.0,
                "avg_latency_ms": int(lat) if lat is not None else None,
            }
            for kind, count, acc, lat in by_kind
        ],
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


# ── Predição do próximo edit / "tab to jump" (Onda 1.2, ADR 0015) ───────────


class RecentEdit(BaseModel):
    path: str = Field(min_length=1, max_length=512)
    diff: str = Field(default="", max_length=4000)


class NextEditRequest(BaseModel):
    project: str = Field(min_length=1)
    path: str = Field(min_length=1)
    file_content: str = Field(min_length=1, max_length=200_000)
    cursor_line: int = Field(ge=1)
    recent_edits: list[RecentEdit] = Field(default_factory=list, max_length=20)
    language: str | None = Field(default=None, max_length=64)


@router.post("/next-edit")
async def next_edit(
    payload: NextEditRequest,
    request: Request,
    settings: SettingsDep,
    engine: EngineDep,
) -> Any:
    """Prevê **um** próximo edit no arquivo aberto (ADR 0015).

    READ-only: nunca escreve — a aplicação acontece no cliente no segundo
    `Tab`. `found: false` e toda falha (kill switch, modelo fora, timeout,
    resposta fora do formato, intervalo inválido) degradam para `204`, igual
    ao autocompletar.
    """
    if not settings.ide_next_edit_enabled:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    await _guard_editor_ai_rate(
        request, feature="next_edit", limit=settings.ide_next_edit_max_per_minute
    )
    await _check_project_access(request, payload.project, min_role="viewer")

    window, base_line = next_edit_engine.select_window(payload.file_content, payload.cursor_line)
    numbered = next_edit_engine.number_lines(window, start=base_line)
    messages = next_edit_engine.build_messages(
        numbered_file=numbered,
        cursor_line=payload.cursor_line,
        recent_edits=[e.model_dump() for e in payload.recent_edits],
    )
    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(
            await_or_abandon_on_disconnect(
                request,
                engine.complete(
                    requested_model=settings.ide_next_edit_profile,
                    params={
                        "messages": messages,
                        "temperature": 0,
                        "max_tokens": next_edit_engine.MAX_TOKENS,
                    },
                    source="ide:next_edit",
                ),
            ),
            timeout=_NEXT_EDIT_HARD_TIMEOUT_S,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.warning("context.next_edit.unavailable", error=str(exc)[:200])
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    predicted = next_edit_engine.predict_from_payload(
        result.payload, full_content=payload.file_content, cursor_line=payload.cursor_line
    )
    if predicted is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return {
        "found": True,
        "suggestion_id": uuid.uuid4().hex,
        "edit": {
            "path": payload.path,
            "start_line": predicted.start_line,
            "end_line": predicted.end_line,
            "old_text": predicted.old_text,
            "new_text": predicted.new_text,
            "diff": predicted.diff,
            "jump_lines": predicted.jump_lines,
        },
        "model": result.model_id,
        "latency_ms": int((time.perf_counter() - started) * 1000),
    }
