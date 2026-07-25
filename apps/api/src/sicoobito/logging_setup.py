"""Configuração do structlog, com redação de segredos."""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

import structlog

# Chaves cujo valor nunca deve aparecer em log, em qualquer nível de aninhamento.
_SECRET_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "token",
    "password",
    "secret",
    "databricks_token",
    "azure_api_key",
    "openai_api_key",
    "anthropic_api_key",
    "github_token",
}

_BEARER_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.IGNORECASE)
_REDACTED = "***"


def _redact(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return value
    if isinstance(value, dict):
        return {
            k: (_REDACTED if k.lower() in _SECRET_KEYS else _redact(v, depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(v, depth + 1) for v in value]
    if isinstance(value, str):
        return _BEARER_RE.sub(r"\1" + _REDACTED, value)
    return value


def _redact_processor(_logger: Any, _name: str, event_dict: dict) -> dict:
    return _redact(event_dict)  # type: ignore[return-value]


def setup_logging(level: str = "INFO", as_json: bool = False) -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
    )
    # O litellm é falante demais em INFO; o que interessa dele nós já logamos.
    logging.getLogger("LiteLLM").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    renderer = (
        structlog.processors.JSONRenderer()
        if as_json
        else structlog.dev.ConsoleRenderer(colors=not as_json)
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _redact_processor,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> Any:
    return structlog.get_logger(name)
