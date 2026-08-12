<script lang="ts">
  import { acceptFile, revertFile } from "../api/agent";

  let {
    sessionId = "",
    path = "",
    beforeContent = "",
    existed = true,
    onResolved
  } = $props<{
    sessionId?: string;
    path?: string;
    beforeContent?: string;
    existed?: boolean;
    onResolved?: (action: "accept" | "revert") => void;
  }>();

  let isProcessing = $state(false);

  async function handleAccept() {
    if (isProcessing || !sessionId || !path) return;
    isProcessing = true;
    try {
      await acceptFile(sessionId, path);
      if (onResolved) onResolved("accept");
    } catch (err: any) {
      alert(`Erro ao aceitar alteração: ${err.message || err}`);
    } finally {
      isProcessing = false;
    }
  }

  async function handleRevert() {
    if (isProcessing || !sessionId || !path) return;
    isProcessing = true;
    try {
      await revertFile(sessionId, path, beforeContent, existed);
      if (onResolved) onResolved("revert");
    } catch (err: any) {
      alert(`Erro ao reverter alteração: ${err.message || err}`);
    } finally {
      isProcessing = false;
    }
  }
</script>

<div class="diff-bar">
  <div class="diff-info">
    <span class="diff-icon">🤖</span>
    <span>O agente agêntico propôs alterações no arquivo <strong>{path}</strong></span>
  </div>

  <div class="diff-actions">
    <button class="btn-diff accept" onclick={handleAccept} disabled={isProcessing}>
      ✓ Aceitar Alteração
    </button>
    <button class="btn-diff revert" onclick={handleRevert} disabled={isProcessing}>
      ↺ Reverter
    </button>
  </div>
</div>

<style>
  .diff-bar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    height: 34px;
    padding: 0 12px;
    background: #1e1b4b;
    border-bottom: 1px solid #4338ca;
    color: #e0e7ff;
    font-size: 0.8rem;
    user-select: none;
  }
  .diff-info {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .diff-icon {
    font-size: 1rem;
  }
  .diff-actions {
    display: flex;
    gap: 8px;
  }
  .btn-diff {
    border: none;
    padding: 4px 10px;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 600;
    cursor: pointer;
  }
  .btn-diff.accept {
    background: #10b981;
    color: white;
  }
  .btn-diff.accept:hover {
    background: #059669;
  }
  .btn-diff.revert {
    background: #ef4444;
    color: white;
  }
  .btn-diff.revert:hover {
    background: #dc2626;
  }
  .btn-diff:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
