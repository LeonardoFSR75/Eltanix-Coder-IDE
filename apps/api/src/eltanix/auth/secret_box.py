"""Cifra em repouso para o segredo TOTP (F-7 em `docs/security_review_2026-08.md`).

O segredo TOTP (`user_mfa.secret`, base32) é a única parte recuperável do 2º
fator — os códigos de recuperação já são `sha256` de uso único. Se o Postgres
vazar junto com o `password_hash` de um usuário, um segredo em claro faz o 2º
fator cair também. Aqui ele passa a ir cifrado com **AES-256-GCM**.

Dependência: `cryptography` — ao contrário de bcrypt/argon2 (rejeitados no
ADR 0005), ela publica wheel `abi3` pré-compilada para `win_amd64`,
`manylinux` e macOS, então não exige toolchain nativo; é o mesmo critério que
já libera `psycopg[binary]`/`pdf-inspector`.

Chave: derivada de `ELTANIX_MFA_SECRET_KEY` via `scrypt` determinístico (mesma
env var → mesma chave, nada persistido). **Sem a env var, o valor é
gravado/lido em claro exatamente como antes** — degrada, não quebra, e o
modelo local-first tolera isso (ver F-7). `main.py` avisa alto no boot quando
ela está vazia mas há MFA em uso.

Formato do envelope: ``enc:v1:`` + base64(nonce[12] || ciphertext || tag).
Um valor sem esse prefixo é texto claro legado — lido como está e re-cifrado
na próxima autenticação bem-sucedida (mesmo padrão do re-hash de senha em
`service.py`).
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_PREFIX = "enc:v1:"
# Salt fixo do KDF: o objetivo é derivar 32 bytes estáveis de uma env var de
# entropia alta, não defender contra rainbow table de senha fraca — o segredo
# de entrada não é uma senha humana.
_KDF_SALT = b"eltanix.mfa.secret_box.v1"
_NONCE_LEN = 12


def _derive_key(material: str) -> bytes:
    return hashlib.scrypt(material.encode("utf-8"), salt=_KDF_SALT, n=2**14, r=8, p=1, dklen=32)


class SecretBox:
    """Cifra/decifra strings curtas. Sem chave configurada, é um no-op
    transparente (retorna a entrada) — o chamador não muda de caminho."""

    def __init__(self, key_material: str) -> None:
        self._key = _derive_key(key_material) if key_material else None

    @property
    def enabled(self) -> bool:
        return self._key is not None

    def encrypt(self, plaintext: str) -> str:
        if self._key is None:
            return plaintext
        nonce = os.urandom(_NONCE_LEN)
        ct = AESGCM(self._key).encrypt(nonce, plaintext.encode("utf-8"), None)
        return _PREFIX + base64.b64encode(nonce + ct).decode("ascii")

    def decrypt(self, stored: str) -> str:
        if not stored.startswith(_PREFIX):
            return stored  # texto claro legado (ou cifra desligada quando gravou)
        if self._key is None:
            raise RuntimeError(
                "valor cifrado em user_mfa.secret mas ELTANIX_MFA_SECRET_KEY não "
                "está definida — defina a mesma chave usada quando o MFA foi ativado"
            )
        raw = base64.b64decode(stored[len(_PREFIX) :])
        nonce, ct = raw[:_NONCE_LEN], raw[_NONCE_LEN:]
        try:
            return AESGCM(self._key).decrypt(nonce, ct, None).decode("utf-8")
        except InvalidTag as exc:  # chave errada ou valor adulterado
            raise RuntimeError("falha ao decifrar user_mfa.secret (InvalidTag)") from exc

    def needs_reencrypt(self, stored: str) -> bool:
        """`True` quando a cifra está ligada mas o valor no banco ainda está
        em claro — gatilho para regravar cifrado na próxima escrita."""
        return self._key is not None and not stored.startswith(_PREFIX)
