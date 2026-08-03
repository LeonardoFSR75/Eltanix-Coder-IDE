"""Estado do grafo do agente."""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict

AgentMode = Literal["ask", "edit", "agent", "plan", "auto", "orchestra"]


class PendingApproval(TypedDict):
    """Chamada de ferramenta aguardando decisão humana."""

    tool_call_id: str
    tool: str
    risk: str
    arguments: dict[str, Any]
    summary: str


class TodoItem(TypedDict):
    """Um passo do checklist mantido pelo modelo via `write_todos`."""

    content: str
    status: Literal["pending", "in_progress", "completed"]


class AgentState(TypedDict, total=False):
    # Histórico no formato OpenAI. `operator.add` faz o LangGraph acumular em
    # vez de sobrescrever a cada nó.
    messages: Annotated[list[dict[str, Any]], operator.add]

    session_id: str
    task: str
    mode: AgentMode
    model: str

    # Ferramentas que pararam o grafo esperando aprovação.
    pending: list[PendingApproval]
    # Decisões do humano, indexadas por `tool_call_id`: True aprova.
    approvals: dict[str, bool]
    approval_reasons: dict[str, str]

    # Checklist da sessão. Sem `Annotated`/`operator.add` de propósito: cada
    # chamada de `write_todos` reenvia a lista inteira e substitui a anterior,
    # não acumula.
    todos: list[TodoItem]

    # Guard de repetição (`agent/graph.py::_is_stuck_repeat`): fingerprint e
    # contagem da última chamada de ferramenta que falhou, para travar antes
    # de repetir a mesma chamada indefinidamente. Substituído a cada turno,
    # igual a `todos` — não acumula.
    last_failed_call: str | None
    last_failed_call_count: int

    iterations: int
    max_iterations: int
    finished: bool
    result: str

    # Acumuladores para a UI e para o custo da sessão.
    files_changed: Annotated[list[str], operator.add]
    total_cost_usd: float
    total_tokens: int
