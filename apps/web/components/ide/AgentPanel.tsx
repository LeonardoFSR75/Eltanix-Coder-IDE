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
    desc: "Analisa a arquitetura e explica o fluxo",
    prompt: "Explicar a arquitetura e o funcionamento do código deste projeto.",
  },
  {
    icon: "🔧",
    title: "Refatorar",
    desc: "Melhora modularidade e padrões",
    prompt: "Refatorar o código do módulo para melhorar legibilidade e modularidade.",
  },
  {
    icon: "🧪",
    title: "Gerar Testes",
    desc: "Cria suíte de testes unitários",
    prompt: "Escrever suíte de testes unitários cobrindo cenários e limites.",
  },
  {
    icon: "🐛",
    title: "Corrigir Bug",
    desc: "Identifica e resolve exceções",
    prompt: "Analisar e corrigir eventuais falhas, exceções ou gargalos de memória.",
  },
  {
    icon: "📐",
    title: "Gerar Plano",
    desc: "Cria roteiro de implementação",
    prompt: "Criar um plano de execução detalhado para a implementação.",
  },
  {
    icon: "📝",
    title: "Documentar",
    desc: "Gera docstrings e README",
    prompt: "Adicionar documentação completa com docstrings e README para este módulo.",
  },
];

import { logAuditEvent } from "@/lib/api/audit";

/* ── Bloco de Código Renderizado ────────────────────────────────── */

function CodeBlock({ code, language }: { code: string; language: string }) {
  const { toast } = useToast();
  const { insertCode } = useIde();
  const [copied, setCopied] = useState(false);

  const copyToClipboard = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    toast("Copiado!", "success");
    setTimeout(() => setCopied(false), 2000);
  };

  const insertIntoEditor = () => {
    insertCode(code);

    logAuditEvent({
      actor: "Agente IA da IDE",
      module: "IDE",
      action: "Inserção de Código Sugerido",
      details: `Inserido bloco de código (${language || "text"}, ${code.length} caracteres) no editor ativo.`,
      risk_level: "low",
      status: "success",
    }).catch(() => {
      // Auditoria é best-effort do ponto de vista da UI: uma falha aqui não
      // deve impedir o usuário de já ter o código inserido no editor.
    });

    toast("Código inserido no editor!", "success");
  };

  return (
    <div className="agent-code-card">
      <div className="agent-code-header">
        <span className="agent-code-lang">{language || "code"}</span>
        <div className="agent-code-actions">
          <button type="button" className="agent-code-btn" onClick={copyToClipboard} title="Copiar código">
            {copied ? "✓ Copiado" : "📋 Copiar"}
          </button>
          <button type="button" className="agent-code-btn primary" onClick={insertIntoEditor} title="Aplicar no editor">
            ▶ Aplicar
          </button>
        </div>
      </div>
      <pre className="agent-code-body">
        <code>{code}</code>
      </pre>
    </div>
  );
}

/* ── Markdown Simples para Respostas do Assistente ──────────────── */

function RenderedAssistantText({ text }: { text: string }) {
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

        // Sanitizar HTML para prevenir XSS antes de aplicar marcações markdown
        const escapedPart = part
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;")
          .replace(/'/g, "&#039;");

        // Processar formatação inline básica
        const formatted = escapedPart
          .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
          .replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');

        return (
          <div
            key={index}
            className="assistant-paragraph"
            dangerouslySetInnerHTML={{ __html: formatted }}
          />
        );
      })}
    </div>
  );
}

/* ── Indicador de Pensamento (Thinking) ──────────────────────────── */

function ThinkingIndicator() {
  return (
    <div className="agent-thinking">
      <div className="thinking-avatar">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
          <defs>
            <linearGradient id="think-g" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#38bdf8" />
              <stop offset="100%" stopColor="#a78bfa" />
            </linearGradient>
          </defs>
          <circle cx="12" cy="12" r="10" fill="url(#think-g)" opacity="0.15" />
          <circle cx="12" cy="12" r="3" fill="url(#think-g)" />
        </svg>
      </div>
      <span className="thinking-label">Sicoobito Agente está pensando</span>
      <span className="thinking-dots">
        <span />
        <span />
        <span />
      </span>
    </div>
  );
}

/* ── Painel Principal do Agente ─────────────────────────────────── */

export function AgentPanel({ session, log, pending, onDecide, onPresetSelect }: AgentPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [decisions, setDecisions] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [log, pending]);

  useEffect(() => {
    setDecisions({});
  }, [pending]);

  const setDecision = (toolCallId: string, approved: boolean) => {
    setDecisions((prev) => ({ ...prev, [toolCallId]: approved }));
  };

  const allDecided = pending.length > 0 && pending.every((a) => decisions[a.tool_call_id] !== undefined);

  // Verifica se o último item do log indica que o agente está processando
  const isThinking = log.length > 0 && log[log.length - 1]?.kind === "info" &&
    (log[log.length - 1]?.text?.includes("Executando") || log[log.length - 1]?.text?.includes("rodando"));

  return (
    <div className="agent-panel-container">
      {/* Barra de contexto da sessão */}
      {session && (
        <div className="agent-meta-bar">
          <span className="agent-meta-chip">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="6" y1="3" x2="6" y2="15" />
              <circle cx="18" cy="6" r="3" />
              <circle cx="6" cy="18" r="3" />
              <path d="M18 9a9 9 0 0 1-9 9" />
            </svg>
            {session.branch || "main"}
          </span>
          <span className={`agent-meta-chip ${session.sandbox_available ? "ok" : ""}`}>
            {session.sandbox_available ? "◉" : "○"} sandbox
          </span>
        </div>
      )}

      {/* Área de mensagens */}
      <div className="agent-messages-scroll" ref={scrollRef}>
        {log.length === 0 ? (
          /* ── Estado Hero (Welcome) — estilo Copilot ── */
          <div className="agent-hero-state">
            <div className="copilot-hero-icon">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none">
                <defs>
                  <linearGradient id="hero-g" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stopColor="#38bdf8" />
                    <stop offset="50%" stopColor="#818cf8" />
                    <stop offset="100%" stopColor="#a78bfa" />
                  </linearGradient>
                </defs>
                <circle cx="12" cy="12" r="10" fill="url(#hero-g)" opacity="0.15" />
                <circle cx="12" cy="12" r="5" fill="url(#hero-g)" opacity="0.4" />
                <circle cx="12" cy="12" r="2" fill="url(#hero-g)" />
              </svg>
            </div>
            <h2 className="agent-hero-title">Sicoobito Agente</h2>
            <p className="agent-hero-subtitle">
              Seu assistente de IA para código. Pergunte, gere, refatore ou corrija bugs.
            </p>

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
          /* ── Stream de Mensagens — estilo Copilot Chat ── */
          <div className="agent-message-stream">
            {log.map((line, index) => {
              if (line.kind === "info") {
                return (
                  <div key={index} className="stream-badge info">
                    <span className="stream-badge-icon">ℹ</span>
                    <span>{line.text}</span>
                  </div>
                );
              }

              if (line.kind === "cost") {
                return (
                  <div key={index} className="stream-badge cost">
                    <span className="stream-badge-icon">⚡</span>
                    <span>{line.text}</span>
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
                return (
                  <div key={index} className="stream-badge tool">
                    <span className="stream-badge-icon">⚙</span>
                    <span className="tool-text">{line.text}</span>
                  </div>
                );
              }

              if (line.kind === "error") {
                return (
                  <div key={index} className="stream-card error">
                    <span className="stream-badge-icon">✕</span>
                    <span>{line.text}</span>
                  </div>
                );
              }

              /* Mensagem do assistente */
              return (
                <div key={index} className="stream-message assistant">
                  <div className="message-header">
                    <div className="message-avatar">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                        <defs>
                          <linearGradient id={`msg-g-${index}`} x1="0%" y1="0%" x2="100%" y2="100%">
                            <stop offset="0%" stopColor="#38bdf8" />
                            <stop offset="100%" stopColor="#a78bfa" />
                          </linearGradient>
                        </defs>
                        <circle cx="12" cy="12" r="8" fill={`url(#msg-g-${index})`} opacity="0.2" />
                        <circle cx="12" cy="12" r="3" fill={`url(#msg-g-${index})`} />
                      </svg>
                    </div>
                    <span className="message-author">Sicoobito Agente</span>
                  </div>
                  <div className="message-body">
                    <RenderedAssistantText text={line.text} />
                  </div>
                </div>
              );
            })}

            {/* Indicador de pensamento quando processando */}
            {isThinking && <ThinkingIndicator />}

            {/* Card de aprovação */}
            {pending.length > 0 && (
              <div className="stream-approval-card">
                <div className="approval-card-header">
                  <div className="approval-icon-wrap">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" strokeWidth="2">
                      <path d="M12 9v2m0 4h.01M5.07 19h13.86c1.22 0 1.97-1.33 1.36-2.4L13.36 4.58c-.61-1.06-2.12-1.06-2.73 0L3.71 16.6C3.1 17.67 3.85 19 5.07 19z" />
                    </svg>
                  </div>
                  <div>
                    <div className="approval-title">Aprovação Necessária</div>
                    <div className="approval-subtitle">
                      {pending.length} {pending.length === 1 ? "ação requer" : "ações requerem"} sua aprovação
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
                            title="Aprovar"
                          >
                            ✓
                          </button>
                          <button
                            type="button"
                            className={`btn-reject-item${decision === false ? " selected" : ""}`}
                            onClick={() => setDecision(action.tool_call_id, false)}
                            title="Recusar"
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
                    ✓ Aceitar Tudo
                  </button>
                  <button
                    type="button"
                    className="btn-reject"
                    onClick={() => setDecisions(Object.fromEntries(pending.map((a) => [a.tool_call_id, false])))}
                  >
                    ✕ Recusar
                  </button>
                  <button
                    type="button"
                    className="btn-confirm-decisions"
                    disabled={!allDecided}
                    onClick={() => onDecide(decisions)}
                    title={allDecided ? "Confirmar decisões" : "Decida cada ação antes de confirmar"}
                  >
                    Confirmar
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
