"""Roda um único burst de `AgentRunner.stream_run()` até o fim sem SSE — o
único jeito de um agente filho avançar sem ninguém consumindo seu stream ao
vivo (ver ADR 0004). Usado tanto para o primeiro burst de um filho recém-
criado (`spawn_agent`) quanto para acordá-lo depois de uma mensagem chegar
enquanto ele não está sendo dirigido por ninguém (`send_message_to_agent`).

`stream_run()` já é, por natureza, limitado: termina sozinho quando o grafo
conclui OU pausa num `interrupt()` (ver docstring de `agent/graph.py`) — este
módulo só drena esse burst e traduz o desfecho pro `AgentCoordinator`, nunca
inventa um loop supervisor novo.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sicoobito.logging_setup import get_logger

if TYPE_CHECKING:
    from sicoobito.agent.coordinator import AgentCoordinator
    from sicoobito.agent.runner import AgentRunner, AgentSession

log = get_logger(__name__)


async def run_headless_burst(
    runner: AgentRunner,
    coordinator: AgentCoordinator,
    session: AgentSession,
    *,
    resume: Any = None,
    message: str | None = None,
) -> None:
    """Nunca lança — qualquer exceção é logada e vira status `"failed"` no
    coordenador, mesmo espírito de degradação do resto do projeto (uma tarefa
    em background que lança destrói a task silenciosamente sem isto)."""
    if await coordinator.is_stopped(session.session_id):
        # `stop_agent` pediu parada antes deste burst começar — honra sem
        # rodar nada. Não cancela um burst já em andamento (não há ponto de
        # cancelamento seguro no meio de um `stream_run()` sem risco de
        # interromper uma escrita de checkpoint); só impede que um agente já
        # marcado como parado seja acordado de novo.
        await coordinator.set_status(session.session_id, "stopped")
        return

    await coordinator.set_status(session.session_id, "running")
    try:
        interrompeu = False
        async for evento in runner.stream_run(session, resume=resume, message=message):
            if evento.get("node") == "interrupt":
                interrompeu = True

        if interrompeu:
            # Correto e esperado: o filho bateu numa ação WRITE/EXEC sem
            # cobertura da política de auto-aprovação do projeto e parou
            # exatamente como qualquer sessão pararia — não é falha, é o
            # invariante de aprovação funcionando pra um chamador sem UI.
            await coordinator.set_status(session.session_id, "waiting_approval")
        else:
            # O grafo terminou (o modelo parou de pedir ferramentas, tenha
            # ele chamado `agent_finish` ou não). Se `agent_finish` nunca
            # rodou, nenhum relatório chega no inbox do pai — um
            # `wait_for_agents` que espera por isto simplesmente expira no
            # timeout, sem precisar de um status intermediário só pra essa
            # distinção.
            await coordinator.set_status(session.session_id, "completed")
    except Exception as exc:
        log.warning(
            "agent.headless.burst_failed", session=session.session_id, error=str(exc)[:200]
        )
        await coordinator.set_status(session.session_id, "failed")
