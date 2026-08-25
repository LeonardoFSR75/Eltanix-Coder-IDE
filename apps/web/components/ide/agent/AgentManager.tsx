"use client";

/**
 * Agent Manager: substitui o antigo histórico "escolher tarefa passada para
 * repreencher o prompt" por uma grade de cards com status, cobrindo tanto as
 * sessões vivas nesta aba (via `useAgentSessions`) quanto o histórico
 * persistido no backend — clicar numa sessão encerrada carrega o transcript
 * real (`/messages`), não só o texto da tarefa.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { PanelState } from "@/components/ide/PanelState";
import {
  getAgentGraph,
  listAgentSessions,
  rootsWithChildren,
  type AgentLiveStatus,
  type AgentSessionRecord as SessionRecord,
} from "@/lib/api/agent";
import { fuzzyScore } from "@/lib/ide-store";
import type { SessionStatus, SessionSummary } from "./sessionTypes";

interface Row {
  id: string;
  task: string;
  mode: string;
  branch: string;
  status: SessionStatus;
  updatedAt: string | null;
  parentId: string | null;
}

// Status ao vivo do AgentCoordinator (ADR 0004) só existe para sessões que
// passaram por spawn_agent — mapeado pro mesmo enum de sempre pra não
// precisar de pill/CSS novo. `waiting_for_message` cai em "running": pro
// usuário, um filho esperando resposta ainda está ativo, a distinção que
// importa de verdade é "esperando aprovação humana".
const LIVE_STATUS_MAP: Record<AgentLiveStatus, SessionStatus> = {
  running: "running",
  waiting_for_message: "running",
  waiting_approval: "awaiting-approval",
  completed: "done",
  failed: "error",
  stopped: "closed",
};

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
  const [liveStatusById, setLiveStatusById] = useState<Map<string, SessionStatus>>(new Map());

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

  // Raízes com pelo menos um filho no histórico (orquestração multiagente,
  // ADR 0004) ganham uma consulta ao AgentCoordinator pra saber se algum
  // descendente está `waiting_approval` — a lista de sessões sozinha não
  // revela isso pra um filho headless que nunca abriu SSE nesta aba.
  useEffect(() => {
    const raizesComFilhos = rootsWithChildren(historico);
    if (raizesComFilhos.length === 0) {
      setLiveStatusById(new Map());
      return;
    }
    let cancelado = false;
    Promise.all(
      raizesComFilhos.map((raiz) => getAgentGraph(raiz.session_id).catch(() => [])),
    ).then((arvores) => {
      if (cancelado) return;
      const mapa = new Map<string, SessionStatus>();
      for (const no of arvores.flat()) {
        mapa.set(no.session_id, LIVE_STATUS_MAP[no.status]);
      }
      setLiveStatusById(mapa);
    });
    return () => {
      cancelado = true;
    };
  }, [historico]);

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
        status: liveStatusById.get(s.id) ?? s.status,
        updatedAt: registro?.updated_at ?? null,
        parentId: registro?.parent_session_id ?? null,
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
        status: liveStatusById.get(r.session_id) ?? (r.status === "closed" ? "closed" : r.live ? "running" : "closed"),
        updatedAt: r.updated_at,
        parentId: r.parent_session_id,
      });
    }

    return linhas;
  }, [liveSessions, historico, liveStatusById]);

  // Sem busca: ordem de árvore (pai, depois seus filhos recursivamente,
  // depois a próxima raiz) — é assim que orquestração multiagente (ADR
  // 0004) fica visível sem precisar abrir GET /api/agent/sessions na mão.
  const arvore = useMemo<(Row & { depth: number })[]>(() => {
    const idsPresentes = new Set(rows.map((r) => r.id));
    const filhosDe = new Map<string | null, Row[]>();
    for (const r of rows) {
      // Pai fora da janela dos últimos 50 registros (ou de outro projeto):
      // trata como raiz em vez de esconder a linha.
      const pai = r.parentId && idsPresentes.has(r.parentId) ? r.parentId : null;
      if (!filhosDe.has(pai)) filhosDe.set(pai, []);
      filhosDe.get(pai)!.push(r);
    }
    const resultado: (Row & { depth: number })[] = [];
    const visitar = (pai: string | null, depth: number) => {
      for (const r of filhosDe.get(pai) ?? []) {
        resultado.push({ ...r, depth });
        visitar(r.id, depth + 1);
      }
    };
    visitar(null, 0);
    return resultado;
  }, [rows]);

  // Com busca: lista plana ordenada por score — indentação só faz sentido
  // navegando a árvore inteira, não um recorte filtrado dela.
  const filtradas = useMemo<(Row & { depth: number })[]>(() => {
    if (!query.trim()) return arvore;
    return rows
      .map((r) => ({ r, score: fuzzyScore(r.task, query) }))
      .filter((x): x is { r: Row; score: number } => x.score !== null)
      .sort((a, b) => b.score - a.score)
      .map(({ r }) => ({ ...r, depth: 0 }));
  }, [arvore, rows, query]);

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

      {erro && <PanelState kind="error" message={erro} onRetry={carregar} />}
      {carregando && rows.length === 0 && <PanelState kind="loading" message="Carregando sessões…" />}
      {!carregando && filtradas.length === 0 && !erro && rows.length === 0 && (
        <PanelState kind="empty" message="Nenhuma sessão neste projeto ainda." />
      )}
      {!carregando && filtradas.length === 0 && !erro && rows.length > 0 && (
        <div className="tree-hint">
          {`Nenhuma sessão corresponde a "${query}". `}
          <button type="button" className="text-btn-inline" onClick={() => setQuery("")}>
            Redefinir filtro
          </button>
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
              style={r.depth > 0 ? { marginLeft: Math.min(r.depth, 3) * 16 } : undefined}
              title={isLive ? "Trocar para esta sessão" : "Abrir o transcript desta sessão"}
              onClick={() => (isLive ? onOpenLive(r.id) : onOpenClosed(r.id, r.task))}
            >
              <div className="agent-session-item-top">
                {r.depth > 0 && (
                  <span className="agent-session-item-child-marker" title="Agente filho (spawn_agent)">
                    ↳
                  </span>
                )}
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
