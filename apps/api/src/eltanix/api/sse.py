"""Framing mínimo de Server-Sent Events.

Compartilhado pelas duas rotas que fazem streaming de resposta
(`api/routes/agent.py` e `api/v1/openai_compat.py`) — só o envelope
`data: ...\n\n`/`data: [DONE]\n\n` que as duas replicavam, não a
serialização em si: cada lado passa seus próprios kwargs de `json.dumps`
(`ensure_ascii`, `default`), que divergem de propósito entre elas.
"""

from __future__ import annotations

import json
from typing import Any

SSE_DONE = "data: [DONE]\n\n"


def sse_event(payload: Any, **json_kwargs: Any) -> str:
    return f"data: {json.dumps(payload, **json_kwargs)}\n\n"
