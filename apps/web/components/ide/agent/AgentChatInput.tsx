"use client";

import { useEffect, useRef } from "react";
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
  running: boolean;
  canSubmit: boolean;
  onSubmit: () => void;
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
  running,
  canSubmit,
  onSubmit,
}: AgentChatInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { active, files } = useIde();

  // Auto-resize textarea conforme o conteúdo
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 180)}px`;
    }
  }, [task]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      if (canSubmit && !running) {
        onSubmit();
      }
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

  const promptAddFolder = () => {
    const input = window.prompt("Informe o caminho relativo da pasta para focar (ex: apps/api ou src):");
    if (input && input.trim()) {
      setFocusFolder(input.trim());
    }
  };

  return (
    <div className="agent-input-container">
      <div className="agent-prompt-card">
        {/* Barra superior do prompt card: Seleção de Modo */}
        <div className="prompt-mode-row">
          <div className="mode-toggle-group">
            <button
              type="button"
              className={`mode-toggle-btn ${mode === "auto" || mode === "agent" || mode === "edit" ? "active" : ""}`}
              onClick={() => setMode("auto")}
              disabled={running}
              title={MODE_HINT.auto}
            >
              ⚡ Agente
            </button>
            <button
              type="button"
              className={`mode-toggle-btn ${mode === "plan" ? "active" : ""}`}
              onClick={() => setMode("plan")}
              disabled={running}
              title={MODE_HINT.plan}
            >
              📋 Plano
            </button>
            <button
              type="button"
              className={`mode-toggle-btn ${mode === "ask" ? "active" : ""}`}
              onClick={() => setMode("ask")}
              disabled={running}
              title={MODE_HINT.ask}
            >
              ❓ Pergunta
            </button>
          </div>
        </div>

        {/* Chips de Foco: Arquivos e Pasta */}
        <div style={{ padding: "4px 8px", display: "flex", flexWrap: "wrap", gap: "6px", alignItems: "center" }}>
          {active && !focusFiles.includes(active) && (
            <button
              type="button"
              onClick={addActiveFile}
              disabled={running}
              style={{
                fontSize: "11px",
                padding: "2px 6px",
                borderRadius: "4px",
                background: "rgba(74, 222, 128, 0.12)",
                color: "#4ade80",
                border: "1px dashed #4ade80",
                cursor: "pointer",
              }}
              title="Anexar arquivo ativo do editor para foco"
            >
              📎 + {active.split("/").pop()}
            </button>
          )}

          {!focusFolder && (
            <button
              type="button"
              onClick={promptAddFolder}
              disabled={running}
              style={{
                fontSize: "11px",
                padding: "2px 6px",
                borderRadius: "4px",
                background: "rgba(59, 130, 246, 0.12)",
                color: "#60a5fa",
                border: "1px dashed #60a5fa",
                cursor: "pointer",
              }}
              title="Indicar pasta específica do projeto para o agente focar"
            >
              📁 + Pasta
            </button>
          )}

          {focusFolder && (
            <span
              style={{
                fontSize: "11px",
                padding: "2px 8px",
                borderRadius: "12px",
                background: "#1e3a8a",
                color: "#93c5fd",
                display: "inline-flex",
                alignItems: "center",
                gap: "4px",
              }}
            >
              📁 {focusFolder}
              <button
                type="button"
                onClick={() => setFocusFolder(null)}
                style={{ background: "none", border: "none", color: "#93c5fd", cursor: "pointer", padding: "0 2px" }}
              >
                ×
              </button>
            </span>
          )}

          {focusFiles.map((file) => (
            <span
              key={file}
              style={{
                fontSize: "11px",
                padding: "2px 8px",
                borderRadius: "12px",
                background: "#065f46",
                color: "#a7f3d0",
                display: "inline-flex",
                alignItems: "center",
                gap: "4px",
              }}
            >
              📄 {file.split("/").pop()}
              <button
                type="button"
                onClick={() => removeFile(file)}
                style={{ background: "none", border: "none", color: "#a7f3d0", cursor: "pointer", padding: "0 2px" }}
              >
                ×
              </button>
            </span>
          ))}
        </div>

        {/* Textarea Principal */}
        <textarea
          ref={textareaRef}
          className="agent-prompt-textarea"
          value={task}
          onChange={(e) => setTask(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="O que o agente deve fazer? (Ctrl+Enter para enviar)"
          rows={2}
          disabled={running}
        />

        {/* Rodapé do prompt card: Seletor de Modelo e Botão Enviar */}
        <div className="agent-prompt-footer">
          <div className="prompt-footer-left">
            <ModelPicker value={profile} onChange={setProfile} disabled={running} />
          </div>

          <button
            type="button"
            className={`agent-send-btn ${canSubmit && !running ? "active" : ""}`}
            onClick={onSubmit}
            disabled={running || !canSubmit}
            title={running ? "Agente em execução" : "Enviar prompt (Ctrl+Enter)"}
          >
            {running ? (
              <span className="spinner-dots">•••</span>
            ) : (
              <>
                <span>Enviar</span>
                <span className="send-arrow">↑</span>
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
