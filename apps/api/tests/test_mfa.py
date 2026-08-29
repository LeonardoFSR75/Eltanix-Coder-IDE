"""Segundo fator (TOTP) — `AuthService` (partes em memória) e a fiação das
rotas. O round-trip completo contra `user_mfa` no Postgres fica em
`test_mfa_store.py` sob `pg_session` (pulado sem `DATABASE_URL_TEST`).
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

os.environ["ELTANIX_API_KEY"] = "chave-de-teste"

from eltanix.auth.service import (
    MFA_CHALLENGE_TTL,
    AuthService,
    _generate_recovery_codes,
    _normalize_recovery_code,
)
from eltanix.config import get_settings
from eltanix.main import create_app

AUTH = {"Authorization": "Bearer chave-de-teste"}


# ── helpers de código de recuperação ──────────────────────────────────────


def test_recovery_codes_are_unique_hyphenated_and_countable():
    codes = _generate_recovery_codes(10)
    assert len(codes) == 10
    assert len(set(codes)) == 10
    for c in codes:
        assert len(c) == 9 and c[4] == "-"


def test_normalize_recovery_code_strips_hyphen_space_and_case():
    assert _normalize_recovery_code("AB1C-2D3E") == "ab1c2d3e"
    assert _normalize_recovery_code("  ab1c 2d3e ") == "ab1c2d3e"


# ── desafio de 2ª etapa (dict em memória, sem tocar no banco) ──────────────


@pytest.mark.asyncio
async def test_mfa_challenge_is_single_use():
    svc = AuthService()
    uid = uuid.uuid4()
    token = svc.create_mfa_challenge(uid)
    assert token in svc._mfa_challenges
    # 1º consumo remove o token; um 2º `complete_mfa_login` não acha nada.
    svc._mfa_challenges.pop(token)
    assert await svc.complete_mfa_login(mfa_token=token, code="123456") is None


@pytest.mark.asyncio
async def test_mfa_challenge_expires():
    svc = AuthService()
    uid = uuid.uuid4()
    token = svc.create_mfa_challenge(uid)
    # força a expiração para o passado
    svc._mfa_challenges[token] = (uid, datetime.now(UTC) - timedelta(seconds=1))
    assert await svc.complete_mfa_login(mfa_token=token, code="123456") is None
    assert token not in svc._mfa_challenges  # consumido mesmo expirado


@pytest.mark.asyncio
async def test_unknown_mfa_token_returns_none():
    svc = AuthService()
    assert await svc.complete_mfa_login(mfa_token="nao-existe", code="123456") is None


def test_prune_drops_only_expired_challenges():
    svc = AuthService()
    vivo = svc.create_mfa_challenge(uuid.uuid4())
    morto = svc.create_mfa_challenge(uuid.uuid4())
    svc._mfa_challenges[morto] = (uuid.uuid4(), datetime.now(UTC) - timedelta(minutes=1))
    svc._prune_mfa_challenges()
    assert vivo in svc._mfa_challenges
    assert morto not in svc._mfa_challenges


def test_challenge_ttl_is_short():
    assert MFA_CHALLENGE_TTL <= timedelta(minutes=10)


# ── fiação das rotas: login em 2 etapas + endpoints exigem sessão ──────────


class _FakeUser:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.username = "alice"
        self.display_name = "Alice"
        self.is_admin = False
        self.is_active = True
        self.password_hash = "x"
        self.created_at = datetime.now(UTC)


class _FakeAuthService:
    """Só o suficiente para exercitar `api/routes/auth.py` sem Postgres."""

    def __init__(self, *, mfa_enabled: bool) -> None:
        self.user = _FakeUser()
        self._mfa_enabled = mfa_enabled
        self.challenges: dict[str, uuid.UUID] = {}
        self.completed_with: list[str] = []

    async def check_and_register_attempt(self, ip, redis=None):
        return True

    async def check_and_register_user_attempt(self, username, redis=None):
        return True

    async def reset_user_attempts(self, username, redis=None):
        return None

    async def reset_failed_attempts(self, ip, redis=None):
        return None

    async def validate_session(self, token):
        # Nenhum teste aqui exercita um cookie de sessão real — os endpoints
        # de gestão de MFA devem responder 401 sem sessão.
        return None

    async def authenticate(self, *, username, password):
        return self.user if (username == "alice" and password == "correct-horse") else None

    async def is_mfa_enabled(self, user_id):
        return self._mfa_enabled

    def create_mfa_challenge(self, user_id):
        tok = f"chal-{len(self.challenges)}"
        self.challenges[tok] = user_id
        return tok

    async def create_session(self, *, user_id, user_agent=None):
        return "sess-token", datetime.now(UTC) + timedelta(days=14)

    async def complete_mfa_login(self, *, mfa_token, code, user_agent=None):
        self.completed_with.append(code)
        if mfa_token in self.challenges and code == "123456":
            return "sess-token", datetime.now(UTC) + timedelta(days=14)
        return None


@pytest.fixture(scope="module")
def client():
    get_settings.cache_clear()
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_auth(client):
    """Cada teste começa com um fake limpo em `app.state.auth` — o fixture do
    client é de módulo (o `lifespan` real custa minutos), então o estado não
    pode vazar entre testes."""
    client.app.state.auth = _FakeAuthService(mfa_enabled=False)
    yield


def test_login_without_mfa_returns_a_session_token(client):
    client.app.state.auth = _FakeAuthService(mfa_enabled=False)
    r = client.post("/api/auth/login", json={"username": "alice", "password": "correct-horse"})
    assert r.status_code == 200
    body = r.json()
    assert body["token"] == "sess-token"
    assert "mfa_required" not in body


def test_login_with_mfa_returns_a_challenge_not_a_session(client):
    client.app.state.auth = _FakeAuthService(mfa_enabled=True)
    r = client.post("/api/auth/login", json={"username": "alice", "password": "correct-horse"})
    assert r.status_code == 200
    body = r.json()
    assert body["mfa_required"] is True
    assert body["mfa_token"] == "chal-0"
    assert "token" not in body


def test_login_mfa_exchanges_a_valid_code_for_a_session(client):
    fake = _FakeAuthService(mfa_enabled=True)
    client.app.state.auth = fake
    client.post("/api/auth/login", json={"username": "alice", "password": "correct-horse"})

    ok = client.post("/api/auth/login/mfa", json={"mfa_token": "chal-0", "code": "123456"})
    assert ok.status_code == 200
    assert ok.json()["token"] == "sess-token"

    bad = client.post("/api/auth/login/mfa", json={"mfa_token": "chal-0", "code": "000000"})
    assert bad.status_code == 401


def test_login_mfa_route_is_reachable_without_credentials(client):
    # é a 2ª etapa do login — não pode exigir sessão (que ainda não existe)
    client.app.state.auth = _FakeAuthService(mfa_enabled=True)
    r = client.post("/api/auth/login/mfa", json={"mfa_token": "x", "code": "y"})
    assert r.status_code in (401, 422)  # 401 = código inválido, nunca 403/redirect


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/auth/mfa/status"),
        ("post", "/api/auth/mfa/setup"),
        ("get", "/api/auth/mfa/qr.svg"),
        ("post", "/api/auth/mfa/activate"),
        ("post", "/api/auth/mfa/disable"),
        ("post", "/api/auth/mfa/recovery-codes"),
        ("get", "/api/auth/sessions"),
        ("delete", "/api/auth/sessions/00000000-0000-0000-0000-000000000000"),
    ],
)
def test_mfa_management_endpoints_require_authentication(client, method, path):
    assert getattr(client, method)(path).status_code == 401


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/api/auth/mfa/setup"),
        ("get", "/api/auth/mfa/qr.svg"),
    ],
)
def test_mfa_endpoints_reject_the_service_api_key(client, method, path):
    # chave de serviço passa no AuthDep mas não tem cookie de sessão -> 401
    r = getattr(client, method)(path, headers=AUTH)
    assert r.status_code == 401
