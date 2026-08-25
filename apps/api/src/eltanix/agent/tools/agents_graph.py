"""Orquestração multiagente: um agente pode spawnar filhos especialistas,
mensageá-los, esperar por eles e reportar de volta ao pai (ver ADR 0004).

Inspirado no conjunto de ferramentas `agents_graph` do Strix
(github.com/usestrix/strix), mas adaptado à diferença fundamental de modelo
de execução: aqui não há loop supervisor rodando em background continuamente
— cada agente avança em "bursts" limitados (`agent/headless.py`), e um filho
que bate numa ação WRITE/EXEC sem cobertura da política de auto-aprovação do
projeto fica parado esperando um humano, exatamente como qualquer sessão.
Multiagente não abre uma porta nova de aprovação — só um novo chamador
(burst sem UI) pro mesmo portão que já existe.
"""

from __future__ import annotations

from typing import Any

from eltanix.agent.tools.base import RiskClass, ToolContext, ToolResult, tool


def _sem_coordenador() -> ToolResult:
    return ToolResult.failure(
        "Orquestração multiagente indisponível (Redis fora do ar ou não configurado)."
    )


@tool(
    name="spawn_agent",
    description=(
        "Cria um agente filho especialista que roda em paralelo, com sua própria sessão, "
        "worktree e orçamento — não é uma chamada de LLM isolada como `request_code_review`, "
        "é um agente completo que pode ler, editar e executar (sujeito à mesma aprovação "
        "que qualquer sessão). Use pra decompor uma tarefa grande em pedaços paralelizáveis "
        "ou que precisam de foco diferente do que você já está fazendo. Chame "
        "`view_agent_graph` antes pra confirmar que nenhum agente já cobre esse escopo — "
        "filhos duplicados desperdiçam orçamento e criam coordenação desnecessária."
    ),
    risk=RiskClass.WRITE,
    parameters={
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "Objetivo específico e concreto pro filho — o que testar/fazer, "
                "o que conta como sucesso.",
            },
            "display_name": {
                "type": "string",
                "description": "Nome curto pro agente (aparece em view_agent_graph); "
                "padrão é um recorte da própria task.",
            },
            "skill_name": {
                "type": "string",
                "description": "Nome de uma Skill existente (ver `list_skills`/`get_skill`) "
                "cujo `system_prompt` vira especialização do filho — some ao prompt dele "
                "junto do resto, não substitui a task. Omitir cria um filho genérico.",
            },
        },
        "required": ["task"],
    },
    summarize=lambda a: f"spawnar agente: {a.get('task', '')[:70]}",
)
async def spawn_agent(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    if ctx.coordinator is None or ctx.spawn_child_agent is None:
        return _sem_coordenador()

    profundidade = await ctx.coordinator.depth_of(ctx.session_id)
    if profundidade >= ctx.max_spawn_depth:
        return ToolResult.failure(
            f"Profundidade máxima de agentes ({ctx.max_spawn_depth}) atingida — "
            "este agente não pode spawnar mais um nível de filho."
        )
    filhos_atuais = await ctx.coordinator.children_of(ctx.session_id)
    if len(filhos_atuais) >= ctx.max_children_per_agent:
        return ToolResult.failure(
            f"Limite de {ctx.max_children_per_agent} agentes filhos por agente atingido."
        )

    tarefa = args.get("task", "").strip()
    if not tarefa:
        return ToolResult.failure("Informe `task` — o objetivo do agente filho.")
    nome = (args.get("display_name") or tarefa[:60]).strip()

    especializacao: str | None = None
    skill_name = (args.get("skill_name") or "").strip()
    if skill_name:
        if ctx.skills is None:
            return ToolResult.failure("Skills indisponíveis nesta sessão.")
        skill = await ctx.skills.get_by_name(skill_name)
        if skill is None:
            return ToolResult.failure(f"Skill desconhecida: {skill_name}")
        if not skill.enabled:
            return ToolResult.failure(f"Skill desabilitada: {skill_name}")
        especializacao = skill.system_prompt

    child_session_id = await ctx.spawn_child_agent(
        task=tarefa, display_name=nome, specialization_prompt=especializacao
    )
    return ToolResult(
        ok=True,
        content=f"Agente filho '{nome}' criado: {child_session_id}",
        data={"child_session_id": child_session_id},
    )


@tool(
    name="view_agent_graph",
    description=(
        "Mostra a árvore de agentes a partir de você mesmo (você e todos os seus "
        "descendentes) — nome, status (running/waiting_approval/waiting_for_message/"
        "completed/failed/stopped) de cada um. Use antes de `spawn_agent` (evita duplicar "
        "escopo) e sempre que quiser saber quem ainda está rodando/esperando."
    ),
    risk=RiskClass.READ,
    parameters={"type": "object", "properties": {}},
    summarize=lambda _a: "ver árvore de agentes",
)
async def view_agent_graph(ctx: ToolContext, _args: dict[str, Any]) -> ToolResult:
    if ctx.coordinator is None:
        return _sem_coordenador()

    nos = await ctx.coordinator.graph_snapshot(ctx.session_id)
    if not nos:
        return ToolResult(ok=True, content="Nenhum agente filho ainda.", data={"agents": []})

    por_id = {n.session_id: n for n in nos}

    def render(session_id: str, profundidade: int) -> list[str]:
        no = por_id.get(session_id)
        if no is None:
            return []
        marcador = "  ← você" if session_id == ctx.session_id else ""
        prefixo = "  " * profundidade
        linhas = [f"{prefixo}- {no.display_name} ({no.session_id}) [{no.status}]{marcador}"]
        for filho_id in no.children:
            linhas.extend(render(filho_id, profundidade + 1))
        return linhas

    texto = "\n".join(render(ctx.session_id, 0))
    return ToolResult(
        ok=True,
        content=texto,
        data={
            "agents": [
                {
                    "session_id": n.session_id,
                    "display_name": n.display_name,
                    "status": n.status,
                    "parent_id": n.parent_id,
                    "depth": n.depth,
                }
                for n in nos
            ]
        },
    )


@tool(
    name="send_message_to_agent",
    description=(
        "Envia uma mensagem pra outro agente (pai, filho ou irmão) — use com moderação: "
        "compartilhar uma descoberta que outro agente precisa, pedir algo focado, ou avisar "
        "um filho pra encerrar/mudar de rumo. NÃO use pra 'oi/status' rotineiro — um filho já "
        "herda o histórico do pai, e o relatório final de `agent_finish` já cobre a conclusão "
        "normal."
    ),
    risk=RiskClass.READ,
    parameters={
        "type": "object",
        "properties": {
            "target_agent_id": {"type": "string", "description": "session_id do destinatário"},
            "message": {
                "type": "string",
                "description": "Corpo completo da mensagem — seja específico, inclua "
                "URLs/caminhos/valores, não só um título.",
            },
        },
        "required": ["target_agent_id", "message"],
    },
    summarize=lambda a: f"mensagem para {a.get('target_agent_id', '?')}",
)
async def send_message_to_agent(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    if ctx.coordinator is None:
        return _sem_coordenador()

    alvo = args.get("target_agent_id", "")
    mensagem = args.get("message", "")
    if not alvo or not mensagem:
        return ToolResult.failure("Informe `target_agent_id` e `message`.")
    if alvo == ctx.session_id:
        return ToolResult.failure("Não é possível mensagear a si mesmo.")

    entregue = await ctx.coordinator.send(from_id=ctx.session_id, to_id=alvo, content=mensagem)
    if not entregue:
        return ToolResult.failure(f"Agente desconhecido, expirado ou indisponível: {alvo}")

    # A mensagem já está na caixa do alvo mesmo sem isto — só acorda um burst
    # novo se ninguém estiver dirigindo o alvo agora, pra ele não ficar
    # esperando o próprio `wait_for_agents`/turno seguinte indefinidamente.
    if ctx.wake_agent is not None:
        await ctx.wake_agent(alvo)

    return ToolResult(ok=True, content=f"Mensagem enviada para {alvo}.", data={"delivered": True})


@tool(
    name="wait_for_agents",
    description=(
        "Pausa até chegar uma mensagem de outro agente (ou o timeout expirar). Use quando "
        "não há nada útil a fazer até um filho responder — tipicamente depois de "
        "`spawn_agent`, esperando o relatório de `agent_finish`. Emita UMA espera e reaja ao "
        "resultado — não é um poll pra repetir. Não use pra esperar um comando demorado "
        "(isso é `run_command`, que já tem seu próprio mecanismo), nem pra falar com o "
        "usuário (isso é a resposta normal do turno)."
    ),
    risk=RiskClass.READ,
    parameters={
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "Nota curta do que está esperando (aparece em view_agent_graph)",
            },
            "timeout_seconds": {
                "type": "number",
                "description": "Segundos máximos de espera (padrão 60; limitado por um teto do "
                "servidor)",
            },
        },
    },
    summarize=lambda a: f"esperar agentes: {a.get('reason', '')[:60]}",
)
async def wait_for_agents(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    if ctx.coordinator is None:
        return _sem_coordenador()

    timeout = min(float(args.get("timeout_seconds") or 60.0), ctx.max_wait_seconds)
    await ctx.coordinator.set_status(ctx.session_id, "waiting_for_message")
    mensagens = await ctx.coordinator.wait_for_message(ctx.session_id, timeout_seconds=timeout)
    await ctx.coordinator.set_status(ctx.session_id, "running")

    if not mensagens:
        return ToolResult(
            ok=True,
            content=f"Nenhuma mensagem em {timeout:.0f}s — continue trabalhando ou espere de novo.",
            data={"messages": []},
        )
    resumo = "\n\n".join(f"De {m['from']}: {m['content']}" for m in mensagens)
    return ToolResult(ok=True, content=resumo, data={"messages": mensagens})


@tool(
    name="agent_finish",
    description=(
        "Encerramento de sub-agente — posta um relatório estruturado pro pai. Só pra "
        "agentes que têm pai (spawnados via `spawn_agent`); uma sessão raiz simplesmente "
        "para de chamar ferramentas quando termina. Escreva o resumo como se o pai não "
        "soubesse nada do que você fez: o que testou, o que descobriu/confirmou, o que "
        "ficou em aberto."
    ),
    risk=RiskClass.READ,
    parameters={
        "type": "object",
        "properties": {
            "result_summary": {
                "type": "string",
                "description": "O que você fez e descobriu — concreto e específico.",
            },
            "success": {
                "type": "boolean",
                "description": "Se a subtarefa foi concluída (padrão true)",
            },
            "report_to_parent": {
                "type": "boolean",
                "description": "Se deve entregar o relatório na caixa do pai (padrão true)",
            },
        },
        "required": ["result_summary"],
    },
    summarize=lambda a: f"finalizar agente: {a.get('result_summary', '')[:60]}",
)
async def agent_finish(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    resumo = args.get("result_summary", "").strip()
    sucesso = bool(args.get("success", True))
    if ctx.parent_session_id is None:
        return ToolResult(
            ok=True,
            content=f"Tarefa concluída com sucesso: {resumo or 'Sem resumo adicional'}",
            data={"finished": True, "success": sucesso, "summary": resumo},
        )
    if ctx.coordinator is None:
        return _sem_coordenador()

    resumo = args.get("result_summary", "").strip()
    if not resumo:
        return ToolResult.failure("Informe `result_summary`.")
    sucesso = bool(args.get("success", True))
    reportar = bool(args.get("report_to_parent", True))

    entregue = False
    if reportar:
        status_txt = "SUCESSO" if sucesso else "FALHOU"
        relatorio = f"== Relatório de {ctx.session_id} ==\nStatus: {status_txt}\n\n{resumo}"
        entregue = await ctx.coordinator.send(
            from_id=ctx.session_id, to_id=ctx.parent_session_id, content=relatorio
        )
        if entregue and ctx.wake_agent is not None:
            await ctx.wake_agent(ctx.parent_session_id)

    await ctx.coordinator.set_status(ctx.session_id, "completed")
    return ToolResult(
        ok=True,
        content=f"Encerrado. Relatório entregue ao pai: {entregue}.",
        data={"reported_to_parent": entregue},
    )


@tool(
    name="stop_agent",
    description=(
        "Para um agente (filho/descendente) que saiu do rumo e não vai se corrigir sozinho. "
        "Prefira `send_message_to_agent` pedindo pra ele encerrar quando isso for suficiente "
        "— `stop_agent` é pra quando isso não é opção. É best-effort: impede que o alvo seja "
        "acordado de novo, mas não interrompe um burst já em andamento no meio de um turno — "
        "ele ainda termina a ação atual antes de parar."
    ),
    risk=RiskClass.WRITE,
    parameters={
        "type": "object",
        "properties": {
            "target_agent_id": {"type": "string", "description": "session_id do agente a parar"},
            "reason": {"type": "string", "description": "Motivo, pra log/auditoria"},
        },
        "required": ["target_agent_id"],
    },
    summarize=lambda a: f"parar agente {a.get('target_agent_id', '?')}",
)
async def stop_agent(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    if ctx.coordinator is None:
        return _sem_coordenador()

    alvo = args.get("target_agent_id", "")
    if not alvo:
        return ToolResult.failure("Informe `target_agent_id`.")
    if alvo == ctx.session_id:
        return ToolResult.failure("Não é possível parar a si mesmo.")

    await ctx.coordinator.request_stop(alvo)
    await ctx.coordinator.set_status(alvo, "stopped")
    return ToolResult(
        ok=True,
        content=f"Pedido de parada enviado a {alvo}.",
        data={"target_agent_id": alvo, "reason": args.get("reason", "")},
    )
