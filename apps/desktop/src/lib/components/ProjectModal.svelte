<script lang="ts">
  import { createProject, type ProjectRecord } from "../api/projects";

  let { isOpen = false, onClose, onProjectCreated } = $props<{
    isOpen?: boolean;
    onClose?: () => void;
    onProjectCreated?: (project: ProjectRecord) => void;
  }>();

  let name = $state("");
  let description = $state("");
  let gitUrl = $state("");
  let initGit = $state(true);
  let isSubmitting = $state(false);
  let error = $state("");

  async function handleSubmit(e: SubmitEvent) {
    e.preventDefault();
    if (!name.trim() || isSubmitting) return;

    isSubmitting = true;
    error = "";

    try {
      const created = await createProject({
        name: name.trim(),
        description: description.trim() || undefined,
        git_url: gitUrl.trim() || undefined,
        init_git: initGit,
      });

      name = "";
      description = "";
      gitUrl = "";

      if (onProjectCreated) onProjectCreated(created);
      if (onClose) onClose();
    } catch (err: any) {
      error = err.message || "Erro ao criar projeto no hub principal.";
    } finally {
      isSubmitting = false;
    }
  }
</script>

{#if isOpen}
  <div class="modal-backdrop" role="dialog" tabindex="-1" onclick={() => onClose?.()}>
    <div class="modal-card" role="document" onclick={(e) => e.stopPropagation()}>
      <div class="modal-header">
        <h3>✨ Criar / Vincular Novo Projeto</h3>
        <button class="btn-close" onclick={() => onClose?.()}>×</button>
      </div>

      {#if error}
        <div class="error-banner">{error}</div>
      {/if}

      <form onsubmit={handleSubmit} class="modal-form">
        <label>
          <span>Nome do Projeto *</span>
          <input
            type="text"
            bind:value={name}
            placeholder="ex: meu-novo-servico"
            required
          />
        </label>

        <label>
          <span>Descrição</span>
          <input
            type="text"
            bind:value={description}
            placeholder="Descrição curta do projeto..."
          />
        </label>

        <label>
          <span>URL do Repositório Git (Opcional)</span>
          <input
            type="text"
            bind:value={gitUrl}
            placeholder="https://github.com/usuario/repo.git"
          />
        </label>

        <label class="checkbox-label">
          <input type="checkbox" bind:checked={initGit} />
          <span>Inicializar repositório Git local se não existir</span>
        </label>

        <div class="modal-footer">
          <button type="button" class="btn-cancel" onclick={() => onClose?.()}>
            Cancelar
          </button>
          <button type="submit" class="btn-submit" disabled={isSubmitting || !name.trim()}>
            {isSubmitting ? "Criando no Hub..." : "Criar Projeto"}
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
  .error-banner {
    background: rgba(239, 68, 68, 0.2);
    border: 1px solid #ef4444;
    color: #fca5a5;
    padding: 6px 10px;
    border-radius: 4px;
    font-size: 0.75rem;
    margin-bottom: 12px;
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
  input[type="text"] {
    background: #0f172a;
    border: 1px solid var(--border-color);
    color: var(--text-main);
    padding: 6px 10px;
    border-radius: 4px;
    font-size: 0.85rem;
  }
  input[type="text"]:focus {
    outline: none;
    border-color: var(--accent-cyan);
  }
  .checkbox-label {
    flex-direction: row;
    align-items: center;
    gap: 8px;
    cursor: pointer;
  }
  .modal-footer {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    margin-top: 8px;
  }
  .btn-cancel {
    background: transparent;
    border: 1px solid var(--border-color);
    color: var(--text-muted);
    padding: 6px 12px;
    border-radius: 4px;
    cursor: pointer;
    font-size: 0.8rem;
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
