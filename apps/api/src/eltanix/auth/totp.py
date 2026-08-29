"""TOTP (RFC 6238) e HOTP (RFC 4226) em stdlib puro.

Sem `pyotp`/`otpauth` de propósito — são ~40 linhas de `hmac`+`struct`, e o
projeto evita dependência que não seja Python puro (ver o teto do `litellm` no
`pyproject.toml`). O QR de provisionamento é gerado à parte com `segno` (que é
Python puro).

Contrato:
  - `generate_secret()` → segredo base32 (sem padding) de 160 bits.
  - `verify(secret, code, *, window=1)` → `True` se `code` casa com o passo
    atual ou com `window` passos antes/depois (tolerância a relógio dessincronizado).
  - `provisioning_uri(secret, account, issuer)` → `otpauth://totp/...` para o QR.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

_PERIOD = 30  # segundos por passo — padrão de fato dos apps autenticadores
_DIGITS = 6
_ALGO = "SHA1"  # o que Google Authenticator / Aegis / 1Password assumem por padrão


def generate_secret() -> str:
    """Base32 sem padding (`=`), como os apps autenticadores esperam colar."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _decode_secret(secret: str) -> bytes:
    # Aceita o segredo com ou sem padding e ignora espaços que o usuário possa
    # ter colado do QR/texto.
    limpo = secret.strip().replace(" ", "").upper()
    padding = "=" * (-len(limpo) % 8)
    return base64.b32decode(limpo + padding, casefold=True)


def _hotp(key: bytes, counter: int, digits: int = _DIGITS) -> str:
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    truncated = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(truncated % (10**digits)).zfill(digits)


def generate(secret: str, *, at: float | None = None, digits: int = _DIGITS) -> str:
    """Código TOTP para o instante `at` (padrão: agora)."""
    counter = int((at if at is not None else time.time()) // _PERIOD)
    return _hotp(_decode_secret(secret), counter, digits)


def verify(secret: str, code: str, *, at: float | None = None, window: int = 1) -> bool:
    """Compara `code` com o passo atual e `window` passos para cada lado.

    Comparação constante-tempo. `window=1` (±30s) é o compromisso usual entre
    tolerar relógio torto e não alargar demais a janela de brute-force — que
    de qualquer forma já é limitada pelo rate limit do endpoint de login.
    """
    code = (code or "").strip().replace(" ", "")
    if not code.isdigit() or len(code) != _DIGITS:
        return False
    try:
        key = _decode_secret(secret)
    except ValueError:
        # binascii.Error (segredo base32 inválido) é subclasse de ValueError.
        return False
    now = at if at is not None else time.time()
    base_counter = int(now // _PERIOD)
    for drift in range(-window, window + 1):
        if hmac.compare_digest(_hotp(key, base_counter + drift), code):
            return True
    return False


def provisioning_uri(secret: str, *, account: str, issuer: str = "Eltanix Coder IDE") -> str:
    """`otpauth://totp/Issuer:account?secret=...&issuer=...` — o que vira QR."""
    label = quote(f"{issuer}:{account}")
    params = urlencode(
        {
            "secret": secret,
            "issuer": issuer,
            "algorithm": _ALGO,
            "digits": _DIGITS,
            "period": _PERIOD,
        }
    )
    return f"otpauth://totp/{label}?{params}"
