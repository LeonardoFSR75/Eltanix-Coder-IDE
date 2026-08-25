"""`RouterEngine._prepare_params` — quirks por provedor aplicados ao request.

Não constrói o `RouterEngine` completo (exigiria Redis/Postgres reais para
health/cache/budget): o método só usa `self._apply_prompt_cache`, que por sua
vez só olha `spec`, então `object.__new__` basta.
"""

from __future__ import annotations

from novaai_studio.router.catalog import ModelSpec
from novaai_studio.router.engine import RouterEngine


def _engine() -> RouterEngine:
    return object.__new__(RouterEngine)


def _spec(provider: str) -> ModelSpec:
    return ModelSpec(id=f"{provider}/model", provider=provider)


def test_databricks_com_tools_desliga_parallel_tool_calls():
    # Databricks Foundation Model API (Llama servido) rejeita com 400
    # ("Multiple tool calls are not supported") uma resposta com mais de uma
    # tool_call no mesmo turno — diferente de OpenAI/Anthropic/Groq.
    prepared = _engine()._prepare_params(
        _spec("databricks"), {"messages": [], "tools": [{"type": "function"}]}
    )
    assert prepared["parallel_tool_calls"] is False


def test_databricks_sem_tools_nao_mexe_no_campo():
    prepared = _engine()._prepare_params(_spec("databricks"), {"messages": []})
    assert "parallel_tool_calls" not in prepared


def test_outros_provedores_nao_sao_restringidos():
    prepared = _engine()._prepare_params(
        _spec("groq"), {"messages": [], "tools": [{"type": "function"}]}
    )
    assert "parallel_tool_calls" not in prepared
