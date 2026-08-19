"""Ingestão e sanitização de trajetórias de chat da IDE."""

from __future__ import annotations

import re
from typing import Any

# Padrões de expressões regulares para sanitização de credenciais e segredos
SECRET_PATTERNS = [
    (re.compile(r"(sk-[a-zA-Z0-9_-]{20,})"), "[REDACTED_API_KEY]"),
    (re.compile(r"(gsk_[a-zA-Z0-9_-]{20,})"), "[REDACTED_GROQ_KEY]"),
    (re.compile(r"(AIzaSy[a-zA-Z0-9_-]{33})"), "[REDACTED_GEMINI_KEY]"),
    (re.compile(r"(Bearer\s+[a-zA-Z0-9._-]{20,})", re.IGNORECASE), "Bearer [REDACTED_TOKEN]"),
    (
        re.compile(
            r"(password|secret|token|api_key)\s*[:=]\s*['\"]?([^'\"\s]+)['\"]?", re.IGNORECASE
        ),
        r"\1: [REDACTED]",
    ),
]


def sanitize_text(text: str) -> str:
    """Sanitiza informações sensíveis (PII, segredos, chaves API) em cadeias de texto."""
    if not text:
        return ""
    sanitized = text
    for pattern, replacement in SECRET_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


def sanitize_payload(obj: Any) -> Any:
    """Sanitiza recursivamente um dicionário ou lista de telemetria."""
    if isinstance(obj, str):
        return sanitize_text(obj)
    elif isinstance(obj, dict):
        return {k: sanitize_payload(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_payload(item) for item in obj]
    return obj


class TrajectoryIngestor:
    """Processa e enriquece telemetria bruta de sessões de chat."""

    @staticmethod
    def process_raw_session(
        session_id: str,
        user_prompt: str,
        steps: list[dict[str, Any]],
        project_slug: str | None = None,
        max_context_tokens: int = 128000,
    ) -> dict[str, Any]:
        """Processa a trajetória bruta e deriva métricas quantitativas de falha."""
        sanitized_prompt = sanitize_text(user_prompt)
        sanitized_steps = sanitize_payload(steps)

        tool_calls_count = 0
        tool_errors_count = 0
        total_tokens = 0
        tool_names: list[str] = []

        for step in sanitized_steps:
            if "tokens" in step and isinstance(step["tokens"], int):
                total_tokens += step["tokens"]

            tool_calls = step.get("tool_calls", [])
            for call in tool_calls:
                tool_calls_count += 1
                tool_name = call.get("name", "unknown")
                tool_names.append(tool_name)
                if call.get("error") or call.get("status") == "error":
                    tool_errors_count += 1

        # Cálculo do Coeficiente de Loop (Repetição de ferramentas consecutivas)
        loop_coefficient = 0.0
        if len(tool_names) > 1:
            repeats = sum(
                1 for i in range(len(tool_names) - 1) if tool_names[i] == tool_names[i + 1]
            )
            loop_coefficient = round(repeats / (len(tool_names) - 1), 2)

        context_saturation = round(min(total_tokens / max_context_tokens, 1.0), 4)

        metrics = {
            "total_tokens": total_tokens,
            "tool_error_rate": round(tool_errors_count / max(tool_calls_count, 1), 2),
            "loop_coefficient": loop_coefficient,
            "context_saturation": context_saturation,
        }

        return {
            "session_id": session_id,
            "project_slug": project_slug,
            "user_prompt": sanitized_prompt,
            "step_count": len(sanitized_steps),
            "tool_calls_count": tool_calls_count,
            "tool_errors_count": tool_errors_count,
            "trajectory_data": {
                "steps": sanitized_steps,
                "tool_names": tool_names,
            },
            "metrics": metrics,
        }
