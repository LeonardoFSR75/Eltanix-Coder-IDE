<script lang="ts">
  import { onMount } from "svelte";
  import { listTree, type WorkspaceEntry } from "../api/workspace";

  let { project = "novaai-studio-code", activeFilePath = "", onSelectFile } = $props<{
    project?: string;
    activeFilePath?: string;
    onSelectFile?: (path: string) => void;
  }>();

  let entries = $state<WorkspaceEntry[]>([]);
  let expandedDirs = $state<Record<string, boolean>>({});
  let childEntriesMap = $state<Record<string, WorkspaceEntry[]>>({});
  let isLoading = $state(false);

  async function loadRoot() {
    isLoading = true;
    try {
      entries = await listTree(project, "");
    } catch {
      entries = [
        { path: "src/main.ts", name: "main.ts", is_dir: false, size_bytes: 120 },
        { path: "src/App.svelte", name: "App.svelte", is_dir: false, size_bytes: 450 },
        { path: "package.json", name: "package.json", is_dir: false, size_bytes: 300 }
      ];
    } finally {
      isLoading = false;
    }
  }

  async function toggleDir(subpath: string) {
    expandedDirs[subpath] = !expandedDirs[subpath];
    if (expandedDirs[subpath] && !childEntriesMap[subpath]) {
      try {
        childEntriesMap[subpath] = await listTree(project, subpath);
      } catch {
        childEntriesMap[subpath] = [];
      }
    }
  }

  function handleFileClick(path: string) {
    if (onSelectFile) onSelectFile(path);
  }

  function getFileIcon(name: string, isDir: boolean): string {
    if (isDir) return "📁";
    if (name.endsWith(".ts") || name.endsWith(".js")) return "📄";
    if (name.endsWith(".svelte")) return "⚡";
    if (name.endsWith(".json") || name.endsWith(".yaml") || name.endsWith(".yml")) return "⚙️";
    if (name.endsWith(".md")) return "📝";
    if (name.endsWith(".py")) return "🐍";
    return "📄";
  }

  $effect(() => {
    if (project) loadRoot();
  });
</script>

<div class="explorer-panel">
  <div class="explorer-header">
    <span class="explorer-title">EXPLORADOR</span>
    <button class="btn-icon" onclick={loadRoot} title="Atualizar árvore">🔄</button>
  </div>

  <div class="explorer-tree">
    {#if isLoading}
      <div class="loading-state">Carregando workspace...</div>
    {:else}
      {#each entries as entry (entry.path)}
        <div class="tree-node">
          {#if entry.is_dir}
            <button
              class="node-row dir"
              onclick={() => toggleDir(entry.path)}
            >
              <span class="arrow">{expandedDirs[entry.path] ? "▼" : "▶"}</span>
              <span class="icon">{getFileIcon(entry.name, true)}</span>
              <span class="name">{entry.name}</span>
            </button>
            {#if expandedDirs[entry.path]}
              <div class="sub-tree">
                {#each childEntriesMap[entry.path] || [] as child (child.path)}
                  <button
                    class="node-row file {activeFilePath === child.path ? 'active' : ''}"
                    onclick={() => handleFileClick(child.path)}
                  >
                    <span class="icon">{getFileIcon(child.name, child.is_dir)}</span>
                    <span class="name">{child.name}</span>
                  </button>
                {/each}
              </div>
            {/if}
          {:else}
            <button
              class="node-row file {activeFilePath === entry.path ? 'active' : ''}"
              onclick={() => handleFileClick(entry.path)}
            >
              <span class="icon">{getFileIcon(entry.name, false)}</span>
              <span class="name">{entry.name}</span>
            </button>
          {/if}
        </div>
      {/each}
    {/if}
  </div>
</div>

<style>
  .explorer-panel {
    display: flex;
    flex-direction: column;
    width: 240px;
    height: 100%;
    background-color: var(--bg-panel);
    border-right: 1px solid var(--border-color);
    user-select: none;
  }
  .explorer-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    height: 32px;
    padding: 0 12px;
    background-color: var(--bg-dark);
    border-bottom: 1px solid var(--border-color);
  }
  .explorer-title {
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    color: var(--text-muted);
  }
  .btn-icon {
    background: transparent;
    border: none;
    color: var(--text-muted);
    cursor: pointer;
    font-size: 0.75rem;
  }
  .btn-icon:hover {
    color: var(--text-main);
  }
  .explorer-tree {
    flex: 1;
    overflow-y: auto;
    padding: 4px 0;
  }
  .loading-state {
    padding: 12px;
    font-size: 0.8rem;
    color: var(--text-muted);
  }
  .node-row {
    display: flex;
    align-items: center;
    gap: 6px;
    width: 100%;
    padding: 4px 12px;
    background: transparent;
    border: none;
    color: var(--text-main);
    font-size: 0.8rem;
    cursor: pointer;
    text-align: left;
  }
  .node-row:hover {
    background-color: var(--bg-surface);
  }
  .node-row.active {
    background-color: #334155;
    color: var(--accent-cyan);
    font-weight: 600;
  }
  .arrow {
    font-size: 0.6rem;
    width: 10px;
    color: var(--text-muted);
  }
  .sub-tree {
    padding-left: 16px;
  }
</style>
