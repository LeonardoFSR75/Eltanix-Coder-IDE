<script lang="ts">
  import { getApiKey, setApiKey } from "../client";

  let { isOpen = false, dismissible = true, onSaved } = $props<{
    isOpen?: boolean;
    /** false no primeiro boot sem chave: não dá para fechar sem configurar. */
    dismissible?: boolean;
    onSaved?: () => void;
  }>();

  let key = $state(getApiKey());

  function handleSubmit(e: SubmitEvent) {
    e.preventDefault();
    if (!key.trim()) return;
    setApiKey(key.trim());
    onSaved?.();
  }
</script>

{#if isOpen}
  <div
    class="modal-backdrop"
    role="dialog"
    tabindex="-1"
    onclick={() => dismissible && onSaved?.()}
  >
    <div class="modal-card" role="document" onclick={(e) => e.stopPropagation()}>
      <div class="modal-header">
        <h3>🔑 Chave de API do SicoobitoCode</h3>
        {#if dismissible}
          <button class="btn-close" onclick={() => onSaved?.()}>×</button>
        {/if}
      </div>

      <p class="hint">
        O Lite fala direto com a API (<code>SICOOBITO_API_KEY</code>) — sem chave, nenhuma
        requisição funciona. Cole aqui a mesma chave configurada no <code>.env</code> da
        stack (ou em Configurações → Chaves de API no hub principal).
      </p>

      <form onsubmit={handleSubmit} class="modal-form">
        <label>
          <span>Chave de API</span>
          <input
            type="password"
            bind:value={key}
            placeholder="cole a SICOOBITO_API_KEY aqui..."
            autocomplete="off"
            required
          />
        </label>

        <div class="modal-footer">
          <button type="submit" class="btn-submit" disabled={!key.trim()}>
            Salvar e continuar
          </button>
        </div>
      </form>
    </div>
  </div>
{/if}

<style>
  .modal-backdrop {
    position: fixed;
    top: 0;
    left: 0;
    width: 100vw;
    height: 100vh;
    background: rgba(0, 0, 0, 0.7);
    display: flex;
    justify-content: center;
    align-items: center;
    z-index: 9999;
  }
  .modal-card {
    background: #1e293b;
    border: 1px solid var(--border-color);
    border-radius: 8px;
    width: 440px;
    padding: 16px;
    box-shadow: 0 10px 25px rgba(0, 0, 0, 0.5);
    color: var(--text-main);
  }
  .modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
  }
  .modal-header h3 {
    font-size: 1rem;
    color: var(--accent-cyan);
  }
  .btn-close {
    background: transparent;
    border: none;
    color: var(--text-muted);
    font-size: 1.2rem;
    cursor: pointer;
  }
  .hint {
    font-size: 0.78rem;
    color: var(--text-muted);
    line-height: 1.5;
    margin-bottom: 14px;
  }
  .hint code {
    background: #0f172a;
    padding: 1px 5px;
    border-radius: 3px;
    color: var(--accent-cyan);
  }
  .modal-form {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  label {
    display: flex;
    flex-direction: column;
    gap: 4px;
    font-size: 0.8rem;
    color: var(--text-muted);
  }
  input[type="password"] {
    background: #0f172a;
    border: 1px solid var(--border-color);
    color: var(--text-main);
    padding: 6px 10px;
    border-radius: 4px;
    font-size: 0.85rem;
    font-family: monospace;
  }
  input[type="password"]:focus {
    outline: none;
    border-color: var(--accent-cyan);
  }
  .modal-footer {
    display: flex;
    justify-content: flex-end;
    margin-top: 4px;
  }
  .btn-submit {
    background: var(--accent-blue);
    color: white;
    border: none;
    padding: 6px 14px;
    border-radius: 4px;
    font-weight: 600;
    cursor: pointer;
    font-size: 0.8rem;
  }
  .btn-submit:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
