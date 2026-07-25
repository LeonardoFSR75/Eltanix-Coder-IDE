"use client";

import MonacoEditor, { DiffEditor } from "@monaco-editor/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { get, put } from "@/lib/client";

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

export function Editor({
  path,
  onDirtyChange,
}: {
  path: string | null;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const [content, setContent] = useState("");
  const [language, setLanguage] = useState("plaintext");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const originalRef = useRef("");

  useEffect(() => {
    if (!path) return;
    let cancelled = false;

    setLoading(true);
    setError(null);
    get<FileResponse>(`/api/workspace/file?path=${encodeURIComponent(path)}`)
      .then((data) => {
        // Sem esta guarda, trocar de arquivo rápido faria a resposta lenta do
        // anterior sobrescrever o conteúdo do atual.
        if (cancelled) return;
        setContent(data.content);
        originalRef.current = data.content;
        setLanguage(MONACO_LANGUAGE[data.language ?? ""] ?? "plaintext");
        setDirty(false);
        onDirtyChange?.(false);
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
  }, [path, onDirtyChange]);

  const save = useCallback(async () => {
    if (!path || !dirty) return;
    setSaving(true);
    try {
      await put("/api/workspace/file", { path, content });
      originalRef.current = content;
      setDirty(false);
      onDirtyChange?.(false);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }, [path, content, dirty, onDirtyChange]);

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
        <button type="button" onClick={() => void save()} disabled={!dirty || saving}>
          {saving ? "salvando…" : "salvar (Ctrl+S)"}
        </button>
      </div>
      {error && <div className="editor-error">{error}</div>}
      {loading ? (
        <div className="editor-empty">carregando…</div>
      ) : (
        <MonacoEditor
          height="100%"
          theme="vs-dark"
          language={language}
          value={content}
          options={EDITOR_OPTIONS}
          onChange={(value) => {
            const next = value ?? "";
            setContent(next);
            const isDirty = next !== originalRef.current;
            setDirty(isDirty);
            onDirtyChange?.(isDirty);
          }}
        />
      )}
    </div>
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
  return (
    <DiffEditor
      height="100%"
      theme="vs-dark"
      language={MONACO_LANGUAGE[language ?? ""] ?? "plaintext"}
      original={original}
      modified={modified}
      options={{ ...EDITOR_OPTIONS, readOnly: true, renderSideBySide: true }}
    />
  );
}
