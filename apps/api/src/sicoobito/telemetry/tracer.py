"""Módulo de Telemetria e Tracing para o SicoobitoCode.

Fornece rastreamento estruturado de spankeys de execução, medição de latência p95
e observabilidade de roteamento de LLMs.
"""

from __future__ import annotations

import time
import structlog
from typing import Any, Callable

log = structlog.get_logger(__name__)


class TelemetryTracer:
    """Tracer estruturado de operações e chamadas a modelos."""

    @staticmethod
    def trace_span(op_name: str, **attributes: Any) -> Callable:
        def decorator(func: Callable) -> Callable:
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                start_time = time.perf_counter()
                status = "ok"
                try:
                    res = await func(*args, **kwargs)
                    return res
                except Exception as exc:
                    status = "error"
                    log.error("telemetry.span.error", op=op_name, error=str(exc), **attributes)
                    raise
                finally:
                    latency_ms = (time.perf_counter() - start_time) * 1000.0
                    log.info(
                        "telemetry.span.complete",
                        op=op_name,
                        latency_ms=round(latency_ms, 2),
                        status=status,
                        **attributes,
                    )
            return wrapper
        return decorator
