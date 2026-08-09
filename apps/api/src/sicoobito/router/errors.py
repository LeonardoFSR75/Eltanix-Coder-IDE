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

import json
import re
from enum import StrEnum
from typing import Any

# Alguns modelos servidos pela Groq (ex.: llama-3.3-70b-versatile) às vezes
# emitem a function-call num formato pseudo-XML (`<function=nome{...}`) em vez
# de preencher `tool_calls` — a API rejeita com 400 (`tool_use_failed`) e
# devolve o texto bruto em `failed_generation`, escapado como string JSON.
_FAILED_GENERATION_RE = re.compile(r'"failed_generation"\s*:\s*"((?:[^"\\]|\\.)*)"')
_FUNCTION_CALL_RE = re.compile(r"<function=([a-zA-Z_][a-zA-Z0-9_]*)")


def extract_failed_tool_call(exc: Exception) -> tuple[str, dict[str, Any]] | None:
    """Recupera nome+argumentos de uma function-call de um erro `tool_use_failed`.

    Retorna `None` sempre que não reconhece o formato — o chamador trata isso
    como falha normal (próximo candidato), sem regressão de comportamento.
    """
    text = str(exc)
    if "tool_use_failed" not in text:
        return None

    match = _FAILED_GENERATION_RE.search(text)
    if not match:
        return None
    try:
        # group(1) é o corpo de uma string JSON válida (aspas já removidas) —
        # reembrulhar em aspas e usar json.loads desescapa (\", \\, \uXXXX...)
        # do jeito certo, em vez de reimplementar as regras de escape do JSON.
        raw = json.loads(f'"{match.group(1)}"')
    except json.JSONDecodeError:
        return None

    fn_match = _FUNCTION_CALL_RE.search(raw)
    if not fn_match:
        return None

    brace_start = raw.find("{", fn_match.end())
    if brace_start == -1:
        return None
    try:
        args, _ = json.JSONDecoder().raw_decode(raw, brace_start)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(args, dict):
        return None

    return fn_match.group(1), args


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
