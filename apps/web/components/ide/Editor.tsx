"use client";

import MonacoEditor, { DiffEditor } from "@monaco-editor/react";
import "@/lib/monaco-loader";
import { useCallback, useEffect, useRef, useState } from "react";
import { getBuffer, setBuffer, updateBufferContent } from "@/lib/editor-buffer-cache";
import { useLsp, type LspStatus } from "@/lib/use-lsp";
import { useTheme } from "@/lib/theme";
import { useIde } from "@/lib/ide-store";

import { logAuditEvent } from "@/lib/api/audit";
import { readFile, writeFile } from "@/lib/api/workspace";
import {
  discardChanges as discardGitChanges,
  getFileVersions,
} from "@/lib/api/git";

import { Breadcrumbs } from "@/components/ide/Breadcrumbs";

// O nome da linguagem no nosso catálogo nem sempre é o id do Monaco.
const MONACO_LANGUAGE: Record<string, string> = {
  python: "python",
  javascript: "javascript",
  typescript: "typescript",
  tsx: "typescript",
  go: "go",
  rust: "rust",
  java: "java",
  ruby: "ruby",
  csharp: "csharp",
  cpp: "cpp",
  c: "c",
  sql: "sql",
  yaml: "yaml",
  json: "json",
  markdown: "markdown",
  html: "html",
  css: "css",
  scss: "scss",
  bash: "shell",
  dockerfile: "dockerfile",
  toml: "ini",
};

export const EDITOR_OPTIONS = {
  fontSize: 13,
  fontFamily: 'JetBrains Mono, ui-monospace, "SF Mono", Menlo, Consolas, monospace',
  minimap: { enabled: true, renderCharacters: true, maxColumn: 120 },
  scrollBeyondLastLine: false,
  renderWhitespace: "selection" as const,
  tabSize: 2,
  automaticLayout: true,
  bracketPairColorization: { enabled: true },
  cursorSmoothCaretAnimation: "on" as const,
  cursorBlinking: "smooth" as const,
  smoothScrolling: true,
  renderLineHighlight: "all" as const,
  padding: { top: 10, bottom: 10 },
};

export function autoDetectLanguage(filePath: string, fileContent?: string): string {
  const lower = filePath.toLowerCase();
  if (lower.endsWith(".py")) return "python";
  if (lower.endsWith(".tsx") || lower.endsWith(".ts")) return "typescript";
  if (lower.endsWith(".jsx") || lower.endsWith(".js")) return "javascript";
  if (lower.endsWith(".go")) return "go";
  if (lower.endsWith(".rs")) return "rust";
  if (lower.endsWith(".json")) return "json";
  if (lower.endsWith(".yaml") || lower.endsWith(".yml")) return "yaml";
  if (lower.endsWith(".sql")) return "sql";
  if (lower.endsWith(".md")) return "markdown";
  if (lower.endsWith(".css") || lower.endsWith(".scss")) return "css";
  if (lower.endsWith(".html")) return "html";
  if (lower.endsWith(".sh") || lower.endsWith(".bash")) return "shell";
  if (lower.includes("dockerfile")) return "dockerfile";

  if (fileContent) {
    if (fileContent.includes("import React") || fileContent.includes("export default")) return "typescript";
    if (fileContent.includes("def ") || fileContent.includes("import os")) return "python";
    if (fileContent.includes("package main") || fileContent.includes("func ")) return "go";
  }
  return "plaintext";
}

export function Editor({
  groupId,
  onNavigate,
  onCursorPositionChange,
}: {
  groupId: string;
  onNavigate?: (path: string, line: number, column: number) => void;
  onCursorPositionChange?: (pos: { line: number; column: number }) => void;
}) {
  const { theme } = useTheme();
  const {
    project,
    groups,
    activeGroupId,
    reveal: globalReveal,
    clearReveal,
    markDirty,
    splitGroup,
    setTerminalOpen,
    fileSyncVersion,
    codeToInsert,
    clearInsertedCode,
  } = useIde();
  const group = groups[groupId];
  const path = group?.active ?? null;
  const reveal = globalReveal?.path === path ? globalReveal : null;
  const syncVersion = path ? fileSyncVersion[path] ?? 0 : 0;
  const [content, setContent] = useState("");
  const [language, setLanguage] = useState("plaintext");
  const [rawLanguage, setRawLanguage] = useState<string | null>(null);
  const [loadedPath, setLoadedPath] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [showDiff, setShowDiff] = useState(false);
  const [showMinimap, setShowMinimap] = useState(false);
  const [headContent, setHeadContent] = useState<string | null>(null);
  const originalRef = useRef("");
  const editorInstanceRef = useRef<any>(null);

  const dirtyRef = useRef(false);
  useEffect(() => {
    dirtyRef.current = dirty;
  }, [dirty]);
  const loadedPathRef = useRef<string | null>(null);

  const lsp = useLsp({
    project,
    path: loadedPath,
    language: rawLanguage,
    onNavigate: (destino, linha, coluna) => {
      if (destino === path) lsp.revealAt(linha, coluna);
      else onNavigate?.(destino, linha, coluna);
    },
  });

  const monacoTheme = theme === "dark" ? "vs-dark" : "vs";

  // A ponte de inserção de código do chat (Fase 3) é global, não por grupo —
  // só o painel com foco no momento a consome, senão um clique em "inserir
  // no editor" com dois painéis abertos escreveria nos dois ao mesmo tempo.
  useEffect(() => {
    if (!codeToInsert || !editorInstanceRef.current || groupId !== activeGroupId) return;
    const editor = editorInstanceRef.current;
    const selection = editor.getSelection();
    const id = { major: 1, minor: 1 };
    const op = {
      identifier: id,
      range: selection,
      text: codeToInsert.code,
      forceMoveMarkers: true,
    };
    editor.executeEdits("ai-insert", [op]);
    clearInsertedCode();
  }, [codeToInsert, clearInsertedCode, groupId, activeGroupId]);

  useEffect(() => {
    if (!path || !project) return;
    // Este efeito também refaz o fetch quando `syncVersion` muda (arquivo
    // alterado no disco por fora do editor, ex.: revert de um diff do
    // agente). Se for o mesmo arquivo já carregado e o usuário tem edição
    // não salva, não sobrescreve — só um path novo força a troca.
    if (path === loadedPathRef.current && dirtyRef.current) return;

    // Recuperado do cache fora do React (editor-buffer-cache.ts): evita ida
    // à rede e, principalmente, evita perder uma edição não salva quando
    // este componente remonta por um motivo alheio ao arquivo — fechar um
    // painel vizinho reorganiza `ide.layout`, e a posição do painel
    // sobrevivente na árvore de componentes muda.
    const cached = getBuffer(path);
    if (cached) {
      setContent(cached.content);
      originalRef.current = cached.original;
      const detected = cached.language || autoDetectLanguage(path, cached.content);
      setRawLanguage(detected);
      setLanguage(MONACO_LANGUAGE[detected] ?? "plaintext");
      const isDirty = cached.content !== cached.original;
      setDirty(isDirty);
      setLoadedPath(path);
      loadedPathRef.current = path;
      setLoading(false);
      setError(null);
      markDirty(path, isDirty, groupId);
      return;
    }

    let cancelled = false;

    setLoading(true);
    setError(null);
    setShowDiff(false);
    readFile(project, path)
      .then((data) => {
        if (cancelled) return;
        setContent(data.content);
        originalRef.current = data.content;
        const detected = data.language || autoDetectLanguage(path, data.content);
        setRawLanguage(detected);
        setLanguage(MONACO_LANGUAGE[detected] ?? "plaintext");
        setDirty(false);
        setLoadedPath(path);
        loadedPathRef.current = path;
        markDirty(path, false, groupId);
        setBuffer(path, { content: data.content, original: data.content, language: data.language });
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [project, path, syncVersion, groupId, markDirty]);

  const save = useCallback(async () => {
    if (!path || !project || !dirty) return;
    setSaving(true);
    try {
      await writeFile(project, path, content);
      originalRef.current = content;
      setDirty(false);
      markDirty(path, false, groupId);
      setBuffer(path, { content, original: content, language: rawLanguage });
      setError(null);
      lsp.onSave();

      logAuditEvent({
        actor: "Usuário Desenvolvedor (IDE)",
        module: "IDE",
        action: "Edição e Salvamento de Código",
        details: `Arquivo "${path}" no projeto "${project}" foi alterado e salvo com sucesso.`,
        risk_level: "low",
        status: "success",
      }).catch(() => {});
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }, [project, path, content, dirty, lsp, groupId, markDirty, rawLanguage]);

  const discardChanges = useCallback(async () => {
    if (!path || !project) return;
    setContent(originalRef.current);
    setDirty(false);
    markDirty(path, false, groupId);
    setBuffer(path, { content: originalRef.current, original: originalRef.current, language: rawLanguage });

    try {
      await discardGitChanges(project, [path]);

      logAuditEvent({
        actor: "Usuário Desenvolvedor (IDE)",
        module: "IDE",
        action: "Descarte de Alterações Git",
        details: `Alterações não salvas do arquivo "${path}" foram descartadas.`,
        risk_level: "medium",
        status: "warning",
      }).catch(() => {});
    } catch {
      // Ignora erro se arquivo não estava sob controle do Git
    }
  }, [path, project, groupId, markDirty, rawLanguage]);

  const toggleDiffView = useCallback(async () => {
    if (showDiff) {
      setShowDiff(false);
      return;
    }
    if (!path || !project) return;
    try {
      const res = await getFileVersions(project, path);
      setHeadContent(res.original);
      setShowDiff(true);
    } catch {
      setHeadContent(originalRef.current);
      setShowDiff(true);
    }
  }, [showDiff, path, project]);

  useEffect(() => {
    if (!reveal || loadedPath !== path) return;
    lsp.revealAt(reveal.line, reveal.column);
    clearReveal();
  }, [reveal, loadedPath, path, lsp, clearReveal]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key === "s") {
        event.preventDefault();
        void save();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [save]);

  if (!path) {
    return <div className="editor-empty">Selecione um arquivo na árvore à esquerda para editar.</div>;
  }

  const editorOptions = {
    fontSize: 13,
    fontFamily: 'ui-monospace, "SF Mono", Menlo, Consolas, monospace',
    minimap: { enabled: showMinimap },
    scrollBeyondLastLine: false,
    renderWhitespace: "selection" as const,
    tabSize: 2,
    automaticLayout: true,
  };

  return (
    <div className="editor-wrap">
      <Breadcrumbs activePath={path} />
      <div className="editor-bar">
        <LspBadge status={lsp.status} />

        <div className="editor-bar-actions" style={{ marginLeft: "auto", display: "flex", gap: 4, alignItems: "center" }}>
          {!lsp.status.language && language && (
            <span className="kbd-badge" title="Linguagem detectada" style={{ fontSize: "11px", padding: "1px 6px" }}>
              ⚡ {language}
            </span>
          )}

          <button
            type="button"
            className={`theme-btn ${showMinimap ? "active" : ""}`}
            onClick={() => setShowMinimap(!showMinimap)}
            title="Alternar Minimapa"
            style={{ padding: "2px 6px", fontSize: "11px" }}
          >
            🗺️ Minimap
          </button>

          <button
            type="button"
            className="theme-btn"
            onClick={() => path && splitGroup(groupId, path, "row")}
            title="Dividir este painel na horizontal (novo grupo à direita)"
            style={{ padding: "2px 6px", fontSize: "11px" }}
          >
            ⬌ Dividir
          </button>

          <button
            type="button"
            className="theme-btn"
            onClick={() => path && splitGroup(groupId, path, "column")}
            title="Dividir este painel na vertical (novo grupo abaixo)"
            style={{ padding: "2px 6px", fontSize: "11px" }}
          >
            ⬍ Dividir
          </button>

          <button
            type="button"
            className="theme-btn"
            onClick={() => void toggleDiffView()}
            title="Revisar alterações lado a lado"
            style={{ padding: "2px 6px", fontSize: "11px" }}
          >
            {showDiff ? "Editor" : "Ver Diff"}
          </button>

          {dirty && (
            <button
              type="button"
              className="theme-btn"
              style={{ color: "var(--danger)", padding: "2px 6px", fontSize: "11px" }}
              onClick={() => void discardChanges()}
              title="Descartar alterações locais e reverter"
            >
              Descartar
            </button>
          )}

          <button
            type="button"
            className="primary"
            onClick={() => void save()}
            disabled={!dirty || saving}
            style={{ padding: "2px 8px", fontSize: "11px" }}
          >
            {saving ? "salvando…" : "Salvar (Ctrl+S)"}
          </button>

          <button
            type="button"
            className="primary"
            onClick={async () => {
              if (dirty) {
                await save();
              }
              setTerminalOpen(true);
              const cmd =
                language === "python"
                  ? `python ${path}`
                  : language === "javascript" || language === "typescript"
                  ? `node ${path}`
                  : `./${path}`;
              const evt = new CustomEvent("sicoobito:terminal:exec", { detail: { command: cmd } });
              window.dispatchEvent(evt);
            }}
            style={{ padding: "2px 10px", fontSize: "11px", background: "#16a34a", color: "#fff", border: "none", cursor: "pointer" }}
            title={`Executar ${path} no terminal do sandbox`}
          >
            ▶ Rodar
          </button>
        </div>
      </div>

      {error && <div className="editor-error">{error}</div>}

      {loading ? (
        <div className="editor-empty">carregando…</div>
      ) : showDiff ? (
        <DiffView
          original={headContent ?? originalRef.current}
          modified={content}
          language={rawLanguage}
        />
      ) : (
        <div className="editor-container-grid">
          <div className="editor-pane">
            <MonacoEditor
              height="100%"
              theme={monacoTheme}
              language={language}
              value={content}
              options={editorOptions}
              onMount={(editor, monaco) => {
                editorInstanceRef.current = editor;
                lsp.onMount(editor, monaco);
                editor.onDidChangeCursorPosition((e) => {
                  onCursorPositionChange?.({
                    line: e.position.lineNumber,
                    column: e.position.column,
                  });
                });
              }}
              onChange={(value, evento) => {
                const next = value ?? "";
                setContent(next);
                const isDirty = next !== originalRef.current;
                setDirty(isDirty);
                if (path) {
                  markDirty(path, isDirty, groupId);
                  updateBufferContent(path, next);
                }
                lsp.onChange(evento);
              }}
            />
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Estado do language server, na barra do editor.
 */
function LspBadge({ status }: { status: LspStatus }) {
  if (!status.language) return null;
  if (status.error) {
    return (
      <span className="lsp-badge lsp-error" title={status.error}>
        <span className="lsp-dot err-dot" />
        LSP falhou
      </span>
    );
  }
  return (
    <span className={`lsp-badge ${status.ready ? "lsp-ok" : "lsp-loading"}`}>
      <span className={`lsp-dot ${status.ready ? "ok-dot" : "pulse-dot"}`} />
      {status.ready ? status.language : `${status.language}…`}
    </span>
  );
}

/** Visualização lado a lado usada para revisar o que o agente propôs. */
export function DiffView({
  original,
  modified,
  language,
}: {
  original: string;
  modified: string;
  language?: string | null;
}) {
  const { theme } = useTheme();
  return (
    <DiffEditor
      height="100%"
      theme={theme === "dark" ? "vs-dark" : "vs"}
      language={MONACO_LANGUAGE[language ?? ""] ?? "plaintext"}
      original={original}
      modified={modified}
      options={{ ...EDITOR_OPTIONS, readOnly: true, renderSideBySide: true }}
    />
  );
}
