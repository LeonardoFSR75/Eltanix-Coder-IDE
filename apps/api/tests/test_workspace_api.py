"""Rotas do workspace usadas pelo editor.

O ponto crítico: elas usam o mesmo `WorkspaceFS` do agente, então a fronteira de
caminho vale igual pelo editor e pelo agente. Duas implementações da mesma
fronteira acabariam divergindo.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ["SICOOBITO_API_KEY"] = "chave-de-teste"
os.environ["REDIS_URL"] = "redis://localhost:65533/0"

from sicoobito.config import get_settings
from sicoobito.main import create_app

AUTH = {"Authorization": "Bearer chave-de-teste"}


@pytest.fixture(scope="module")
def workspace(tmp_path_factory):
    root = tmp_path_factory.mktemp("workspace")
    (root / "src").mkdir()
    # `write_bytes` e não `write_text`: no Windows o segundo traduziria \n para
    # \r\n e o teste passaria a medir a tradução do Python, não a rota.
    (root / "src" / "app.py").write_bytes(b"x = 1\n")
    (root / "README.md").write_bytes(b"# Projeto\n")
    (root.parent / "fora.txt").write_bytes(b"segredo")
    return root


@pytest.fixture(scope="module")
def client(workspace):
    os.environ["WORKSPACE_ROOT"] = str(workspace)
    get_settings.cache_clear()
    with TestClient(create_app()) as test_client:
        yield test_client
    os.environ.pop("WORKSPACE_ROOT", None)
    get_settings.cache_clear()


def test_tree_lists_the_workspace_root(client):
    resposta = client.get("/api/workspace/tree", headers=AUTH)
    assert resposta.status_code == 200

    nomes = {e["name"] for e in resposta.json()["entries"]}
    assert {"src", "README.md"} <= nomes


def test_tree_reports_language_per_file(client):
    entries = client.get("/api/workspace/tree", headers=AUTH).json()["entries"]
    por_nome = {e["name"]: e for e in entries}
    assert por_nome["README.md"]["language"] == "markdown"
    assert por_nome["src"]["is_dir"] is True


def test_read_file_returns_content_and_language(client):
    resposta = client.get("/api/workspace/file", params={"path": "src/app.py"}, headers=AUTH)
    assert resposta.status_code == 200

    corpo = resposta.json()
    assert corpo["content"] == "x = 1\n"
    assert corpo["language"] == "python"


def test_read_outside_the_workspace_is_forbidden(client):
    resposta = client.get("/api/workspace/file", params={"path": "../fora.txt"}, headers=AUTH)
    assert resposta.status_code == 403


def test_write_then_read_round_trips(client):
    escrita = client.put(
        "/api/workspace/file",
        json={"path": "src/novo.py", "content": "y = 2\n"},
        headers=AUTH,
    )
    assert escrita.status_code == 200

    leitura = client.get("/api/workspace/file", params={"path": "src/novo.py"}, headers=AUTH)
    assert leitura.json()["content"] == "y = 2\n"


def test_write_outside_the_workspace_is_forbidden(client):
    resposta = client.put(
        "/api/workspace/file",
        json={"path": "../invasao.txt", "content": "x"},
        headers=AUTH,
    )
    assert resposta.status_code == 403


def test_missing_file_returns_404(client):
    resposta = client.get("/api/workspace/file", params={"path": "nao-existe.py"}, headers=AUTH)
    assert resposta.status_code == 404


def test_workspace_routes_require_the_api_key(client):
    assert client.get("/api/workspace/tree").status_code == 401


def test_terminal_ticket_is_issued_for_authenticated_callers(client):
    resposta = client.post("/api/workspace/terminal/abc/ticket", headers=AUTH)
    assert resposta.status_code == 200

    corpo = resposta.json()
    assert len(corpo["ticket"]) >= 32
    assert corpo["expires_in"] > 0


def test_terminal_websocket_refuses_a_bogus_ticket(client):
    # O Starlette recusa o handshake antes do accept, então a conexão nunca se
    # estabelece — o formato exato da recusa varia com a versão, mas o que
    # importa é que não abre.
    with pytest.raises(Exception) as erro:
        with client.websocket_connect("/api/workspace/terminal/abc?ticket=inventado"):
            pass

    assert "WebSocket" in type(erro.value).__name__ or "4401" in str(erro.value)


def test_terminal_websocket_accepts_a_valid_ticket(client):
    """O teste de recusa acima passava pelo motivo errado.

    A rota WebSocket herdava a dependência de autenticação por header do router,
    e o browser não consegue enviar `Authorization` ao abrir um WebSocket —
    então *toda* conexão morria antes de o ticket ser avaliado, e o mecanismo de
    ticket era código morto. Um teste que só afirma "falhou" passa por qualquer
    motivo; este exige que o handshake **complete**.
    """
    ticket = client.post(
        "/api/workspace/terminal/sessao-x/ticket", headers=AUTH
    ).json()["ticket"]

    with client.websocket_connect(f"/api/workspace/terminal/sessao-x?ticket={ticket}") as ws:
        # Conexão aceita. A sessão não existe neste teste, então o servidor
        # informa isso pelo próprio canal — o que só é possível após o accept.
        mensagem = ws.receive_json()
        assert mensagem["type"] == "error"
        assert "sessao-x" in mensagem["message"]


def test_agent_tools_endpoint_exposes_risk_classes(client):
    resposta = client.get("/api/agent/tools", headers=AUTH)
    assert resposta.status_code == 200

    por_nome = {t["name"]: t for t in resposta.json()["tools"]}
    assert por_nome["read_file"]["requires_approval"] is False
    assert por_nome["run_command"]["requires_approval"] is True
    assert por_nome["run_command"]["risk"] == "exec"
