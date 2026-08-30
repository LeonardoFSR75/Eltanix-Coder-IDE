"""Handler de exceção não-tratada.

Sem isto, uma exceção que escapa de um handler vira o 500 de texto puro do
Starlette — sem `X-Request-ID` no header (o `CorrelationIdMiddleware` não chega
a setá-lo quando a request estoura) e sem nada no corpo que ligue a resposta à
linha de log correspondente. Este handler fecha as duas pontas: loga com
`log.exception` (stack completa, já com `request_id` no contexto porque ainda
estamos dentro do escopo do middleware quando ele roda) e devolve um JSON
enxuto com o mesmo id, que o cliente web (`apps/web/lib/client.ts`) já sabe
extrair de `body.detail`.

`HTTPException` e `RequestValidationError` continuam com o tratamento padrão do
FastAPI — são resolvidos no `ExceptionMiddleware` interno e nunca chegam aqui.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from eltanix.logging_setup import get_logger

log = get_logger(__name__)

_HEADER = "X-Request-ID"


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    log.exception(
        "api.unhandled_exception",
        path=request.url.path,
        method=request.method,
        error_type=type(exc).__name__,
    )
    headers = {_HEADER: request_id} if request_id else None
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Erro interno no servidor.",
            "request_id": request_id,
        },
        headers=headers,
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(Exception, unhandled_exception_handler)
