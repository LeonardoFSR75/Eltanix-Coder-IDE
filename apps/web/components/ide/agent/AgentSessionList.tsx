"use client";

/**
 * Histórico de sessões — busca uma lista limitada uma vez por projeto e
 * filtra no cliente com o mesmo `fuzzyScore` que o Quick Open já usa. Volume
 * pequeno (uso local-first), então não vale a pena um endpoint de busca no
 * servidor para isto — ver `apps/api/.../api/routes/agent.py: list_sessions`.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { get } from "@/lib/client";
import { fuzzyScore } from "@/lib/ide-store";

interface SessionRecord {
  session_id: string;
  project: string;
  task: string;
  mode: string;
  profile: string | null;
  branch: string | null;
  status: "open" | "closed";
  created_at: string;
  updated_at: string;
  live: boolean;
}

function tempoRelativo(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const min = Math.round(diffMs / 60000);
  if (min < 1) return "agora";
  if (min < 60) return `${min}min`;
  const h = Math.round(min / 60);
  if (h < 24) return `${h}h`;
  return `${Math.round(h / 24)}d`;
}

export function AgentSessionList({
  project,
  refreshKey,
  onPickTask,
  onClose,
}: {
  project: string | null;
  refreshKey: number;
  onPickTask: (task: string, mode: string, profile: string | null) => void;
  onClose: () => void;
}) {
  const [sessoes, setSessoes] = useState<SessionRecord[]>([]);
  const [query, setQuery] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(false);

  const carregar = useCallback(async () => {
    if (!project) return;
    setCarregando(true);
    try {
      const data = await get<{ sessions: SessionRecord[] }>(
        `/api/agent/sessions?project=${encodeURIComponent(project)}&limit=50`,
      );
      setSessoes(data.sessions);
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

  const filtradas = useMemo(() => {
    if (!query.trim()) return sessoes;
    return sessoes
      .map((s) => ({ s, score: fuzzyScore(s.task, query) }))
      .filter((r): r is { s: SessionRecord; score: number } => r.score !== null)
      .sort((a, b) => b.score - a.score)
      .map(({ s }) => s);
  }, [sessoes, query]);

  if (!project) return null;

  return (
    <div className="agent-session-list">
      <div className="agent-session-list-search">
        <input
          value={query}
          placeholder="Buscar no histórico…"
          onChange={(e) => setQuery(e.target.value)}
          autoFocus
        />
        <button type="button" className="icon-action-btn" onClick={onClose} title="Fechar histórico">
          ×
        </button>
      </div>

      {erro && <div className="panel-error">{erro}</div>}
      {carregando && sessoes.length === 0 && <div className="tree-hint">carregando…</div>}
      {!carregando && filtradas.length === 0 && !erro && (
        <div className="tree-hint">
          {sessoes.length === 0 ? "Nenhuma sessão neste projeto ainda." : `Nenhuma sessão corresponde a "${query}". `}
          {sessoes.length > 0 && (
            <button type="button" className="text-btn-inline" onClick={() => setQuery("")}>
              Redefinir filtro
            </button>
          )}
        </div>
      )}

      <div className="agent-session-items">
        {filtradas.map((s) => (
          <button
            key={s.session_id}
            type="button"
            className="agent-session-item"
            title="Iniciar uma nova sessão com a mesma tarefa"
            onClick={() => onPickTask(s.task, s.mode, s.profile)}
          >
            <div className="agent-session-item-top">
              <span className={`pulse-dot ${s.live ? "ok" : ""}`} style={!s.live ? { background: "var(--text-muted)", boxShadow: "none" } : undefined} />
              <span className="agent-session-item-task">{s.task}</span>
            </div>
            <div className="agent-session-item-meta">
              <span>{s.branch || "sem branch"}</span>
              <span>{s.mode}</span>
              <span>{tempoRelativo(s.updated_at)}</span>
              {!s.live && <span className="pill">encerrada</span>}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
