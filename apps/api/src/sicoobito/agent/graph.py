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
import time
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

# Mesmo default do RepetitionDetector do projeto MLXCode (kochj23/MLXCode),
# adaptado de nível de token (lá, o app controla a geração local) para nível
# de chamada de ferramenta (aqui, o router fala com APIs externas — não há
# stream de token para inspecionar, só o resultado de cada `tool_call`).
REPETITION_THRESHOLD = 3


def _tool_fingerprint(nome: str, argumentos: dict[str, Any]) -> str:
    """Identifica uma chamada por nome + argumentos, para comparar repetições."""
    return f"{nome}:{json.dumps(argumentos, sort_keys=True, default=str)}"


def _is_stuck_repeat(fingerprint: str, ultima_falha: str | None, contagem: int) -> bool:
    """Verdadeiro quando a MESMA chamada, com os MESMOS argumentos, já falhou
    `REPETITION_THRESHOLD` vezes seguidas sem nenhuma chamada diferente ter
    sido bem-sucedida no meio.

    Um sucesso ou uma falha de outra chamada zeram a contagem (ver
    `_next_repetition_state`) — rodar o mesmo `run_command` várias vezes de
    propósito entre edições (o próprio ciclo do modo Orquestra) nunca aciona
    isto, porque cada falha idêntica só conta se a anterior também foi.
    """
    return fingerprint == ultima_falha and contagem >= REPETITION_THRESHOLD


def _next_repetition_state(
    fingerprint: str, ok: bool, ultima_falha: str | None, contagem: int
) -> tuple[str | None, int]:
    """Próximo `(last_failed_call, last_failed_call_count)` depois de uma chamada."""
    if ok:
        return None, 0
    if fingerprint == ultima_falha:
        return fingerprint, contagem + 1
    return fingerprint, 1


def _tool_schemas(mode: str, has_plan: bool) -> list[dict[str, Any]]:
    """Ferramentas oferecidas por modo.

    Restringir por schema é mais confiável que instruir o modelo a não chamar:
    o que não está na lista não pode ser chamado.

    `plan`/`orchestra` sem `has_plan` caem na mesma lista de `ask` — leitura e
    `write_todos` (RiskClass.READ, já incluído), nada de escrever ou
    executar. Sem isto, só a instrução no prompt pedia "planeje primeiro", e
    nada impedia o modelo de pular direto para editar/executar sem nunca
    chamar `write_todos` — o "Modo Planejar" na prática não mostrava plano
    nenhum, só executava como o modo agente comum. `orchestra` reusa esse
    mesmo portão: o ciclo plano→TDD→revisão→commit não começa sem plano.
    """
    if mode in ("ask", "explore"):
        # `explore` é somente-leitura como `ask` — a diferença entre os dois
        # é o prompt (ver `prompts.py`), não o conjunto de ferramentas.
        return registry.schemas(allow_exec=False, allow_write=False)
    if mode == "edit":
        return registry.schemas(allow_exec=False, allow_write=True)
    if mode in ("plan", "orchestra") and not has_plan:
        return registry.schemas(allow_exec=False, allow_write=False)
    return registry.schemas()


# Chaves que a API OpenAI-compatível reconhece numa mensagem. `data`/`ok`
# (Fase 1) existem só para a UI montar o card por tipo de ferramenta — viajam
# dentro do mesmo dict que também é `state["messages"]`, e portanto a própria
# conversa reenviada ao provedor a cada turno. Sem filtrar, a primeira
# ferramenta chamada já quebra toda sessão: o Groq rejeita com 400 qualquer
# propriedade fora do schema numa mensagem `role: tool`, e sem candidato que
# aceite a mensagem "suja" a sessão trava (foi como o bug foi encontrado —
# nenhum turno seguinte completava, então nenhum botão parecia fazer nada).
_CHAVES_MENSAGEM_API = {"role", "content", "name", "tool_call_id", "tool_calls"}


def _para_api(mensagens: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in m.items() if k in _CHAVES_MENSAGEM_API} for m in mensagens]


def build_graph(engine: RouterEngine, context: ToolContext):
    # Calculado uma vez por sessão, não a cada turno: instruções do projeto não
    # mudam no meio de uma sessão, e manter o prefixo do system prompt estável
    # entre turnos é o que permite o cache de prompt (ver docstring de
    # SYSTEM_PROMPT em prompts.py).
    system_prompt = SYSTEM_PROMPT
    if context.custom_instructions:
        system_prompt = (
            f"{SYSTEM_PROMPT}\n\n## Instruções do projeto\n\n{context.custom_instructions}"
        )

    async def think(state: AgentState) -> dict[str, Any]:
        mensagens = _para_api([{"role": "system", "content": system_prompt}, *state["messages"]])

        resultado = await engine.complete(
            requested_model=state.get("model") or "coding",
            params={
                "messages": mensagens,
                "tools": _tool_schemas(state.get("mode", "agent"), bool(state.get("todos"))),
                "temperature": 0,
            },
            source=f"agent:{state.get('mode', 'agent')}",
            project_slug=context.project_slug or None,
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

        if context.audit is not None:
            try:
                await context.audit.record_approvals(
                    session_id=state.get("session_id", ""),
                    pending=pendentes,
                    approvals=aprovacoes,
                    reasons=motivos,
                )
            except Exception as exc:
                # Auditoria não pode travar a execução do agente — um soluço
                # no banco aqui derrubaria uma sessão por um problema de log,
                # não de verdade da ação em si.
                log.warning("agent.audit.failed", error=str(exc)[:200])

        return {"approvals": aprovacoes, "approval_reasons": motivos, "pending": []}

    async def act(state: AgentState) -> dict[str, Any]:
        ultima = state["messages"][-1] if state["messages"] else {}
        tool_calls = ultima.get("tool_calls") or []
        aprovacoes = state.get("approvals") or {}
        motivos = state.get("approval_reasons") or {}

        respostas: list[dict[str, Any]] = []
        alterados: list[str] = []
        todos_atualizados: list[dict[str, Any]] | None = None
        ultima_falha = state.get("last_failed_call")
        contagem_falha = state.get("last_failed_call_count", 0)

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
            fingerprint = _tool_fingerprint(nome, argumentos)

            if _is_stuck_repeat(fingerprint, ultima_falha, contagem_falha):
                respostas.append(
                    _tool_message(
                        call_id,
                        nome,
                        f"ERRO: você repetiu exatamente a mesma chamada de `{nome}`, com os "
                        f"mesmos argumentos, {contagem_falha} vezes seguidas sem sucesso. Pare "
                        "de repetir — tente uma abordagem diferente ou explique ao usuário o "
                        "que está impedindo o progresso.",
                        ok=False,
                        data={"blocked_repetition": True},
                    )
                )
                continue

            inicio = time.perf_counter()
            try:
                resultado = await ferramenta.handler(context, argumentos)
            except Exception as exc:
                log.warning("agent.tool.failed", tool=nome, error=str(exc)[:200])
                if context.trace_recorder is not None:
                    context.trace_recorder.record(
                        kind="tool",
                        name=nome,
                        latency_ms=(time.perf_counter() - inicio) * 1000.0,
                        status="error",
                        session_id=state.get("session_id", ""),
                        error=str(exc),
                    )
                respostas.append(_tool_message(call_id, nome, f"ERRO: {exc}", ok=False))
                ultima_falha, contagem_falha = _next_repetition_state(
                    fingerprint, False, ultima_falha, contagem_falha
                )
                continue

            if context.trace_recorder is not None:
                context.trace_recorder.record(
                    kind="tool",
                    name=nome,
                    latency_ms=(time.perf_counter() - inicio) * 1000.0,
                    status="ok" if resultado.ok else "error",
                    session_id=state.get("session_id", ""),
                )

            respostas.append(
                _tool_message(call_id, nome, resultado.content, ok=resultado.ok, data=resultado.data)
            )
            ultima_falha, contagem_falha = _next_repetition_state(
                fingerprint, resultado.ok, ultima_falha, contagem_falha
            )
            if caminho := resultado.data.get("path"):
                alterados.append(str(caminho))
            if "todos" in resultado.data:
                todos_atualizados = resultado.data["todos"]

        atualizacao: dict[str, Any] = {
            "messages": respostas,
            "files_changed": alterados,
            "approvals": {},
            "last_failed_call": ultima_falha,
            "last_failed_call_count": contagem_falha,
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
