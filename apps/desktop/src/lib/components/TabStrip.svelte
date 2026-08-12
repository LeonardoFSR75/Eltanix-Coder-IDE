<script lang="ts">
  export interface TabItem {
    path: string;
    name: string;
    isDirty: boolean;
  }

  let { tabs = [], activePath = "", onSelectTab, onCloseTab } = $props<{
    tabs?: TabItem[];
    activePath?: string;
    onSelectTab?: (path: string) => void;
    onCloseTab?: (path: string) => void;
  }>();

  function handleSelect(path: string) {
    if (onSelectTab) onSelectTab(path);
  }

  function handleClose(e: MouseEvent, path: string) {
    e.stopPropagation();
    if (onCloseTab) onCloseTab(path);
  }
</script>

<div class="tab-strip">
  {#each tabs as tab (tab.path)}
    <div
      class="tab-item {activePath === tab.path ? 'active' : ''}"
      role="button"
      tabindex="0"
      onclick={() => handleSelect(tab.path)}
      onkeydown={(e) => { if (e.key === 'Enter') handleSelect(tab.path); }}
    >
      <span class="tab-name">
        {tab.name}{#if tab.isDirty}<span class="dirty-dot">*</span>{/if}
      </span>
      <button class="btn-close" onclick={(e) => handleClose(e, tab.path)}>×</button>
    </div>
  {/each}
</div>

<style>
  .tab-strip {
    display: flex;
    height: 32px;
    background-color: #18181b;
    border-bottom: 1px solid var(--border-color);
    overflow-x: auto;
    user-select: none;
  }
  .tab-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 0 12px;
    height: 100%;
    background-color: #27272a;
    border-right: 1px solid #3f3f46;
    color: var(--text-muted);
    font-size: 0.8rem;
    cursor: pointer;
    white-space: nowrap;
  }
  .tab-item.active {
    background-color: #0f172a;
    color: var(--text-main);
    border-top: 2px solid var(--accent-cyan);
    font-weight: 500;
  }
  .dirty-dot {
    color: #f59e0b;
    font-weight: bold;
    margin-left: 2px;
  }
  .btn-close {
    background: transparent;
    border: none;
    color: var(--text-muted);
    font-size: 1rem;
    cursor: pointer;
    padding: 0 2px;
    border-radius: 2px;
  }
  .btn-close:hover {
    color: #ef4444;
    background: rgba(239, 68, 68, 0.2);
  }
</style>
