<script lang="ts">
  import { onMount } from "svelte";
  import * as monaco from "monaco-editor";
  import {
    applyDiagnostics,
    clearDiagnostics,
    closeDocument,
    definitionAt,
    documentChanged,
    documentSaved,
    openDocument,
    registerProviders,
  } from "../lsp-monaco";
  import { closeConnectionsFor, getConnection, supportedLanguages, type LspConnection } from "../lsp";

  /** Nome no nosso catálogo (mesmo vocabulário de `getLanguageFromPath` em App.svelte) → languageId do protocolo. */
  const LSP_LANGUAGE: Record<string, string> = {
    python: "python",
    typescript: "typescript",
    tsx: "typescriptreact",
    javascript: "javascript",
    json: "json",
    yaml: "yaml",
    css: "css",
    scss: "scss",
    html: "html",
    bash: "shellscript",
  };

  /** languageId do protocolo → id da linguagem no Monaco. */
  const MONACO_DE_LSP: Record<string, string> = {
    python: "python",
    typescript: "typescript",
    typescriptreact: "typescript",
    javascript: "javascript",
    javascriptreact: "javascript",
    json: "json",
    yaml: "yaml",
    css: "css",
    scss: "scss",
    html: "html",
    shellscript: "shell",
  };

  export interface RevealTarget {
    line: number;
    column: number;
  }

  let {
    value = $bindable(""),
    language = "typescript",
    path = "file.ts",
    project = "",
    readonly = false,
    revealTarget = null,
    onchange,
    onNavigate,
  } = $props<{
    value?: string;
    language?: string;
    path?: string;
    /** Slug do projeto — sem isso não há como abrir ticket de LSP. */
    project?: string;
    readonly?: boolean;
    /** Muda a cada "ir para definição" bem-sucedido para o mesmo arquivo já aberto. */
    revealTarget?: RevealTarget | null;
    onchange?: (val: string) => void;
    /** Disparado quando "ir para definição"/Ctrl+clique aponta para outro arquivo do projeto. */
    onNavigate?: (path: string, line: number, column: number) => void;
  }>();

  let containerEl: HTMLDivElement;
  let editor: monaco.editor.IStandaloneCodeEditor | null = null;

  let lspReady = $state(false);
  let lspError = $state<string | null>(null);
  let lspLanguage = $derived(LSP_LANGUAGE[language] ?? null);

  let connection: LspConnection | null = null;
  let connectedModel: monaco.editor.ITextModel | null = null;
  let unsubscribeDiagnostics: (() => void) | null = null;
  let unsubscribeState: (() => void) | null = null;
  let connectSeq = 0;
  let previousProject: string | null = null;

  function disconnectLsp(): void {
    unsubscribeDiagnostics?.();
    unsubscribeDiagnostics = null;
    unsubscribeState?.();
    unsubscribeState = null;
    if (connectedModel && !connectedModel.isDisposed()) closeDocument(connectedModel);
    connectedModel = null;
    connection = null;
  }

  async function connectLsp(): Promise<void> {
    const seq = ++connectSeq;
    disconnectLsp();

    const model = editor?.getModel();
    if (!editor || !model || !project || !path || !lspLanguage) {
      lspReady = false;
      lspError = null;
      return;
    }

    const suportadas = await supportedLanguages();
    if (seq !== connectSeq) return;
    if (!(lspLanguage in suportadas)) {
      // Degradar em silêncio: a imagem pode não ter o servidor dessa linguagem.
      lspReady = false;
      lspError = null;
      return;
    }

    let conexao: LspConnection;
    try {
      conexao = await getConnection(project, lspLanguage);
    } catch (erro) {
      if (seq !== connectSeq) return;
      lspReady = false;
      lspError = erro instanceof Error ? erro.message : String(erro);
      return;
    }
    if (seq !== connectSeq || model.isDisposed()) return;

    connection = conexao;
    connectedModel = model;

    const monacoLanguage = MONACO_DE_LSP[lspLanguage] ?? lspLanguage;
    registerProviders(monaco, monacoLanguage);
    clearDiagnostics(monaco, model);
    openDocument(conexao, model, path, lspLanguage);

    unsubscribeDiagnostics = conexao.onDiagnostics((arquivo, itens) => {
      if (connectedModel) applyDiagnostics(monaco, connectedModel, arquivo, itens);
    });
    unsubscribeState = conexao.onStateChange((pronto, erro) => {
      lspReady = pronto;
      lspError = erro;
    });
  }

  async function gotoDefinition(): Promise<void> {
    const model = editor?.getModel();
    const posicao = editor?.getPosition();
    if (!editor || !model || !posicao) return;

    let destino;
    try {
      destino = await definitionAt(model, posicao);
    } catch {
      return;
    }
    if (!destino || destino.external) return;
    onNavigate?.(destino.path, destino.line, destino.column);
  }

  function applyReveal(target: RevealTarget): void {
    const ed = editor;
    if (!ed) return;
    // Reaplicada, e não aplicada uma vez: quando o arquivo troca de conteúdo no
    // mesmo instante em que pedimos a posição, o wrapper reposiciona o cursor
    // depois de nós — ver a mesma nota em `use-lsp.ts` (apps/web).
    const posicao = { lineNumber: target.line, column: target.column };
    const aplicar = () => {
      ed.revealPositionInCenter(posicao);
      ed.setPosition(posicao);
    };
    aplicar();
    let restantes = 12;
    const insistir = () => {
      const atual = ed.getPosition();
      if (atual?.lineNumber !== target.line) aplicar();
      if (--restantes > 0) requestAnimationFrame(insistir);
      else ed.focus();
    };
    requestAnimationFrame(insistir);
  }

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

    const changeSubscription = editor.onDidChangeModelContent((evento) => {
      if (!editor) return;
      const val = editor.getValue();
      value = val;
      onchange?.(val);
      const model = editor.getModel();
      if (model) documentChanged(model, evento);
    });

    editor.addAction({
      id: "eltanix.gotoDefinition",
      label: "Ir para definição",
      keybindings: [monaco.KeyCode.F12],
      contextMenuGroupId: "navigation",
      contextMenuOrder: 1,
      run: () => void gotoDefinition(),
    });

    // Ctrl+clique é a memória muscular de quem vem do VS Code.
    editor.onMouseDown((evento) => {
      if (!evento.event.ctrlKey && !evento.event.metaKey) return;
      if (evento.target.type !== monaco.editor.MouseTargetType.CONTENT_TEXT) return;
      evento.event.preventDefault();
      void gotoDefinition();
    });

    void connectLsp();

    return () => {
      changeSubscription.dispose();
      disconnectLsp();
      editor?.dispose();
      editor = null;
    };
  });

  // Reconecta o LSP quando o arquivo, o projeto ou a linguagem detectada mudam.
  $effect(() => {
    void path;
    void project;
    void lspLanguage;
    if (editor) void connectLsp();
  });

  // Trocar de projeto invalida os servidores conectados nele: indexaram outra raiz.
  $effect(() => {
    if (previousProject !== null && previousProject !== project) {
      closeConnectionsFor(previousProject);
    }
    previousProject = project;
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

  $effect(() => {
    if (revealTarget) applyReveal(revealTarget);
  });

  /** Chamado pelo pai (via `bind:this`) depois de um save bem-sucedido no disco. */
  export function notifySaved(): void {
    const model = editor?.getModel();
    if (model) documentSaved(model);
  }
</script>

<div class="editor-wrapper">
  <div class="editor-header">
    <span class="file-path">{path}</span>
    <span class="file-lang">{language}</span>
    {#if lspLanguage}
      <span class="lsp-badge {lspError ? 'lsp-error' : lspReady ? 'lsp-ok' : 'lsp-loading'}" title={lspError ?? undefined}>
        <span class="lsp-dot"></span>
        {lspError ? "LSP falhou" : lspReady ? "LSP" : "LSP…"}
      </span>
    {/if}
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
    align-items: center;
    gap: 10px;
    height: 28px;
    padding: 0 12px;
    background-color: #252526;
    color: #cccccc;
    font-size: 0.75rem;
    border-bottom: 1px solid #333;
  }
  .file-path {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .file-lang {
    color: #858585;
  }
  .lsp-badge {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 0.68rem;
    padding: 1px 6px;
    border-radius: 3px;
    border: 1px solid #3a3a3a;
  }
  .lsp-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
  }
  .lsp-ok {
    color: #4ade80;
  }
  .lsp-ok .lsp-dot {
    background: #4ade80;
  }
  .lsp-loading {
    color: #94a3b8;
  }
  .lsp-loading .lsp-dot {
    background: #94a3b8;
    animation: pulse 1.2s ease-in-out infinite;
  }
  .lsp-error {
    color: #f87171;
  }
  .lsp-error .lsp-dot {
    background: #f87171;
  }
  @keyframes pulse {
    0%, 100% { opacity: 0.3; }
    50% { opacity: 1; }
  }
  .monaco-container {
    flex: 1;
    width: 100%;
    height: calc(100% - 28px);
  }
</style>
