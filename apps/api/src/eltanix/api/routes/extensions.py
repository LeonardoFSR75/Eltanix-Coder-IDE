"""Rotas da API para gerenciamento de extensões, catálogo e atualização automática."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from eltanix.api.deps import AuthDep
from eltanix.db.session import session_scope
from eltanix.extensions.manager import get_extensions_manager
from eltanix.logging_setup import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/api/extensions", tags=["extensions"], dependencies=[AuthDep])


class ToggleExtensionRequest(BaseModel):
    active: bool | None = None


class AutoUpdateRequest(BaseModel):
    enabled: bool


@router.get("/catalog")
async def get_catalog() -> dict[str, Any]:
    """Retorna o catálogo de extensões instaladas com informações de atualização pendente."""
    mgr = get_extensions_manager()
    return mgr.get_catalog()


@router.post("/sync")
async def sync_extensions(force: bool = Query(default=True)) -> dict[str, Any]:
    """Dispara sincronização ativa contra os repositórios oficiais Open VSX / VS Code."""
    mgr = get_extensions_manager()
    async with session_scope() as session:
        return await mgr.sync_with_marketplace(session, force=force)


@router.post("/{extension_id}/toggle")
async def toggle_extension(
    extension_id: str, payload: ToggleExtensionRequest | None = None
) -> dict[str, Any]:
    """Ativa ou desativa uma extensão específica. Quando ligada a um servidor
    LSP (ver `lsp/extension_bridge.py`), desligar aqui bloqueia novas sessões
    daquele servidor até reativar."""
    mgr = get_extensions_manager()
    req_active = payload.active if payload else None
    async with session_scope() as session:
        new_state = await mgr.toggle_extension(session, extension_id, active=req_active)
    if new_state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Extensão '{extension_id}' não existe no catálogo.",
        )
    return {"id": extension_id, "active": new_state}


@router.post("/{extension_id}/update")
async def update_extension(extension_id: str) -> dict[str, Any]:
    """Atualiza o número de versão registrado de uma extensão para o que o
    Open VSX Registry reporta como mais recente (dado real, vindo de
    `OpenVSXClient.check_updates_batch`). **Não baixa nem instala binário
    algum** — este catálogo não roda extensões de verdade, é o inventário que
    o agente/LSP consultam (ver `manager.py`); `metadata_only=true` na
    resposta deixa isso explícito para quem chama."""
    mgr = get_extensions_manager()
    async with session_scope() as session:
        success = await mgr.update_extension(session, extension_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Extensão '{extension_id}' não possui atualização pendente ou não existe.",
        )
    return {"id": extension_id, "updated": True, "metadata_only": True}


@router.post("/update-all")
async def update_all_extensions() -> dict[str, Any]:
    """Aplica todas as atualizações de metadado pendentes de uma só vez (ver
    ressalva de `update_extension` acima — `metadata_only=true`)."""
    mgr = get_extensions_manager()
    async with session_scope() as session:
        updated_count = await mgr.update_all_extensions(session)
    return {"updated_count": updated_count, "metadata_only": True, "catalog": mgr.get_catalog()}


@router.post("/auto-update")
async def set_auto_update(payload: AutoUpdateRequest) -> dict[str, Any]:
    """Configura o modo de atualização automática."""
    mgr = get_extensions_manager()
    async with session_scope() as session:
        enabled = await mgr.set_auto_update(session, payload.enabled)
    return {"auto_update_enabled": enabled}


@router.get("/search")
async def search_online_marketplace(q: str = Query(..., min_length=2)) -> dict[str, Any]:
    """Pesquisa extensões públicas online no Open VSX Registry (cacheado no
    Redis por alguns minutos — ver `extensions/manager.py::search_online`)."""
    mgr = get_extensions_manager()
    results = await mgr.search_online(q)
    return {"query": q, "results": results, "count": len(results)}
