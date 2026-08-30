"""Cifra em repouso do segredo TOTP (F-7) — `auth/secret_box.py`.

Unitário, sem banco: exercita cifra/decifra, o no-op transparente sem chave,
a leitura de texto claro legado e a detecção de adulteração.
"""

from __future__ import annotations

import pytest

from eltanix.auth.secret_box import _PREFIX, SecretBox

_KEY = "chave-de-teste-com-entropia-suficiente-123"
_SECRET = "JBSWY3DPEHPK3PXP"  # base32 típico de segredo TOTP


def test_disabled_box_is_a_transparent_noop():
    box = SecretBox("")
    assert box.enabled is False
    assert box.encrypt(_SECRET) == _SECRET
    assert box.decrypt(_SECRET) == _SECRET
    assert box.needs_reencrypt(_SECRET) is False


def test_roundtrip_with_key():
    box = SecretBox(_KEY)
    assert box.enabled is True
    token = box.encrypt(_SECRET)
    assert token.startswith(_PREFIX)
    assert _SECRET not in token
    assert box.decrypt(token) == _SECRET


def test_ciphertext_is_non_deterministic():
    box = SecretBox(_KEY)
    assert box.encrypt(_SECRET) != box.encrypt(_SECRET)  # nonce aleatório


def test_legacy_plaintext_is_read_through_even_with_key():
    box = SecretBox(_KEY)
    assert box.decrypt(_SECRET) == _SECRET  # sem prefixo => texto claro legado
    assert box.needs_reencrypt(_SECRET) is True
    assert box.needs_reencrypt(box.encrypt(_SECRET)) is False


def test_wrong_key_fails_closed():
    token = SecretBox(_KEY).encrypt(_SECRET)
    with pytest.raises(RuntimeError):
        SecretBox("outra-chave-completamente-diferente").decrypt(token)


def test_tampered_ciphertext_is_rejected():
    box = SecretBox(_KEY)
    token = box.encrypt(_SECRET)
    tampered = token[:-2] + ("AA" if not token.endswith("AA") else "BB")
    with pytest.raises(RuntimeError):
        box.decrypt(tampered)


def test_encrypted_value_without_key_raises():
    token = SecretBox(_KEY).encrypt(_SECRET)
    with pytest.raises(RuntimeError):
        SecretBox("").decrypt(token)
