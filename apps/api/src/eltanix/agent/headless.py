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

from eltanix.logging_setup import get_logger

if TYPE_CHECKING:
    from eltanix.agent.coordinator import AgentCoordinator
    from eltanix.agent.runner import AgentRunner, AgentSession

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

    # Import local (não no topo do módulo) para evitar ciclo de import com
    # `agent/runner.py`, que já importa `run_headless_burst` deste módulo.
    from eltanix.agent.runner import SessionAlreadyRunningError

    await coordinator.set_status(session.session_id, "running")
    try:
        interrompeu = False
        falhou = False
        async for evento in runner.stream_run(session, resume=resume, message=message):
            no = evento.get("node")
            if no == "interrupt":
                interrompeu = True
            elif no == "error":
                # `stream_run`/`_run_graph` engolem exceções de execução do
                # grafo e as traduzem num evento `{"node": "error", ...}` em
                # vez de relançar — sem checar isto aqui, uma falha real do
                # burst nunca cai no `except` abaixo e acaba reportada como
                # `"completed"`, indistinguível de sucesso pro pai/UI.
                falhou = True

        if interrompeu:
            # Correto e esperado: o filho bateu numa ação WRITE/EXEC sem
            # cobertura da política de auto-aprovação do projeto e parou
            # exatamente como qualquer sessão pararia — não é falha, é o
            # invariante de aprovação funcionando pra um chamador sem UI.
            await coordinator.set_status(session.session_id, "waiting_approval")
        elif falhou:
            await coordinator.set_status(session.session_id, "failed")
        else:
            # O grafo terminou (o modelo parou de pedir ferramentas, tenha
            # ele chamado `agent_finish` ou não). Se `agent_finish` nunca
            # rodou, nenhum relatório chega no inbox do pai — um
            # `wait_for_agents` que espera por isto simplesmente expira no
            # timeout, sem precisar de um status intermediário só pra essa
            # distinção.
            await coordinator.set_status(session.session_id, "completed")
    except SessionAlreadyRunningError:
        # Outra chamada (humano via SSE, ou outro burst) já pegou o lock da
        # sessão entre a checagem de `_wake_agent` e este burst realmente
        # rodar — não é uma falha deste agente, é a outra chamada dirigindo a
        # sessão de verdade. Deixa o status como está (ela mesma vai
        # atualizar via seu próprio `stream_run`) em vez de marcar "failed".
        log.info("agent.headless.burst_skipped_already_running", session=session.session_id)
    except Exception as exc:
        log.warning("agent.headless.burst_failed", session=session.session_id, error=str(exc)[:200])
        await coordinator.set_status(session.session_id, "failed")
