<script lang="ts">
  export interface ToolCallData {
    id: string;
    name: string;
    risk: string;
    args: any;
    requiresApproval: boolean;
    approved?: boolean;
    result?: string;
  }

  let { toolCall, onApprove } = $props<{
    toolCall: ToolCallData;
    onApprove?: (approved: boolean) => void;
  }>();

  function formatArgs(args: any): string {
    if (typeof args === "string") return args;
    try {
      return JSON.stringify(args, null, 2);
    } catch {
      return String(args);
    }
  }

  function getToolIcon(name: string): string {
    if (name.includes("command") || name.includes("exec")) return "💻";
    if (name.includes("file") || name.includes("write") || name.includes("edit")) return "📝";
    if (name.includes("search") || name.includes("find")) return "🔍";
    if (name.includes("git")) return "🌿";
    return "⚡";
  }
</script>

<div class="tool-card risk-{toolCall.risk.toLowerCase()}">
  <div class="card-header">
    <div class="tool-title">
      <span>{getToolIcon(toolCall.name)}</span>
      <strong>{toolCall.name}</strong>
    </div>
    <span class="risk-badge risk-{toolCall.risk.toLowerCase()}">{toolCall.risk}</span>
  </div>

  {#if toolCall.args}
    <div class="args-preview">
      <pre><code>{formatArgs(toolCall.args)}</code></pre>
    </div>
  {/if}

  {#if toolCall.requiresApproval && toolCall.approved === undefined}
    <div class="approval-box">
      <span class="approval-title">⚠️ Esta ferramenta exige aprovação humana:</span>
      <div class="approval-buttons">
        <button class="btn-approve" onclick={() => onApprove?.(true)}>
          ✓ Aprovar Execução
        </button>
        <button class="btn-reject" onclick={() => onApprove?.(false)}>
          ✗ Recusar
        </button>
      </div>
    </div>
  {:else if toolCall.approved !== undefined}
    <div class="approval-badge {toolCall.approved ? 'approved' : 'rejected'}">
      {toolCall.approved ? "✓ Execução Aprovada pelo Usuário" : "✗ Execução Recusada pelo Usuário"}
    </div>
  {/if}

  {#if toolCall.result}
    <div class="tool-result">
      <span class="result-label">Resultado:</span>
      <pre><code>{toolCall.result}</code></pre>
    </div>
  {/if}
</div>

<style>
  .tool-card {
    margin: 8px 0;
    padding: 10px;
    background: #0f172a;
    border: 1px solid var(--border-color);
    border-left: 4px solid var(--accent-blue);
    border-radius: 6px;
    font-size: 0.75rem;
  }
  .tool-card.risk-write {
    border-left-color: #f59e0b;
  }
  .tool-card.risk-exec {
    border-left-color: #ef4444;
  }
  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 6px;
  }
  .tool-title {
    display: flex;
    align-items: center;
    gap: 6px;
    color: var(--text-main);
  }
  .risk-badge {
    padding: 2px 6px;
    border-radius: 3px;
    font-size: 0.65rem;
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
  .args-preview {
    background: #1e293b;
    padding: 6px 8px;
    border-radius: 4px;
    max-height: 120px;
    overflow-y: auto;
    color: #cbd5e1;
    font-family: monospace;
  }
  .approval-box {
    margin-top: 8px;
    padding: 8px;
    background: rgba(245, 158, 11, 0.1);
    border: 1px solid #f59e0b;
    border-radius: 4px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .approval-title {
    color: #fbbf24;
    font-weight: 600;
  }
  .approval-buttons {
    display: flex;
    gap: 8px;
  }
  .btn-approve {
    background: #10b981;
    color: white;
    border: none;
    padding: 4px 10px;
    border-radius: 4px;
    cursor: pointer;
    font-weight: 600;
  }
  .btn-approve:hover {
    background: #059669;
  }
  .btn-reject {
    background: #ef4444;
    color: white;
    border: none;
    padding: 4px 10px;
    border-radius: 4px;
    cursor: pointer;
  }
  .btn-reject:hover {
    background: #dc2626;
  }
  .approval-badge {
    margin-top: 6px;
    font-weight: bold;
    font-size: 0.7rem;
  }
  .approval-badge.approved {
    color: #34d399;
  }
  .approval-badge.rejected {
    color: #f87171;
  }
  .tool-result {
    margin-top: 6px;
    padding-top: 6px;
    border-top: 1px solid var(--border-color);
  }
  .result-label {
    color: var(--text-muted);
    font-size: 0.7rem;
  }
</style>
