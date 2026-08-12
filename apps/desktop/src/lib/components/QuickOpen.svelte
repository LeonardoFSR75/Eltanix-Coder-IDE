<script lang="ts">
  /** Ctrl+P — abrir arquivo por nome. Porta de `QuickOpen` em `apps/web/components/ide/Overlays.tsx`. */
  import { listAllFiles, type FlatFile } from "../api/workspace";
  import { fuzzyScore } from "../fuzzy";
  import Overlay, { type OverlayItem } from "./Overlay.svelte";

  let { project = "", onOpenFile, onClose } = $props<{
    project?: string;
    onOpenFile: (path: string) => void;
    onClose: () => void;
  }>();

  let files = $state<FlatFile[]>([]);
  let loading = $state(true);

  (async () => {
    try {
      files = await listAllFiles(project);
    } catch {
      files = [];
    } finally {
      loading = false;
    }
  })();

  function items(query: string): OverlayItem[] {
    if (!query) {
      return files.slice(0, 60).map((f) => ({ id: f.path, label: f.name, hint: f.path }));
    }
    return files
      .map((f) => ({ f, score: fuzzyScore(f.path, query) }))
      .filter((r): r is { f: FlatFile; score: number } => r.score !== null)
      .sort((a, b) => b.score - a.score)
      .map(({ f }) => ({ id: f.path, label: f.name, hint: f.path }));
  }
</script>

<Overlay
  placeholder={loading ? "Carregando arquivos do projeto…" : "Abrir arquivo por nome…"}
  items={items}
  onSelect={onOpenFile}
  {onClose}
  empty="Nenhum arquivo corresponde."
/>
