"""Ferramenta de busca em documentos (RAG) — global, não por projeto.

Documentos e notas do segundo cérebro formam uma base de conhecimento única
do usuário, disponível em qualquer sessão do agente, ao contrário do índice de
código (`search_code`), que é por workspace.
"""

from __future__ import annotations

from typing import Any

from sicoobito.agent.tools.base import RiskClass, ToolContext, ToolResult, tool

MAX_HITS = 8
MAX_OUTPUT_CHARS = 24_000


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    metade = limit // 2
    omitido = len(text) - limit
    return f"{text[:metade]}\n\n... [{omitido} caracteres omitidos no meio] ...\n\n{text[-metade:]}"


@tool(
    name="search_documents",
    description=(
        "Busca semântica e textual nos documentos (PDFs) que o usuário enviou ao RAG. "
        "Use quando a pergunta puder ter resposta em material de referência anexado, "
        "não no código do projeto."
    ),
    risk=RiskClass.READ,
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "O que procurar, em linguagem natural",
            },
            "limit": {"type": "integer", "description": f"Máximo de trechos; padrão {MAX_HITS}"},
        },
        "required": ["query"],
    },
    summarize=lambda a: f"buscar nos documentos: {a.get('query')!r}",
)
async def search_documents(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    if ctx.documents is None:
        return ToolResult.failure("Busca em documentos indisponível.")

    hits = await ctx.documents.search(args["query"], limit=args.get("limit", MAX_HITS))
    if not hits:
        return ToolResult(ok=True, content="Nenhum trecho encontrado.", data={"hits": []})

    blocos = [f"--- {hit.filename} (p.{hit.page_number})\n{hit.content}" for hit in hits]
    return ToolResult(
        ok=True,
        content=_truncate("\n\n".join(blocos)),
        data={
            "hits": [
                {"document_id": h.document_id, "filename": h.filename, "score": h.score}
                for h in hits
            ]
        },
    )
