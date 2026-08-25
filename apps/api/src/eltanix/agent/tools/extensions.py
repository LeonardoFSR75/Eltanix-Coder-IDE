"""Ferramenta de gestão de extensões da IDE para o agente.

Simetria com `agent/tools/packages.py`: dá ao agente a mesma visão e controle
que o usuário tem no painel de Extensões (`ExtensionsPanel.tsx`), em vez de
deixar o catálogo visível só no frontend. `list`/`search`/`recommend` são
somente leitura; `toggle`/`update`/`update_all`/`sync` mudam estado
persistido em Postgres (`extensions/store.py`) e, quando a extensão tem
contraparte de language server (`lsp/extension_bridge.py`), afetam
imediatamente quais servidores LSP o editor consegue abrir.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from eltanix.agent.tools.base import RiskClass, ToolContext, ToolResult, tool
from eltanix.db.session import session_scope
from eltanix.logging_setup import get_logger
from eltanix.lsp.extension_bridge import LSP_SERVER_TO_EXTENSION_ID

log = get_logger(__name__)

_READ_ACTIONS = {"list", "search", "recommend"}


def _extensions_risk(args: dict[str, Any], _context: ToolContext | None = None) -> RiskClass:
    action = (args.get("action") or "list").strip().lower()
    return RiskClass.READ if action in _READ_ACTIONS else RiskClass.WRITE


# Heurística simples ecossistema/arquivo → extensões do catálogo que valem a
# pena sugerir. Não tenta ser exaustiva — só cobre os casos onde o catálogo
# tem uma extensão de linguagem/framework claramente correspondente.
_RECOMMEND_BY_ECOSYSTEM: dict[str, tuple[str, ...]] = {
    "python": ("ms-python.python", "meta.pyrefly", "ms-python.debugpy"),
    "nodejs": ("eamodio.gitlens", "usernamehw.errorlens"),
    "go": ("eamodio.gitlens",),
    "rust": ("eamodio.gitlens",),
    "php": ("eamodio.gitlens",),
}
_RECOMMEND_BY_FILE_MARKER: tuple[tuple[str, str], ...] = (
    ("tailwind.config.js", "tailwindcss.vscode-tailwindcss"),
    ("tailwind.config.ts", "tailwindcss.vscode-tailwindcss"),
    ("vite.config.ts", "usernamehw.errorlens"),
    ("playwright.config.ts", "eltanix.playwright-visual-studio"),
    ("docker-compose.yml", "eltanix.minio-storage-explorer"),
)


@tool(
    name="manage_extensions",
    description=(
        "Gerencia as extensões da IDE agêntica (catálogo estilo VS Code/Open VSX). Use "
        "'list' para ver o que está instalado/ativo, 'search' para procurar no Open VSX "
        "Registry, 'recommend' para sugerir extensões relevantes ao projeto atual, "
        "'toggle' para ativar/desativar uma extensão pelo id, 'update'/'update_all' para "
        "atualizar o número de versão registrado (não instala binário — ver nota na "
        "resposta), e 'sync' para sincronizar com o marketplace. Extensões desativadas que "
        "correspondem a um language server (ex: 'ms-python.python' → pyright) bloqueiam "
        "aquele servidor até serem reativadas."
    ),
    risk=_extensions_risk,
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "search", "recommend", "toggle", "update", "update_all", "sync"],
                "description": "Ação a realizar",
            },
            "extension_id": {
                "type": "string",
                "description": (
                    "Id da extensão no catálogo (ex: 'ms-python.python') — "
                    "obrigatório em toggle/update"
                ),
            },
            "active": {
                "type": "boolean",
                "description": (
                    "Novo estado explícito para 'toggle' (omitir inverte o estado atual)"
                ),
            },
            "query": {
                "type": "string",
                "description": "Termo de busca — obrigatório em 'search'",
            },
        },
        "required": ["action"],
    },
    summarize=(
        lambda a: (
            f"gerenciar extensões ({a.get('action')}, "
            f"id={a.get('extension_id') or a.get('query') or 'N/A'})"
        )
    ),
)
async def manage_extensions(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    mgr = ctx.extensions_manager
    if mgr is None:
        return ToolResult.failure("ExtensionsManager indisponível nesta sessão.")

    action = (args.get("action") or "list").strip().lower()

    if action == "list":
        catalog = mgr.get_catalog()
        items = catalog["extensions"]
        ativas = [i for i in items if i.get("active")]
        content = (
            f"=== Extensões ({catalog['total_count']} no catálogo, {len(ativas)} ativas) ===\n"
            f"Updates pendentes: {catalog['pending_updates_count']} | "
            f"Auto-update: {'ligado' if catalog['auto_update_enabled'] else 'desligado'}\n"
        )
        if ativas:
            amostra = ", ".join(f"{i['id']}@{i['version']}" for i in ativas[:15])
            content += f"Ativas (primeiras 15): {amostra}\n"
        return ToolResult(ok=True, content=content, data=catalog)

    if action == "search":
        query = (args.get("query") or "").strip()
        if not query:
            return ToolResult.failure("O parâmetro 'query' é obrigatório para 'search'.")
        results = await mgr.search_online(query)
        content = f"=== Busca no Open VSX por '{query}' ({len(results)} resultado(s)) ===\n"
        if results:
            content += "\n".join(
                f"- {r.get('id')}: {r.get('description', '')}" for r in results[:10]
            )
        return ToolResult(
            ok=True,
            content=content,
            data={"query": query, "results": results, "count": len(results)},
        )

    if action == "recommend":
        from eltanix.api.routes.packages import detect_ecosystem

        project_path = Path(ctx.workspace_root)
        eco = detect_ecosystem(project_path)
        catalog = mgr.get_catalog()
        by_id = {item["id"]: item for item in catalog["extensions"]}

        candidatos = list(_RECOMMEND_BY_ECOSYSTEM.get(eco, ()))
        for marker, ext_id in _RECOMMEND_BY_FILE_MARKER:
            if (project_path / marker).exists():
                candidatos.append(ext_id)

        # Também sinaliza os servidores LSP com extensão correspondente ainda
        # desligada, já que são os que mais visivelmente quebram o editor.
        for ext_id in LSP_SERVER_TO_EXTENSION_ID.values():
            item = by_id.get(ext_id)
            if item is not None and not item.get("active") and ext_id not in candidatos:
                candidatos.append(ext_id)

        vistos: set[str] = set()
        recomendadas: list[dict[str, Any]] = []
        for ext_id in candidatos:
            if ext_id in vistos:
                continue
            vistos.add(ext_id)
            item = by_id.get(ext_id)
            if item is None:
                continue
            recomendadas.append(item)

        if not recomendadas:
            return ToolResult(
                ok=True,
                content=f"Nenhuma recomendação específica para o ecossistema '{eco}' detectado.",
                data={"ecosystem": eco, "recommended": []},
            )

        content = f"=== Recomendadas para este projeto (ecossistema: {eco}) ===\n"
        content += "\n".join(
            f"- {i['id']} ({'ativa' if i.get('active') else 'INATIVA'}): {i.get('description', '')}"
            for i in recomendadas
        )
        return ToolResult(
            ok=True, content=content, data={"ecosystem": eco, "recommended": recomendadas}
        )

    if action == "toggle":
        extension_id = (args.get("extension_id") or "").strip()
        if not extension_id:
            return ToolResult.failure("O parâmetro 'extension_id' é obrigatório para 'toggle'.")
        active = args.get("active")
        async with session_scope() as session:
            new_state = await mgr.toggle_extension(session, extension_id, active=active)
        if new_state is None:
            return ToolResult.failure(f"Extensão '{extension_id}' não existe no catálogo.")
        return ToolResult(
            ok=True,
            content=f"Extensão '{extension_id}' agora está {'ativa' if new_state else 'inativa'}.",
            data={"id": extension_id, "active": new_state},
        )

    if action == "update":
        extension_id = (args.get("extension_id") or "").strip()
        if not extension_id:
            return ToolResult.failure("O parâmetro 'extension_id' é obrigatório para 'update'.")
        async with session_scope() as session:
            success = await mgr.update_extension(session, extension_id)
        if not success:
            return ToolResult.failure(
                f"Extensão '{extension_id}' não tem atualização pendente ou não existe."
            )
        return ToolResult(
            ok=True,
            content=(
                f"Versão registrada de '{extension_id}' atualizada para a mais recente do Open VSX "
                "(metadado apenas — nenhum binário foi baixado)."
            ),
            data={"id": extension_id, "updated": True, "metadata_only": True},
        )

    if action == "update_all":
        async with session_scope() as session:
            count = await mgr.update_all_extensions(session)
        return ToolResult(
            ok=True,
            content=f"{count} extensão(ões) atualizada(s) (metadado apenas).",
            data={"updated_count": count, "metadata_only": True},
        )

    if action == "sync":
        async with session_scope() as session:
            catalog = await mgr.sync_with_marketplace(session, force=True)
        return ToolResult(
            ok=True,
            content=(
                f"Sincronizado com o Open VSX Registry. "
                f"{catalog['pending_updates_count']} atualização(ões) pendente(s)."
            ),
            data=catalog,
        )

    return ToolResult.failure(f"Ação desconhecida: {action}")
