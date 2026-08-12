<script lang="ts">
  import { onMount } from "svelte";
  import { streamEvents, post } from "../client";
  import { listAgentSessions, type AgentSessionRecord } from "../api/agent";
  import CodeBlock from "./CodeBlock.svelte";
  import ToolCallCard, { type ToolCallData } from "./ToolCallCard.svelte";

  interface ChatMessage {
    id: string;
    role: "user" | "assistant" | "system" | "tool";
    content: string;
    toolCall?: ToolCallData;
  }

  let { activeFile = "", onInsertCode } = $props<{
    activeFile?: string;
    onInsertCode?: (snippet: string) => void;
  }>();

  let prompt = $state("");
  let mode = $state("agent");
  let isStreaming = $state(false);
  let sessions = $state<AgentSessionRecord[]>([]);
  let currentSessionId = $state<string | null>(null);

  let messages = $state<ChatMessage[]>([
    {
      id: "1",
      role: "assistant",
      content: "Olá! Sou o agente agêntico do SicoobitoCode Lite. Posso analisar, criar testes ou aplicar edições diretamente no seu código.",
    },
  ]);

  let statusText = $derived(
    isStreaming ? "Agente pensando..." : `${messages.length} mensagens na sessão`
  );

  async function loadSessions() {
    try {
      sessions = await listAgentSessions("sicoobito-code", 20);
    } catch {
      sessions = [];
    }
  }

  onMount(() => {
    loadSessions();
  });

  async function handleSubmit(e?: SubmitEvent) {
    if (e) e.preventDefault();
    if (!prompt.trim() || isStreaming) return;

    const userMessage = prompt;
    prompt = "";
    messages = [...messages, { id: String(Date.now()), role: "user", content: userMessage }];

    const assistantId = String(Date.now() + 1);
    messages = [...messages, { id: assistantId, role: "assistant", content: "" }];

    isStreaming = true;

    try {
      await streamEvents(
        "/api/agent/stream",
        { prompt: userMessage, mode, active_file: activeFile, session_id: currentSessionId },
        (event: any) => {
          if (event.session_id && !currentSessionId) {
            currentSessionId = event.session_id;
          }

          if (event.content || event.text || event.delta) {
            const token = event.content || event.text || event.delta;
            messages = messages.map((m) =>
              m.id === assistantId ? { ...m, content: m.content + token } : m
            );
          } else if (event.type === "tool_call" || event.tool_name) {
            const toolCall: ToolCallData = {
              id: event.tool_call_id || String(Date.now()),
              name: event.tool_name || event.name || "ferramenta",
              risk: event.risk || "WRITE",
              args: event.args || {},
              requiresApproval: event.requires_approval ?? true,
            };
            messages = messages.map((m) =>
              m.id === assistantId ? { ...m, toolCall } : m
            );
          }
        }
      );
    } catch (err: any) {
      messages = messages.map((m) =>
        m.id === assistantId
          ? { ...m, content: m.content || `[Erro no streaming: ${err.message || err}]` }
          : m
      );
    } finally {
      isStreaming = false;
      loadSessions();
    }
  }

  function handleStopAgent() {
    isStreaming = false;
  }

  async function handleApproveTool(messageId: string, approved: boolean) {
    messages = messages.map((m) => {
      if (m.id === messageId && m.toolCall) {
        return {
          ...m,
          toolCall: { ...m.toolCall, approved },
        };
      }
      return m;
    });

    try {
      await post("/api/agent/approve", { approved });
    } catch {
      // continua gracioso
    }
  }

  function setQuickPrompt(text: string) {
    prompt = text;
    handleSubmit();
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
</script>

<div class="agent-dock">
  <div class="dock-header">
    <div class="title-group">
      <span class="dock-title">🤖 Agente agêntico</span>
      <span class="dock-status">{statusText}</span>
    </div>
    <select bind:value={mode} class="mode-select">
      <option value="ask">ask (pergunta)</option>
      <option value="edit">edit (edição)</option>
      <option value="agent">agent (autônomo)</option>
      <option value="plan">plan (planejar)</option>
      <option value="orchestra">orchestra (TDD)</option>
    </select>
  </div>

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
    {#each messages as msg (msg.id)}
      <div class="message {msg.role}">
        <div class="role-tag">{msg.role.toUpperCase()}</div>

        {#each parseContentParts(msg.content) as part}
          {#if part.type === "code"}
            <CodeBlock code={part.content} language={part.lang} onInsert={onInsertCode} />
          {:else}
            <div class="message-text">{part.content}</div>
          {/if}
        {/each}

        {#if msg.toolCall}
          <ToolCallCard toolCall={msg.toolCall} onApprove={(app) => handleApproveTool(msg.id, app)} />
        {/if}
      </div>
    {/each}
  </div>

  <form onsubmit={handleSubmit} class="chat-input-area">
    <textarea
      bind:value={prompt}
      placeholder="Peça para o agente editar código, criar funções ou analisar lints..."
      rows={3}
      disabled={isStreaming}
      onkeydown={(e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          handleSubmit();
        }
      }}
    ></textarea>
    <div class="input-actions">
      {#if isStreaming}
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
  .mode-select {
    background: var(--bg-surface);
    color: var(--text-main);
    border: 1px solid var(--border-color);
    border-radius: 4px;
    padding: 2px 6px;
    font-size: 0.75rem;
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
