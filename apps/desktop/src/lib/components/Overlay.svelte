<script lang="ts">
  /**
   * Overlay genérico de lista filtrada — porta do `Overlay` interno em
   * `apps/web/components/ide/Overlays.tsx`. Quick Open e Command Palette são
   * a mesma interação (digitar filtra, setas navegam, Enter confirma); só a
   * fonte dos itens muda, então os dois componentes envolvem este aqui.
   */
  import { onMount } from "svelte";

  export interface OverlayItem {
    id: string;
    label: string;
    hint?: string;
  }

  let {
    placeholder,
    items,
    onSelect,
    onClose,
    empty = "Nenhum resultado.",
  } = $props<{
    placeholder: string;
    items: (query: string) => OverlayItem[];
    onSelect: (id: string) => void;
    onClose: () => void;
    empty?: string;
  }>();

  let query = $state("");
  let cursor = $state(0);
  let inputEl: HTMLInputElement;
  let listEl: HTMLDivElement;

  let visible = $derived(items(query).slice(0, 60));

  onMount(() => {
    inputEl?.focus();
  });

  // Digitar filtra a lista; sem isto o cursor apontaria para um índice que não existe mais.
  $effect(() => {
    void query;
    cursor = 0;
  });

  $effect(() => {
    void cursor;
    listEl?.querySelector<HTMLElement>(`[data-index="${cursor}"]`)?.scrollIntoView({ block: "nearest" });
  });

  function handleKeydown(e: KeyboardEvent): void {
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      cursor = Math.min(cursor + 1, visible.length - 1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      cursor = Math.max(cursor - 1, 0);
    } else if (e.key === "Enter") {
      e.preventDefault();
      const escolhido = visible[cursor];
      if (escolhido) {
        onSelect(escolhido.id);
        onClose();
      }
    }
  }

  function choose(item: OverlayItem): void {
    onSelect(item.id);
    onClose();
  }
</script>

<div class="overlay-backdrop" role="presentation" onmousedown={() => onClose()}>
  <div class="overlay" role="dialog" onmousedown={(e) => e.stopPropagation()}>
    <input
      bind:this={inputEl}
      bind:value={query}
      {placeholder}
      onkeydown={handleKeydown}
      class="overlay-input"
    />
    <div class="overlay-list" bind:this={listEl}>
      {#each visible as item, index (item.id)}
        <button
          type="button"
          data-index={index}
          class="overlay-item {index === cursor ? 'active' : ''}"
          onmouseenter={() => (cursor = index)}
          onclick={() => choose(item)}
        >
          <span class="overlay-label">{item.label}</span>
          {#if item.hint}
            <span class="overlay-hint">{item.hint}</span>
          {/if}
        </button>
      {/each}
      {#if visible.length === 0}
        <div class="overlay-empty">{empty}</div>
      {/if}
    </div>
  </div>
</div>

<style>
  .overlay-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.5);
    display: flex;
    justify-content: center;
    align-items: flex-start;
    padding-top: 12vh;
    z-index: 10000;
  }
  .overlay {
    width: 560px;
    max-width: 90vw;
    max-height: 60vh;
    display: flex;
    flex-direction: column;
    background: #1e293b;
    border: 1px solid var(--border-color);
    border-radius: 8px;
    box-shadow: 0 20px 50px rgba(0, 0, 0, 0.6);
    overflow: hidden;
  }
  .overlay-input {
    background: var(--bg-dark);
    border: none;
    border-bottom: 1px solid var(--border-color);
    color: var(--text-main);
    padding: 12px 14px;
    font-size: 0.9rem;
  }
  .overlay-input:focus {
    outline: none;
  }
  .overlay-list {
    overflow-y: auto;
    padding: 4px;
  }
  .overlay-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    width: 100%;
    background: transparent;
    border: none;
    color: var(--text-main);
    padding: 7px 10px;
    border-radius: 4px;
    font-size: 0.82rem;
    cursor: pointer;
    text-align: left;
  }
  .overlay-item.active {
    background: var(--accent-blue);
    color: white;
  }
  .overlay-label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .overlay-hint {
    color: var(--text-muted);
    font-size: 0.7rem;
    flex-shrink: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 45%;
  }
  .overlay-item.active .overlay-hint {
    color: rgba(255, 255, 255, 0.75);
  }
  .overlay-empty {
    padding: 16px;
    text-align: center;
    color: var(--text-muted);
    font-size: 0.8rem;
  }
</style>
