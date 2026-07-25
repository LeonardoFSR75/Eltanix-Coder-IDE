import { ErrorNotice } from "@/components/ErrorNotice";
import {
  apiGet,
  type ModelUsage,
  type SourceUsage,
  type Summary,
  type TimeseriesPoint,
} from "@/lib/api";
import { formatMs, formatPercent, formatTokens, formatUsd } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  const [summary, byModel, bySource, series] = await Promise.all([
    apiGet<Summary>("/api/metrics/summary?days=30"),
    apiGet<{ models: ModelUsage[] }>("/api/metrics/by-model?days=30"),
    apiGet<{ sources: SourceUsage[] }>("/api/metrics/by-source?days=30"),
    apiGet<{ points: TimeseriesPoint[] }>("/api/metrics/timeseries?days=30"),
  ]);

  if (!summary.ok) return <ErrorNotice error={summary.error} />;

  const s = summary.data;
  const points = series.ok ? series.data.points : [];
  const maxCost = Math.max(...points.map((p) => p.cost_usd), 0.0001);

  return (
    <>
      <div className="grid">
        <Stat label="Custo (30d)" value={formatUsd(s.cost_usd)} hint={`${s.requests} requests`} />
        <Stat
          label="Tokens"
          value={formatTokens(s.total_tokens)}
          hint={`${formatTokens(s.prompt_tokens)} in · ${formatTokens(s.completion_tokens)} out`}
        />
        <Stat
          label="Economia por cache"
          value={formatUsd(s.savings.cost_saved_usd)}
          hint={`${formatTokens(s.savings.tokens_saved)} tokens evitados`}
        />
        <Stat
          label="Taxa de cache"
          value={formatPercent(s.cache_hit_rate)}
          hint={`${s.cache_hits} acertos`}
        />
        <Stat
          label="Latência média"
          value={formatMs(s.avg_latency_ms)}
          hint={s.errors > 0 ? `${s.errors} erros` : "sem erros"}
        />
      </div>

      {s.unpriced_requests > 0 && (
        <section>
          <div className="notice">
            <strong>{s.unpriced_requests} requests sem preço em <code>pricing.yaml</code>.</strong>{" "}
            O custo acima é um piso, não o total. Adicione o modelo à tabela para fechar a conta.
          </div>
        </section>
      )}

      {(s.budget.daily_limit_usd > 0 || s.budget.monthly_limit_usd > 0) && (
        <section>
          <h2>
            Orçamento
            {s.budget.hard_stop && <span className="sub">bloqueio ativo ao estourar</span>}
          </h2>
          <div className="grid">
            {s.budget.daily_limit_usd > 0 && (
              <BudgetCard
                label="Hoje"
                spent={s.budget.daily_spent_usd}
                limit={s.budget.daily_limit_usd}
              />
            )}
            {s.budget.monthly_limit_usd > 0 && (
              <BudgetCard
                label="Mês"
                spent={s.budget.monthly_spent_usd}
                limit={s.budget.monthly_limit_usd}
              />
            )}
          </div>
        </section>
      )}

      {points.length > 0 && (
        <section>
          <h2>
            Custo por dia<span className="sub">últimos 30 dias</span>
          </h2>
          <div className="card">
            <div className="sparkline">
              {points.map((p) => (
                <div
                  key={p.day}
                  style={{ height: `${Math.max(4, (p.cost_usd / maxCost) * 100)}%` }}
                  title={`${p.day}: ${formatUsd(p.cost_usd)} · ${p.requests} requests`}
                />
              ))}
            </div>
          </div>
        </section>
      )}

      <section>
        <h2>
          Por modelo<span className="sub">ordenado por custo</span>
        </h2>
        <div className="table-wrap">
          {byModel.ok && byModel.data.models.length > 0 ? (
            <table>
              <thead>
                <tr>
                  <th>Modelo</th>
                  <th>Provedor</th>
                  <th className="num">Requests</th>
                  <th className="num">Tokens</th>
                  <th className="num">Latência méd.</th>
                  <th className="num">Erros</th>
                  <th className="num">Custo</th>
                </tr>
              </thead>
              <tbody>
                {byModel.data.models.map((m) => (
                  <tr key={m.model}>
                    <td>
                      <code>{m.model}</code>
                    </td>
                    <td>{m.provider ?? "—"}</td>
                    <td className="num">{m.requests}</td>
                    <td className="num">{formatTokens(m.total_tokens)}</td>
                    <td className="num">{formatMs(m.avg_latency_ms)}</td>
                    <td className="num">
                      {m.errors > 0 ? <span className="pill bad">{m.errors}</span> : "—"}
                    </td>
                    <td className="num">{formatUsd(m.cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="empty">
              Nenhum request registrado ainda. Aponte uma ferramenta para{" "}
              <code>http://localhost:8000/v1</code> e recarregue.
            </div>
          )}
        </div>
      </section>

      <section>
        <h2>
          Por ferramenta<span className="sub">quem está consumindo o orçamento</span>
        </h2>
        <div className="table-wrap">
          {bySource.ok && bySource.data.sources.length > 0 ? (
            <table>
              <thead>
                <tr>
                  <th>Origem</th>
                  <th className="num">Requests</th>
                  <th className="num">Tokens</th>
                  <th className="num">Custo</th>
                </tr>
              </thead>
              <tbody>
                {bySource.data.sources.map((src) => (
                  <tr key={src.source}>
                    <td>{src.source}</td>
                    <td className="num">{src.requests}</td>
                    <td className="num">{formatTokens(src.total_tokens)}</td>
                    <td className="num">{formatUsd(src.cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="empty">Sem dados de origem ainda.</div>
          )}
        </div>
      </section>
    </>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="card">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {hint && <div className="hint">{hint}</div>}
    </div>
  );
}

function BudgetCard({ label, spent, limit }: { label: string; spent: number; limit: number }) {
  const pct = Math.min(100, (spent / limit) * 100);
  return (
    <div className="card">
      <div className="label">{label}</div>
      <div className="value">{formatUsd(spent)}</div>
      <div className="hint">
        de {formatUsd(limit)} · {pct.toFixed(0)}%
      </div>
      <div className="bar">
        <span
          style={{
            width: `${pct}%`,
            background: pct >= 100 ? "var(--danger)" : pct >= 80 ? "var(--warn)" : "var(--accent)",
          }}
        />
      </div>
    </div>
  );
}
