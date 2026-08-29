"""Lote 2 / item 85 — o invariante do ADR 0005 ("login obrigatório: toda rota
usa `AuthDep`, nunca fica aberta por omissão") virando teste executável.

Em vez de inspecionar a árvore de dependências (frágil: o FastAPI 0.141 monta
os routers incluídos de forma preguiçosa via `_IncludedRouter`, então
`app.routes` não é mais a lista achatada de `APIRoute`), este teste **bate em
cada rota do schema OpenAPI sem nenhuma credencial** e exige `401`. É
comportamento observável, imune a mudança de plumbing interno do framework.

Rotas WebSocket não aparecem no schema OpenAPI e não entram aqui — a auth
delas é feita dentro do handler (ver `api/routes/browser.py`, `lsp.py`,
`workspace.py`).
"""

from __future__ import annotations

import os
import re

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ELTANIX_API_KEY", "chave-de-teste")
os.environ.setdefault("REDIS_URL", "redis://localhost:65533/0")

from eltanix.config import get_settings
from eltanix.main import create_app

# (método, path) que podem responder sem credencial, com o porquê. Qualquer
# outra rota tem de devolver 401 sem auth.
ROTAS_PUBLICAS_POR_DESIGN: set[tuple[str, str]] = {
    ("GET", "/"),  # meta: nome/versão/base-url, sem dado sensível
    ("POST", "/api/auth/login"),  # o único jeito de obter uma sessão
}

# Valores concretos para placeholders de path — o recurso não precisa existir:
# se a auth funciona, o 401 vem antes de qualquer 404.
_SUBSTITUICOES_DE_PARAM = {
    "slug": "proj-inexistente",
    "project": "proj-inexistente",
    "session_id": "sess-inexistente",
    "id": "id-inexistente",
    "name": "nome-inexistente",
    "path": "arquivo.txt",
    "language": "python",
    "card_id": "card-inexistente",
    "filename": "arquivo.txt",
    "key": "chave-inexistente",
}


def _preencher_path(template: str) -> str:
    def _sub(m: re.Match[str]) -> str:
        nome = m.group(1).split(":")[0]
        return _SUBSTITUICOES_DE_PARAM.get(nome, "x")

    return re.sub(r"\{([^}]+)\}", _sub, template)


@pytest.fixture(scope="module")
def client():
    get_settings.cache_clear()
    with TestClient(create_app()) as c:
        yield c


def test_toda_rota_do_openapi_responde_401_sem_credencial(client):
    schema = client.app.openapi()
    violacoes: list[str] = []

    for template, operacoes in schema["paths"].items():
        for metodo, _detalhe in operacoes.items():
            if metodo.lower() not in ("get", "post", "put", "patch", "delete"):
                continue
            metodo_up = metodo.upper()
            if (metodo_up, template) in ROTAS_PUBLICAS_POR_DESIGN:
                continue

            url = _preencher_path(template)
            resp = client.request(metodo_up, url, json={})
            if resp.status_code != 401:
                violacoes.append(f"{metodo_up} {template} -> {resp.status_code} (esperado 401)")

    assert not violacoes, (
        "Rotas que respondem sem credencial (viola ADR 0005 — login "
        "obrigatório):\n  " + "\n  ".join(sorted(violacoes))
    )


def test_allowlist_bate_com_rotas_reais(client):
    """Entrada de allowlist que não corresponde a nenhuma rota real vira lixo
    que mascara regressão. `GET /` não está no schema OpenAPI por ser meta —
    é checado à parte."""
    schema = client.app.openapi()
    pares_reais = {
        (metodo.upper(), template)
        for template, ops in schema["paths"].items()
        for metodo in ops
        if metodo.lower() in ("get", "post", "put", "patch", "delete")
    }
    pares_reais.add(("GET", "/"))  # meta, fora do schema

    orfas = ROTAS_PUBLICAS_POR_DESIGN - pares_reais
    assert not orfas, f"Entradas da allowlist sem rota correspondente: {orfas}"


def test_get_raiz_e_publico_de_proposito(client):
    assert client.get("/").status_code == 200
