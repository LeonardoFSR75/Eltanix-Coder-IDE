"""POST /api/agent/inline-edit — edição inline estilo Cmd+K (Fase 7 do upgrade
do agente).

Fora do grafo do LangGraph de propósito: uma chamada isolada ao router (mesmo
padrão de `agent/review_common.py`, engine falso aqui) mais o reaproveitamento
de `ApprovalPolicy`/`evaluate_policy` já existentes — sem Postgres/Redis reais.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient

os.environ["NOVAAI_STUDIO_API_KEY"] = "chave-de-teste"
os.environ["REDIS_URL"] = "redis://localhost:65533/0"

from novaai_studio.config import get_settings
from novaai_studio.main import create_app

AUTH = {"Authorization": "Bearer chave-de-teste"}


@dataclass
class _FakeCompletionResult:
    payload: dict[str, Any] = field(default_factory=dict)


class _FakeEngine:
    """Mesmo padrão de `test_review_common.py::_FakeEngine` — sem rede."""

    def __init__(self, resposta: str) -> None:
        self.resposta = resposta
        self.chamadas: list[dict[str, Any]] = []

    async def complete(self, *, requested_model, params, source, session_id=None):
        self.chamadas.append(
            {"requested_model": requested_model, "params": params, "source": source}
        )
        return _FakeCompletionResult(payload={"choices": [{"message": {"content": self.resposta}}]})


def _write_app_py(root) -> None:
    (root / "src").mkdir()
    (root / "src" / "app.py").write_bytes(b"def soma(a, b):\n    return a + b\n")


@pytest.fixture(scope="module")
def workspace(tmp_path_factory):
    """Raiz de projetos com dois projetos, não um só mutado entre testes:
    `demo` (sem política de auto-aprovação) e `demo-auto` (com uma regra já
    configurada) — dois projetos em vez de escrever `.novaai_studio/` dentro de
    um teste, para o resultado de um teste nunca depender da ordem em que os
    outros rodaram. Escopo de módulo (mesmo padrão de
    `test_workspace_api.py`): subir o app inteiro (lifespan com retry/backoff
    de Redis/MinIO ausentes) é caro, então uma vez por arquivo, não por teste.
    """
    projects_root = tmp_path_factory.mktemp("projetos")

    demo = projects_root / "demo"
    demo.mkdir()
    _write_app_py(demo)

    demo_auto = projects_root / "demo-auto"
    demo_auto.mkdir()
    _write_app_py(demo_auto)
    (demo_auto / ".novaai_studio").mkdir()
    (demo_auto / ".novaai_studio" / "approval_policy.yaml").write_text(
        "version: 1\n"
        "second_opinion: false\n"
        "rules:\n"
        "  - kind: edit_path_glob\n"
        "    tools: [edit_file]\n"
        "    path_glob: 'src/*.py'\n"
        "    max_changed_lines: 50\n"
    )

    return projects_root


@pytest.fixture(scope="module")
def client(workspace):
    os.environ["PROJECTS_ROOT"] = str(workspace)
    get_settings.cache_clear()
    with TestClient(create_app()) as test_client:
        yield test_client
    os.environ.pop("PROJECTS_ROOT", None)
    get_settings.cache_clear()


def _set_engine(client: TestClient, resposta: str) -> _FakeEngine:
    engine = _FakeEngine(resposta)
    client.app.state.engine = engine
    return engine


def test_not_auto_approved_returns_diff_without_writing(client, workspace):
    _set_engine(client, "    return a + b + 1")

    resposta = client.post(
        "/api/agent/inline-edit",
        json={
            "project": "demo",
            "path": "src/app.py",
            "selected_text": "    return a + b",
            "instruction": "soma 1 ao resultado",
            "context_before": "def soma(a, b):\n",
            "context_after": "",
        },
        headers=AUTH,
    )
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["applied"] is False
    assert corpo["auto_approved_reason"] is None
    assert corpo["new_text"] == "    return a + b + 1"
    assert corpo["changed_lines"] >= 1
    assert "return a + b + 1" in corpo["after"]

    # Sem política de auto-aprovação, o arquivo no disco não muda.
    conteudo_no_disco = (workspace / "demo" / "src" / "app.py").read_text()
    assert "return a + b + 1" not in conteudo_no_disco


def test_auto_approved_by_policy_writes_the_file(client, workspace):
    _set_engine(client, "    return a + b + 1")

    resposta = client.post(
        "/api/agent/inline-edit",
        json={
            "project": "demo-auto",
            "path": "src/app.py",
            "selected_text": "    return a + b",
            "instruction": "soma 1 ao resultado",
        },
        headers=AUTH,
    )
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["applied"] is True
    assert corpo["auto_approved_reason"] is not None

    conteudo_no_disco = (workspace / "demo-auto" / "src" / "app.py").read_text()
    assert "return a + b + 1" in conteudo_no_disco


def test_ambiguous_selection_is_rejected(client):
    _set_engine(client, "não deveria ser chamado")

    resposta = client.post(
        "/api/agent/inline-edit",
        json={
            "project": "demo",
            "path": "src/app.py",
            "selected_text": "texto que não existe no arquivo",
            "instruction": "qualquer coisa",
        },
        headers=AUTH,
    )
    assert resposta.status_code == 409


def test_strips_markdown_fence_from_model_response(client, workspace):
    _set_engine(client, "```python\n    return a + b + 1\n```")

    resposta = client.post(
        "/api/agent/inline-edit",
        json={
            "project": "demo",
            "path": "src/app.py",
            "selected_text": "    return a + b",
            "instruction": "soma 1 ao resultado",
        },
        headers=AUTH,
    )
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert "```" not in corpo["new_text"]
    assert corpo["new_text"] == "    return a + b + 1"


def test_requires_auth(client):
    resposta = client.post(
        "/api/agent/inline-edit",
        json={
            "project": "demo",
            "path": "src/app.py",
            "selected_text": "    return a + b",
            "instruction": "qualquer coisa",
        },
    )
    assert resposta.status_code == 401
