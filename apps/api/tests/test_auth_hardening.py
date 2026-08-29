"""Follow-ups da revisão de segurança (docs/security_review_2026-08.md):
F-3 (saneamento de CORS_ORIGINS), F-4 (rate limit por username).
As partes que tocam o banco (F-5, lista/revoga sessão) ficam em
`test_auth.py`/pg_session.
"""

from __future__ import annotations

import warnings

import pytest

from eltanix.auth.service import AuthService
from eltanix.config import Settings

# ── F-3: CORS_ORIGINS ─────────────────────────────────────────────────────


def test_cors_origins_drops_wildcard_and_warns():
    with pytest.warns(UserWarning, match=r"\*"):
        s = Settings(CORS_ORIGINS="*,http://localhost:5400")
    assert "*" not in s.cors_origins
    assert "http://localhost:5400" in s.cors_origins


def test_cors_origins_warns_on_non_loopback_origin():
    with pytest.warns(UserWarning, match="não-loopback"):
        s = Settings(CORS_ORIGINS="https://ide.example.com")
    assert s.cors_origins == ["https://ide.example.com"]  # não descartada, só avisada


def test_cors_origins_loopback_list_is_silent():
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # qualquer warning vira erro
        s = Settings(CORS_ORIGINS="http://localhost:5400,http://127.0.0.1:5400")
    assert len(s.cors_origins) == 2


# ── F-4: rate limit por username (fallback em memória) ─────────────────────


@pytest.mark.asyncio
async def test_user_rate_limit_blocks_after_the_limit():
    svc = AuthService()
    limite = AuthService._USER_ATTEMPT_LIMIT
    for _ in range(limite):
        assert await svc.check_and_register_user_attempt("alice") is True
    # a (limite+1)-ésima tentativa é barrada
    assert await svc.check_and_register_user_attempt("alice") is False


@pytest.mark.asyncio
async def test_user_rate_limit_is_per_username_and_case_insensitive():
    svc = AuthService()
    for _ in range(AuthService._USER_ATTEMPT_LIMIT):
        await svc.check_and_register_user_attempt("Alice")
    assert await svc.check_and_register_user_attempt("alice") is False  # mesma conta
    assert await svc.check_and_register_user_attempt("bob") is True  # conta diferente


@pytest.mark.asyncio
async def test_reset_user_attempts_clears_the_counter():
    svc = AuthService()
    for _ in range(AuthService._USER_ATTEMPT_LIMIT):
        await svc.check_and_register_user_attempt("carol")
    assert await svc.check_and_register_user_attempt("carol") is False
    await svc.reset_user_attempts("carol")
    assert await svc.check_and_register_user_attempt("carol") is True
