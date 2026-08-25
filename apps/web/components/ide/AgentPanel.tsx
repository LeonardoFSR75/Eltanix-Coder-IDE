"use client";

import { useEffect, useRef, useState } from "react";
import { useToast } from "@/components/Toast";
import { useIde } from "@/lib/ide-store";
import { hasDedicatedCard, ToolCallCard } from "./agent/cards";
import type { ActivityEvent, LogLine, PendingAction, Session } from "./agent/sessionTypes";
import { UnifiedDiffPreview } from "./agent/UnifiedDiffPreview";
import { type AgentCheckpoint, listCheckpoints } from "@/lib/api/agent";
import { ConfirmDialog } from "@/components/ide/Overlays";
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
  onRewind?: (iteration: number) => void;
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

export function AgentLiveActivity({
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
      ? "NovaAI Studio Agente está pensando e planejando o próximo passo..."
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

/** Lista de pontos de restauração da sessão (Fase 8 do upgrade do agente) —
 * painel autocontido, à parte do fluxo turno a turno do `MessageStream`: um
 * checkpoint é por chamada ao modelo (`iteration`), granularidade mais fina
 * que "um por turno de conversa", então misturá-lo nas fronteiras de
 * mensagem do log só confundiria. Busca a lista sob demanda (ao expandir),
 * não a cada mudança de `log` — não é algo que muda turno a turno. */
function CheckpointsPanel({
  session,
  running,
  readOnly,
  onRewind,
}: {
  session: Session | null;
  running?: boolean;
  readOnly?: boolean;
  onRewind?: (iteration: number) => void;
}) {
  const [collapsed, setCollapsed] = useState(true);
  const [checkpoints, setCheckpoints] = useState<AgentCheckpoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [confirmIteration, setConfirmIteration] = useState<number | null>(null);

  useEffect(() => {
    setCheckpoints([]);
    setCollapsed(true);
  }, [session?.session_id]);

  const carregar = async () => {
    if (!session) return;
    setLoading(true);
    try {
      const pontos = await listCheckpoints(session.session_id);
      setCheckpoints(pontos);
    } catch {
      setCheckpoints([]);
    } finally {
      setLoading(false);
    }
  };

  const toggle = () => {
    const abrindo = collapsed;
    setCollapsed((prev) => !prev);
    if (abrindo) void carregar();
  };

  if (!session || !onRewind || readOnly) return null;

  return (
    <div className="agent-summary-strip">
      <div className="agent-summary-header">
        <span className="agent-section-label">Checkpoints</span>
        <button
          type="button"
          className="agent-summary-toggle"
          onClick={toggle}
          aria-label={collapsed ? "Expandir checkpoints" : "Minimizar checkpoints"}
          title={collapsed ? "Expandir checkpoints" : "Minimizar checkpoints"}
        >
          {collapsed ? "▸" : "▾"}
        </button>
      </div>

      {!collapsed && (
        <div className="agent-checkpoints-list">
          {loading && <span className="agent-checkpoints-empty">carregando…</span>}
          {!loading && checkpoints.length === 0 && (
            <span className="agent-checkpoints-empty">nenhum checkpoint ainda</span>
          )}
          {!loading &&
            checkpoints.map((cp) => (
              <div key={cp.iteration} className="agent-checkpoint-row">
                <span className="agent-checkpoint-iteration">#{cp.iteration}</span>
                <span className="agent-checkpoint-summary" title={cp.summary}>
                  {cp.summary || (cp.finished ? "(sem resposta de texto)" : "em andamento…")}
                </span>
                <button
                  type="button"
                  className="agent-checkpoint-restore"
                  disabled={running}
                  title="Restaurar a sessão e os arquivos para este ponto"
                  onClick={() => setConfirmIteration(cp.iteration)}
                >
                  restaurar aqui
                </button>
              </div>
            ))}
        </div>
      )}

      {confirmIteration !== null && (
        <ConfirmDialog
          danger
          message={`Restaurar a sessão para o checkpoint #${confirmIteration}? Turnos e escritas de arquivo posteriores serão desfeitos.`}
          onConfirm={() => onRewind(confirmIteration)}
          onClose={() => setConfirmIteration(null)}
        />
      )}
    </div>
  );
}

// Espelha a RiskClass do backend (agent/tools/base.py) — read/write/exec chega em
// `PendingAction.risk` como string crua; mapeamos para as variantes já estilizadas
// de `.tool-card-risk-badge` (ToolCardShell.tsx) em vez de duplicar a paleta aqui.
function riskBadgeLevel(risk: string): "low" | "medium" | "high" {
  if (risk === "exec") return "high";
  if (risk === "write") return "medium";
  return "low";
}

function reviewVerdictLabel(verdict: "approved" | "needs_revision" | "unavailable"): string {
  switch (verdict) {
    case "approved":
      return "segunda opinião: aprovado";
    case "needs_revision":
      return "segunda opinião: revisão sugerida";
    case "unavailable":
      return "segunda opinião: indisponível";
  }
}

interface PlanReviewItem {
  content?: string;
  status?: string;
}

function planItemStatusIcon(status?: string): string {
  switch (status) {
    case "completed":
      return "✓";
    case "in_progress":
      return "◐";
    default:
      return "○";
  }
}

/** Corpo especial de `write_todos` no card de aprovação (Fase 3 — Modo
 * Planejamento estilo Antigravity): em vez do resumo de uma linha genérico,
 * mostra a lista completa de itens do plano com status, para o usuário
 * revisar o plano proposto antes de liberar as ferramentas de escrita. */
function PlanReviewBody({ action }: { action: PendingAction }) {
  const itens = Array.isArray(action.arguments?.items)
    ? (action.arguments.items as PlanReviewItem[])
    : [];

  return (
    <div className="approval-plan-review">
      <p className="approval-plan-review-title">📐 Revisar plano antes de executar</p>
      <p className="approval-plan-review-hint">
        Aprovar libera as ferramentas de criação/edição de arquivos para esta sessão.
      </p>
      {itens.length > 0 ? (
        <ul className="approval-plan-items">
          {itens.map((item, idx) => (
            <li
              key={`${idx}-${item.content ?? ""}`}
              className={`approval-plan-item status-${item.status || "pending"}`}
            >
              <span className="approval-plan-item-status" aria-hidden="true">
                {planItemStatusIcon(item.status)}
              </span>
              <span className="approval-plan-item-content">{item.content}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="action-summary">{action.summary}</p>
      )}
    </div>
  );
}

export function ApprovalCard({
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

  const decidedCount = pending.filter((action) => action.tool_call_id in decisions).length;
  const allDecided = decidedCount === pending.length;

  return (
    <div className="agent-approval-section compact-approval">
      <div className="stream-approval-card">
        <div className="approval-card-header">
          <div className="approval-header-copy">
            <span className="approval-title">
              {pending.length === 1
                ? "1 ação aguardando aprovação de execução"
                : `${pending.length} ações aguardando aprovação de execução`}
            </span>
            <span className="approval-subtitle">Revise cada item — o agente só continua depois da sua decisão</span>
          </div>
        </div>

        <ul className="approval-list">
          {pending.map((action) => {
            const decided = decisions[action.tool_call_id];
            const level = riskBadgeLevel(action.risk);
            return (
              <li key={action.tool_call_id} className="approval-item">
                <div className="approval-item-main">
                  <div className="approval-item-head">
                    <span className="approval-item-tool">{action.tool}</span>
                    <span
                      className={`tool-card-risk-badge ${level}`}
                      title={`Nível de risco: ${action.risk}`}
                    >
                      {action.risk}
                    </span>
                  </div>

                  {action.tool === "write_todos" ? (
                    <PlanReviewBody action={action} />
                  ) : (
                    <p className="action-summary">{action.summary}</p>
                  )}

                  {action.risk === "exec" && (
                    <p className="approval-sandbox-note">
                      Roda em sandbox descartável: usuário não-root, sem privilégios extras, sem acesso à rede.
                    </p>
                  )}

                  {action.diff && <UnifiedDiffPreview diff={action.diff} />}

                  {action.review && (
                    <p className={`approval-review-note ${action.review.verdict}`}>
                      {reviewVerdictLabel(action.review.verdict)}
                      {action.review.summary ? ` — ${action.review.summary}` : ""}
                    </p>
                  )}
                </div>

                <div className="approval-item-actions">
                  <button
                    type="button"
                    className={`btn-approve-item ${decided === true ? "selected" : ""}`}
                    onClick={() => onDecision(action.tool_call_id, true)}
                    title="Aprovar execução deste item"
                  >
                    ✓
                  </button>
                  <button
                    type="button"
                    className={`btn-reject-item ${decided === false ? "selected" : ""}`}
                    onClick={() => onDecision(action.tool_call_id, false)}
                    title="Negar execução deste item"
                  >
                    ✕
                  </button>
                </div>
              </li>
            );
          })}
        </ul>

        <div className="approval-footer-actions">
          <button
            type="button"
            className="btn-approve compact-btn"
            disabled={running}
            onClick={() => onDecide(Object.fromEntries(pending.map((a) => [a.tool_call_id, true])))}
          >
            Aprovar tudo
          </button>
          <button
            type="button"
            className="btn-reject compact-btn"
            disabled={running}
            onClick={() => onDecide(Object.fromEntries(pending.map((a) => [a.tool_call_id, false])))}
          >
            Negar tudo
          </button>
          <button
            type="button"
            className="btn-confirm-decisions"
            disabled={running || !allDecided}
            onClick={() => onDecide(decisions)}
            title={allDecided ? "Confirmar decisões" : "Decida todos os itens antes de confirmar"}
          >
            Confirmar decisões ({decidedCount}/{pending.length})
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
                <span className="message-author">NovaAI Studio Agente</span>
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
  onRewind,
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
  }, [log, pending, activity, recentActivities, running]);

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

          <CheckpointsPanel
            session={session}
            running={running}
            readOnly={readOnly}
            onRewind={onRewind}
          />
        </>
      )}

      {/* Conteúdo principal com scroll */}
      <div ref={scrollRef} className="agent-messages-scroll">
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
