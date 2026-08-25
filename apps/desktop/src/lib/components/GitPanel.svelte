<script lang="ts">
  import {
    checkoutBranch,
    commitChanges,
    discardChanges,
    getBranches,
    getGitDiff,
    getGitStatus,
    stageFiles,
    unstageFiles,
    type GitBranches,
    type GitFile,
    type GitStatus,
  } from "../api/git";

  let { project = "novaai-studio-code", onOpenFile } = $props<{
    project?: string;
    /** Abre o arquivo no editor ao clicar numa linha (opcional). */
    onOpenFile?: (path: string) => void;
  }>();

  let status = $state<GitStatus | null>(null);
  let branches = $state<GitBranches | null>(null);
  let loading = $state(false);
  let erro = $state<string | null>(null);
  let commitMessage = $state("");
  let committing = $state(false);
  let showBranchPicker = $state(false);

  let diffPath = $state<string | null>(null);
  let diffStaged = $state(false);
  let diffText = $state<string | null>(null);
  let diffLoading = $state(false);

  let staged = $derived((status?.files ?? []).filter((f: GitFile) => f.status === "staged"));
  let untracked = $derived((status?.files ?? []).filter((f: GitFile) => f.status === "untracked"));
  let changed = $derived(
    (status?.files ?? []).filter((f: GitFile) => f.status !== "staged" && f.status !== "untracked"),
  );

  async function refresh(): Promise<void> {
    if (!project) return;
    loading = true;
    erro = null;
    try {
      const [s, b] = await Promise.all([getGitStatus(project), getBranches(project)]);
      status = s;
      branches = b;
    } catch (err) {
      erro = err instanceof Error ? err.message : String(err);
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    if (project) void refresh();
  });

  async function openDiff(path: string, staged: boolean): Promise<void> {
    diffPath = path;
    diffStaged = staged;
    diffLoading = true;
    diffText = null;
    try {
      const res = await getGitDiff(project, path, staged);
      diffText = res.diff || "(sem diferenças textuais — binário ou arquivo novo vazio)";
    } catch (err) {
      diffText = err instanceof Error ? err.message : String(err);
    } finally {
      diffLoading = false;
    }
  }

  async function doStage(paths: string[]): Promise<void> {
    if (paths.length === 0) return;
    try {
      await stageFiles(project, paths);
      await refresh();
    } catch (err) {
      erro = err instanceof Error ? err.message : String(err);
    }
  }

  async function doUnstage(paths: string[]): Promise<void> {
    if (paths.length === 0) return;
    try {
      await unstageFiles(project, paths);
      await refresh();
    } catch (err) {
      erro = err instanceof Error ? err.message : String(err);
    }
  }

  async function doDiscard(path: string): Promise<void> {
    if (!confirm(`Descartar as alterações locais em "${path}"? Isso não pode ser desfeito.`)) return;
    try {
      await discardChanges(project, [path]);
      await refresh();
    } catch (err) {
      erro = err instanceof Error ? err.message : String(err);
    }
  }

  async function doCommit(): Promise<void> {
    const mensagem = commitMessage.trim();
    if (!mensagem || staged.length === 0 || committing) return;
    committing = true;
    erro = null;
    try {
      await commitChanges(project, mensagem);
      commitMessage = "";
      await refresh();
    } catch (err) {
      erro = err instanceof Error ? err.message : String(err);
    } finally {
      committing = false;
    }
  }

  async function switchBranch(branch: string): Promise<void> {
    if (!branches || branch === branches.current) {
      showBranchPicker = false;
      return;
    }
    try {
      await checkoutBranch(project, branch);
      showBranchPicker = false;
      await refresh();
    } catch (err) {
      erro = err instanceof Error ? err.message : String(err);
    }
  }

  function statusIcon(s: GitFile["status"]): string {
    switch (s) {
      case "added":
        return "A";
      case "modified":
        return "M";
      case "deleted":
        return "D";
      case "renamed":
        return "R";
      case "untracked":
        return "U";
      case "staged":
        return "●";
      default:
        return "?";
    }
  }
</script>

<div class="git-panel">
  <div class="git-header">
    <span class="git-title">GIT</span>
    <button class="btn-icon" onclick={refresh} title="Atualizar status">🔄</button>
  </div>

  {#if status}
    <div class="branch-row">
      <button class="branch-btn" onclick={() => (showBranchPicker = !showBranchPicker)} title="Trocar de branch">
        🌿 {status.branch}
      </button>
      <span class="head-sha">{status.head}</span>
    </div>
    {#if showBranchPicker && branches}
      <div class="branch-picker">
        {#each branches.branches as b (b)}
          <button class="branch-option {b === branches.current ? 'current' : ''}" onclick={() => switchBranch(b)}>
            {b}
          </button>
        {/each}
      </div>
    {/if}
  {/if}

  {#if erro}
    <div class="git-error">{erro}</div>
  {/if}

  <div class="git-sections">
    {#if loading && !status}
      <div class="git-hint">carregando…</div>
    {:else if status && staged.length === 0 && changed.length === 0 && untracked.length === 0}
      <div class="git-hint">Nada para commitar — working tree limpa.</div>
    {/if}

    {#if staged.length > 0}
      <div class="git-section">
        <div class="section-title">
          <span>Staged ({staged.length})</span>
          <button class="text-btn" onclick={() => doUnstage(staged.map((f) => f.path))}>desfazer tudo</button>
        </div>
        {#each staged as f (f.path)}
          <div class="file-row">
            <button class="file-main" onclick={() => openDiff(f.path, true)} title="Ver diff">
              <span class="status-code staged">{statusIcon(f.status)}</span>
              <span class="file-path">{f.path}</span>
            </button>
            <button class="file-action" onclick={() => doUnstage([f.path])} title="Tirar do stage">−</button>
          </div>
        {/each}
      </div>
    {/if}

    {#if changed.length > 0}
      <div class="git-section">
        <div class="section-title">
          <span>Alterações ({changed.length})</span>
          <button class="text-btn" onclick={() => doStage(changed.map((f) => f.path))}>stage tudo</button>
        </div>
        {#each changed as f (f.path)}
          <div class="file-row">
            <button class="file-main" onclick={() => openDiff(f.path, false)} title="Ver diff">
              <span class="status-code {f.status}">{statusIcon(f.status)}</span>
              <span class="file-path">{f.path}</span>
            </button>
            <button class="file-action" onclick={() => doStage([f.path])} title="Stage">+</button>
            <button class="file-action danger" onclick={() => doDiscard(f.path)} title="Descartar">⨯</button>
          </div>
        {/each}
      </div>
    {/if}

    {#if untracked.length > 0}
      <div class="git-section">
        <div class="section-title">
          <span>Sem rastreamento ({untracked.length})</span>
          <button class="text-btn" onclick={() => doStage(untracked.map((f) => f.path))}>stage tudo</button>
        </div>
        {#each untracked as f (f.path)}
          <div class="file-row">
            <button class="file-main" onclick={() => onOpenFile?.(f.path)} title="Abrir arquivo">
              <span class="status-code untracked">{statusIcon(f.status)}</span>
              <span class="file-path">{f.path}</span>
            </button>
            <button class="file-action" onclick={() => doStage([f.path])} title="Stage">+</button>
          </div>
        {/each}
      </div>
    {/if}

    {#if diffPath}
      <div class="diff-preview">
        <div class="diff-header">
          <span>{diffPath} {diffStaged ? "(staged)" : ""}</span>
          <button class="btn-icon" onclick={() => (diffPath = null)}>×</button>
        </div>
        {#if diffLoading}
          <div class="git-hint">carregando diff…</div>
        {:else}
          <pre class="diff-text">{diffText}</pre>
        {/if}
      </div>
    {/if}
  </div>

  <div class="commit-box">
    <textarea
      bind:value={commitMessage}
      placeholder={staged.length > 0 ? "Mensagem do commit..." : "Faça stage de algo primeiro..."}
      rows={2}
      disabled={staged.length === 0 || committing}
    ></textarea>
    <button
      class="btn-commit"
      onclick={doCommit}
      disabled={!commitMessage.trim() || staged.length === 0 || committing}
    >
      {committing ? "Commitando..." : `Commit (${staged.length})`}
    </button>
  </div>
</div>

<style>
  .git-panel {
    display: flex;
    flex-direction: column;
    width: 260px;
    height: 100%;
    background-color: var(--bg-panel);
    border-right: 1px solid var(--border-color);
    font-size: 0.8rem;
  }
  .git-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    height: 32px;
    padding: 0 12px;
    background-color: var(--bg-dark);
    border-bottom: 1px solid var(--border-color);
  }
  .git-title {
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
    font-size: 0.85rem;
  }
  .btn-icon:hover {
    color: var(--text-main);
  }
  .branch-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 6px 12px;
    border-bottom: 1px solid var(--border-color);
  }
  .branch-btn {
    background: transparent;
    border: none;
    color: var(--accent-cyan);
    cursor: pointer;
    font-size: 0.78rem;
    padding: 0;
  }
  .head-sha {
    color: var(--text-muted);
    font-family: monospace;
    font-size: 0.7rem;
  }
  .branch-picker {
    display: flex;
    flex-direction: column;
    max-height: 140px;
    overflow-y: auto;
    border-bottom: 1px solid var(--border-color);
  }
  .branch-option {
    background: transparent;
    border: none;
    color: var(--text-main);
    text-align: left;
    padding: 4px 16px;
    font-size: 0.76rem;
    cursor: pointer;
  }
  .branch-option:hover {
    background: var(--bg-surface);
  }
  .branch-option.current {
    color: var(--accent-cyan);
    font-weight: 600;
  }
  .git-error {
    background: rgba(239, 68, 68, 0.15);
    color: #fca5a5;
    padding: 6px 12px;
    font-size: 0.72rem;
  }
  .git-sections {
    flex: 1;
    overflow-y: auto;
    padding: 4px 0;
  }
  .git-hint {
    padding: 10px 12px;
    color: var(--text-muted);
    font-size: 0.75rem;
  }
  .git-section {
    padding: 4px 0;
  }
  .section-title {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 4px 12px;
    color: var(--text-muted);
    font-size: 0.68rem;
    font-weight: 700;
    text-transform: uppercase;
  }
  .text-btn {
    background: none;
    border: none;
    color: var(--accent-cyan);
    cursor: pointer;
    font-size: 0.65rem;
    text-transform: none;
    font-weight: 600;
  }
  .file-row {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 2px 12px;
  }
  .file-row:hover {
    background: var(--bg-surface);
  }
  .file-main {
    flex: 1;
    display: flex;
    align-items: center;
    gap: 6px;
    background: transparent;
    border: none;
    color: var(--text-main);
    cursor: pointer;
    padding: 3px 0;
    text-align: left;
    overflow: hidden;
  }
  .file-path {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 0.76rem;
  }
  .status-code {
    font-weight: 700;
    font-size: 0.68rem;
    width: 14px;
    text-align: center;
    flex-shrink: 0;
  }
  .status-code.added,
  .status-code.staged {
    color: #34d399;
  }
  .status-code.modified {
    color: #fbbf24;
  }
  .status-code.deleted {
    color: #f87171;
  }
  .status-code.renamed {
    color: #60a5fa;
  }
  .status-code.untracked {
    color: #94a3b8;
  }
  .file-action {
    background: transparent;
    border: none;
    color: var(--text-muted);
    cursor: pointer;
    font-size: 0.8rem;
    padding: 2px 6px;
    flex-shrink: 0;
  }
  .file-action:hover {
    color: var(--text-main);
  }
  .file-action.danger:hover {
    color: #f87171;
  }
  .diff-preview {
    margin: 6px 8px;
    border: 1px solid var(--border-color);
    border-radius: 4px;
    background: #0f172a;
  }
  .diff-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 4px 8px;
    border-bottom: 1px solid var(--border-color);
    font-size: 0.7rem;
    color: var(--text-muted);
  }
  .diff-text {
    margin: 0;
    padding: 8px;
    max-height: 300px;
    overflow: auto;
    font-size: 0.68rem;
    font-family: monospace;
    white-space: pre-wrap;
    word-break: break-word;
    color: #cbd5e1;
  }
  .commit-box {
    padding: 8px;
    border-top: 1px solid var(--border-color);
    background: var(--bg-dark);
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .commit-box textarea {
    background: var(--bg-panel);
    border: 1px solid var(--border-color);
    color: var(--text-main);
    border-radius: 4px;
    padding: 6px 8px;
    font-size: 0.78rem;
    resize: none;
    font-family: inherit;
  }
  .commit-box textarea:focus {
    outline: none;
    border-color: var(--accent-cyan);
  }
  .btn-commit {
    background: var(--accent-blue);
    color: white;
    border: none;
    padding: 6px;
    border-radius: 4px;
    font-size: 0.78rem;
    font-weight: 600;
    cursor: pointer;
  }
  .btn-commit:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
