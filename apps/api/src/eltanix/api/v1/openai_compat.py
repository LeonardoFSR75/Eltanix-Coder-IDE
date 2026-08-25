"""Fachada OpenAI-compatible.

Não é um detalhe de implementação: é o que faz Cline, Continue, Aider e Claude
Code funcionarem contra o gateway sem nenhuma adaptação. Toda a lógica está no
`RouterEngine`; aqui só há tradução de protocolo.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from eltanix.api.deps import ActorDep, AuthDep, EngineDep, ProjectDep, SourceDep
from eltanix.api.schemas import ChatCompletionRequest, EmbeddingRequest, ModelCard, ModelList
from eltanix.api.sse import SSE_DONE, sse_event
from eltanix.logging_setup import get_logger
from eltanix.router.budget import BudgetExceededError
from eltanix.router.errors import AllCandidatesFailedError, NoCandidatesError

log = get_logger(__name__)

router = APIRouter(prefix="/v1", tags=["openai"], dependencies=[AuthDep])


def _error_body(message: str, err_type: str, code: str | None = None) -> dict[str, Any]:
    """Formato de erro da OpenAI — clientes fazem parsing disto."""
    return {"error": {"message": _truncate(message), "type": err_type, "param": None, "code": code}}


def _truncate(text: str, limit: int = 300) -> str:
    """Mesmo limite de `router/engine.py` para exceções logadas — mensagens de
    erro de SDK/provedor não truncadas podem incluir `api_base`, corpo de
    resposta ou outros detalhes de infraestrutura interna que não devem
    vazar para fora da API."""
    texto = str(text)
    return texto if len(texto) <= limit else f"{texto[:limit]}…"


@router.get("/models", response_model=ModelList)
async def list_models(engine: EngineDep) -> ModelList:
    cards = [
        ModelCard(
            id=spec.id,
            context_window=spec.context_window,
            tags=spec.tags,
            capabilities=spec.capabilities,
            available=spec.usable,
            unavailable_reason=spec.unavailable_reason,
            owned_by=spec.provider,
        )
        for spec in engine.catalog.models.values()
    ]
    # Perfis também aparecem como "modelos": é assim que o cliente pede `auto/cheap`
    # num campo que só aceita um nome de modelo.
    cards.extend(
        ModelCard(
            id=f"auto/{name}" if name != "auto" else "auto",
            owned_by="eltanix-router",
            tags=["profile", profile.strategy],
            capabilities=["chat"],
            available=bool(profile.models),
        )
        for name, profile in engine.catalog.profiles.items()
    )
    return ModelList(data=cards)


@router.post("/chat/completions")
async def chat_completions(
    payload: ChatCompletionRequest,
    engine: EngineDep,
    source: SourceDep,
    project: ProjectDep,
    actor: ActorDep,
):
    params = payload.to_params()

    try:
        if payload.stream:
            return StreamingResponse(
                _sse(engine, payload.model, params, source, project, actor),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        result = await engine.complete(
            requested_model=payload.model,
            params=params,
            source=source,
            project_slug=project,
            actor=actor,
        )
    except BudgetExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=_error_body(str(exc), "budget_exceeded"),
        ) from exc
    except NoCandidatesError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_error_body(
                f"{exc} Motivos: {'; '.join(exc.excluded) or 'nenhum'}",
                "no_candidates",
            ),
        ) from exc
    except AllCandidatesFailedError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_error_body(f"{exc}. Último erro: {exc.last_error}", "upstream_error"),
        ) from exc
    except Exception as exc:
        log.error("chat.failed", error=str(exc), error_type=type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_error_body(str(exc), type(exc).__name__),
        ) from exc

    # Devolve o id do catálogo, não o nome interno do provedor: é o que o cliente
    # reconhece e o que ele pode pedir de volta explicitamente.
    body = dict(result.payload)
    body["model"] = result.model_id
    body["x_eltanix"] = {
        "provider": result.provider,
        "cache_hit": result.cache_hit,
        "cost_usd": float(result.cost_usd),
        "cost_known": result.cost_known,
        "latency_ms": result.latency_ms,
        "fallback_from": result.fallback_from,
        "usage_estimated": result.usage.estimated,
    }
    return body


async def _sse(
    engine: Any,
    requested_model: str,
    params: dict[str, Any],
    source: str,
    project: str | None = None,
    actor: str | None = None,
) -> AsyncIterator[str]:
    try:
        async for chunk in engine.stream(
            requested_model=requested_model,
            params=params,
            source=source,
            project_slug=project,
            actor=actor,
        ):
            yield sse_event(chunk, default=str)
    except (NoCandidatesError, AllCandidatesFailedError, BudgetExceededError) as exc:
        # O status HTTP já foi 200 quando o stream abriu; o único canal de erro
        # que resta é um evento no próprio stream.
        yield sse_event(_error_body(str(exc), type(exc).__name__))
    except Exception as exc:
        log.error("stream.failed", error=str(exc), error_type=type(exc).__name__)
        yield sse_event(_error_body(str(exc), type(exc).__name__))
    finally:
        yield SSE_DONE


@router.post("/embeddings")
async def embeddings(
    payload: EmbeddingRequest,
    engine: EngineDep,
    source: SourceDep,
    project: ProjectDep,
    actor: ActorDep,
):
    try:
        result = await engine.embed(
            requested_model=payload.model,
            inputs=payload.inputs(),
            source=source,
            project_slug=project,
            actor=actor,
        )
    except NoCandidatesError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_error_body(str(exc), "no_candidates"),
        ) from exc
    except AllCandidatesFailedError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_error_body(f"{exc}. Último erro: {exc.last_error}", "upstream_error"),
        ) from exc

    body = dict(result.payload)
    body["model"] = result.model_id
    return body


@router.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "timestamp": int(time.time())}
