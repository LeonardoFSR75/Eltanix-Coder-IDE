<script lang="ts">
  let {
    project = "novaai-studio-code",
    projects = [],
    profile = "auto",
    showSidebar = true,
    showTerminal = true,
    showAgent = true,
    onProjectChange,
    onProfileChange,
    onToggleSidebar,
    onToggleTerminal,
    onToggleAgent,
    onSaveFile,
    onOpenProjectModal,
    onOpenLoginModal
  } = $props<{
    project?: string;
    projects?: { slug: string; name: string }[];
    profile?: string;
    showSidebar?: boolean;
    showTerminal?: boolean;
    showAgent?: boolean;
    onProjectChange?: (proj: string) => void;
    onProfileChange?: (prof: string) => void;
    onToggleSidebar?: () => void;
    onToggleTerminal?: () => void;
    onToggleAgent?: () => void;
    onSaveFile?: () => void;
    onOpenProjectModal?: () => void;
    onOpenLoginModal?: () => void;
  }>();

  const profiles = [
    { id: "auto", label: "auto (equilibrado)" },
    { id: "coding", label: "coding (código avançado)" },
    { id: "cheap", label: "cheap (econômico)" },
    { id: "fast", label: "fast (resposta rápida)" },
    { id: "local-first", label: "local-first (Ollama local)" }
  ];
</script>

<header class="top-menu-bar">
  <div class="brand-section">
    <span class="logo">⚡</span>
    <span class="app-name">NovaAI Studio <span class="lite-badge">Lite IDE</span></span>
  </div>

  <div class="controls-section">
    <div class="project-selector-group">
      <label class="control-label">
        📁 Projeto:
        <select
          value={project}
          onchange={(e) => onProjectChange?.((e.target as HTMLSelectElement).value)}
          class="select-input"
        >
          {#each projects as proj}
            <option value={proj.slug}>{proj.name}</option>
          {/each}
          {#if !projects.length}
            <option value="novaai-studio-code">novaai-studio-code</option>
          {/if}
        </select>
      </label>
      <button class="btn-add-project" onclick={() => onOpenProjectModal?.()} title="Criar ou vincular novo projeto no Hub">
        +
      </button>
    </div>

    <label class="control-label">
      🧠 Modelo:
      <select
        value={profile}
        onchange={(e) => onProfileChange?.((e.target as HTMLSelectElement).value)}
        class="select-input"
      >
        {#each profiles as p}
          <option value={p.id}>{p.label}</option>
        {/each}
      </select>
    </label>

    <button class="btn-action" onclick={() => onSaveFile?.()} title="Salvar arquivo ativo (Ctrl+S)">
      💾 Salvar
    </button>
  </div>

  <div class="layout-toggles">
    <button
      class="toggle-btn {showSidebar ? 'active' : ''}"
      onclick={() => onToggleSidebar?.()}
      title="Alternar Explorador de Arquivos (Ctrl+B)"
    >
      📂 Sidebar
    </button>
    <button
      class="toggle-btn {showTerminal ? 'active' : ''}"
      onclick={() => onToggleTerminal?.()}
      title="Alternar Terminal (Ctrl+`)"
    >
      💻 Terminal
    </button>
    <button
      class="toggle-btn {showAgent ? 'active' : ''}"
      onclick={() => onToggleAgent?.()}
      title="Alternar Agente Agêntico"
    >
      🤖 Agente
    </button>
    <button
      class="toggle-btn"
      onclick={() => onOpenLoginModal?.()}
      title="Autenticação e Sessão de Usuário"
    >
      👤 Login
    </button>
  </div>
</header>

<style>
  .top-menu-bar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    height: 38px;
    background-color: var(--bg-dark);
    border-bottom: 1px solid var(--border-color);
    padding: 0 12px;
    font-size: 0.8rem;
    user-select: none;
  }
  .brand-section {
    display: flex;
    align-items: center;
    gap: 8px;
    font-weight: 700;
  }
  .lite-badge {
    background: #0284c7;
    color: white;
    font-size: 0.65rem;
    padding: 2px 6px;
    border-radius: 4px;
    text-transform: uppercase;
    font-weight: 700;
  }
  .controls-section {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .project-selector-group {
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .btn-add-project {
    background: var(--bg-surface);
    color: var(--accent-cyan);
    border: 1px solid var(--border-color);
    border-radius: 4px;
    padding: 1px 6px;
    font-weight: bold;
    cursor: pointer;
  }
  .btn-add-project:hover {
    background: var(--accent-blue);
    color: white;
  }
  .control-label {
    display: flex;
    align-items: center;
    gap: 6px;
    color: var(--text-muted);
  }
  .select-input {
    background: var(--bg-surface);
    color: var(--text-main);
    border: 1px solid var(--border-color);
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 0.75rem;
  }
  .btn-action {
    background: var(--accent-blue);
    color: white;
    border: none;
    padding: 4px 10px;
    border-radius: 4px;
    font-size: 0.75rem;
    cursor: pointer;
    font-weight: 600;
  }
  .btn-action:hover {
    background: #2563eb;
  }
  .layout-toggles {
    display: flex;
    gap: 4px;
  }
  .toggle-btn {
    background: transparent;
    border: 1px solid var(--border-color);
    color: var(--text-muted);
    padding: 3px 8px;
    border-radius: 4px;
    font-size: 0.75rem;
    cursor: pointer;
  }
  .toggle-btn.active {
    background: var(--bg-surface);
    color: var(--accent-cyan);
    border-color: var(--accent-cyan);
  }
</style>
