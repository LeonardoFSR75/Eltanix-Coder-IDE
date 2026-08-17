"""Rotas da API para gerenciamento de extensões, catálogo e atualização automática.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from sicoobito.api.deps import AuthDep
from sicoobito.extensions.manager import get_extensions_manager
from sicoobito.logging_setup import get_logger

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
    return await mgr.sync_with_marketplace(force=force)


@router.post("/{extension_id}/toggle")
async def toggle_extension(extension_id: str, payload: ToggleExtensionRequest | None = None) -> dict[str, Any]:
    """Ativa ou desativa uma extensão específica."""
    mgr = get_extensions_manager()
    req_active = payload.active if payload else None
    new_state = mgr.toggle_extension(extension_id, active=req_active)
    return {"id": extension_id, "active": new_state}


@router.post("/{extension_id}/update")
async def update_extension(extension_id: str) -> dict[str, Any]:
    """Atualiza uma extensão específica para a versão mais recente upstream."""
    mgr = get_extensions_manager()
    success = mgr.update_extension(extension_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Extensão '{extension_id}' não possui atualização pendente ou não existe.",
        )
    return {"id": extension_id, "updated": True}


@router.post("/update-all")
async def update_all_extensions() -> dict[str, Any]:
    """Aplica todas as atualizações pendentes de uma só vez."""
    mgr = get_extensions_manager()
    updated_count = mgr.update_all_extensions()
    return {"updated_count": updated_count, "catalog": mgr.get_catalog()}


@router.post("/auto-update")
async def set_auto_update(payload: AutoUpdateRequest) -> dict[str, Any]:
    """Configura o modo de atualização automática."""
    mgr = get_extensions_manager()
    enabled = mgr.set_auto_update(payload.enabled)
    return {"auto_update_enabled": enabled}


@router.get("/search")
async def search_online_marketplace(q: str = Query(..., min_length=2)) -> dict[str, Any]:
    """Pesquisa extensões públicas online no Open VSX Registry."""
    mgr = get_extensions_manager()
    results = await mgr.search_online(q)
    return {"query": q, "results": results, "count": len(results)}
