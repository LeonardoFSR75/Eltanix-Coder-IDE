"""Ferramenta de leitura do Code Knowledge Graph (`context/edges.py`)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sicoobito.agent.tools.base import RiskClass, ToolContext, ToolResult, tool
from sicoobito.context import edges as context_edges
from sicoobito.context import store as context_store
from sicoobito.db.session import session_scope


@tool(
    name="code_graph",
    description=(
        "Mostra a vizinhança de um símbolo no Code Knowledge Graph: o que ele "
        "contém (métodos de uma classe), o que o contém, e os arquivos que "
        "ele importa / que o importam. Use para entender estrutura antes de "
        "mudar algo, ou para achar dependência circular e módulo órfão."
    ),
    risk=RiskClass.READ,
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Caminho do arquivo"},
            "symbol": {
                "type": "string",
                "description": "Nome do símbolo (função/classe/método); sem ele, usa o topo do "
                "arquivo",
            },
        },
        "required": ["path"],
    },
    summarize=lambda a: f"grafo de {a.get('path')}"
    + (f"::{a['symbol']}" if a.get("symbol") else ""),
)
async def code_graph(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    if ctx.indexer is None:
        return ToolResult.failure("Índice de contexto indisponível.")

    workspace = ctx.indexer.workspace_key(Path(ctx.workspace_root))
    path = args["path"]

    async with session_scope() as session:
        result = await context_store.code_graph(
            session, workspace=workspace, path=path, symbol=args.get("symbol")
        )

    if result.chunk is None:
        return ToolResult.failure(
            f"Nenhum chunk indexado em {path!r}. Rode a indexação do projeto primeiro."
        )

    linhas = [f"{result.chunk.path} · {result.chunk.symbol or '(topo do arquivo)'}"]
    if result.contained_by:
        linhas.append(f"contido por: {result.contained_by.symbol}")
    if result.contains:
        linhas.append("contém:")
        linhas.extend(f"  {c.symbol} ({c.kind})" for c in result.contains)
    if result.imports:
        linhas.append("importa:")
        linhas.extend(f"  {p}" for p in result.imports)
    if result.imported_by:
        linhas.append("importado por:")
        linhas.extend(f"  {p}" for p in result.imported_by)

    return ToolResult(
        ok=True,
        content="\n".join(linhas),
        data={
            "node": {
                "path": result.chunk.path,
                "symbol": result.chunk.symbol,
                "kind": result.chunk.kind,
            },
            "contains": [
                {"symbol": c.symbol, "kind": c.kind, "path": c.path} for c in result.contains
            ],
            "contained_by": (
                {"symbol": result.contained_by.symbol, "kind": result.contained_by.kind}
                if result.contained_by
                else None
            ),
            "imports": result.imports,
            "imported_by": result.imported_by,
        },
    )


@tool(
    name="find_circular_imports",
    description=(
        "Procura dependência circular entre arquivos, seguindo as arestas de "
        "import do Code Knowledge Graph. Devolve os ciclos como listas de "
        "caminho — cada um é evidência (a cadeia de imports), não uma "
        "suposição. Projeto precisa estar indexado."
    ),
    risk=RiskClass.READ,
    parameters={"type": "object", "properties": {}},
    summarize=lambda _a: "procurar dependência circular",
)
async def find_circular_imports(ctx: ToolContext, _args: dict[str, Any]) -> ToolResult:
    if ctx.indexer is None:
        return ToolResult.failure("Índice de contexto indisponível.")

    workspace = ctx.indexer.workspace_key(Path(ctx.workspace_root))
    async with session_scope() as session:
        graph = await context_store.import_graph(session, workspace=workspace)
    cycles = context_edges.find_cycles(graph)

    if not cycles:
        return ToolResult(
            ok=True, content="Nenhuma dependência circular encontrada.", data={"cycles": []}
        )

    linhas = [f"{len(cycles)} ciclo(s) encontrado(s):"]
    linhas.extend("  " + " → ".join(cycle) for cycle in cycles)
    return ToolResult(ok=True, content="\n".join(linhas), data={"cycles": cycles})


@tool(
    name="find_orphan_modules",
    description=(
        "Lista arquivos que nenhum outro arquivo do workspace importa. NÃO é "
        "uma lista de código morto pronta: pontos de entrada legítimos "
        "(main.py, __init__.py, arquivo de teste, script de migração) também "
        "aparecem aqui, porque de fato ninguém os importa. Confirme cada "
        "candidato (ex. com `code_history` ou lendo o arquivo) antes de "
        "afirmar que é órfão de verdade."
    ),
    risk=RiskClass.READ,
    parameters={"type": "object", "properties": {}},
    summarize=lambda _a: "procurar módulos órfãos",
)
async def find_orphan_modules(ctx: ToolContext, _args: dict[str, Any]) -> ToolResult:
    if ctx.indexer is None:
        return ToolResult.failure("Índice de contexto indisponível.")

    workspace = ctx.indexer.workspace_key(Path(ctx.workspace_root))
    async with session_scope() as session:
        orphans = await context_store.orphan_modules(session, workspace=workspace)

    if not orphans:
        return ToolResult(ok=True, content="Nenhum candidato a módulo órfão.", data={"orphans": []})

    linhas = [f"{len(orphans)} candidato(s) — confirme antes de tratar como código morto:"]
    linhas.extend(f"  {path}" for path in orphans)
    return ToolResult(ok=True, content="\n".join(linhas), data={"orphans": orphans})
