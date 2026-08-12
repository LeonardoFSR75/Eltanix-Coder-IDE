<script lang="ts">
  import { onMount } from "svelte";
  import * as monaco from "monaco-editor";

  let {
    value = $bindable(""),
    language = "typescript",
    path = "file.ts",
    readonly = false,
    onchange
  } = $props<{
    value?: string;
    language?: string;
    path?: string;
    readonly?: boolean;
    onchange?: (val: string) => void;
  }>();

  let containerEl: HTMLDivElement;
  let editor: monaco.editor.IStandaloneCodeEditor | null = null;

  onMount(() => {
    if (!containerEl) return;

    editor = monaco.editor.create(containerEl, {
      value,
      language,
      theme: "vs-dark",
      automaticLayout: true,
      readOnly: readonly,
      fontSize: 13,
      minimap: { enabled: true },
      scrollBeyondLastLine: false,
    });

    const changeSubscription = editor.onDidChangeModelContent(() => {
      if (editor) {
        const val = editor.getValue();
        value = val;
        if (onchange) onchange(val);
      }
    });

    return () => {
      changeSubscription.dispose();
      editor?.dispose();
    };
  });

  $effect(() => {
    if (editor && editor.getValue() !== value) {
      editor.setValue(value);
    }
  });

  $effect(() => {
    if (editor && editor.getModel()) {
      monaco.editor.setModelLanguage(editor.getModel()!, language);
    }
  });
</script>

<div class="editor-wrapper">
  <div class="editor-header">
    <span class="file-path">{path}</span>
    <span class="file-lang">{language}</span>
  </div>
  <div bind:this={containerEl} class="monaco-container"></div>
</div>

<style>
  .editor-wrapper {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100%;
    background-color: #1e1e1e;
  }
  .editor-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    height: 28px;
    padding: 0 12px;
    background-color: #252526;
    color: #cccccc;
    font-size: 0.75rem;
    border-bottom: 1px solid #333;
  }
  .monaco-container {
    flex: 1;
    width: 100%;
    height: calc(100% - 28px);
  }
</style>
