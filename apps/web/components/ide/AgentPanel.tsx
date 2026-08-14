"use client";

import { useEffect, useRef, useState } from "react";
import { useToast } from "@/components/Toast";
import { useIde } from "@/lib/ide-store";
import { hasDedicatedCard, ToolCallCard } from "./agent/cards";
import type { ActivityEvent, LogLine, PendingAction, Session } from "./agent/sessionTypes";
import DOMPurify from "dompurify";

interface AgentPanelProps {
  session: Session | null;
  log: LogLine[];
  pending: PendingAction[];
  running?: boolean;
  activity?: ActivityEvent | null;
  recentActivities?: ActivityEvent[];
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

/* ── Indicador de Atividade ao Vivo com Cronômetro e Etapas ──────── */

function getToolMeta(tool?: string, stage?: string) {
  if (stage === "thinking" || !tool) {
    return {
      icon: "🧠",
      badge: "Pensando",
      className: "activity-thinking",
    };
  }
  switch (tool) {
    case "read_file":
    case "list_files":
      return { icon: "📄", badge: "Leitura de Arquivo", className: "activity-read" };
    case "edit_file":
    case "write_file":
      return { icon: "✍️", badge: "Edição de Código", className: "activity-write" };
    case "run_command":
      return { icon: "⚙️", badge: "Terminal / Sandbox", className: "activity-exec" };
    case "browser_action":
      return { icon: "🌐", badge: "Navegador Headless", className: "activity-browser" };
    case "search_code":
      return { icon: "🔍", badge: "Busca no Código", className: "activity-search" };
    case "git_status":
    case "git_diff":
    case "git_commit":
      return { icon: "🌿", badge: "Git", className: "activity-git" };
    case "write_todos":
      return { icon: "📋", badge: "Plano / Tarefas", className: "activity-todo" };
    default:
      return { icon: "⚡", badge: tool, className: "activity-default" };
  }
}

function AgentLiveActivity({
  activity,
  recentActivities,
}: {
  activity: ActivityEvent | null;
  recentActivities: ActivityEvent[];
}) {
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [showHistory, setShowHistory] = useState(false);

  useEffect(() => {
    setElapsedSeconds(0);
    const start = Date.now();
    const interval = setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - start) / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, [activity?.tool, activity?.stage]);

  const meta = getToolMeta(activity?.tool, activity?.stage);
  const title =
    activity?.summary ||
    activity?.detail ||
    (activity?.stage === "thinking"
      ? "Sicoobito Agente está pensando e planejando o próximo passo..."
      : `Executando ${activity?.tool}...`);

  const formatTimer = (s: number) => {
    const mins = Math.floor(s / 60);
    const secs = s % 60;
    return `${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}s`;
  };

  return (
    <div className={`agent-live-activity ${meta.className}`}>
      <div className="live-activity-header">
        <div className="live-activity-badge-group">
          <span className="live-activity-pulse-dot" />
          <span className="live-activity-icon">{meta.icon}</span>
          <span className="live-activity-badge">{meta.badge}</span>
        </div>

        <span className="live-activity-timer">{formatTimer(elapsedSeconds)}</span>
      </div>

      <div className="live-activity-content">
        <div className="live-activity-title">{title}</div>
      </div>

      {recentActivities.length > 1 && (
        <div className="live-activity-history-toggle">
          <button
            type="button"
            className="live-activity-btn-toggle"
            onClick={() => setShowHistory((prev) => !prev)}
          >
            <span>{showHistory ? "▾ Ocultar etapas deste turno" : `▸ Ver ${recentActivities.length} etapas deste turno`}</span>
          </button>
        </div>
      )}

      {showHistory && recentActivities.length > 0 && (
        <div className="live-activity-timeline">
          {recentActivities.map((item, idx) => {
            const itemMeta = getToolMeta(item.tool, item.stage);
            const isLatest = idx === recentActivities.length - 1;
            return (
              <div key={idx} className={`timeline-item ${isLatest ? "active" : "completed"}`}>
                <span className="timeline-icon">{itemMeta.icon}</span>
                <span className="timeline-text">{item.summary || item.detail || item.tool}</span>
                {typeof item.duration_ms === "number" && (
                  <span className="timeline-duration">{(item.duration_ms / 1000).toFixed(1)}s</span>
                )}
                {item.ok === false && <span className="timeline-fail">falha</span>}
              </div>
            );
          })}
        </div>
      )}
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
  activity,
  recentActivities,
  decisions,
  running,
  onDecision,
  onDecide,
}: {
  log: LogLine[];
  session: Session | null;
  pending: PendingAction[];
  isThinking: boolean;
  activity?: ActivityEvent | null;
  recentActivities?: ActivityEvent[];
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
              <div key={index} className={`stream-tool-call ${line.toolOk === false ? "failed" : "ok"}`}>
                <div className="tool-call-header">
                  <span className="tool-call-icon">{line.toolOk === false ? "✗" : "⚙"}</span>
                  <span className="tool-call-name">{line.tool || "ferramenta"}</span>
                  <span className="tool-call-status">
                    {line.toolOk === false ? "falha" : "concluído"}
                  </span>
                </div>
                <p className="tool-call-summary">{line.text}</p>
              </div>
            );
          }

          if (line.kind === "error") {
            return (
              <div key={index} className="stream-error-banner">
                <span className="stream-error-icon">⚠</span>
                <span>{line.text}</span>
              </div>
            );
          }

          // Resposta do assistente
          return (
            <div key={index} className="stream-message assistant">
              <div className="message-header">
                <div className="message-avatar">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
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

        {isThinking && (
          <AgentLiveActivity
            activity={activity ?? null}
            recentActivities={recentActivities ?? []}
          />
        )}
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

export function AgentPanel({
  session,
  log,
  pending,
  running,
  activity,
  recentActivities,
  readOnly,
  onDecide,
  onPresetSelect,
}: AgentPanelProps) {
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
                {session.profile && (
                  <span className="agent-summary-pill">Perfil: {session.profile}</span>
                )}
                {session.model && (
                  <span className="agent-summary-pill">Modelo: {session.model}</span>
                )}
                <span
                  className={`agent-summary-pill ${session.sandbox_available ? "ok" : "warn"}`}
                >
                  Sandbox: {session.sandbox_available ? "conectado" : "indisponível"}
                </span>
                <span
                  className={`agent-summary-pill ${session.github_available ? "ok" : "dim"}`}
                >
                  GitHub: {session.github_available ? "conectado" : "sem token"}
                </span>
              </div>
            )}
          </div>

          <StartupGuardSummary
            session={session}
            collapsed={guardCollapsed}
            onToggle={() => setGuardCollapsed((prev) => !prev)}
          />
        </>
      )}

      {/* Conteúdo principal com scroll */}
      <div ref={scrollRef} className="agent-panel-scroll">
        {log.length === 0 && !isThinking ? (
          <div className="agent-empty-hero">
            <div className="agent-hero-avatar">
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none">
                <defs>
                  <linearGradient id="hero-g" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stopColor="#38bdf8" />
                    <stop offset="100%" stopColor="#a78bfa" />
                  </linearGradient>
                </defs>
                <circle cx="12" cy="12" r="10" fill="url(#hero-g)" opacity="0.15" />
                <path
                  d="M12 6v6l4 2"
                  stroke="url(#hero-g)"
                  strokeWidth="2"
                  strokeLinecap="round"
                />
              </svg>
            </div>
            <h3 className="agent-hero-title">Como posso ajudar?</h3>
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
            activity={activity}
            recentActivities={recentActivities}
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
