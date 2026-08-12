<script lang="ts">
  /** Ctrl+Shift+P — paleta de comandos. Porta de `CommandPalette` em `apps/web/components/ide/Overlays.tsx`. */
  import { fuzzyScore } from "../fuzzy";
  import Overlay, { type OverlayItem } from "./Overlay.svelte";

  export interface Command {
    id: string;
    title: string;
    shortcut?: string;
    run: () => void;
  }

  let { commands = [], onClose } = $props<{
    commands?: Command[];
    onClose: () => void;
  }>();

  function items(query: string): OverlayItem[] {
    return commands
      .map((c: Command) => ({ c, score: fuzzyScore(c.title, query) }))
      .filter((r: { c: Command; score: number | null }): r is { c: Command; score: number } => r.score !== null)
      .sort((a: { score: number }, b: { score: number }) => b.score - a.score)
      .map(({ c }: { c: Command }) => ({ id: c.id, label: c.title, hint: c.shortcut }));
  }

  function runCommand(id: string): void {
    commands.find((c: Command) => c.id === id)?.run();
  }
</script>

<Overlay
  placeholder="Digite um comando…"
  items={items}
  onSelect={runCommand}
  {onClose}
  empty="Nenhum comando corresponde."
/>
