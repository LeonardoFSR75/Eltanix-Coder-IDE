<script lang="ts">
  import { searchInFiles, type SearchMatch } from "../api/workspace";

  let { project = "novaai-studio-code", onOpenMatch } = $props<{
    project?: string;
    /** Abre o arquivo no editor e revela a linha/coluna do resultado. */
    onOpenMatch?: (path: string, line: number, column: number) => void;
  }>();

  let query = $state("");
  let regex = $state(false);
  let caseSensitive = $state(false);
  let wholeWord = $state(false);
  let showOptions = $state(false);

  let loading = $state(false);
  let erro = $state<string | null>(null);
  let matches = $state<SearchMatch[]>([]);
  let filesSearched = $state(0);
  let truncated = $state(false);
  let searched = $state(false);

  let grouped = $derived.by((): Map<string, SearchMatch[]> => {
    const mapa = new Map<string, SearchMatch[]>();
    for (const m of matches) {
      if (!mapa.has(m.path)) mapa.set(m.path, []);
      mapa.get(m.path)!.push(m);
    }
    return mapa;
  });

  let debounceTimer: ReturnType<typeof setTimeout> | null = null;

  function scheduleSearch(): void {
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(runSearch, 300);
  }

  async function runSearch(): Promise<void> {
    const termo = query.trim();
    searched = true;
    if (!termo || !project) {
      matches = [];
      filesSearched = 0;
      truncated = false;
      return;
    }
    loading = true;
    erro = null;
    try {
      const res = await searchInFiles(project, termo, {
        regex,
        caseSensitive,
        wholeWord,
      });
      matches = res.matches;
      filesSearched = res.files_searched;
      truncated = res.truncated;
    } catch (err) {
      erro = err instanceof Error ? err.message : String(err);
      matches = [];
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    void query;
    void regex;
    void caseSensitive;
    void wholeWord;
    scheduleSearch();
  });
</script>

<div class="search-panel">
  <div class="search-header">
    <span class="search-title">BUSCAR</span>
  </div>

  <div class="search-input-row">
    <input
      bind:value={query}
      placeholder="Buscar no projeto…"
      class="search-input"
      onkeydown={(e) => {
        if (e.key === 'Enter') { if (debounceTimer) clearTimeout(debounceTimer); runSearch(); }
      }}
    />
    <button
      class="btn-toggle-options {showOptions ? 'active' : ''}"
      onclick={() => (showOptions = !showOptions)}
      title="Opções de busca"
    >
      ⚙️
    </button>
  </div>

  {#if showOptions}
    <div class="search-options">
      <label><input type="checkbox" bind:checked={regex} /> .* Regex</label>
      <label><input type="checkbox" bind:checked={caseSensitive} /> Aa Maiúsc/minúsc</label>
      <label><input type="checkbox" bind:checked={wholeWord} /> ab Palavra inteira</label>
    </div>
  {/if}

  <div class="search-results">
    {#if loading}
      <div class="search-hint">buscando…</div>
    {:else if erro}
      <div class="search-error">{erro}</div>
    {:else if searched && query.trim() && matches.length === 0}
      <div class="search-hint">Nenhum resultado para "{query}".</div>
    {:else if matches.length > 0}
      <div class="search-summary">
        {matches.length} resultado(s) em {grouped.size} arquivo(s) · {filesSearched} arquivo(s) varrido(s)
        {#if truncated}<span class="truncated-flag"> (truncado)</span>{/if}
      </div>
      {#each [...grouped.entries()] as [path, itens] (path)}
        <div class="search-file-group">
          <div class="search-file-path">{path} <span class="match-count">({itens.length})</span></div>
          {#each itens as m (`${m.line}:${m.column}`)}
            <button class="search-match" onclick={() => onOpenMatch?.(path, m.line, m.column)}>
              <span class="match-line">{m.line}</span>
              <span class="match-preview">{m.preview}</span>
            </button>
          {/each}
        </div>
      {/each}
    {/if}
  </div>
</div>

<style>
  .search-panel {
    display: flex;
    flex-direction: column;
    width: 280px;
    height: 100%;
    background-color: var(--bg-panel);
    border-right: 1px solid var(--border-color);
  }
  .search-header {
    display: flex;
    align-items: center;
    height: 32px;
    padding: 0 12px;
    background-color: var(--bg-dark);
    border-bottom: 1px solid var(--border-color);
  }
  .search-title {
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    color: var(--text-muted);
  }
  .search-input-row {
    display: flex;
    gap: 4px;
    padding: 8px;
  }
  .search-input {
    flex: 1;
    background: var(--bg-dark);
    border: 1px solid var(--border-color);
    color: var(--text-main);
    border-radius: 4px;
    padding: 5px 8px;
    font-size: 0.8rem;
  }
  .search-input:focus {
    outline: none;
    border-color: var(--accent-cyan);
  }
  .btn-toggle-options {
    background: transparent;
    border: 1px solid var(--border-color);
    border-radius: 4px;
    color: var(--text-muted);
    cursor: pointer;
    font-size: 0.75rem;
    padding: 0 6px;
  }
  .btn-toggle-options.active {
    border-color: var(--accent-cyan);
    color: var(--accent-cyan);
  }
  .search-options {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 0 8px 8px;
    font-size: 0.72rem;
    color: var(--text-muted);
  }
  .search-options label {
    display: flex;
    align-items: center;
    gap: 6px;
    cursor: pointer;
  }
  .search-results {
    flex: 1;
    overflow-y: auto;
    padding: 4px 0;
  }
  .search-hint {
    padding: 10px 12px;
    color: var(--text-muted);
    font-size: 0.75rem;
  }
  .search-error {
    padding: 10px 12px;
    color: #fca5a5;
    font-size: 0.75rem;
  }
  .search-summary {
    padding: 4px 12px;
    color: var(--text-muted);
    font-size: 0.68rem;
  }
  .truncated-flag {
    color: #fbbf24;
  }
  .search-file-group {
    padding: 4px 0;
  }
  .search-file-path {
    padding: 3px 12px;
    font-size: 0.74rem;
    color: var(--accent-cyan);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .match-count {
    color: var(--text-muted);
  }
  .search-match {
    display: flex;
    align-items: baseline;
    gap: 8px;
    width: 100%;
    background: transparent;
    border: none;
    color: var(--text-main);
    padding: 2px 12px 2px 20px;
    font-size: 0.74rem;
    text-align: left;
    cursor: pointer;
    overflow: hidden;
  }
  .search-match:hover {
    background: var(--bg-surface);
  }
  .match-line {
    color: var(--text-muted);
    flex-shrink: 0;
    min-width: 24px;
    text-align: right;
    font-family: monospace;
    font-size: 0.68rem;
  }
  .match-preview {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-family: monospace;
  }
</style>
