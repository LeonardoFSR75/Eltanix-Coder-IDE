"""Ferramentas do Segundo Cérebro — busca (READ) e gravação (WRITE) de notas.

Globais, como `search_documents`: notas de conhecimento pessoal fazem sentido
disponíveis em qualquer sessão, não amarradas a um projeto.
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
    name="search_notes",
    description=(
        "Busca semântica e textual nas notas do Segundo Cérebro do usuário. Use para "
        "recuperar conhecimento, decisões ou convenções que o usuário já registrou."
    ),
    risk=RiskClass.READ,
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "O que procurar, em linguagem natural"},
            "limit": {"type": "integer", "description": f"Máximo de trechos; padrão {MAX_HITS}"},
        },
        "required": ["query"],
    },
    summarize=lambda a: f"buscar nas notas: {a.get('query')!r}",
)
async def search_notes(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    if ctx.notes is None:
        return ToolResult.failure("Busca em notas indisponível.")

    hits = await ctx.notes.search(args["query"], limit=args.get("limit", MAX_HITS))
    if not hits:
        return ToolResult(ok=True, content="Nenhuma nota encontrada.", data={"hits": []})

    blocos = [f"--- {hit.title}\n{hit.content}" for hit in hits]
    return ToolResult(
        ok=True,
        content=_truncate("\n\n".join(blocos)),
        data={"hits": [{"note_id": h.note_id, "title": h.title, "score": h.score} for h in hits]},
    )


@tool(
    name="save_note",
    description=(
        "Cria ou atualiza (por título) uma nota no Segundo Cérebro — grava conhecimento "
        "de forma permanente e pesquisável, não apenas no histórico da conversa. Use "
        "quando o usuário pedir para 'lembrar', 'anotar' ou 'guardar' algo, ou quando "
        "você mesmo concluir algo que vale a pena persistir para sessões futuras."
    ),
    risk=RiskClass.WRITE,
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Título da nota — usado para upsert"},
            "content": {
                "type": "string",
                "description": "Conteúdo em Markdown; use [[Título]] para linkar outras notas",
            },
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["title", "content"],
    },
    summarize=lambda a: f"salvar nota: {a.get('title')!r}",
)
async def save_note(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    if ctx.notes is None:
        return ToolResult.failure("Gravação de notas indisponível.")

    note = await ctx.notes.upsert_by_title(
        title=args["title"],
        content=args["content"],
        tags=args.get("tags"),
        project_slug=ctx.project_slug or None,
    )
    return ToolResult(
        ok=True,
        content=f"Nota {note.title!r} salva ({len(note.links)} link(s) detectado(s)).",
        data={"note_id": str(note.id), "title": note.title},
    )
