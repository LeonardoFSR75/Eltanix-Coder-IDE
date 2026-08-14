"use client";

import { useEffect, useRef, useState } from "react";
import { useToast } from "@/components/Toast";
import { useIde } from "@/lib/ide-store";
import { hasDedicatedCard, ToolCallCard } from "./agent/cards";
import type { LogLine, PendingAction, Session } from "./agent/sessionTypes";
import DOMPurify from "dompurify";

interface AgentPanelProps {
  session: Session | null;
  log: LogLine[];
  pending: PendingAction[];
  running?: boolean;
  readOnly?: boolean;
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

        // Processar formatação inline básica e sanitizar com DOMPurify
        const formatted = part
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;")
          .replace(/'/g, "&#039;")
          .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
          .replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');

        const sanitized = DOMPurify.sanitize(formatted, {
          ALLOWED_TAGS: ["strong", "code", "em", "br"],
          ALLOWED_ATTR: ["class"],
        });

        return (
          <div
            key={index}
            className="assistant-paragraph"
            dangerouslySetInnerHTML={{ __html: sanitized }}
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

function StartupGuardSummary({
  session,
  collapsed,
  onToggle,
}: {
  session: Session | null;
  collapsed: boolean;
  onToggle: () => void;
}) {
  const guard = session?.startup_guard;
  if (!session || !guard) return null;

  const items = [
    { label: "Projeto validado", ok: guard.project_verified },
    { label: "Arquivos listados", ok: guard.workspace_listed },
    { label: "Pacotes verificados", ok: guard.packages_checked },
    {
      label: "Git inicializado",
      ok: guard.git_ready ?? true,
      title: guard.git_ready ?? true
        ? "Git inicializado automaticamente antes da sessão"
        : "Git ainda não foi inicializado para esta sessão",
    },
  ];

  return (
    <div className="agent-summary-strip startup-guard-strip">
      <div className="agent-summary-header">
        <span className="agent-section-label">Inicialização</span>
        <button
          type="button"
          className="agent-summary-toggle"
          onClick={onToggle}
          aria-label={collapsed ? "Expandir inicialização" : "Minimizar inicialização"}
          title={collapsed ? "Expandir inicialização" : "Minimizar inicialização"}
        >
          {collapsed ? "▸" : "▾"}
        </button>
      </div>

      {!collapsed && (
        <div className="agent-summary-items">
          {items.map((item) => (
            <span
              key={item.label}
              className={`agent-summary-pill ${item.ok ? "ok" : "pending"}`}
              title={item.title ?? (item.ok ? `${item.label}: confirmado` : `${item.label}: pendente`)}
            >
              <span className="guard-dot" />
              {item.label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function ApprovalCard({
  pending,
  decisions,
  running,
  onDecide,
  onDecision,
}: {
  pending: PendingAction[];
  decisions: Record<string, boolean>;
  running?: boolean;
  onDecide: (decisions: Record<string, boolean>) => void;
  onDecision: (toolCallId: string, approved: boolean) => void;
}) {
  if (pending.length === 0) return null;

  return (
    <div className="agent-approval-section compact-approval">
      <div className="agent-approval-bar">
        <span className="agent-approval-meta">
          {pending.length === 1 ? pending[0].summary : `${pending.length} pendente${pending.length === 1 ? "" : "s"}`}
        </span>

        <div className="approval-quick-actions">
          <button
            type="button"
            className="btn-approve compact-btn"
            disabled={running}
            onClick={() => onDecide(Object.fromEntries(pending.map((a) => [a.tool_call_id, true])))}
          >
            Aceitar tudo
          </button>
          <button
            type="button"
            className="btn-reject compact-btn"
            disabled={running}
            onClick={() => onDecide(Object.fromEntries(pending.map((a) => [a.tool_call_id, false])))}
          >
            Recusar tudo
          </button>
        </div>
      </div>
    </div>
  );
}

function MessageStream({
  log,
  session,
  pending,
  isThinking,
  decisions,
  running,
  onDecision,
  onDecide,
}: {
  log: LogLine[];
  session: Session | null;
  pending: PendingAction[];
  isThinking: boolean;
  decisions: Record<string, boolean>;
  running?: boolean;
  onDecision: (toolCallId: string, approved: boolean) => void;
  onDecide: (decisions: Record<string, boolean>) => void;
}) {
  return (
    <div className="agent-message-stream">
      <div className="agent-stream-section">
        {log.map((line, index) => {
          if (line.kind === "user") {
            return (
              <div key={index} className="stream-message user">
                <div className="message-body user-body">
                  <p className="user-text">{line.text}</p>
                </div>
              </div>
            );
          }

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
            if (line.tool && line.toolData && hasDedicatedCard(line.tool)) {
              return (
                <div key={index}>
                  <ToolCallCard
                    tool={line.tool}
                    content={line.toolContent ?? ""}
                    data={line.toolData}
                    ok={line.toolOk ?? true}
                    sessionId={session?.session_id ?? null}
                  />
                </div>
              );
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

        {isThinking && <ThinkingIndicator />}
      </div>

      {pending.length > 0 && (
        <div className="agent-chat-footer-approval">
          <ApprovalCard
            pending={pending}
            decisions={decisions}
            running={running}
            onDecide={onDecide}
            onDecision={onDecision}
          />
        </div>
      )}
    </div>
  );
}

/* ── Painel Principal do Agente ─────────────────────────────────── */

export function AgentPanel({ session, log, pending, running, readOnly, onDecide, onPresetSelect }: AgentPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [decisions, setDecisions] = useState<Record<string, boolean>>({});
  const [summaryCollapsed, setSummaryCollapsed] = useState(false);
  const [guardCollapsed, setGuardCollapsed] = useState(false);

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

  // `running` vem do sessionRuntime (via AgentDock) — reflete se há um turno
  // em voo de verdade, ao contrário de inspecionar texto de log (nenhum
  // evento real emite "Executando"/"rodando", então isso nunca disparava).
  // Some quando já existe aprovação pendente para não duplicar indicador.
  const isThinking = Boolean(running) && pending.length === 0;

  return (
    <div className="agent-panel-container">
      {/* Barra de contexto da sessão */}
      {session && (
        <>
          <div className="agent-summary-strip">
            <div className="agent-summary-header">
              <span className="agent-section-label">Resumo</span>
              <button
                type="button"
                className="agent-summary-toggle"
                onClick={() => setSummaryCollapsed((prev) => !prev)}
                aria-label={summaryCollapsed ? "Expandir resumo" : "Minimizar resumo"}
                title={summaryCollapsed ? "Expandir resumo" : "Minimizar resumo"}
              >
                {summaryCollapsed ? "▸" : "▾"}
              </button>
            </div>

            {!summaryCollapsed && (
              <div className="agent-summary-items">
                <span className="agent-summary-pill">Ramo: {session.branch || "main"}</span>
                <span className="agent-summary-pill">Sandbox: {session.sandbox_available ? "ativo" : "inativo"}</span>
                <span className="agent-summary-pill">Modelo: {session.profile || session.model || "padrão"}</span>
              </div>
            )}
          </div>
          <StartupGuardSummary session={session} collapsed={guardCollapsed} onToggle={() => setGuardCollapsed((prev) => !prev)} />
        </>
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
              Pergunte, gere, refatore ou corrija bugs.
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
          <MessageStream
            log={log}
            session={session}
            pending={pending}
            isThinking={isThinking}
            decisions={decisions}
            running={running}
            onDecision={setDecision}
            onDecide={onDecide}
          />
        )}
      </div>
    </div>
  );
}
