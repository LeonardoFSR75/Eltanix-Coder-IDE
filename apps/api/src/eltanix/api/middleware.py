"""Correlation ID: um id por requisição amarrado em todo log emitido durante ela.

`logging_setup.py` já tem `structlog.contextvars.merge_contextvars` no
pipeline — faltava só alguém chamar `bind_contextvars`. Sem isto, achar todas
as linhas de log de uma requisição específica (ou de uma sessão do agente,
que pode gerar dezenas de spans de ferramentas) exige grep manual por
timestamp aproximado; com isto, é filtrar por um único `request_id`.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

_HEADER = "X-Request-ID"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Um proxy à frente (ou um chamador programático) pode já ter gerado
        # um id — reusar em vez de sobrescrever mantém a correlação ponta a
        # ponta em vez de quebrá-la na borda do gateway.
        request_id = request.headers.get(_HEADER) or uuid.uuid4().hex[:12]
        # Também em `request.state`: o handler de exceção não-tratada
        # (`api/errors.py`) roda no `ServerErrorMiddleware`, que é externo a
        # este middleware — quando ele dispara, o `finally` abaixo já limpou
        # os contextvars do structlog, então é daqui que ele lê o id para
        # devolver no corpo e no header da resposta 500.
        request.state.request_id = request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()
        response.headers[_HEADER] = request_id
        return response
