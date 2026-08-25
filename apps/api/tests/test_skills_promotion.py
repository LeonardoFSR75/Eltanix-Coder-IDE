"""`skills/promotion.py` (Horizonte 4, item 2 — protótipo mínimo de promoção de
padrões a skills). Sem Postgres real: `session_store.list_sessions` é
monkeypatchado, engine e `SkillService` são dublês — mesmo padrão de
`test_review_common.py` para `agent/review_common.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from eltanix.agent import session_store
from eltanix.skills import promotion


@dataclass
class _FakeCompletionResult:
    payload: dict[str, Any] = field(default_factory=dict)


class _FakeEngine:
    def __init__(self, resposta: str) -> None:
        self.resposta = resposta
        self.chamadas: list[dict[str, Any]] = []

    async def complete(self, *, requested_model, params, source, session_id=None):
        self.chamadas.append(
            {"requested_model": requested_model, "params": params, "source": source}
        )
        return _FakeCompletionResult(payload={"choices": [{"message": {"content": self.resposta}}]})


class _FakeSkillService:
    def __init__(self, nomes: list[str] | None = None) -> None:
        self._skills = [SimpleNamespace(name=n) for n in (nomes or [])]

    async def list_all(self):
        return self._skills


def _registro(session_id: str, task: str, *, failed: int = 0) -> SimpleNamespace:
    return SimpleNamespace(session_id=session_id, task=task, last_failed_call_count=failed)


def _mock_sessions(monkeypatch, registros: list[SimpleNamespace]) -> AsyncMock:
    mock = AsyncMock(return_value=registros)
    monkeypatch.setattr(session_store, "list_sessions", mock)
    return mock


async def test_fewer_than_two_valid_sessions_skips_llm_call(monkeypatch):
    _mock_sessions(monkeypatch, [_registro("a", "única tarefa")])
    engine = _FakeEngine("não deveria ser chamado")

    resultado = await promotion.analyze_recent_sessions(
        db=None, engine=engine, skills=_FakeSkillService()
    )

    assert resultado.candidates == []
    assert resultado.sessions_analyzed == 1
    assert engine.chamadas == []


async def test_sessions_with_failed_calls_are_excluded_from_the_sample(monkeypatch):
    _mock_sessions(
        monkeypatch,
        [
            _registro("a", "corrige bug de autenticação", failed=0),
            _registro("b", "corrige bug de autenticação", failed=2),
        ],
    )
    engine = _FakeEngine('{"candidates": []}')

    resultado = await promotion.analyze_recent_sessions(
        db=None, engine=engine, skills=_FakeSkillService()
    )

    # só "a" sobrevive ao filtro de sucesso — não bate o mínimo de 2 pra chamar o LLM
    assert resultado.sessions_analyzed == 1
    assert engine.chamadas == []


async def test_sessions_with_blank_task_are_excluded(monkeypatch):
    _mock_sessions(
        monkeypatch,
        [
            _registro("a", "  "),
            _registro("b", "adiciona endpoint de exportação CSV"),
            _registro("c", "adiciona endpoint de exportação CSV"),
        ],
    )
    engine = _FakeEngine('{"candidates": []}')

    resultado = await promotion.analyze_recent_sessions(
        db=None, engine=engine, skills=_FakeSkillService()
    )

    assert resultado.sessions_analyzed == 2
    assert len(engine.chamadas) == 1


async def test_parses_valid_json_candidates(monkeypatch):
    _mock_sessions(
        monkeypatch,
        [
            _registro("a", "adiciona endpoint de exportação CSV"),
            _registro("b", "adiciona endpoint de exportação CSV para relatórios"),
        ],
    )
    resposta = (
        '{"candidates": [{"name": "export-csv-endpoint", '
        '"description": "cria endpoint de exportação CSV", '
        '"category": "code", "rationale": "sessões a e b", '
        '"system_prompt_suggestion": "Você cria endpoints de exportação..."}]}'
    )
    engine = _FakeEngine(resposta)

    resultado = await promotion.analyze_recent_sessions(
        db=None, engine=engine, skills=_FakeSkillService()
    )

    assert resultado.unparseable is False
    assert len(resultado.candidates) == 1
    candidato = resultado.candidates[0]
    assert candidato.name == "export-csv-endpoint"
    assert candidato.category == "code"


async def test_unknown_category_falls_back_to_automation(monkeypatch):
    _mock_sessions(
        monkeypatch,
        [
            _registro("a", "tarefa x"),
            _registro("b", "tarefa x"),
        ],
    )
    resposta = '{"candidates": [{"name": "algo", "category": "inventada"}]}'
    engine = _FakeEngine(resposta)

    resultado = await promotion.analyze_recent_sessions(
        db=None, engine=engine, skills=_FakeSkillService()
    )

    assert resultado.candidates[0].category == "automation"


async def test_unparseable_response_returns_no_candidates_but_keeps_raw_text(monkeypatch):
    _mock_sessions(
        monkeypatch,
        [
            _registro("a", "tarefa x"),
            _registro("b", "tarefa x"),
        ],
    )
    engine = _FakeEngine("desculpe, não consigo ajudar com isso")

    resultado = await promotion.analyze_recent_sessions(
        db=None, engine=engine, skills=_FakeSkillService()
    )

    assert resultado.candidates == []
    assert resultado.unparseable is True
    assert "não consigo" in resultado.raw_text


async def test_strips_markdown_code_fence_before_parsing(monkeypatch):
    _mock_sessions(
        monkeypatch,
        [
            _registro("a", "tarefa x"),
            _registro("b", "tarefa x"),
        ],
    )
    resposta = '```json\n{"candidates": [{"name": "algo"}]}\n```'
    engine = _FakeEngine(resposta)

    resultado = await promotion.analyze_recent_sessions(
        db=None, engine=engine, skills=_FakeSkillService()
    )

    assert resultado.unparseable is False
    assert resultado.candidates[0].name == "algo"


async def test_prompt_lists_existing_skills_and_session_tasks(monkeypatch):
    _mock_sessions(
        monkeypatch,
        [
            _registro("a", "tarefa recorrente única"),
            _registro("b", "tarefa recorrente única"),
        ],
    )
    engine = _FakeEngine('{"candidates": []}')

    await promotion.analyze_recent_sessions(
        db=None,
        engine=engine,
        skills=_FakeSkillService(["skill-existente"]),
        source="teste:promotion",
    )

    chamada = engine.chamadas[0]
    assert chamada["source"] == "teste:promotion"
    conteudo_usuario = chamada["params"]["messages"][1]["content"]
    assert "skill-existente" in conteudo_usuario
    assert "tarefa recorrente única" in conteudo_usuario
    # nunca participa do histórico de uma sessão de agente
    assert chamada["params"]["messages"][0]["role"] == "system"
