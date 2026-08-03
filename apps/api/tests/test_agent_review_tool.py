"""`request_code_review`: segunda opinião isolada da conversa principal.

Sem Postgres/Redis — só um repositório Git real (para o diff) e um `engine`
falso (para não depender de um provedor de LLM de verdade).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from git import Repo

from sicoobito.agent.tools import ToolContext
from sicoobito.agent.tools.review import request_code_review as _request_code_review_tool
from sicoobito.workspace.fs import WorkspaceFS

# O decorador `@tool` devolve um `Tool` (dataclass), não a função crua — o
# handler de verdade é `.handler`, mesma convenção de test_agent_tools.py.
request_code_review = _request_code_review_tool.handler


@pytest.fixture
def repo(tmp_path):
    caminho = tmp_path / "projeto"
    caminho.mkdir()
    repositorio = Repo.init(caminho, initial_branch="main")
    with repositorio.config_writer() as config:
        config.set_value("user", "name", "Teste")
        config.set_value("user", "email", "teste@exemplo.com")

    (caminho / "app.py").write_text("print('v1')\n", encoding="utf-8")
    repositorio.index.add(["app.py"])
    repositorio.index.commit("commit inicial")
    return caminho


@dataclass
class _FakeCompletionResult:
    payload: dict[str, Any] = field(default_factory=dict)


class _FakeEngine:
    def __init__(self, resposta: str) -> None:
        self.resposta = resposta
        self.chamadas: list[dict[str, Any]] = []

    async def complete(self, *, requested_model, params, source):
        self.chamadas.append({"requested_model": requested_model, "source": source})
        return _FakeCompletionResult(
            payload={"choices": [{"message": {"content": self.resposta}}]}
        )


def _ctx(root, engine=None) -> ToolContext:
    return ToolContext(
        session_id="teste",
        workspace_root=root,
        fs=WorkspaceFS(root),
        engine=engine,
    )


async def test_fails_without_engine(repo):
    resultado = await request_code_review(_ctx(repo), {"summary": "x"})
    assert resultado.ok is False
    assert "router" in resultado.content.lower()


async def test_fails_when_nothing_changed(repo):
    engine = _FakeEngine("VEREDITO: APROVADO\nok")
    resultado = await request_code_review(_ctx(repo, engine), {"summary": "x"})
    assert resultado.ok is False
    assert "nada para revisar" in resultado.content.lower()
    assert engine.chamadas == []  # não gasta chamada de LLM sem diff


async def test_approved_verdict_is_parsed(repo):
    (repo / "app.py").write_text("print('v2')\n", encoding="utf-8")
    engine = _FakeEngine("VEREDITO: APROVADO\nMudança pequena e correta.")

    resultado = await request_code_review(_ctx(repo, engine), {"summary": "corrige saída"})

    assert resultado.ok is True
    assert resultado.data["verdict"] == "approved"
    assert engine.chamadas[0]["requested_model"] == "coding"
    assert engine.chamadas[0]["source"] == "agent:code_review"


async def test_needs_revision_verdict_is_parsed(repo):
    (repo / "app.py").write_text("print('v2')\n", encoding="utf-8")
    engine = _FakeEngine("VEREDITO: PRECISA_REVISAO\nFalta teste.")

    resultado = await request_code_review(_ctx(repo, engine), {"summary": "corrige saída"})

    assert resultado.ok is False
    assert resultado.data["verdict"] == "needs_revision"


async def test_unparseable_response_fails_closed(repo):
    (repo / "app.py").write_text("print('v2')\n", encoding="utf-8")
    engine = _FakeEngine("Parece bom, pode seguir.")  # sem o marcador VEREDITO:

    resultado = await request_code_review(_ctx(repo, engine), {"summary": "x"})

    assert resultado.ok is False
    assert resultado.data["verdict"] == "needs_revision"
