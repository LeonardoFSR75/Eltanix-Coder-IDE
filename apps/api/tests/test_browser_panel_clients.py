"""Item 11 do plano de robustez do navegador interno: `app.state.
browser_panel_clients` cresce sem limite quando um painel é abandonado sem
`DELETE /sessions/{id}` explícito (usuário só fecha a aba) — sem cobertura
antes desta mudança.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

from novaai_studio.api.routes.browser import (
    PANEL_CLIENT_IDLE_TTL_SECONDS,
    purge_idle_panel_clients,
)


async def test_purge_removes_only_clients_idle_past_the_ttl():
    agora = time.time()
    state = SimpleNamespace(
        browser_panel_clients={"panel-velho": object(), "panel-ativo": object()},
        browser_panel_client_last_used={
            "panel-velho": agora - PANEL_CLIENT_IDLE_TTL_SECONDS - 10,
            "panel-ativo": agora,
        },
    )

    removidos = await purge_idle_panel_clients(state)

    assert removidos == 1
    assert "panel-velho" not in state.browser_panel_clients
    assert "panel-ativo" in state.browser_panel_clients
    assert "panel-velho" not in state.browser_panel_client_last_used


async def test_purge_treats_missing_last_used_entry_as_fresh():
    # Um cliente sem registro em `last_used` (não deveria acontecer, mas é
    # defensivo) não pode ser removido por engano — trata como recém-usado.
    state = SimpleNamespace(
        browser_panel_clients={"panel-sem-registro": object()},
        browser_panel_client_last_used={},
    )

    removidos = await purge_idle_panel_clients(state)

    assert removidos == 0
    assert "panel-sem-registro" in state.browser_panel_clients


async def test_purge_with_no_clients_is_a_noop():
    state = SimpleNamespace(browser_panel_clients={}, browser_panel_client_last_used={})

    assert await purge_idle_panel_clients(state) == 0
