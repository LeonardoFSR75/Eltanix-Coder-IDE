"use client";

import MonacoEditor, { DiffEditor } from "@monaco-editor/react";
import "@/lib/monaco-loader";
import { useCallback, useEffect, useRef, useState } from "react";
import { get, post, put } from "@/lib/client";
import { useLsp, type LspStatus } from "@/lib/use-lsp";
import { useTheme } from "@/lib/theme";

interface FileResponse {
  path: string;
  content: string;
  language: string | null;
  lines: number;
}

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

const EDITOR_OPTIONS = {
  fontSize: 13,
  fontFamily: 'ui-monospace, "SF Mono", Menlo, Consolas, monospace',
  minimap: { enabled: false },
  scrollBeyondLastLine: false,
  renderWhitespace: "selection" as const,
  tabSize: 2,
  automaticLayout: true,
};

function autoDetectLanguage(filePath: string, fileContent?: string): string {
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
  project,
  path,
  onDirtyChange,
  onNavigate,
  reveal,
  onRevealed,
  onCursorPositionChange,
}: {
  project: string | null;
  path: string | null;
  onDirtyChange?: (dirty: boolean) => void;
  onNavigate?: (path: string, line: number, column: number) => void;
  reveal?: { line: number; column: number } | null;
  onRevealed?: () => void;
  onCursorPositionChange?: (pos: { line: number; column: number }) => void;
}) {
  const { theme } = useTheme();
  const [content, setContent] = useState("");
  const [language, setLanguage] = useState("plaintext");
  const [rawLanguage, setRawLanguage] = useState<string | null>(null);
  const [loadedPath, setLoadedPath] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [showDiff, setShowDiff] = useState(false);
  const [headContent, setHeadContent] = useState<string | null>(null);
  const originalRef = useRef("");

  const onDirtyRef = useRef(onDirtyChange);
  useEffect(() => {
    onDirtyRef.current = onDirtyChange;
  }, [onDirtyChange]);

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

  useEffect(() => {
    if (!path || !project) return;
    let cancelled = false;

    setLoading(true);
    setError(null);
    setShowDiff(false);
    get<FileResponse>(
      `/api/workspace/file?project=${encodeURIComponent(project)}&path=${encodeURIComponent(path)}`,
    )
      .then((data) => {
        if (cancelled) return;
        setContent(data.content);
        originalRef.current = data.content;
        const detected = data.language || autoDetectLanguage(path, data.content);
        setRawLanguage(detected);
        setLanguage(MONACO_LANGUAGE[detected] ?? "plaintext");
        setDirty(false);
        setLoadedPath(path);
        onDirtyRef.current?.(false);
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
  }, [project, path]);

  const save = useCallback(async () => {
    if (!path || !project || !dirty) return;
    setSaving(true);
    try {
      await put("/api/workspace/file", { project, path, content });
      originalRef.current = content;
      setDirty(false);
      onDirtyRef.current?.(false);
      setError(null);
      lsp.onSave();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }, [project, path, content, dirty, lsp]);

  const discardChanges = useCallback(async () => {
    if (!path || !project) return;
    // Descarta alterações locais na memória
    setContent(originalRef.current);
    setDirty(false);
    onDirtyRef.current?.(false);

    // Se houver alteração registrada no Git, chama endpoint de discard
    try {
      await post("/api/git/discard", { project, paths: [path] });
    } catch {
      // Ignora erro se arquivo não estava sob controle do Git
    }
  }, [path, project]);

  const toggleDiffView = useCallback(async () => {
    if (showDiff) {
      setShowDiff(false);
      return;
    }
    if (!path || !project) return;
    try {
      const res = await get<{ original: string; modified: string }>(
        `/api/git/file-versions?project=${encodeURIComponent(project)}&path=${encodeURIComponent(path)}`,
      );
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
    onRevealed?.();
  }, [reveal, loadedPath, path, lsp, onRevealed]);

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
    return <div className="editor-empty">Selecione um arquivo na árvore à esquerda.</div>;
  }

  return (
    <div className="editor-wrap">
      <div className="editor-bar">
        <span className="editor-path">
          {path}
          {dirty && <span className="dot" title="não salvo" />}
        </span>

        <LspBadge status={lsp.status} />

        <div className="editor-bar-actions" style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
          <span className="kbd-badge" title="Linguagem detectada automaticamente">
            ⚡ {language}
          </span>

          <button
            type="button"
            className="theme-btn"
            onClick={() => void toggleDiffView()}
            title="Revisar alterações lado a lado"
          >
            {showDiff ? "Editor" : "Ver Diff"}
          </button>

          {dirty && (
            <button
              type="button"
              className="theme-btn"
              style={{ color: "var(--danger)" }}
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
          >
            {saving ? "salvando…" : "Manter (Ctrl+S)"}
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
        <MonacoEditor
          height="100%"
          theme={monacoTheme}
          language={language}
          value={content}
          options={EDITOR_OPTIONS}
          onMount={(editor, monaco) => {
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
            onDirtyRef.current?.(isDirty);
            lsp.onChange(evento);
          }}
        />
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
