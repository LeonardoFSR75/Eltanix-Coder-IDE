"use client";

import MonacoEditor, { DiffEditor } from "@monaco-editor/react";
import "@/lib/monaco-loader";
import { useCallback, useEffect, useRef, useState } from "react";
import { getBuffer, setBuffer, updateBufferContent } from "@/lib/editor-buffer-cache";
import { useLsp, type LspStatus } from "@/lib/use-lsp";
import { useTheme } from "@/lib/theme";
import { useIde } from "@/lib/ide-store";

import { acceptFile, revertFile } from "@/lib/api/agent";
import { logAuditEvent } from "@/lib/api/audit";
import { readFile, readFileOrNull, writeFile } from "@/lib/api/workspace";
import {
  discardChanges as discardGitChanges,
  getFileVersions,
} from "@/lib/api/git";

import { Breadcrumbs } from "@/components/ide/Breadcrumbs";
import { InlineDiffApprovalBar } from "@/components/ide/InlineDiffApprovalBar";


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
    activeSessionId,
    notifyFileChanged,
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
  const [showZebra, setShowZebra] = useState(true);
  const [headContent, setHeadContent] = useState<string | null>(null);
  const originalRef = useRef("");
  const editorInstanceRef = useRef<any>(null);

  const acceptAgentCode = useCallback(async () => {
    if (!path || !activeSessionId) return;
    try {
      await acceptFile(activeSessionId, path);
      notifyFileChanged(path);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [path, activeSessionId, notifyFileChanged]);

  const rejectAgentCode = useCallback(async () => {
    if (!path || !project || !activeSessionId) return;
    try {
      // O "antes" real é o arquivo no workspace principal (sem session_id,
      // fora do worktree isolado do agente) — mandar "" aqui apagaria/
      // esvaziaria um arquivo que já tinha conteúdo real antes da edição.
      const principal = await readFileOrNull(project, path);
      await revertFile(activeSessionId, path, principal?.content ?? "", principal !== null);
      notifyFileChanged(path);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [path, project, activeSessionId, notifyFileChanged]);

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
    const cached = getBuffer(project, path);
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
    readFile(project, path, activeSessionId)
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
        setBuffer(project, path, { content: data.content, original: data.content, language: data.language });
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
  }, [project, path, syncVersion, activeSessionId, groupId, markDirty]);


  const save = useCallback(async () => {
    if (!path || !project || saving) return;
    setSaving(true);
    try {
      await writeFile(project, path, content);
      originalRef.current = content;
      setDirty(false);
      markDirty(path, false, groupId);
      setBuffer(project, path, { content, original: content, language: rawLanguage });
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
  }, [project, path, content, saving, lsp, groupId, markDirty, rawLanguage]);

  const discardChanges = useCallback(async () => {
    if (!path || !project) return;
    if (!window.confirm(`Descartar as alterações não salvas de "${path}"? Essa ação não pode ser desfeita.`)) {
      return;
    }
    setContent(originalRef.current);
    setDirty(false);
    markDirty(path, false, groupId);
    setBuffer(project, path, { content: originalRef.current, original: originalRef.current, language: rawLanguage });

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
    // Guarda contra troca de arquivo antes da resposta chegar: sem isso, um
    // clique em "Ver Diff" seguido de troca rápida de arquivo aplicava o HEAD
    // do arquivo antigo contra o `content` do arquivo novo — um diff sem
    // sentido. `loadedPathRef` é atualizado pelo efeito de carregamento
    // sempre que o arquivo ativo muda de verdade.
    const requestedPath = path;
    try {
      const res = await getFileVersions(project, path);
      if (loadedPathRef.current !== requestedPath) return;
      setHeadContent(res.original);
      setShowDiff(true);
    } catch {
      if (loadedPathRef.current !== requestedPath) return;
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
      } else if (event.altKey && !event.shiftKey && (event.key === "Enter" || event.code === "Enter")) {
        if (activeSessionId) {
          event.preventDefault();
          void acceptAgentCode();
        }
      } else if (event.altKey && event.shiftKey && (event.key === "Backspace" || event.code === "Backspace")) {
        if (activeSessionId) {
          event.preventDefault();
          void rejectAgentCode();
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [save, activeSessionId, acceptAgentCode, rejectAgentCode]);


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
    <div className={`editor-wrap ${showZebra ? "zebra-stripes" : ""}`}>
      <Breadcrumbs activePath={path} />
      <div className="editor-bar">
        <LspBadge status={lsp.status} />

        <div className="editor-bar-actions" style={{ marginLeft: "auto", display: "flex", gap: 6, alignItems: "center" }}>
          {activeSessionId && (
            <div className="agent-worktree-pill">
              <span className="agent-worktree-label">
                <span className="agent-worktree-dot" />
                🤖 Agente (Worktree)
              </span>
              <div className="agent-worktree-actions">
                <button
                  type="button"
                  className="agent-worktree-btn-accept"
                  onClick={() => void acceptAgentCode()}
                  title="Aceitar alterações do agente e gravar no projeto principal (Alt+Enter)"
                >
                  ✓ Aceitar na IDE
                </button>
                <button
                  type="button"
                  className="agent-worktree-btn-reject"
                  onClick={() => void rejectAgentCode()}
                  title="Reverter alterações do agente (Shift+Alt+Backspace)"
                >
                  ✕ Rejeitar
                </button>
              </div>
            </div>
          )}

          {!lsp.status.language && language && (
            <span className="kbd-badge" title="Linguagem detectada" style={{ fontSize: "11px", padding: "1px 6px" }}>
              ⚡ {language}
            </span>
          )}


          <button
            type="button"
            className={`theme-btn ${showZebra ? "active" : ""}`}
            onClick={() => setShowZebra(!showZebra)}
            title="Alternar Linhas Alternadas (Zebrado)"
            style={{ padding: "4px 6px", display: "inline-flex", alignItems: "center", justifyContent: "center" }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="3" y1="6" x2="21" y2="6" />
              <line x1="3" y1="12" x2="21" y2="12" />
              <line x1="3" y1="18" x2="21" y2="18" />
              <rect x="3" y="9" width="18" height="6" fill="currentColor" fillOpacity="0.25" stroke="none" />
            </svg>
          </button>

          <button
            type="button"
            className={`theme-btn ${showMinimap ? "active" : ""}`}
            onClick={() => setShowMinimap(!showMinimap)}
            title="Alternar Minimapa"
            style={{ padding: "4px 6px", display: "inline-flex", alignItems: "center", justifyContent: "center" }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <line x1="15" y1="3" x2="15" y2="21" />
              <line x1="17" y1="7" x2="19" y2="7" />
              <line x1="17" y1="11" x2="19" y2="11" />
              <line x1="17" y1="15" x2="19" y2="15" />
            </svg>
          </button>

          <button
            type="button"
            className="theme-btn"
            onClick={() => path && splitGroup(groupId, path, "row")}
            title="Dividir painel na horizontal (novo grupo à direita)"
            style={{ padding: "4px 6px", display: "inline-flex", alignItems: "center", justifyContent: "center" }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <line x1="12" y1="3" x2="12" y2="21" />
            </svg>
          </button>

          <button
            type="button"
            className="theme-btn"
            onClick={() => path && splitGroup(groupId, path, "column")}
            title="Dividir painel na vertical (novo grupo abaixo)"
            style={{ padding: "4px 6px", display: "inline-flex", alignItems: "center", justifyContent: "center" }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <line x1="3" y1="12" x2="21" y2="12" />
            </svg>
          </button>

          <button
            type="button"
            className={`theme-btn ${showDiff ? "active" : ""}`}
            onClick={() => void toggleDiffView()}
            title={showDiff ? "Voltar ao Editor" : "Ver Comparação de Alterações (Diff)"}
            style={{ padding: "4px 6px", display: "inline-flex", alignItems: "center", justifyContent: "center" }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="18" cy="18" r="3" />
              <circle cx="6" cy="6" r="3" />
              <path d="M13 6h3a2 2 0 0 1 2 2v7" />
              <line x1="6" y1="9" x2="6" y2="21" />
            </svg>
          </button>

          {dirty && (
            <button
              type="button"
              className="theme-btn"
              style={{ color: "var(--danger)", padding: "4px 6px", display: "inline-flex", alignItems: "center", justifyContent: "center" }}
              onClick={() => void discardChanges()}
              title="Descartar alterações locais e reverter"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M3 6h18" />
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
              </svg>
            </button>
          )}

          <button
            type="button"
            className="primary"
            onClick={() => void save()}
            disabled={saving}
            style={{
              padding: "4px 7px",
              fontSize: "11px",
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
              cursor: saving ? "not-allowed" : "pointer",
              opacity: saving ? 0.7 : 1,
            }}
            title={dirty ? "Salvar alterações não salvas no disco (Ctrl+S)" : "Forçar salvamento do arquivo no disco (Ctrl+S)"}
          >
            {dirty && (
              <span
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: "50%",
                  backgroundColor: "#fbbf24",
                  boxShadow: "0 0 6px #fbbf24",
                  display: "inline-block",
                }}
                title="Alterações não salvas"
              />
            )}
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" />
              <polyline points="17 21 17 13 7 13 7 21" />
              <polyline points="7 3 7 8 15 8" />
            </svg>
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
            style={{
              padding: "4px 8px",
              fontSize: "11px",
              background: "#16a34a",
              color: "#fff",
              border: "none",
              cursor: "pointer",
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              borderRadius: 6,
            }}
            title={`Executar ${path} no terminal do sandbox`}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" stroke="none">
              <polygon points="5 3 19 12 5 21 5 3" />
            </svg>
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
          onAccept={activeSessionId ? () => void acceptAgentCode() : undefined}
          onReject={activeSessionId ? () => void rejectAgentCode() : undefined}
          zebra={showZebra}
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
                if (path && project) {
                  markDirty(path, isDirty, groupId);
                  updateBufferContent(project, path, next);
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

/** Visualização inline / lado a lado usada para revisar o que o agente propôs. */
export function DiffView({
  original,
  modified,
  language,
  onAccept,
  onReject,
  busy = false,
  zebra = true,
}: {
  original: string;
  modified: string;
  language?: string | null;
  onAccept?: () => void;
  onReject?: () => void;
  busy?: boolean;
  zebra?: boolean;
}) {
  const { theme } = useTheme();
  const [sideBySide, setSideBySide] = useState(false);

  return (
    <div className={`editor-diff-wrapper ${zebra ? "zebra-stripes" : ""}`}>
      {(onAccept || onReject) && (
        <div className="inline-approval-floating-overlay">
          <InlineDiffApprovalBar
            onAccept={() => onAccept?.()}
            onReject={() => onReject?.()}
            onToggleSideBySide={() => setSideBySide((prev) => !prev)}
            isSideBySide={sideBySide}
            busy={busy}
          />
        </div>
      )}
      <DiffEditor
        height="100%"
        theme={theme === "dark" ? "vs-dark" : "vs"}
        language={MONACO_LANGUAGE[language ?? ""] ?? "plaintext"}
        original={original}
        modified={modified}
        options={{
          ...EDITOR_OPTIONS,
          readOnly: true,
          renderSideBySide: sideBySide,
        }}
      />
    </div>
  );
}

