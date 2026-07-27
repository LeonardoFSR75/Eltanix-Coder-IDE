"use client";

import { useState } from "react";
import { MODE_HINT, MODES, type Mode } from "./modes";
import { ModelPicker } from "./ModelPicker";

const PRESET_PROMPTS = [
  { label: "💡 Explicar", prompt: "Explicar a arquitetura e o funcionamento do código deste projeto." },
  { label: "⚡ Refatorar", prompt: "Refatorar o código do módulo para melhorar legibilidade e modularidade." },
  { label: "🧪 Testes", prompt: "Escrever suíte de testes unitários cobrindo cenários e limites." },
  { label: "🐞 Bugs", prompt: "Analisar e corrigir eventuais falhas, exceções ou gargalos de memória." },
  { label: "📋 Plano", prompt: "Criar um plano de execução detalhado para a implementação." },
];

export function AgentChatInput({
  task,
  setTask,
  mode,
  setMode,
  profile,
  setProfile,
  running,
  canSubmit,
  onSubmit,
}: {
  task: string;
  setTask: (task: string) => void;
  mode: Mode;
  setMode: (mode: Mode) => void;
  profile: string | null;
  setProfile: (profile: string | null) => void;
  running: boolean;
  canSubmit: boolean;
  onSubmit: () => void;
}) {
  const [showAdvanced, setShowAdvanced] = useState(false);

  return (
    <div className="agent-controls">
      <div className="dual-mode-wrap" style={{ display: "flex", gap: 8, marginBottom: 8 }}>
        <button
          type="button"
          className={`mode-btn-large ${mode === "auto" || mode === "agent" || mode === "plan" || mode === "edit" ? "active" : ""}`}
          onClick={() => setMode("auto")}
          disabled={running}
          style={{ flex: 1, padding: "8px 12px", fontSize: 13, borderRadius: 8, cursor: "pointer" }}
        >
          ⚡ Agente Autônomo
        </button>
        <button
          type="button"
          className={`mode-btn-large ${mode === "ask" ? "active" : ""}`}
          onClick={() => setMode("ask")}
          disabled={running}
          style={{ flex: 1, padding: "8px 12px", fontSize: 13, borderRadius: 8, cursor: "pointer" }}
        >
          ❓ Pergunta & Leitura
        </button>
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <span className="mode-hint" style={{ fontSize: 12, color: "var(--text-dim)", marginBottom: 0 }}>
          {MODE_HINT[mode]}
        </span>
        <button
          type="button"
          className="text-btn"
          style={{ fontSize: 11, background: "none", border: "none", color: "var(--accent)", cursor: "pointer" }}
          onClick={() => setShowAdvanced(!showAdvanced)}
        >
          {showAdvanced ? "Esconder avançados ▲" : "Modos avançados ▼"}
        </button>
      </div>

      {showAdvanced && (
        <div className="mode-row" style={{ marginBottom: 10 }}>
          {MODES.map((option) => (
            <button
              key={option}
              type="button"
              className={`mode${mode === option ? " active" : ""}`}
              onClick={() => setMode(option)}
              disabled={running}
            >
              {option === "plan" ? "📋 planejar" : option === "auto" ? "⚡ auto" : option}
            </button>
          ))}
        </div>
      )}

      <div className="agent-presets">
        {PRESET_PROMPTS.map((p) => (
          <button
            key={p.label}
            type="button"
            className="preset-chip"
            disabled={running}
            onClick={() => setTask(p.prompt)}
          >
            {p.label}
          </button>
        ))}
      </div>

      <textarea
        value={task}
        onChange={(event) => setTask(event.target.value)}
        placeholder="O que o agente deve fazer? Ex.: refatorar função e criar testes."
        rows={4}
        disabled={running}
      />

      <div className="agent-input-bar">
        <ModelPicker value={profile} onChange={setProfile} disabled={running} />
        <button type="button" className="primary" onClick={onSubmit} disabled={running || !canSubmit}>
          {running ? "trabalhando…" : "iniciar"}
        </button>
      </div>
    </div>
  );
}
