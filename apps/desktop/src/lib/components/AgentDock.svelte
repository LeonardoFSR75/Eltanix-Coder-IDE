<script lang="ts">
  import { onDestroy } from "svelte";
  import { AgentSessionRuntime, type LogLine, type PendingAction } from "../agent/sessionRuntime";
  import { MODE_HINT, MODES, type Mode } from "../agent/modes";
  import type { SessionStatus, SessionSummary } from "../agent/sessionTypes";
  import CodeBlock from "./CodeBlock.svelte";
  import ToolCallCard, { type ToolCallData } from "./ToolCallCard.svelte";
  import AgentManager from "./AgentManager.svelte";

  let { project = "eltanix-code", activeFile = "", onInsertCode } = $props<{
    project?: string;
    activeFile?: string;
    onInsertCode?: (snippet: string) => void;
  }>();

  let prompt = $state("");
  let mode = $state<Mode>("agent");
  let showManager = $state(false);
  let refreshKey = $state(0);

  /** Todas as sessões conhecidas nesta aba — vivas ou transcript já carregado. */
  let sessions = $state(new Map<string, AgentSessionRuntime>());
  let activeSessionId = $state<string | null>(null);

  // Espelho local do estado da sessão ATIVA — os campos de `AgentSessionRuntime`
  // são planos (não `$state`), então precisam ser copiados a cada `onChange`
  // para o Svelte perceber a mudança e re-renderizar.
  let log = $state<LogLine[]>([]);
  let pending = $state<PendingAction[]>([]);
  let running = $state(false);
  let readOnly = $state(false);
  /** Rascunho de decisões por `tool_call_id` — só vira POST ao confirmar. */
  let decisions = $state<Record<string, boolean>>({});

  let statusText = $derived(
    running
      ? "Agente pensando..."
      : pending.length > 0
        ? `${pending.length} ação(ões) aguardando aprovação`
        : readOnly
          ? "sessão encerrada · somente leitura"
          : `${log.length} evento(s) na sessão`,
  );

  function statusOf(rt: AgentSessionRuntime): SessionStatus {
    if (rt.errored) return "error";
    if (rt.pending.length > 0) return "awaiting-approval";
    if (rt.running) return "running";
    if (rt.readOnly) return "closed";
    if (rt.finished) return "done";
    return "closed";
  }

  let liveSummaries = $derived.by((): SessionSummary[] =>
    Array.from(sessions.entries()).map(([id, rt]) => ({
      id,
      task: rt.task,
      mode,
      branch: rt.session?.branch ?? "",
      status: statusOf(rt),
      closed: rt.readOnly,
    })),
  );

  function mirrorActive(): void {
    const rt = activeSessionId ? (sessions.get(activeSessionId) ?? null) : null;
    log = rt?.log ?? [];
    pending = rt?.pending ?? [];
    running = rt?.running ?? false;
    readOnly = rt?.readOnly ?? false;
    if (pending.length === 0) decisions = {};
  }

  /** Chamado no `onChange` de qualquer runtime — reatribui a entrada do Map
   * (mesma referência) só para o Svelte notar a mudança em sessões de fundo,
   * e re-espelha se for a sessão ativa. */
  function touch(rt: AgentSessionRuntime): void {
    const id = rt.session?.session_id;
    if (id) sessions.set(id, rt);
    if (id && id === activeSessionId) mirrorActive();
  }

  function openLive(id: string): void {
    activeSessionId = id;
    mirrorActive();
  }

  async function openClosed(id: string, task: string): Promise<void> {
    if (sessions.has(id)) {
      openLive(id);
      return;
    }
    const rtRef: { current: AgentSessionRuntime | null } = { current: null };
    const rt = await AgentSessionRuntime.loadClosed(
      id,
      { project, onChange: () => rtRef.current && touch(rtRef.current) },
      task,
    );
    rtRef.current = rt;
    sessions.set(id, rt);
    activeSessionId = id;
    mirrorActive();
  }

  async function handleSubmit(e?: SubmitEvent): Promise<void> {
    if (e) e.preventDefault();
    const texto = prompt.trim();
    if (!texto || running) return;
    prompt = "";

    const atual = activeSessionId ? sessions.get(activeSessionId) : null;
    if (!atual || atual.readOnly) {
      const rtRef: { current: AgentSessionRuntime | null } = { current: null };
      const rt = await AgentSessionRuntime.start(
        { project, onChange: () => rtRef.current && touch(rtRef.current) },
        texto,
        mode,
      );
      rtRef.current = rt;
      const id = rt.session?.session_id;
      if (id) {
        sessions.set(id, rt);
        activeSessionId = id;
      }
      mirrorActive();
      refreshKey += 1;
    } else {
      await atual.sendMessage(texto);
    }
  }

  function handleStopAgent(): void {
    if (activeSessionId) sessions.get(activeSessionId)?.abort();
  }

  function handleNewSession(): void {
    // Não aborta a sessão atual — ela pode continuar rodando em segundo
    // plano. Só desmarca a ativa; a próxima mensagem cria uma sessão nova.
    activeSessionId = null;
    mirrorActive();
  }

  function setDecision(id: string, approved: boolean): void {
    decisions = { ...decisions, [id]: approved };
  }

  function confirmDecisions(): void {
    const rt = activeSessionId ? sessions.get(activeSessionId) : null;
    if (!rt || Object.keys(decisions).length === 0) return;
    void rt.decide(decisions);
  }

  function decideAll(approved: boolean): void {
    const rt = activeSessionId ? sessions.get(activeSessionId) : null;
    if (!rt) return;
    const todas = Object.fromEntries(pending.map((a) => [a.tool_call_id, approved]));
    void rt.decide(todas);
  }

  function setQuickPrompt(text: string): void {
    prompt = text;
    void handleSubmit();
  }

  function toolCallFromLog(linha: LogLine): ToolCallData {
    // `LogLine` (resultado já executado) não carrega a RiskClass original da
    // ferramenta — só o resultado. Rotular como READ/WRITE/EXEC aqui seria
    // adivinhação; "tool" fica honesto sobre o que de fato sabemos.
    return {
      id: linha.toolCallId ?? String(Math.random()),
      name: linha.tool ?? "ferramenta",
      risk: linha.toolOk === false ? "falhou" : "tool",
      args: linha.toolData ?? {},
      requiresApproval: false,
      result: linha.toolContent ?? linha.text,
    };
  }

  function parseContentParts(text: string): { type: "text" | "code"; content: string; lang?: string }[] {
    const parts: { type: "text" | "code"; content: string; lang?: string }[] = [];
    const regex = /```(\w*)\n([\s\S]*?)```/g;
    let lastIndex = 0;
    let match;

    while ((match = regex.exec(text)) !== null) {
      if (match.index > lastIndex) {
        parts.push({ type: "text", content: text.slice(lastIndex, match.index) });
      }
      parts.push({ type: "code", lang: match[1] || "text", content: match[2].trimEnd() });
      lastIndex = regex.lastIndex;
    }

    if (lastIndex < text.length) {
      parts.push({ type: "text", content: text.slice(lastIndex) });
    }

    return parts;
  }

  onDestroy(() => {
    for (const rt of sessions.values()) rt.abort();
  });
</script>

<div class="agent-dock">
  <div class="dock-header">
    <div class="title-group">
      <span class="dock-title">🤖 Agente agêntico</span>
      <span class="dock-status">{statusText}</span>
    </div>
    <div class="header-actions">
      <select bind:value={mode} class="mode-select" title={MODE_HINT[mode]} disabled={readOnly}>
        {#each MODES as m}
          <option value={m}>{m}</option>
        {/each}
      </select>
      <button
        class="btn-manager {showManager ? 'active' : ''}"
        onclick={() => (showManager = !showManager)}
        title="Sessões do agente (Agent Manager)"
      >
        🗂️ Sessões
      </button>
      <button class="btn-new-session" onclick={handleNewSession} title="Começar uma sessão nova">
        + Nova
      </button>
    </div>
  </div>

  {#if showManager}
    <AgentManager
      {project}
      {refreshKey}
      liveSessions={liveSummaries}
      activeId={activeSessionId}
      onOpenLive={openLive}
      onOpenClosed={openClosed}
      onClose={() => (showManager = false)}
    />
  {/if}

  <div class="quick-prompts">
    <button onclick={() => setQuickPrompt("Refatore o código do arquivo ativo trazendo boas práticas.")}>
      ✨ Refatorar
    </button>
    <button onclick={() => setQuickPrompt("Gere testes de unidade completos para o arquivo ativo.")}>
      🧪 Gerar Testes
    </button>
    <button onclick={() => setQuickPrompt("Explique a arquitetura e o funcionamento deste arquivo.")}>
      💡 Explicar
    </button>
  </div>

  <div class="chat-messages">
    {#if log.length === 0 && pending.length === 0}
      <div class="empty-hint">
        Olá! Sou o agente agêntico do Eltanix Coder IDE Lite. Descreva uma tarefa abaixo — posso
        analisar, criar testes ou aplicar edições diretamente no seu código.
      </div>
    {/if}

    {#each log as linha, i (i)}
      {#if linha.kind === "user" || linha.kind === "assistant"}
        <div class="message {linha.kind}">
          <div class="role-tag">{linha.kind.toUpperCase()}</div>
          {#each parseContentParts(linha.text) as part}
            {#if part.type === "code"}
              <CodeBlock code={part.content} language={part.lang} onInsert={onInsertCode} />
            {:else if part.content.trim()}
              <div class="message-text">{part.content}</div>
            {/if}
          {/each}
        </div>
      {:else if linha.kind === "tool"}
        <ToolCallCard toolCall={toolCallFromLog(linha)} />
      {:else if linha.kind === "error"}
        <div class="message error">{linha.text}</div>
      {:else if linha.kind === "cost" || linha.kind === "info"}
        <div class="log-meta">{linha.text}</div>
      {/if}
    {/each}

    {#if pending.length > 0}
      <div class="pending-block">
        <div class="pending-header">
          ⚠️ {pending.length} {pending.length === 1 ? "ação requer" : "ações requerem"} sua aprovação
        </div>

        {#each pending as action (action.tool_call_id)}
          <div class="pending-card risk-{action.risk.toLowerCase()}">
            <div class="pending-card-header">
              <strong>{action.tool}</strong>
              <span class="risk-badge risk-{action.risk.toLowerCase()}">{action.risk}</span>
            </div>
            {#if action.summary}
              <div class="pending-summary">{action.summary}</div>
            {/if}
            <div class="pending-decision-buttons">
              <button
                class="btn-approve {decisions[action.tool_call_id] === true ? 'selected' : ''}"
                onclick={() => setDecision(action.tool_call_id, true)}
              >
                ✓ Aprovar
              </button>
              <button
                class="btn-reject {decisions[action.tool_call_id] === false ? 'selected' : ''}"
                onclick={() => setDecision(action.tool_call_id, false)}
              >
                ✗ Recusar
              </button>
            </div>
          </div>
        {/each}

        <div class="pending-bulk-actions">
          <button class="btn-bulk-approve" onclick={() => decideAll(true)}>Aprovar Tudo</button>
          <button class="btn-bulk-reject" onclick={() => decideAll(false)}>Recusar Tudo</button>
          {#if Object.keys(decisions).length > 0}
            <button class="btn-confirm" onclick={confirmDecisions}>
              Confirmar decisões ({Object.keys(decisions).length}/{pending.length})
            </button>
          {/if}
        </div>
      </div>
    {/if}
  </div>

  {#if readOnly}
    <div class="readonly-banner">
      📖 Sessão encerrada — somente leitura. Clique em "+ Nova" para começar outra.
    </div>
  {:else}
    <form onsubmit={handleSubmit} class="chat-input-area">
      <textarea
        bind:value={prompt}
        placeholder="Peça para o agente editar código, criar funções ou analisar lints..."
        rows={3}
        disabled={running}
        onkeydown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSubmit();
          }
        }}
      ></textarea>
      <div class="input-actions">
        {#if running}
          <button type="button" class="btn-stop" onclick={handleStopAgent}>
            🛑 Interromper
          </button>
        {:else}
          <button type="submit" class="btn-send" disabled={!prompt.trim()}>
            Enviar (Enter)
          </button>
        {/if}
      </div>
    </form>
  {/if}
</div>

<style>
  .agent-dock {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100%;
    background-color: var(--bg-panel);
    border-left: 1px solid var(--border-color);
  }
  .dock-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 12px;
    background-color: var(--bg-dark);
    border-bottom: 1px solid var(--border-color);
    gap: 8px;
    flex-wrap: wrap;
  }
  .dock-title {
    font-weight: 600;
    font-size: 0.85rem;
  }
  .dock-status {
    font-size: 0.75rem;
    color: var(--text-muted);
    margin-left: 8px;
  }
  .header-actions {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .mode-select {
    background: var(--bg-surface);
    color: var(--text-main);
    border: 1px solid var(--border-color);
    border-radius: 4px;
    padding: 2px 6px;
    font-size: 0.75rem;
  }
  .btn-manager,
  .btn-new-session {
    background: transparent;
    color: var(--text-muted);
    border: 1px solid var(--border-color);
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 0.72rem;
    cursor: pointer;
    white-space: nowrap;
  }
  .btn-manager:hover,
  .btn-new-session:hover {
    color: var(--text-main);
    border-color: var(--accent-cyan);
  }
  .btn-manager.active {
    color: var(--accent-cyan);
    border-color: var(--accent-cyan);
  }
  .quick-prompts {
    display: flex;
    gap: 6px;
    padding: 6px 12px;
    background: #18181b;
    border-bottom: 1px solid var(--border-color);
    overflow-x: auto;
  }
  .quick-prompts button {
    background: var(--bg-surface);
    color: var(--text-main);
    border: 1px solid var(--border-color);
    border-radius: 4px;
    padding: 3px 8px;
    font-size: 0.7rem;
    cursor: pointer;
    white-space: nowrap;
  }
  .quick-prompts button:hover {
    background: var(--accent-blue);
    color: white;
  }
  .chat-messages {
    flex: 1;
    overflow-y: auto;
    padding: 12px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .empty-hint {
    color: var(--text-muted);
    font-size: 0.8rem;
    line-height: 1.5;
    padding: 4px 2px;
  }
  .message {
    padding: 8px 12px;
    border-radius: 6px;
    font-size: 0.85rem;
    line-height: 1.4;
  }
  .message.user {
    background: #1e3a8a;
    align-self: flex-end;
    max-width: 85%;
  }
  .message.assistant {
    background: var(--bg-surface);
    align-self: flex-start;
    max-width: 92%;
  }
  .message.error {
    background: rgba(239, 68, 68, 0.15);
    border: 1px solid #ef4444;
    color: #fca5a5;
  }
  .role-tag {
    font-size: 0.65rem;
    color: var(--text-muted);
    margin-bottom: 4px;
    font-weight: bold;
  }
  .message-text {
    white-space: pre-wrap;
    word-break: break-word;
  }
  .log-meta {
    font-size: 0.7rem;
    color: var(--text-muted);
    padding: 0 2px;
  }
  .pending-block {
    background: rgba(245, 158, 11, 0.08);
    border: 1px solid #f59e0b;
    border-radius: 6px;
    padding: 10px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .pending-header {
    color: #fbbf24;
    font-weight: 600;
    font-size: 0.8rem;
  }
  .pending-card {
    background: #0f172a;
    border: 1px solid var(--border-color);
    border-left: 4px solid var(--accent-blue);
    border-radius: 4px;
    padding: 8px 10px;
    font-size: 0.78rem;
  }
  .pending-card.risk-write {
    border-left-color: #d97706;
  }
  .pending-card.risk-exec {
    border-left-color: #dc2626;
  }
  .pending-card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .risk-badge {
    padding: 2px 6px;
    border-radius: 3px;
    font-size: 0.62rem;
    font-weight: bold;
    color: white;
  }
  .risk-badge.risk-read {
    background: #0284c7;
  }
  .risk-badge.risk-write {
    background: #d97706;
  }
  .risk-badge.risk-exec {
    background: #dc2626;
  }
  .pending-summary {
    color: var(--text-muted);
    margin-top: 4px;
  }
  .pending-decision-buttons {
    display: flex;
    gap: 6px;
    margin-top: 6px;
  }
  .btn-approve,
  .btn-reject {
    border: 1px solid var(--border-color);
    background: transparent;
    color: var(--text-main);
    padding: 3px 10px;
    border-radius: 4px;
    font-size: 0.72rem;
    cursor: pointer;
  }
  .btn-approve.selected {
    background: #10b981;
    border-color: #10b981;
    color: white;
  }
  .btn-reject.selected {
    background: #ef4444;
    border-color: #ef4444;
    color: white;
  }
  .pending-bulk-actions {
    display: flex;
    gap: 8px;
    justify-content: flex-end;
    margin-top: 2px;
  }
  .btn-bulk-approve,
  .btn-bulk-reject,
  .btn-confirm {
    border: none;
    padding: 5px 10px;
    border-radius: 4px;
    font-size: 0.75rem;
    cursor: pointer;
    font-weight: 600;
  }
  .btn-bulk-approve {
    background: #10b981;
    color: white;
  }
  .btn-bulk-reject {
    background: #ef4444;
    color: white;
  }
  .btn-confirm {
    background: var(--accent-blue);
    color: white;
  }
  .readonly-banner {
    padding: 10px 12px;
    background-color: var(--bg-dark);
    border-top: 1px solid var(--border-color);
    color: var(--text-muted);
    font-size: 0.78rem;
    text-align: center;
  }
  .chat-input-area {
    padding: 8px;
    background-color: var(--bg-dark);
    border-top: 1px solid var(--border-color);
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  textarea {
    width: 100%;
    background: var(--bg-panel);
    border: 1px solid var(--border-color);
    color: var(--text-main);
    border-radius: 4px;
    padding: 8px;
    font-size: 0.85rem;
    resize: none;
    font-family: inherit;
  }
  textarea:focus {
    outline: none;
    border-color: var(--accent-cyan);
  }
  .input-actions {
    display: flex;
    justify-content: flex-end;
  }
  .btn-send {
    background: var(--accent-blue);
    color: white;
    border: none;
    padding: 6px 14px;
    border-radius: 4px;
    font-size: 0.8rem;
    cursor: pointer;
    font-weight: 600;
  }
  .btn-stop {
    background: #ef4444;
    color: white;
    border: none;
    padding: 6px 14px;
    border-radius: 4px;
    font-size: 0.8rem;
    cursor: pointer;
    font-weight: 600;
  }
</style>
