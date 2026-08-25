"""Estimativa local de tokens.

Serve a dois propósitos: escolher a rota antes de gastar (o custo estimado
depende do tamanho do prompt) e preencher `usage` quando o provedor não devolve
contagem — o que acontece com frequência em streaming no Databricks e em alguns
endpoints Foundry.

A estimativa usa `cl100k_base` para todos os modelos. Não é exata para famílias
Llama/Qwen, mas o erro é da ordem de 10–20%, suficiente para ordenar candidatos.
Quando o provedor reporta `usage`, o valor reportado sempre prevalece.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from novaai_studio.logging_setup import get_logger

log = get_logger(__name__)

# Sobrecarga aproximada por mensagem no formato chat (delimitadores de papel).
_PER_MESSAGE_OVERHEAD = 4
_REPLY_PRIMER = 3


@lru_cache(maxsize=1)
def _encoder() -> Any | None:
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception as exc:
        log.warning("tokens.encoder.unavailable", error=str(exc))
        return None


def count_text(text: str) -> int:
    if not text:
        return 0
    encoder = _encoder()
    if encoder is None:
        # Heurística de fallback: ~4 caracteres por token em texto latino.
        return max(1, len(text) // 4)
    return len(encoder.encode(text, disallowed_special=()))


def _content_to_text(content: Any) -> str:
    """Achata o `content`, que pode ser string ou lista de partes multimodais."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                if part.get("type") == "text":
                    parts.append(str(part.get("text", "")))
                else:
                    # Imagens e áudio não são contáveis por BPE; o custo real vem
                    # do provedor. Contamos só o descritor para não zerar.
                    parts.append(json.dumps(part)[:200])
        return "\n".join(parts)
    return str(content)


def count_messages(messages: list[dict[str, Any]]) -> int:
    total = 0
    for message in messages:
        total += _PER_MESSAGE_OVERHEAD
        total += count_text(str(message.get("role", "")))
        total += count_text(_content_to_text(message.get("content")))
        if tool_calls := message.get("tool_calls"):
            total += count_text(json.dumps(tool_calls))
        if name := message.get("name"):
            total += count_text(str(name))
    return total + _REPLY_PRIMER


def count_tools(tools: list[dict[str, Any]] | None) -> int:
    """Definições de ferramenta entram no prompt e costumam ser subestimadas."""
    if not tools:
        return 0
    return count_text(json.dumps(tools))


def estimate_prompt_tokens(
    messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
) -> int:
    return count_messages(messages) + count_tools(tools)
