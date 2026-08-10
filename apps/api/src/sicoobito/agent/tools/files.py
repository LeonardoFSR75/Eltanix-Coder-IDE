"""Ferramentas de leitura e escrita de arquivo."""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from sicoobito.agent.tools.base import RiskClass, ToolContext, ToolResult, tool
from sicoobito.workspace.fs import FileTooLargeError, PathEscapeError

# Truncar aqui e não no prompt: a saída da ferramenta é o que entra no histórico
# e volta em toda chamada seguinte.
MAX_TOOL_OUTPUT_CHARS = 24_000


def _truncate(text: str, limit: int = MAX_TOOL_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    metade = limit // 2
    omitido = len(text) - limit
    return f"{text[:metade]}\n\n... [{omitido} caracteres omitidos no meio] ...\n\n{text[-metade:]}"


@tool(
    name="read_file",
    description=(
        "Lê o conteúdo de um arquivo do workspace. Use `start_line`/`end_line` "
        "para ler apenas um trecho de arquivos grandes."
    ),
    risk=RiskClass.READ,
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Caminho relativo à raiz do projeto"},
            "start_line": {"type": "integer", "description": "Primeira linha (1-based)"},
            "end_line": {"type": "integer", "description": "Última linha, inclusive"},
        },
        "required": ["path"],
    },
    summarize=lambda a: f"ler {a.get('path')}",
)
async def read_file(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    path = args["path"]
    try:
        if args.get("start_line") or args.get("end_line"):
            content = ctx.fs.read_lines(path, args.get("start_line", 1), args.get("end_line"))
        else:
            content = ctx.fs.read(path)
    except (PathEscapeError, FileNotFoundError, FileTooLargeError, ValueError) as exc:
        return ToolResult.failure(str(exc))

    return ToolResult(
        ok=True,
        content=_truncate(content),
        data={"path": path, "lines": content.count("\n") + 1},
    )


@tool(
    name="list_files",
    description="Lista arquivos e pastas de um diretório do workspace.",
    risk=RiskClass.READ,
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Diretório relativo; padrão é a raiz"}
        },
    },
    summarize=lambda a: f"listar {a.get('path', '.')}",
)
async def list_files(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    path = args.get("path", ".")
    try:
        entries = ctx.fs.list_dir(path)
    except (PathEscapeError, NotADirectoryError) as exc:
        return ToolResult.failure(str(exc))

    linhas = [f"{'dir ' if e.is_dir else 'file'} {e.path}" for e in entries]
    return ToolResult(
        ok=True,
        content="\n".join(linhas) or "(diretório vazio)",
        data={"entries": [{"path": e.path, "is_dir": e.is_dir} for e in entries]},
    )


@tool(
    name="write_file",
    description=(
        "Cria ou substitui um arquivo por completo. Para alterações pontuais "
        "prefira `edit_file`, que é mais seguro e produz um diff menor."
    ),
    risk=RiskClass.WRITE,
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string", "description": "Conteúdo integral do arquivo"},
        },
        "required": ["path", "content"],
    },
    summarize=lambda a: f"escrever {a.get('path')} ({len(a.get('content', ''))} caracteres)",
)
async def write_file(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    path, content = args["path"], args["content"]
    try:
        existia = ctx.fs.exists(path)
        anterior = ctx.fs.read(path) if existia else ""
        ctx.fs.write(path, content)
    except (PathEscapeError, ValueError, OSError) as exc:
        return ToolResult.failure(str(exc))

    return ToolResult(
        ok=True,
        content=f"{path} gravado ({len(content)} caracteres).",
        # `before`/`after` completos poupam o frontend de parsear diff
        # unificado: a Fase 3 (revisão de diff) alimenta o DiffEditor do
        # Monaco direto com estas duas strings. `existed` diz se rejeitar a
        # edição deve reescrever o conteúdo anterior ou apagar o arquivo —
        # sem depender de git, que pode nem existir no projeto (ver
        # `POST /sessions/{id}/files/revert`).
        data={
            "path": path,
            "diff": unified_diff(path, anterior, content),
            "before": anterior,
            "after": content,
            "existed": existia,
        },
    )


@tool(
    name="edit_file",
    description=(
        "Substitui um trecho exato de um arquivo. `old_text` precisa aparecer "
        "uma única vez — inclua linhas de contexto suficientes para torná-lo "
        "inequívoco. Falha em vez de adivinhar se houver ambiguidade."
    ),
    risk=RiskClass.WRITE,
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_text": {"type": "string", "description": "Trecho exato a substituir"},
            "new_text": {"type": "string", "description": "Texto que entra no lugar"},
        },
        "required": ["path", "old_text", "new_text"],
    },
    summarize=lambda a: f"editar {a.get('path')}",
)
async def edit_file(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    path, old_text, new_text = args["path"], args["old_text"], args["new_text"]

    try:
        atual = ctx.fs.read(path)
    except (PathEscapeError, FileNotFoundError, FileTooLargeError, ValueError) as exc:
        return ToolResult.failure(str(exc))

    # O modelo escreve `old_text` com \n; um arquivo criado no Windows tem
    # \r\n. Comparar cru faria toda edição falhar com "trecho não encontrado",
    # de forma silenciosa e sistemática. Casamos com as pontas normalizadas e
    # devolvemos o arquivo na convenção que ele já usava.
    quebra = "\r\n" if "\r\n" in atual else "\n"
    atual_norm = atual.replace("\r\n", "\n")
    old_norm = old_text.replace("\r\n", "\n")
    new_norm = new_text.replace("\r\n", "\n")

    ocorrencias = atual_norm.count(old_norm)
    if ocorrencias == 0:
        return ToolResult.failure(
            f"O trecho não foi encontrado em {path}. "
            "Leia o arquivo novamente: ele pode ter mudado, ou a indentação difere."
        )
    if ocorrencias > 1:
        # Substituir a primeira ocorrência silenciosamente editaria o lugar
        # errado sem ninguém perceber.
        return ToolResult.failure(
            f"O trecho aparece {ocorrencias} vezes em {path}. "
            "Inclua mais linhas de contexto para identificar qual delas editar."
        )

    novo_norm = atual_norm.replace(old_norm, new_norm, 1)
    novo = novo_norm.replace("\n", quebra) if quebra == "\r\n" else novo_norm
    try:
        ctx.fs.write(path, novo)
    except (PathEscapeError, OSError) as exc:
        return ToolResult.failure(str(exc))

    # O diff sai normalizado: mostrar ^M em toda linha esconderia a mudança real.
    diff = unified_diff(path, atual_norm, novo_norm)
    return ToolResult(
        ok=True,
        content=f"{path} editado.\n\n{diff}",
        # `edit_file` exige o arquivo já existir (lido no início da função),
        # então `existed` é sempre True aqui — ver write_file para o outro caso.
        data={
            "path": path,
            "diff": diff,
            "before": atual_norm,
            "after": novo_norm,
            "existed": True,
        },
    )


@tool(
    name="search_code",
    description=(
        "Busca semântica e textual no índice do repositório. Prefira esta "
        "ferramenta a ler arquivos no escuro: ela devolve os trechos relevantes "
        "com arquivo e linha."
    ),
    risk=RiskClass.READ,
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "O que procurar, em linguagem natural ou como identificador",
            },
            "limit": {"type": "integer", "description": "Máximo de trechos; padrão 8"},
        },
        "required": ["query"],
    },
    summarize=lambda a: f"buscar no código: {a.get('query')!r}",
)
async def search_code(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    if ctx.indexer is None:
        return ToolResult.failure("Índice de contexto indisponível.")

    hits = await ctx.indexer.search(
        root=Path(ctx.workspace_root), query=args["query"], limit=args.get("limit", 8)
    )
    if not hits:
        return ToolResult(ok=True, content="Nenhum trecho encontrado.", data={"hits": []})

    blocos = [f"--- {hit.citation}\n{hit.content}" for hit in hits]
    return ToolResult(
        ok=True,
        content=_truncate("\n\n".join(blocos)),
        data={"hits": [{"path": h.path, "citation": h.citation, "score": h.score} for h in hits]},
    )


def unified_diff(path: str, antes: str, depois: str) -> str:
    linhas = difflib.unified_diff(
        antes.splitlines(keepends=True),
        depois.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=3,
    )
    return _truncate("".join(linhas), 8000)
