"""Classificação de erros de provedor.

Nem toda falha merece a mesma reação. Três categorias importam:

- `FATAL`     erro do cliente (prompt inválido, política de conteúdo). Tentar
              outro modelo só repetiria o mesmo erro e gastaria dinheiro.
- `SKIP`      o modelo não serve para este request (contexto estourado), mas o
              provedor está saudável — não deve contar falha no breaker.
- `TRANSIENT` provedor com problema (timeout, 429, 5xx, auth). Conta falha,
              alimenta o circuit breaker e tenta o próximo candidato.
"""

from __future__ import annotations

from enum import StrEnum


class FailureKind(StrEnum):
    FATAL = "fatal"
    SKIP = "skip"
    TRANSIENT = "transient"


class NoCandidatesError(RuntimeError):
    """Nenhum modelo elegível para o request."""

    def __init__(self, message: str, *, excluded: list[str] | None = None) -> None:
        super().__init__(message)
        self.excluded = excluded or []


class AllCandidatesFailedError(RuntimeError):
    """Todos os candidatos foram tentados e falharam."""

    def __init__(self, message: str, *, attempts: list[str], last_error: Exception) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.last_error = last_error


def classify(exc: Exception) -> FailureKind:
    name = type(exc).__name__

    if name == "ContextWindowExceededError":
        return FailureKind.SKIP

    if name in {"ContentPolicyViolationError", "UnsupportedParamsError"}:
        return FailureKind.FATAL

    if name in {"BadRequestError", "NotFoundError", "AuthenticationError", "PermissionDeniedError"}:
        text = str(exc).lower()
        if "context" in text and ("length" in text or "window" in text or "maximum" in text):
            return FailureKind.SKIP
        # Falhas de saldo, chave, quota ou cobrança são do provedor específico, não do prompt.
        if any(w in text for w in ("credit", "balance", "quota", "billing", "plan", "key", "auth", "payment", "unauthorized", "invalid_request_error")):
            return FailureKind.TRANSIENT
        return FailureKind.FATAL

    return FailureKind.TRANSIENT
