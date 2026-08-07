"use client";

/**
 * Agent Manager: substitui o antigo histórico "escolher tarefa passada para
 * repreencher o prompt" por uma grade de cards com status, cobrindo tanto as
 * sessões vivas nesta aba (via `useAgentSessions`) quanto o histórico
 * persistido no backend — clicar numa sessão encerrada carrega o transcript
 * real (`/messages`), não só o texto da tarefa.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { listAgentSessions, type AgentSessionRecord as SessionRecord } from "@/lib/api/agent";
import { fuzzyScore } from "@/lib/ide-store";
import type { SessionStatus, SessionSummary } from "./sessionTypes";

interface Row {
  id: string;
  task: string;
  mode: string;
  branch: string;
  status: SessionStatus;
  updatedAt: string | null;
}

const STATUS_LABEL: Record<SessionStatus, string> = {
  running: "rodando",
  "awaiting-approval": "aguardando aprovação",
  done: "concluída",
  error: "erro",
  closed: "encerrada",
};

function tempoRelativo(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const min = Math.round(diffMs / 60000);
  if (min < 1) return "agora";
  if (min < 60) return `${min}min`;
  const h = Math.round(min / 60);
  if (h < 24) return `${h}h`;
  return `${Math.round(h / 24)}d`;
}

export function AgentManager({
  project,
  refreshKey,
  liveSessions,
  activeId,
  onOpenLive,
  onOpenClosed,
  onClose,
}: {
  project: string | null;
  refreshKey: number;
  liveSessions: SessionSummary[];
  activeId: string | null;
  onOpenLive: (sessionId: string) => void;
  onOpenClosed: (sessionId: string, task: string) => void;
  onClose: () => void;
}) {
  const [historico, setHistorico] = useState<SessionRecord[]>([]);
  const [query, setQuery] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(false);

  const carregar = useCallback(async () => {
    if (!project) return;
    setCarregando(true);
    try {
      const sessions = await listAgentSessions(project, 50);
      setHistorico(sessions);
      setErro(null);
    } catch (err) {
      setErro(err instanceof Error ? err.message : String(err));
    } finally {
      setCarregando(false);
    }
  }, [project]);

  useEffect(() => {
    void carregar();
  }, [carregar, refreshKey]);

  const liveById = useMemo(() => new Map(liveSessions.map((s) => [s.id, s])), [liveSessions]);

  const rows = useMemo<Row[]>(() => {
    const vistos = new Set<string>();
    const linhas: Row[] = [];

    // Sessões vivas nesta aba primeiro — são as mais relevantes agora.
    for (const s of liveSessions) {
      vistos.add(s.id);
      const registro = historico.find((r) => r.session_id === s.id);
      linhas.push({
        id: s.id,
        task: s.task,
        mode: registro?.mode ?? "",
        branch: s.branch || registro?.branch || "",
        status: s.status,
        updatedAt: registro?.updated_at ?? null,
      });
    }

    for (const r of historico) {
      if (vistos.has(r.session_id)) continue;
      linhas.push({
        id: r.session_id,
        task: r.task,
        mode: r.mode,
        branch: r.branch ?? "",
        // `live` aqui é "rodando em algum processo do backend", não
        // necessariamente nesta aba — tratamos como encerrada para o clique
        // recair em "carregar transcript", que funciona nos dois casos.
        status: r.status === "closed" ? "closed" : r.live ? "running" : "closed",
        updatedAt: r.updated_at,
      });
    }

    return linhas;
  }, [liveSessions, historico]);

  const filtradas = useMemo(() => {
    if (!query.trim()) return rows;
    return rows
      .map((r) => ({ r, score: fuzzyScore(r.task, query) }))
      .filter((x): x is { r: Row; score: number } => x.score !== null)
      .sort((a, b) => b.score - a.score)
      .map(({ r }) => r);
  }, [rows, query]);

  if (!project) return null;

  return (
    <div className="agent-session-list">
      <div className="agent-session-list-search">
        <input
          value={query}
          placeholder="Buscar sessões…"
          onChange={(e) => setQuery(e.target.value)}
          autoFocus
        />
        <button type="button" className="icon-action-btn" onClick={onClose} title="Fechar Agent Manager">
          ×
        </button>
      </div>

      {erro && <div className="panel-error">{erro}</div>}
      {carregando && rows.length === 0 && <div className="tree-hint">carregando…</div>}
      {!carregando && filtradas.length === 0 && !erro && (
        <div className="tree-hint">
          {rows.length === 0 ? "Nenhuma sessão neste projeto ainda." : `Nenhuma sessão corresponde a "${query}". `}
          {rows.length > 0 && (
            <button type="button" className="text-btn-inline" onClick={() => setQuery("")}>
              Redefinir filtro
            </button>
          )}
        </div>
      )}

      <div className="agent-session-items">
        {filtradas.map((r) => {
          const isLive = liveById.has(r.id);
          return (
            <button
              key={r.id}
              type="button"
              className={`agent-session-item${r.id === activeId ? " active" : ""}`}
              title={isLive ? "Trocar para esta sessão" : "Abrir o transcript desta sessão"}
              onClick={() => (isLive ? onOpenLive(r.id) : onOpenClosed(r.id, r.task))}
            >
              <div className="agent-session-item-top">
                <span className={`session-status-pill ${r.status}`}>{STATUS_LABEL[r.status]}</span>
                <span className="agent-session-item-task">{r.task}</span>
              </div>
              <div className="agent-session-item-meta">
                <span>{r.branch || "sem branch"}</span>
                {r.mode && <span>{r.mode}</span>}
                {r.updatedAt && <span>{tempoRelativo(r.updatedAt)}</span>}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
