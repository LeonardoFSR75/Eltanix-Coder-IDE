"""Testes da integração de observabilidade com Langfuse."""

from unittest.mock import MagicMock, patch

import pytest
from sicoobito.config import Settings
from sicoobito.telemetry.langfuse_tracer import (
    flush_langfuse,
    get_langfuse_callback,
    is_langfuse_configured,
)


def test_is_langfuse_configured_default_empty():
    settings = Settings(
        LANGFUSE_PUBLIC_KEY="",
        LANGFUSE_SECRET_KEY="",
        LANGFUSE_ENABLED=True,
    )
    assert is_langfuse_configured(settings) is False


def test_is_langfuse_configured_when_disabled():
    settings = Settings(
        LANGFUSE_PUBLIC_KEY="pk-lf-12345",
        LANGFUSE_SECRET_KEY="sk-lf-12345",
        LANGFUSE_ENABLED=False,
    )
    assert is_langfuse_configured(settings) is False


def test_is_langfuse_configured_when_valid():
    settings = Settings(
        LANGFUSE_PUBLIC_KEY="pk-lf-12345",
        LANGFUSE_SECRET_KEY="sk-lf-12345",
        LANGFUSE_ENABLED=True,
    )
    assert is_langfuse_configured(settings) is True


def test_get_langfuse_callback_returns_none_when_unconfigured():
    settings = Settings(
        LANGFUSE_PUBLIC_KEY="",
        LANGFUSE_SECRET_KEY="",
    )
    handler = get_langfuse_callback(session_id="sess-123", settings=settings)
    assert handler is None


def test_get_langfuse_callback_graceful_on_exception():
    settings = Settings(
        LANGFUSE_PUBLIC_KEY="pk-lf-12345",
        LANGFUSE_SECRET_KEY="sk-lf-12345",
        LANGFUSE_ENABLED=True,
    )
    mock_cls = MagicMock(side_effect=Exception("Connection refused"))
    with patch("sicoobito.telemetry.langfuse_tracer.is_langfuse_configured", return_value=True):
        with patch("sicoobito.telemetry.langfuse_tracer._get_callback_class", return_value=mock_cls):
            handler = get_langfuse_callback(session_id="sess-123", settings=settings)
            assert handler is None


def test_flush_langfuse_does_not_raise():
    # Deve executar e encerrar sem exceções (degradação graciosa)
    flush_langfuse()
