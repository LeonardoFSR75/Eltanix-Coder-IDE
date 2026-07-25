import { ErrorNotice } from "@/components/ErrorNotice";
import { apiGet, type RecentRequest } from "@/lib/api";
import { formatDateTime, formatMs, formatTokens, formatUsd } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function RequestsPage() {
  const recent = await apiGet<{ requests: RecentRequest[] }>("/api/metrics/recent?limit=100");
  if (!recent.ok) return <ErrorNotice error={recent.error} />;

  return (
    <section>
      <h2>
        Requests recentes<span className="sub">últimos 100</span>
      </h2>
      <div className="table-wrap">
        {recent.data.requests.length > 0 ? (
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
              {recent.data.requests.map((r) => (
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
