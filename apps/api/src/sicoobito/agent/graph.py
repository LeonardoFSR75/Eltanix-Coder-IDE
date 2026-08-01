"""Grafo do agente.

Ciclo: `think` chama o modelo, `approve` interrompe quando há ação de risco,
`act` executa as ferramentas, e volta a `think`. Termina quando o modelo para
de pedir ferramentas ou o teto de iterações é atingido.

Duas decisões estruturam o resto:

**A aprovação é um nó, não um `if` dentro do executor.** Sendo nó, o
`interrupt()` do LangGraph salva o estado no checkpointer e devolve o controle;
a sessão pode ser retomada depois, e a decisão humana fica registrada no
histórico do grafo em vez de viver na memória de um processo.

**O teto de iterações existe.** Um agente sem limite que entra em laço —
tentando a mesma edição que falha, relendo o mesmo arquivo — gasta dinheiro real
até alguém perceber.
"""

from __future__ import annotations

import json
from typing import Any

from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from sicoobito.agent.prompts import APPROVAL_DENIED_TEMPLATE, SYSTEM_PROMPT
from sicoobito.agent.state import AgentState, PendingApproval
from sicoobito.agent.tools import RiskClass, ToolContext, registry
from sicoobito.logging_setup import get_logger
from sicoobito.router.engine import RouterEngine

log = get_logger(__name__)

DEFAULT_MAX_ITERATIONS = 25


def _tool_schemas(mode: str) -> list[dict[str, Any]]:
    """Ferramentas oferecidas por modo.

    Restringir por schema é mais confiável que instruir o modelo a não chamar:
    o que não está na lista não pode ser chamado.
    """
    if mode == "ask":
        return registry.schemas(allow_exec=False, allow_write=False)
    if mode == "edit":
        return registry.schemas(allow_exec=False, allow_write=True)
    return registry.schemas()


def build_graph(engine: RouterEngine, context: ToolContext):
    async def think(state: AgentState) -> dict[str, Any]:
        mensagens = [{"role": "system", "content": SYSTEM_PROMPT}, *state["messages"]]

        resultado = await engine.complete(
            requested_model=state.get("model") or "coding",
            params={
                "messages": mensagens,
                "tools": _tool_schemas(state.get("mode", "agent")),
                "temperature": 0,
            },
            source=f"agent:{state.get('mode', 'agent')}",
        )

        escolha = (resultado.payload.get("choices") or [{}])[0]
        mensagem = escolha.get("message") or {}
        tool_calls = mensagem.get("tool_calls") or []

        atualizacao: dict[str, Any] = {
            "messages": [mensagem],
            "iterations": state.get("iterations", 0) + 1,
            "total_cost_usd": state.get("total_cost_usd", 0.0) + float(resultado.cost_usd),
            "total_tokens": state.get("total_tokens", 0) + resultado.usage.total_tokens,
        }

        if not tool_calls:
            atualizacao["finished"] = True
            atualizacao["result"] = mensagem.get("content") or ""
            return atualizacao

        pendentes: list[PendingApproval] = []
        for chamada in tool_calls:
            nome = (chamada.get("function") or {}).get("name", "")
            ferramenta = registry.get(nome)
            if ferramenta is None or not ferramenta.risk.requires_approval:
                continue
            argumentos = _parse_arguments(chamada)
            pendentes.append(
                PendingApproval(
                    tool_call_id=chamada.get("id", ""),
                    tool=nome,
                    risk=str(ferramenta.risk),
                    arguments=argumentos,
                    summary=ferramenta.describe_call(argumentos),
                )
            )

        atualizacao["pending"] = pendentes
        return atualizacao

    async def approve(state: AgentState) -> dict[str, Any]:
        pendentes = state.get("pending") or []
        if not pendentes:
            return {"approvals": {}}

        # Devolve o controle a quem chamou. Ao retomar, o valor enviado volta
        # como retorno de `interrupt`.
        decisao = interrupt(
            {
                "type": "approval_required",
                "session_id": state.get("session_id"),
                "actions": pendentes,
            }
        )

        aprovacoes: dict[str, bool] = {}
        motivos: dict[str, str] = {}
        for pendente in pendentes:
            item = (decisao or {}).get(pendente["tool_call_id"], {})
            if isinstance(item, bool):
                aprovacoes[pendente["tool_call_id"]] = item
                continue
            # Ausência de decisão explícita é recusa: aprovar por omissão
            # transformaria um erro de UI em escrita não autorizada.
            aprovacoes[pendente["tool_call_id"]] = bool(item.get("approved", False))
            motivos[pendente["tool_call_id"]] = item.get("reason", "")

        return {"approvals": aprovacoes, "approval_reasons": motivos, "pending": []}

    async def act(state: AgentState) -> dict[str, Any]:
        ultima = state["messages"][-1] if state["messages"] else {}
        tool_calls = ultima.get("tool_calls") or []
        aprovacoes = state.get("approvals") or {}
        motivos = state.get("approval_reasons") or {}

        respostas: list[dict[str, Any]] = []
        alterados: list[str] = []
        todos_atualizados: list[dict[str, Any]] | None = None

        for chamada in tool_calls:
            call_id = chamada.get("id", "")
            nome = (chamada.get("function") or {}).get("name", "")
            ferramenta = registry.get(nome)

            if ferramenta is None:
                respostas.append(
                    _tool_message(call_id, nome, f"ERRO: ferramenta desconhecida: {nome}", ok=False)
                )
                continue

            if ferramenta.risk.requires_approval and not aprovacoes.get(call_id, False):
                respostas.append(
                    _tool_message(
                        call_id,
                        nome,
                        APPROVAL_DENIED_TEMPLATE.format(
                            tool=nome, reason=motivos.get(call_id) or "não informado"
                        ),
                        ok=False,
                        data={"denied": True, "reason": motivos.get(call_id) or ""},
                    )
                )
                continue

            argumentos = _parse_arguments(chamada)
            try:
                resultado = await ferramenta.handler(context, argumentos)
            except Exception as exc:
                log.warning("agent.tool.failed", tool=nome, error=str(exc)[:200])
                respostas.append(_tool_message(call_id, nome, f"ERRO: {exc}", ok=False))
                continue

            respostas.append(
                _tool_message(call_id, nome, resultado.content, ok=resultado.ok, data=resultado.data)
            )
            if caminho := resultado.data.get("path"):
                alterados.append(str(caminho))
            if "todos" in resultado.data:
                todos_atualizados = resultado.data["todos"]

        atualizacao: dict[str, Any] = {
            "messages": respostas,
            "files_changed": alterados,
            "approvals": {},
        }
        # Ausente na maioria dos turnos: sem `write_todos` nesta rodada, o
        # checklist da sessão fica como estava — omitir a chave preserva o
        # valor anterior em vez de apagá-lo.
        if todos_atualizados is not None:
            atualizacao["todos"] = todos_atualizados
        return atualizacao

    def route_after_think(state: AgentState) -> str:
        if state.get("finished"):
            return END
        if state.get("iterations", 0) >= state.get("max_iterations", DEFAULT_MAX_ITERATIONS):
            log.warning("agent.iteration_limit", session=state.get("session_id"))
            return END
        return "approve" if state.get("pending") else "act"

    grafo = StateGraph(AgentState)
    grafo.add_node("think", think)
    grafo.add_node("approve", approve)
    grafo.add_node("act", act)

    grafo.set_entry_point("think")
    grafo.add_conditional_edges(
        "think", route_after_think, {"approve": "approve", "act": "act", END: END}
    )
    grafo.add_edge("approve", "act")
    grafo.add_edge("act", "think")
    return grafo


def _parse_arguments(chamada: dict[str, Any]) -> dict[str, Any]:
    """Argumentos vêm como string JSON e nem sempre são válidos."""
    cru = (chamada.get("function") or {}).get("arguments") or "{}"
    if isinstance(cru, dict):
        return cru
    try:
        parsed = json.loads(cru)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _tool_message(
    call_id: str,
    name: str,
    content: str,
    *,
    ok: bool = True,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # `data` carrega o que a ferramenta produziu de estruturado (diff, exit
    # code, hits de busca...) — é o que permite a UI renderizar um card por
    # tipo de ferramenta em vez de uma linha de texto truncado.
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "name": name,
        "content": content,
        "ok": ok,
        "data": data or {},
    }


__all__ = ["DEFAULT_MAX_ITERATIONS", "RiskClass", "build_graph"]
