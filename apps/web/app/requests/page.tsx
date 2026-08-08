"use client";

import { useEffect, useState } from "react";
import { ErrorNotice } from "@/components/ErrorNotice";
import { getRecentRequests, type RecentRequest } from "@/lib/api/metrics";
import { formatDateTime, formatMs, formatTokens, formatUsd } from "@/lib/format";
import { useProject } from "@/components/providers/ProjectContext";

export default function RequestsPage() {
  const { currentProject } = useProject();
  const [requests, setRequests] = useState<RecentRequest[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getRecentRequests(100, currentProject)
      .then((data) => {
        if (!cancelled) setRequests(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [currentProject]);

  if (error) return <ErrorNotice error={error} />;
  if (requests === null) return null;

  return (
    <div className="shell">
      <section>
        <h2>
          Requests recentes
          <span className="sub">
            últimos 100{currentProject ? ` · projeto ${currentProject}` : ""}
          </span>
        </h2>
        <div className="table-wrap">
          {requests.length > 0 ? (
            <table>
              <thead>
                <tr>
                  <th>Quando</th>
                  <th>Origem</th>
                  <th>Pedido</th>
                  <th>Resolvido</th>
                  <th className="num">Latência</th>
                  <th className="num">Tokens</th>
                  <th className="num">Custo</th>
                  <th>Notas</th>
                </tr>
              </thead>
              <tbody>
                {requests.map((r) => (
                  <tr key={r.id}>
                    <td>{formatDateTime(r.created_at)}</td>
                    <td>{r.source}</td>
                    <td>
                      <code>{r.requested_model}</code>
                    </td>
                    <td>{r.resolved_model ? <code>{r.resolved_model}</code> : "—"}</td>
                    <td className="num">{formatMs(r.latency_ms)}</td>
                    <td className="num">{formatTokens(r.total_tokens)}</td>
                    <td className="num">{r.cost_known ? formatUsd(r.cost_usd) : "?"}</td>
                    <td style={{ whiteSpace: "normal" }}>
                      <Notes request={r} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="empty">Nenhum request registrado ainda.</div>
          )}
        </div>
      </section>
    </div>
  );
}

function Notes({ request }: { request: RecentRequest }) {
  const notes: React.ReactNode[] = [];

  if (request.status === "error") {
    notes.push(
      <span key="err" className="pill bad">
        {request.error_type ?? "erro"}
      </span>,
    );
  }
  if (request.cache_hit) {
    notes.push(
      <span key="cache" className="pill ok">
        cache
      </span>,
    );
  }
  if (request.fallback_from.length > 0) {
    notes.push(
      <span key="fb" className="pill warn" title={request.fallback_from.join(", ")}>
        fallback ×{request.fallback_from.length}
      </span>,
    );
  }
  // Tokens estimados localmente não são medição; marcar evita ler chute como fato.
  if (request.usage_estimated) {
    notes.push(
      <span key="est" className="pill">
        tokens estimados
      </span>,
    );
  }
  if (!request.cost_known) {
    notes.push(
      <span key="np" className="pill warn">
        sem preço
      </span>,
    );
  }

  if (notes.length === 0) return <>—</>;
  return <span style={{ display: "inline-flex", gap: 6, flexWrap: "wrap" }}>{notes}</span>;
}
