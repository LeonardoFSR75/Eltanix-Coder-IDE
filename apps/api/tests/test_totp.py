"""TOTP/HOTP stdlib (`auth/totp.py`) — RFC 6238/4226 sem dependência externa."""

from __future__ import annotations

import base64
import time

import pytest

from eltanix.auth import totp

# Vetores de teste do RFC 4226 (Appendix D) — segredo ASCII "12345678901234567890".
_RFC4226_SECRET = base64.b32encode(b"12345678901234567890").decode()
_RFC4226_HOTP = {
    0: "755224",
    1: "287082",
    2: "359152",
    3: "969429",
    4: "338314",
    5: "254676",
    6: "287922",
    7: "162583",
    8: "399871",
    9: "520489",
}


@pytest.mark.parametrize("counter,esperado", _RFC4226_HOTP.items())
def test_hotp_matches_rfc4226_vectors(counter: int, esperado: str):
    got = totp._hotp(totp._decode_secret(_RFC4226_SECRET), counter)
    assert got == esperado


def test_rfc6238_vector_sha1():
    # RFC 6238 Appendix B: T=59s, SHA1, 8 dígitos -> 94287082 (6 dígitos: 287082).
    assert totp.generate(_RFC4226_SECRET, at=59, digits=6) == "287082"


def test_generate_secret_is_base32_without_padding_160_bits():
    s = totp.generate_secret()
    assert "=" not in s
    assert len(s) == 32  # 20 bytes -> 32 chars base32
    base64.b32decode(s + "=" * (-len(s) % 8))  # não levanta


def test_verify_accepts_current_step():
    s = totp.generate_secret()
    assert totp.verify(s, totp.generate(s))


def test_verify_rejects_wrong_and_malformed_codes():
    s = totp.generate_secret()
    assert not totp.verify(s, "000000") or totp.generate(s) == "000000"
    assert not totp.verify(s, "abcdef")
    assert not totp.verify(s, "12345")
    assert not totp.verify(s, "")
    assert not totp.verify(s, "1234567")


def test_verify_window_tolerates_one_step_of_clock_drift():
    s = totp.generate_secret()
    agora = time.time()
    assert totp.verify(s, totp.generate(s, at=agora - 30), at=agora, window=1)
    assert totp.verify(s, totp.generate(s, at=agora + 30), at=agora, window=1)
    assert not totp.verify(s, totp.generate(s, at=agora - 90), at=agora, window=1)


def test_verify_is_false_for_garbage_secret():
    assert not totp.verify("not-valid-base32!!!", "123456")


def test_verify_ignores_spaces_in_the_code():
    s = totp.generate_secret()
    c = totp.generate(s)
    assert totp.verify(s, f"{c[:3]} {c[3:]}")


def test_provisioning_uri_shape():
    s = totp.generate_secret()
    uri = totp.provisioning_uri(s, account="alice@example.com")
    assert uri.startswith("otpauth://totp/Eltanix%20Coder%20IDE%3Aalice%40example.com?")
    assert f"secret={s}" in uri
    assert "algorithm=SHA1" in uri
    assert "digits=6" in uri
    assert "period=30" in uri
