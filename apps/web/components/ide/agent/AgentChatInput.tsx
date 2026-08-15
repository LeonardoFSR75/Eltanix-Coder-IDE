"use client";

import { useEffect, useRef, useState } from "react";
import { MODE_HINT, type Mode } from "./modes";
import { ModelPicker } from "./ModelPicker";
import { useIde } from "@/lib/ide-store";

interface AgentChatInputProps {
  task: string;
  setTask: (task: string) => void;
  mode: Mode;
  setMode: (mode: Mode) => void;
  profile: string | null;
  setProfile: (profile: string | null) => void;
  focusFiles: string[];
  setFocusFiles: React.Dispatch<React.SetStateAction<string[]>>;
  focusFolder: string | null;
  setFocusFolder: (folder: string | null) => void;
  images?: string[];
  setImages?: React.Dispatch<React.SetStateAction<string[]>>;
  running: boolean;
  canSubmit: boolean;
  onSubmit: () => void;
  // True assim que a sessão ativa já tem `session` (POST /api/agent/sessions
  // concluído) — o backend fixa o modelo na criação e nunca relê o campo
  // depois, então o ModelPicker trava a partir daqui (ver ModelPicker.tsx).
  sessionStarted?: boolean;
}

export function AgentChatInput({
  task,
  setTask,
  mode,
  setMode,
  profile,
  setProfile,
  focusFiles,
  setFocusFiles,
  focusFolder,
  setFocusFolder,
  images = [],
  setImages,
  running,
  canSubmit,
  onSubmit,
  sessionStarted,
}: AgentChatInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { active, files } = useIde();
  const [showSlashHint, setShowSlashHint] = useState(false);

  // Auto-resize textarea conforme o conteúdo
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 180)}px`;
    }
  }, [task]);

  // Detecta se o usuário está digitando /
  useEffect(() => {
    setShowSlashHint(task.startsWith("/"));
  }, [task]);

  const handlePaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const items = e.clipboardData?.items;
    if (!items || !setImages) return;
    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      if (item.type.startsWith("image/")) {
        const file = item.getAsFile();
        if (file) {
          e.preventDefault();
          const reader = new FileReader();
          reader.onload = (uploadEvt) => {
            const base64 = uploadEvt.target?.result as string;
            if (base64) {
              setImages((prev) => [...prev, base64]);
            }
          };
          reader.readAsDataURL(file);
        }
      }
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const fileList = e.target.files;
    if (!fileList || !setImages) return;
    for (let i = 0; i < fileList.length; i++) {
      const file = fileList[i];
      if (file.type.startsWith("image/")) {
        const reader = new FileReader();
        reader.onload = (uploadEvt) => {
          const base64 = uploadEvt.target?.result as string;
          if (base64) {
            setImages((prev) => [...prev, base64]);
          }
        };
        reader.readAsDataURL(file);
      }
    }
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !(e.ctrlKey || e.metaKey)) {
      if (canSubmit && !running) {
        e.preventDefault();
        onSubmit();
      }
      return;
    }

    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      const textarea = e.currentTarget;
      const start = textarea.selectionStart ?? 0;
      const end = textarea.selectionEnd ?? 0;
      const nextValue = `${task.slice(0, start)}\n${task.slice(end)}`;
      setTask(nextValue);
      requestAnimationFrame(() => {
        textarea.selectionStart = start + 1;
        textarea.selectionEnd = start + 1;
      });
    }
  };

  const addActiveFile = () => {
    if (active && !focusFiles.includes(active)) {
      setFocusFiles((prev) => [...prev, active]);
    }
  };

  const removeFile = (path: string) => {
    setFocusFiles((prev) => prev.filter((p) => p !== path));
  };

  const removeImage = (index: number) => {
    setImages?.((prev) => prev.filter((_, i) => i !== index));
  };

  const [showFolderInput, setShowFolderInput] = useState(false);
  const [folderDraft, setFolderDraft] = useState("");
  const folderInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (showFolderInput && folderInputRef.current) {
      folderInputRef.current.focus();
    }
  }, [showFolderInput]);

  const submitFolder = () => {
    if (folderDraft.trim()) {
      setFocusFolder(folderDraft.trim());
    }
    setFolderDraft("");
    setShowFolderInput(false);
  };

  return (
    <div className="agent-input-container">
      <div className="agent-prompt-card">
        {/* Context Chips: Imagens anexadas, Arquivos e Pasta */}
        {(focusFiles.length > 0 || focusFolder || images.length > 0) && (
          <div className="context-chips-row flex flex-wrap gap-1.5 p-2 border-b border-border/40">
            {images.map((img, idx) => (
              <span key={idx} className="relative inline-flex items-center gap-1 bg-surface-2/80 rounded border border-border/60 p-0.5 pr-1.5 text-xs">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={img} alt="Anexo" className="w-6 h-6 object-cover rounded" />
                <span className="text-[10px] text-muted font-mono">img-{idx + 1}</span>
                <button
                  type="button"
                  className="chip-remove text-muted hover:text-foreground text-xs leading-none"
                  onClick={() => removeImage(idx)}
                >
                  ×
                </button>
              </span>
            ))}
            {focusFolder && (
              <span className="context-chip folder">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
                </svg>
                {focusFolder}
                <button
                  type="button"
                  className="chip-remove"
                  onClick={() => setFocusFolder(null)}
                >
                  ×
                </button>
              </span>
            )}
            {focusFiles.map((file) => (
              <span key={file} className="context-chip file">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
                  <polyline points="13 2 13 9 20 9" />
                </svg>
                {file.split("/").pop()}
                <button type="button" className="chip-remove" onClick={() => removeFile(file)}>
                  ×
                </button>
              </span>
            ))}
          </div>
        )}

        {/* Textarea Principal */}
        <textarea
          ref={textareaRef}
          className="agent-prompt-textarea"
          value={task}
          onChange={(e) => setTask(e.target.value)}
          onPaste={handlePaste}
          onKeyDown={handleKeyDown}
          placeholder="Pergunte ao Sicoobito Agente, cole imagens (Ctrl+V) ou use / para comandos..."
          rows={1}
          disabled={running}
        />

        {/* Slash command hint */}
        {showSlashHint && (
          <div className="slash-hint">
            <kbd>/explain</kbd> <kbd>/fix</kbd> <kbd>/test</kbd> <kbd>/refactor</kbd> <kbd>/docs</kbd>
          </div>
        )}

        {/* Rodapé do prompt card */}
        <div className="agent-prompt-footer">
          <div className="prompt-footer-left">
            {/* Modo de execução */}
            <div className="mode-toggle-group">
              <button
                type="button"
                className={`mode-toggle-btn${mode === "auto" || mode === "agent" || mode === "edit" ? " active" : ""}`}
                onClick={() => setMode("auto")}
                disabled={running}
                title={MODE_HINT.auto}
              >
                Agent
              </button>
              <button
                type="button"
                className={`mode-toggle-btn${mode === "ask" ? " active" : ""}`}
                onClick={() => setMode("ask")}
                disabled={running}
                title={MODE_HINT.ask}
              >
                Ask
              </button>
              <button
                type="button"
                className={`mode-toggle-btn${mode === "plan" ? " active" : ""}`}
                onClick={() => setMode("plan")}
                disabled={running}
                title={MODE_HINT.plan}
              >
                Plan
              </button>
            </div>

            {/* Badge de modo avançado (orchestra/explore selecionado via popover) */}
            {(mode === "orchestra" || mode === "explore") && (
              <span className="mode-active-badge" title={MODE_HINT[mode]}>
                {mode === "orchestra" ? "🎼 Orchestra" : "🔍 Explore"}
              </span>
            )}

            {/* Botões de contexto */}
            <div className="context-actions">
              {/* Botão Anexar Imagem */}
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                multiple
                className="hidden"
                style={{ display: "none" }}
                onChange={handleFileChange}
              />
              <button
                type="button"
                className="context-add-btn"
                onClick={() => fileInputRef.current?.click()}
                disabled={running}
                title="Anexar imagem (ou cole com Ctrl+V)"
              >
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                  <circle cx="8.5" cy="8.5" r="1.5" />
                  <polyline points="21 15 16 10 5 21" />
                </svg>
              </button>
              {active && !focusFiles.includes(active) && (
                <button
                  type="button"
                  className="context-add-btn"
                  onClick={addActiveFile}
                  disabled={running}
                  title={`Anexar arquivo ativo (${active.split("/").pop()})`}
                >
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                    <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
                  </svg>
                </button>
              )}
              {!focusFolder && !showFolderInput && (
                <button
                  type="button"
                  className="context-add-btn"
                  onClick={() => setShowFolderInput(true)}
                  disabled={running}
                  title="Anexar pasta de contexto"
                >
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                    <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
                    <line x1="12" y1="11" x2="12" y2="17" />
                    <line x1="9" y1="14" x2="15" y2="14" />
                  </svg>
                </button>
              )}
              {showFolderInput && (
                <div className="folder-inline-input">
                  <input
                    ref={folderInputRef}
                    type="text"
                    className="folder-input"
                    placeholder="apps/api ou src..."
                    value={folderDraft}
                    onChange={(e) => setFolderDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") { e.preventDefault(); submitFolder(); }
                      if (e.key === "Escape") { setFolderDraft(""); setShowFolderInput(false); }
                    }}
                    onBlur={() => { if (!folderDraft.trim()) setShowFolderInput(false); }}
                  />
                  <button type="button" className="folder-input-ok" onClick={submitFolder}>✓</button>
                </div>
              )}
            </div>

            {/* Model Picker */}
            <ModelPicker value={profile} onChange={setProfile} disabled={running} locked={sessionStarted} />
          </div>

          {/* Botão Enviar */}
          <button
            type="button"
            className={`agent-send-btn${canSubmit && !running ? " active" : ""}`}
            onClick={onSubmit}
            disabled={running || !canSubmit}
            title={running ? "Agente em execução…" : "Enviar (Ctrl+Enter)"}
          >
            {running ? (
              <span className="thinking-dots">
                <span />
                <span />
                <span />
              </span>
            ) : (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <line x1="12" y1="19" x2="12" y2="5" />
                <polyline points="5 12 12 5 19 12" />
              </svg>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
