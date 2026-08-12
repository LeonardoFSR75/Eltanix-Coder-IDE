<script lang="ts">
  /**
   * Agent Manager do Lite — porta simplificada de
   * `apps/web/components/ide/agent/AgentManager.tsx`.
   *
   * Lista as sessões do projeto (vivas nesta aba + histórico persistido) numa
   * árvore por `parent_session_id` (spawn_agent, ADR 0004). Diferença
   * deliberada em relação ao hub: não consulta `getAgentGraph` para status ao
   * vivo de filhos headless — um filho que nunca abriu stream nesta aba
   * aparece com o status do último registro conhecido, não em tempo real.
   * Simplificação aceitável para um cliente "lite"; o hub continua sendo a
   * fonte de verdade para orquestração multiagente observada de perto.
   */
  import { onMount } from "svelte";
  import { listAgentSessions, type AgentSessionRecord } from "../api/agent";
  import type { SessionStatus, SessionSummary } from "../agent/sessionTypes";

  interface Row {
    id: string;
    task: string;
    mode: string;
    branch: string;
    status: SessionStatus;
    updatedAt: string | null;
    parentId: string | null;
    depth: number;
  }

  let { project = "", refreshKey = 0, liveSessions = [], activeId = null, onOpenLive, onOpenClosed, onClose } = $props<{
    project?: string;
    /** Incrementar de fora força um novo `GET /sessions` (ex.: após criar sessão). */
    refreshKey?: number;
    liveSessions?: SessionSummary[];
    activeId?: string | null;
    onOpenLive?: (sessionId: string) => void;
    onOpenClosed?: (sessionId: string, task: string) => void;
    onClose?: () => void;
  }>();

  const STATUS_LABEL: Record<SessionStatus, string> = {
    running: "rodando",
    "awaiting-approval": "aguardando aprovação",
    done: "concluída",
    error: "erro",
    closed: "encerrada",
  };

  let historico = $state<AgentSessionRecord[]>([]);
  let query = $state("");
  let erro = $state<string | null>(null);
  let carregando = $state(false);

  async function carregar() {
    if (!project) return;
    carregando = true;
    try {
      historico = await listAgentSessions(project, 50);
      erro = null;
    } catch (err) {
      erro = err instanceof Error ? err.message : String(err);
    } finally {
      carregando = false;
    }
  }

  onMount(carregar);
  $effect(() => {
    void refreshKey;
    void project;
    void carregar();
  });

  let liveIds = $derived(new Set(liveSessions.map((s: SessionSummary) => s.id)));

  let rows = $derived.by((): Omit<Row, "depth">[] => {
    const vistos = new Set<string>();
    const linhas: Omit<Row, "depth">[] = [];

    for (const s of liveSessions as SessionSummary[]) {
      vistos.add(s.id);
      const registro = historico.find((r) => r.session_id === s.id);
      linhas.push({
        id: s.id,
        task: s.task,
        mode: registro?.mode ?? "",
        branch: s.branch || registro?.branch || "",
        status: s.status,
        updatedAt: registro?.updated_at ?? null,
        parentId: registro?.parent_session_id ?? null,
      });
    }

    for (const r of historico) {
      if (vistos.has(r.session_id)) continue;
      linhas.push({
        id: r.session_id,
        task: r.task,
        mode: r.mode,
        branch: r.branch ?? "",
        status: r.status === "closed" ? "closed" : r.live ? "running" : "closed",
        updatedAt: r.updated_at,
        parentId: r.parent_session_id,
      });
    }

    return linhas;
  });

  // Sem busca: árvore (pai, filhos recursivamente, próxima raiz).
  let arvore = $derived.by((): Row[] => {
    const idsPresentes = new Set(rows.map((r) => r.id));
    const filhosDe = new Map<string | null, Omit<Row, "depth">[]>();
    for (const r of rows) {
      const pai = r.parentId && idsPresentes.has(r.parentId) ? r.parentId : null;
      if (!filhosDe.has(pai)) filhosDe.set(pai, []);
      filhosDe.get(pai)!.push(r);
    }
    const resultado: Row[] = [];
    const visitar = (pai: string | null, depth: number) => {
      for (const r of filhosDe.get(pai) ?? []) {
        resultado.push({ ...r, depth });
        visitar(r.id, depth + 1);
      }
    };
    visitar(null, 0);
    return resultado;
  });

  // Com busca: substring case-insensitive, lista plana (sem indentação de árvore).
  let filtradas = $derived.by((): Row[] => {
    const termo = query.trim().toLowerCase();
    if (!termo) return arvore;
    return rows
      .filter((r) => r.task.toLowerCase().includes(termo))
      .map((r) => ({ ...r, depth: 0 }));
  });

  function tempoRelativo(iso: string): string {
    const diffMs = Date.now() - new Date(iso).getTime();
    const min = Math.round(diffMs / 60000);
    if (min < 1) return "agora";
    if (min < 60) return `${min}min`;
    const h = Math.round(min / 60);
    if (h < 24) return `${h}h`;
    return `${Math.round(h / 24)}d`;
  }
</script>

<div class="agent-manager">
  <div class="manager-search">
    <input bind:value={query} placeholder="Buscar sessões…" />
    {#if onClose}
      <button type="button" class="btn-close-manager" onclick={() => onClose?.()} title="Fechar Agent Manager">
        ×
      </button>
    {/if}
  </div>

  {#if erro}
    <div class="manager-error">{erro}</div>
  {/if}
  {#if carregando && rows.length === 0}
    <div class="manager-hint">carregando…</div>
  {/if}
  {#if !carregando && filtradas.length === 0 && !erro}
    <div class="manager-hint">
      {rows.length === 0 ? "Nenhuma sessão neste projeto ainda." : `Nenhuma sessão corresponde a "${query}".`}
      {#if rows.length > 0}
        <button type="button" class="text-btn-inline" onclick={() => (query = "")}>Redefinir filtro</button>
      {/if}
    </div>
  {/if}

  <div class="manager-items">
    {#each filtradas as r (r.id)}
      <button
        type="button"
        class="manager-item {r.id === activeId ? 'active' : ''}"
        style={r.depth > 0 ? `margin-left: ${Math.min(r.depth, 3) * 16}px` : undefined}
        title={liveIds.has(r.id) ? "Trocar para esta sessão" : "Abrir o transcript desta sessão"}
        onclick={() => (liveIds.has(r.id) ? onOpenLive?.(r.id) : onOpenClosed?.(r.id, r.task))}
      >
        <div class="manager-item-top">
          {#if r.depth > 0}
            <span class="child-marker" title="Agente filho (spawn_agent)">↳</span>
          {/if}
          <span class="status-pill {r.status}">{STATUS_LABEL[r.status]}</span>
          <span class="manager-item-task">{r.task}</span>
        </div>
        <div class="manager-item-meta">
          <span>{r.branch || "sem branch"}</span>
          {#if r.mode}<span>{r.mode}</span>{/if}
          {#if r.updatedAt}<span>{tempoRelativo(r.updatedAt)}</span>{/if}
        </div>
      </button>
    {/each}
  </div>
</div>

<style>
  .agent-manager {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 8px;
    background: #18181b;
    border-bottom: 1px solid var(--border-color);
    max-height: 260px;
    overflow-y: auto;
  }
  .manager-search {
    display: flex;
    gap: 6px;
    align-items: center;
  }
  .manager-search input {
    flex: 1;
    background: var(--bg-dark);
    border: 1px solid var(--border-color);
    color: var(--text-main);
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 0.78rem;
  }
  .manager-search input:focus {
    outline: none;
    border-color: var(--accent-cyan);
  }
  .btn-close-manager {
    background: transparent;
    border: none;
    color: var(--text-muted);
    font-size: 1rem;
    cursor: pointer;
    padding: 0 4px;
  }
  .manager-error {
    color: #fca5a5;
    font-size: 0.72rem;
  }
  .manager-hint {
    color: var(--text-muted);
    font-size: 0.72rem;
  }
  .text-btn-inline {
    background: none;
    border: none;
    color: var(--accent-cyan);
    cursor: pointer;
    text-decoration: underline;
    font-size: inherit;
    padding: 0;
  }
  .manager-items {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .manager-item {
    display: flex;
    flex-direction: column;
    gap: 2px;
    background: var(--bg-dark);
    border: 1px solid var(--border-color);
    border-radius: 4px;
    padding: 5px 8px;
    text-align: left;
    cursor: pointer;
    color: var(--text-main);
  }
  .manager-item:hover {
    border-color: var(--accent-cyan);
  }
  .manager-item.active {
    border-color: var(--accent-blue);
    background: #1e293b;
  }
  .manager-item-top {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 0.78rem;
  }
  .child-marker {
    color: var(--text-muted);
  }
  .manager-item-task {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 1;
  }
  .manager-item-meta {
    display: flex;
    gap: 8px;
    font-size: 0.65rem;
    color: var(--text-muted);
  }
  .status-pill {
    font-size: 0.62rem;
    font-weight: 700;
    padding: 1px 6px;
    border-radius: 8px;
    white-space: nowrap;
  }
  .status-pill.running {
    background: rgba(59, 130, 246, 0.2);
    color: #60a5fa;
  }
  .status-pill.awaiting-approval {
    background: rgba(245, 158, 11, 0.2);
    color: #fbbf24;
  }
  .status-pill.done {
    background: rgba(16, 185, 129, 0.2);
    color: #34d399;
  }
  .status-pill.error {
    background: rgba(239, 68, 68, 0.2);
    color: #f87171;
  }
  .status-pill.closed {
    background: rgba(148, 163, 184, 0.2);
    color: #94a3b8;
  }
</style>
