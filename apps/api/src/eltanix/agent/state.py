"""Estado do grafo do agente."""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, NotRequired, TypedDict

# Os 7 modos embutidos, cada um com bloco de prompt fixo (`agent/prompts.py::
# build_task_prompt`) e gate de ferramentas fixo (`agent/graph.py::
# _tool_schemas`). Qualquer `mode` fora desta lista é tratado como o id (UUID
# em texto) de um modo customizado (Fase 6 do upgrade do agente, ver
# `agent/custom_modes.py`) — resolvido uma única vez na criação da sessão
# (`AgentRunner._resolve_custom_mode`), nunca consultado no banco a cada turno.
BUILTIN_MODES: frozenset[str] = frozenset(
    {"ask", "edit", "agent", "plan", "auto", "orchestra", "explore"}
)
# Antes um `Literal` fixo dos 7 valores acima — alargado para `str` pela Fase
# 6 para também aceitar o id de um modo customizado. A validação de "isto é um
# modo válido" não é mais responsabilidade do tipo: é responsabilidade de
# `_tool_schemas`/`build_task_prompt` degradarem com segurança (somente
# leitura) quando `mode` não bate com nenhum modo embutido nem customizado
# resolvido.
AgentMode = str


class ReviewNote(TypedDict):
    """Nota consultiva de uma segunda opinião automática (Fase C) — nunca
    decide a aprovação sozinha, só informa o humano que ainda vai decidir."""

    verdict: Literal["approved", "needs_revision", "unavailable"]
    summary: str


class PendingApproval(TypedDict):
    """Chamada de ferramenta aguardando decisão humana."""

    tool_call_id: str
    tool: str
    risk: str
    arguments: dict[str, Any]
    summary: str
    # Presente sempre que a ferramenta é `edit_file`/`write_file` e o diff
    # calcula sem erro — ver `agent/graph.py::_attach_diffs`.
    diff: NotRequired[str]
    # Presente só quando `.eltanix/approval_policy.yaml` liga
    # `second_opinion` e a ferramenta é `edit_file`/`write_file` — ver
    # `agent/graph.py::_attach_review_notes`.
    review: NotRequired[ReviewNote]


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
