"use client";

import { useEffect, useRef, useState } from "react";
import { useToast } from "@/components/Toast";
import { useIde } from "@/lib/ide-store";
import { ToolCallCard } from "./agent/cards";
import type { LogLine, PendingAction, Session } from "./agent/sessionTypes";

interface AgentPanelProps {
  session: Session | null;
  log: LogLine[];
  pending: PendingAction[];
  onDecide: (decisions: Record<string, boolean>) => void;
  onPresetSelect?: (prompt: string) => void;
}

const PRESET_CARDS = [
  {
    icon: "💡",
    title: "Explicar Código",
    desc: "Analisar e explicar a arquitetura e fluxo de módulos",
    prompt: "Explicar a arquitetura e o funcionamento do código deste projeto.",
  },
  {
    icon: "⚡",
    title: "Refatorar",
    desc: "Melhorar modularidade, clareza e padrão do código",
    prompt: "Refatorar o código do módulo para melhorar legibilidade e modularidade.",
  },
  {
    icon: "🧪",
    title: "Criar Testes",
    desc: "Escrever suíte de testes unitários automatizados",
    prompt: "Escrever suíte de testes unitários cobrindo cenários e limites.",
  },
  {
    icon: "🐞",
    title: "Corrigir Bugs",
    desc: "Identificar e resolver exceções ou falhas",
    prompt: "Analisar e corrigir eventuais falhas, exceções ou gargalos de memória.",
  },
  {
    icon: "📋",
    title: "Criar Plano",
    desc: "Gerar plano de implementação passo a passo",
    prompt: "Criar um plano de execução detalhado para a implementação.",
  },
];

function CodeBlock({ code, language }: { code: string; language: string }) {
  const { toast } = useToast();
  const { insertCode } = useIde();

  const copyToClipboard = () => {
    navigator.clipboard.writeText(code);
    toast("Código copiado para a área de transferência!", "success");
  };

  const insertIntoEditor = () => {
    insertCode(code);
    toast("Código inserido no editor ativo!", "success");
  };

  return (
    <div className="agent-code-card">
      <div className="agent-code-header">
        <span className="agent-code-lang">{language || "code"}</span>
        <div className="agent-code-actions">
          <button type="button" className="agent-code-btn" onClick={copyToClipboard} title="Copiar código">
            📋 Copiar
          </button>
          <button type="button" className="agent-code-btn primary" onClick={insertIntoEditor} title="Inserir no editor ativo">
            📥 Inserir no Editor
          </button>
        </div>
      </div>
      <pre className="agent-code-body">
        <code>{code}</code>
      </pre>
    </div>
  );
}

function RenderedAssistantText({ text }: { text: string }) {
  // Separa texto normal de blocos de código ```lang ... ```
  const parts = text.split(/(```[\s\S]*?```)/g);

  return (
    <div className="assistant-text-content">
      {parts.map((part, index) => {
        const match = part.match(/^```(\w*)\n([\s\S]*?)```$/);
        if (match) {
          const [, lang, code] = match;
          return <CodeBlock key={index} language={lang.trim()} code={code.trimEnd()} />;
        }
        if (!part.trim()) return null;
        return (
          <div key={index} className="assistant-paragraph" style={{ whiteSpace: "pre-wrap" }}>
            {part}
          </div>
        );
      })}
    </div>
  );
}

export function AgentPanel({ session, log, pending, onDecide, onPresetSelect }: AgentPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [decisions, setDecisions] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [log, pending]);

  // Cada novo lote de aprovação (novo `interrupt`) começa sem decisões — o
  // usuário escolhe item a item antes de confirmar.
  useEffect(() => {
    setDecisions({});
  }, [pending]);

  const setDecision = (toolCallId: string, approved: boolean) => {
    setDecisions((prev) => ({ ...prev, [toolCallId]: approved }));
  };

  const allDecided = pending.length > 0 && pending.every((a) => decisions[a.tool_call_id] !== undefined);

  return (
    <div className="agent-panel-container">
      {session && (
        <div className="agent-meta-bar">
          <span className="agent-meta-badge branch">🌿 {session.branch || "main"}</span>
          <span className={`agent-meta-badge ${session.sandbox_available ? "active" : "disabled"}`}>
            📦 sandbox {session.sandbox_available ? "ativo" : "off"}
          </span>
          <span className={`agent-meta-badge ${session.github_available ? "active" : ""}`}>
            🐙 github {session.github_available ? "ok" : "off (opcional)"}
          </span>
        </div>
      )}

      <div className="agent-messages-scroll" ref={scrollRef}>
        {log.length === 0 ? (
          <div className="agent-hero-state">
            <div className="agent-hero-icon">⚡</div>
            <h2 className="agent-hero-title">Sicoobito AI Assistant</h2>
            <p className="agent-hero-subtitle">Como posso ajudar no seu projeto hoje?</p>

            <div className="agent-preset-grid">
              {PRESET_CARDS.map((card) => (
                <button
                  key={card.title}
                  type="button"
                  className="agent-preset-card"
                  onClick={() => onPresetSelect?.(card.prompt)}
                >
                  <span className="preset-card-icon">{card.icon}</span>
                  <div className="preset-card-text">
                    <div className="preset-card-title">{card.title}</div>
                    <div className="preset-card-desc">{card.desc}</div>
                  </div>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="agent-message-stream">
            {log.map((line, index) => {
              if (line.kind === "info") {
                return (
                  <div key={index} className="stream-badge info">
                    <span className="badge-icon">ℹ️</span> {line.text}
                  </div>
                );
              }

              if (line.kind === "cost") {
                return (
                  <div key={index} className="stream-badge cost">
                    📊 {line.text}
                  </div>
                );
              }

              if (line.kind === "tool") {
                if (line.tool && line.toolData) {
                  const card = (
                    <ToolCallCard
                      tool={line.tool}
                      content={line.toolContent ?? ""}
                      data={line.toolData}
                      ok={line.toolOk ?? true}
                      sessionId={session?.session_id ?? null}
                    />
                  );
                  if (card) return <div key={index}>{card}</div>;
                }
                // Ferramenta sem card dedicado: badge de texto truncado.
                return (
                  <div key={index} className="stream-badge tool">
                    <span className="badge-icon">🔧</span>
                    <span className="tool-text">{line.text}</span>
                  </div>
                );
              }

              if (line.kind === "error") {
                return (
                  <div key={index} className="stream-card error">
                    <span className="badge-icon">⚠️</span> {line.text}
                  </div>
                );
              }

              return (
                <div key={index} className="stream-message assistant">
                  <div className="message-header">
                    <span className="message-avatar">⚡</span>
                    <span className="message-author">Assistente</span>
                  </div>
                  <div className="message-body">
                    <RenderedAssistantText text={line.text} />
                  </div>
                </div>
              );
            })}

            {pending.length > 0 && (
              <div className="stream-approval-card">
                <div className="approval-card-header">
                  <span className="approval-icon">🛡️</span>
                  <div>
                    <div className="approval-title">Aprovação Solicitada</div>
                    <div className="approval-subtitle">
                      O agente deseja executar {pending.length} ação{pending.length > 1 ? "ões" : ""}:
                    </div>
                  </div>
                </div>

                <ul className="approval-list">
                  {pending.map((action) => {
                    const decision = decisions[action.tool_call_id];
                    return (
                      <li key={action.tool_call_id} className="approval-item">
                        <span className={`risk-pill ${action.risk === "exec" ? "high" : "med"}`}>
                          {action.risk}
                        </span>
                        <span className="action-summary">{action.summary}</span>
                        <div className="approval-item-actions">
                          <button
                            type="button"
                            className={`btn-approve-item${decision === true ? " selected" : ""}`}
                            onClick={() => setDecision(action.tool_call_id, true)}
                            title="Aprovar esta ação"
                          >
                            ✓
                          </button>
                          <button
                            type="button"
                            className={`btn-reject-item${decision === false ? " selected" : ""}`}
                            onClick={() => setDecision(action.tool_call_id, false)}
                            title="Recusar esta ação"
                          >
                            ✕
                          </button>
                        </div>
                      </li>
                    );
                  })}
                </ul>

                <div className="approval-actions-row">
                  <button
                    type="button"
                    className="btn-approve"
                    onClick={() => setDecisions(Object.fromEntries(pending.map((a) => [a.tool_call_id, true])))}
                  >
                    ✓ Aprovar Todas
                  </button>
                  <button
                    type="button"
                    className="btn-reject"
                    onClick={() => setDecisions(Object.fromEntries(pending.map((a) => [a.tool_call_id, false])))}
                  >
                    ✕ Recusar Todas
                  </button>
                  <button
                    type="button"
                    className="btn-confirm-decisions"
                    disabled={!allDecided}
                    onClick={() => onDecide(decisions)}
                    title={allDecided ? "Enviar decisões" : "Decida cada ação antes de confirmar"}
                  >
                    Confirmar Decisões
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
