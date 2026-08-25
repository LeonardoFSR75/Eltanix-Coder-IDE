"""Módulo de sanitização dinâmica de PII (Personally Identifiable Information) e segredos.

Mascara dados sensíveis como CPFs, e-mails, cartões de crédito e chaves de API
em textos de prompt antes do envio para modelos remotos de nuvem pública.
"""

from __future__ import annotations

import re
from typing import NamedTuple


class PIIMaskResult(NamedTuple):
    sanitized_text: str
    redacted_count: int


class PIIRedactor:
    """Sanitizador de PII baseado em regexes otimizadas."""

    # CPF regex: 000.000.000-00 ou 11 dígitos sequenciais sem formatação
    CPF_PATTERN = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")

    # E-mail regex
    EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

    # Cartão de crédito (13 a 19 dígitos com ou sem hífens/espaços)
    CREDIT_CARD_PATTERN = re.compile(
        r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b"
    )

    # Segredos / API Keys comuns
    API_KEY_PATTERN = re.compile(
        r"(?i)\b(?:sk-[a-zA-Z0-9_\-]{15,}|Bearer\s+[a-zA-Z0-9_\-\.]{20,}|ghp_[a-zA-Z0-9]{36})\b"
    )

    @classmethod
    def redact(cls, text: str) -> PIIMaskResult:
        """Sanitiza o texto substituindo PIIs por marcadores genéricos."""
        if not text:
            return PIIMaskResult(sanitized_text="", redacted_count=0)

        redacted_count = 0

        def replace_cpf(match: re.Match) -> str:
            nonlocal redacted_count
            redacted_count += 1
            return "[REDACTED_CPF]"

        def replace_email(match: re.Match) -> str:
            nonlocal redacted_count
            redacted_count += 1
            return "[REDACTED_EMAIL]"

        def replace_card(match: re.Match) -> str:
            nonlocal redacted_count
            redacted_count += 1
            return "[REDACTED_CARD]"

        def replace_key(match: re.Match) -> str:
            nonlocal redacted_count
            redacted_count += 1
            return "[REDACTED_API_KEY]"

        sanitized = text
        sanitized = cls.CPF_PATTERN.sub(replace_cpf, sanitized)
        sanitized = cls.EMAIL_PATTERN.sub(replace_email, sanitized)
        sanitized = cls.CREDIT_CARD_PATTERN.sub(replace_card, sanitized)
        sanitized = cls.API_KEY_PATTERN.sub(replace_key, sanitized)

        return PIIMaskResult(sanitized_text=sanitized, redacted_count=redacted_count)
