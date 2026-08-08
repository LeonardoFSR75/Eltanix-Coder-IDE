"""Gravação do `request_log`.

Isolada do engine para que uma falha de banco nunca derrube um request que já
foi respondido com sucesso pelo provedor. Perder telemetria é aceitável; perder
a resposta pela qual já se pagou, não.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from sicoobito.db.models import RequestLog
from sicoobito.db.session import session_scope
from sicoobito.logging_setup import get_logger

log = get_logger(__name__)


@dataclass(slots=True)
class TelemetryEntry:
    requested_model: str
    source: str = "unknown"
    endpoint: str = "chat"
    profile: str | None = None
    resolved_model: str | None = None
    provider: str | None = None
    fallback_from: list[str] = field(default_factory=list)
    attempts: int = 1
    status: str = "ok"
    error_type: str | None = None
    error_message: str | None = None
    stream: bool = False
    latency_ms: int | None = None
    ttft_ms: int | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    usage_estimated: bool = False
    cost_usd: Decimal = Decimal(0)
    cost_known: bool = True
    cache_hit: bool = False
    tokens_saved: int = 0
    cost_saved_usd: Decimal = Decimal(0)
    savings_breakdown: dict[str, int] = field(default_factory=dict)
    complexity: str | None = None
    project_slug: str | None = None


async def record(entry: TelemetryEntry) -> None:
    try:
        async with session_scope() as session:
            session.add(
                RequestLog(
                    source=entry.source[:64],
                    endpoint=entry.endpoint[:64],
                    project_slug=entry.project_slug[:128] if entry.project_slug else None,
                    requested_model=entry.requested_model[:128],
                    profile=entry.profile[:64] if entry.profile else None,
                    resolved_model=entry.resolved_model[:128] if entry.resolved_model else None,
                    provider=entry.provider[:64] if entry.provider else None,
                    fallback_from=entry.fallback_from,
                    attempts=entry.attempts,
                    status=entry.status,
                    error_type=entry.error_type[:128] if entry.error_type else None,
                    # Mensagem de erro de provedor pode vir com corpo HTTP inteiro.
                    error_message=entry.error_message[:4000] if entry.error_message else None,
                    stream=entry.stream,
                    latency_ms=entry.latency_ms,
                    ttft_ms=entry.ttft_ms,
                    prompt_tokens=entry.prompt_tokens,
                    completion_tokens=entry.completion_tokens,
                    cache_read_tokens=entry.cache_read_tokens,
                    cache_write_tokens=entry.cache_write_tokens,
                    total_tokens=entry.prompt_tokens + entry.completion_tokens,
                    usage_estimated=entry.usage_estimated,
                    cost_usd=entry.cost_usd,
                    cost_known=entry.cost_known,
                    cache_hit=entry.cache_hit,
                    tokens_saved=entry.tokens_saved,
                    cost_saved_usd=entry.cost_saved_usd,
                    savings_breakdown=entry.savings_breakdown,
                    complexity=entry.complexity,
                )
            )
    except Exception as exc:
        log.error("telemetry.write.failed", error=str(exc), model=entry.resolved_model)
