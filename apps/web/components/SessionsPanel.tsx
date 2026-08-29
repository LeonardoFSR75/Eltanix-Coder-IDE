"use client";

import React, { useCallback, useEffect, useState } from "react";
import { useToast } from "@/components/Toast";
import {
  listAuthSessions,
  revokeAuthSession,
  type AuthSessionInfo,
} from "@/lib/api/authSessions";

function fmt(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("pt-BR");
  } catch {
    return iso;
  }
}

export default function SessionsPanel() {
  const { addToast } = useToast();
  const [sessions, setSessions] = useState<AuthSessionInfo[] | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const { sessions } = await listAuthSessions();
      setSessions(sessions);
    } catch (err) {
      addToast(err instanceof Error ? err.message : "Falha ao listar sessões.", "error");
    }
  }, [addToast]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleRevoke = async (id: string) => {
    setBusyId(id);
    try {
      await revokeAuthSession(id);
      addToast("Sessão revogada.", "success");
      await refresh();
    } catch (err) {
      addToast(err instanceof Error ? err.message : "Falha ao revogar.", "error");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="panel-box">
      <div className="panel-header">
        <h3>🖥️ Sessões ativas</h3>
        <button type="button" className="btn-secondary-sm" onClick={() => void refresh()}>
          Atualizar
        </button>
      </div>

      {!sessions && <p className="text-xs text-muted">Carregando…</p>}
      {sessions && sessions.length === 0 && (
        <p className="text-xs text-muted">Nenhuma outra sessão ativa.</p>
      )}

      {sessions && sessions.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Dispositivo / navegador</th>
                <th>Última atividade</th>
                <th>Expira</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {sessions.map((s) => (
                <tr key={s.id}>
                  <td className="font-mono text-xs">
                    {s.user_agent ?? "desconhecido"}
                    {s.current && <span className="badge-tag green" style={{ marginLeft: 8 }}>esta</span>}
                  </td>
                  <td className="text-xs">{fmt(s.last_seen_at ?? s.created_at)}</td>
                  <td className="text-xs">{fmt(s.expires_at)}</td>
                  <td>
                    {!s.current && (
                      <button
                        type="button"
                        className="btn-danger-sm"
                        disabled={busyId === s.id}
                        onClick={() => handleRevoke(s.id)}
                      >
                        {busyId === s.id ? "…" : "Revogar"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
