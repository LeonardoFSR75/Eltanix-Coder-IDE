<script lang="ts">
  let { activeTab = "ide", onTabChange } = $props<{
    activeTab?: string;
    onTabChange?: (tab: string) => void;
  }>();

  const tabs = [
    { id: "ide", label: "IDE & Code" },
    { id: "rag", label: "Docs & RAG" },
    { id: "second-brain", label: "Second Brain" },
    { id: "graphify", label: "Graphify 360°" },
    { id: "mcp", label: "MCP Tools" },
    { id: "skills", label: "Skills" },
    { id: "settings", label: "Settings" }
  ];

  function selectTab(id: string) {
    if (onTabChange) onTabChange(id);
  }
</script>

<header class="header">
  <div class="brand">
    <span class="logo">⚡</span>
    <span class="title">SicoobitoCode <span class="badge">Desktop Svelte 5</span></span>
  </div>

  <nav class="nav">
    {#each tabs as tab}
      <button
        class="nav-item {activeTab === tab.id ? 'active' : ''}"
        onclick={() => selectTab(tab.id)}
      >
        {tab.label}
      </button>
    {/each}
  </nav>

  <div class="actions">
    <span class="status-indicator">● Online</span>
  </div>
</header>

<style>
  .header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: 42px;
    background-color: var(--bg-dark);
    border-bottom: 1px solid var(--border-color);
    padding: 0 16px;
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 8px;
    font-weight: 700;
  }
  .badge {
    font-size: 0.7rem;
    background: var(--accent-blue);
    color: white;
    padding: 2px 6px;
    border-radius: 4px;
    font-weight: normal;
  }
  .nav {
    display: flex;
    gap: 4px;
  }
  .nav-item {
    background: transparent;
    border: none;
    color: var(--text-muted);
    padding: 6px 12px;
    font-size: 0.85rem;
    cursor: pointer;
    border-radius: 4px;
    transition: all 0.15s ease;
  }
  .nav-item:hover {
    color: var(--text-main);
    background: var(--bg-panel);
  }
  .nav-item.active {
    color: var(--accent-cyan);
    background: var(--bg-panel);
    font-weight: 600;
  }
  .status-indicator {
    font-size: 0.75rem;
    color: #10b981;
  }
</style>
