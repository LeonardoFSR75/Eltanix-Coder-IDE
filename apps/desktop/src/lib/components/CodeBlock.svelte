<script lang="ts">
  let { code = "", language = "text", onInsert } = $props<{
    code?: string;
    language?: string;
    onInsert?: (codeSnippet: string) => void;
  }>();

  let copied = $state(false);

  function handleCopy() {
    navigator.clipboard.writeText(code);
    copied = true;
    setTimeout(() => {
      copied = false;
    }, 2000);
  }

  function handleInsert() {
    if (onInsert) onInsert(code);
  }
</script>

<div class="code-card">
  <div class="code-header">
    <span class="code-lang">{language}</span>
    <div class="code-actions">
      <button class="btn-code" onclick={handleCopy} title="Copiar para área de transferência">
        {copied ? "✓ Copiado" : "📋 Copiar"}
      </button>
      <button class="btn-code primary" onclick={handleInsert} title="Inserir na aba ativa do editor">
        ▶ Aplicar no Editor
      </button>
    </div>
  </div>
  <pre class="code-body"><code>{code}</code></pre>
</div>

<style>
  .code-card {
    margin: 8px 0;
    background: #090d16;
    border: 1px solid var(--border-color);
    border-radius: 6px;
    overflow: hidden;
  }
  .code-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 4px 10px;
    background: #1e293b;
    border-bottom: 1px solid var(--border-color);
    font-size: 0.75rem;
  }
  .code-lang {
    color: var(--text-muted);
    font-family: monospace;
    font-weight: bold;
    text-transform: lowercase;
  }
  .code-actions {
    display: flex;
    gap: 6px;
  }
  .btn-code {
    background: transparent;
    border: 1px solid var(--border-color);
    color: var(--text-muted);
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.7rem;
    cursor: pointer;
  }
  .btn-code:hover {
    color: var(--text-main);
    background: var(--bg-surface);
  }
  .btn-code.primary {
    background: var(--accent-blue);
    color: white;
    border: none;
    font-weight: 600;
  }
  .btn-code.primary:hover {
    background: #2563eb;
  }
  .code-body {
    padding: 10px;
    font-family: Consolas, Monaco, "Courier New", monospace;
    font-size: 0.8rem;
    color: #e2e8f0;
    overflow-x: auto;
    white-space: pre;
    line-height: 1.4;
  }
</style>
