"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { get, post } from "@/lib/client";
import { useToast } from "@/components/Toast";
import { TraceEntry, listRecentTraces } from "@/lib/api/telemetry";

interface HealthView {
  status: string;
  cache_enabled: boolean;
}

interface MetricsSummary {
  cache_hits: number;
  cache_hit_rate: number;
  savings: {
    tokens_saved: number;
    cost_saved_usd: number;
  };
}

interface ProviderHealth {
  model: string;
  provider?: string;
  ok: boolean;
  detail?: string;
  circuit_open?: boolean;
  cooldown_remaining_s?: number;
  consecutive_fails?: number;
  success_rate?: number;
}

interface ProvidersHealthResponse {
  healthy: number;
  total: number;
  providers: ProviderHealth[];
}

export default function SettingsPage() {
  const { addToast } = useToast();

  const [health, setHealth] = useState<HealthView | null>(null);
  const [metrics, setMetrics] = useState<MetricsSummary | null>(null);
  const [providersHealth, setProvidersHealth] = useState<ProvidersHealthResponse | null>(null);
  const [traces, setTraces] = useState<TraceEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [clearingCache, setClearingCache] = useState(false);
  const [resettingModel, setResettingModel] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [h, m, p, t] = await Promise.all([
        get<HealthView>("/api/health"),
        get<MetricsSummary>("/api/metrics/summary"),
        get<ProvidersHealthResponse>("/api/health/providers"),
        listRecentTraces(30),
      ]);
      setHealth(h);
      setMetrics(m);
      setProvidersHealth(p);
      setTraces(t);
    } catch (err) {
      addToast(
        err instanceof Error ? err.message : "Falha ao carregar status do backend.",
        "error",
      );
    } finally {
      setLoading(false);
    }
  }, [addToast]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleClearCache = async () => {
    setClearingCache(true);
    try {
      const { removed } = await post<{ removed: number }>("/api/cache/clear");
      addToast(`Cache exato limpo (${removed} entrada(s) removida(s)).`, "success");
      await refresh();
    } catch (err) {
      addToast(err instanceof Error ? err.message : "Falha ao limpar cache.", "error");
    } finally {
      setClearingCache(false);
    }
  };

  const handleResetCircuit = async (model: string) => {
    setResettingModel(model);
    try {
      // A rota usa `{model_id:path}` — o id do modelo (que pode ter "/", ex.
      // "ollama/qwen2.5-coder:7b") entra cru, sem encodeURIComponent.
      await post(`/api/providers/${model}/reset`);
      addToast(`Circuito de "${model}" resetado.`, "success");
      await refresh();
    } catch (err) {
      addToast(err instanceof Error ? err.message : "Falha ao resetar circuito.", "error");
    } finally {
      setResettingModel(null);
    }
  };

  return (
    <div className="shell">
      <div className="page-header">
        <div>
          <span className="page-badge">⚙️ Status do Gateway</span>
          <h1>Cache & Circuit Breakers</h1>
          <p>
            Estado real do cache exato e dos disjuntores por modelo. Credenciais e perfis de
            roteamento ficam em <Link href="/providers">Provedores</Link>.
          </p>
        </div>
      </div>

      <section className="section-block mb-6">
        <div className="panel-box">
          <div className="panel-header">
            <h3>⚡ Cache Exato</h3>
            <span className={`badge-tag ${health?.cache_enabled ? "green" : "red"}`}>
              {health?.cache_enabled ? "Ativo" : "Desativado"}
            </span>
          </div>

          {loading && <p className="text-xs text-muted">Carregando…</p>}

          {metrics && (
            <div className="grid grid-4 mb-4">
              <div className="stat-card">
                <span className="stat-icon">⚡</span>
                <div className="stat-value">{metrics.cache_hits}</div>
                <div className="stat-label">Cache Hits (30d)</div>
              </div>
              <div className="stat-card">
                <span className="stat-icon">📊</span>
                <div className="stat-value">{(metrics.cache_hit_rate * 100).toFixed(1)}%</div>
                <div className="stat-label">Hit rate</div>
              </div>
              <div className="stat-card">
                <span className="stat-icon">🔢</span>
                <div className="stat-value">
                  {(metrics.savings.tokens_saved / 1000).toFixed(1)}k
                </div>
                <div className="stat-label">Tokens economizados</div>
              </div>
              <div className="stat-card">
                <span className="stat-icon">💰</span>
                <div className="stat-value">${metrics.savings.cost_saved_usd.toFixed(4)}</div>
                <div className="stat-label">Economia (USD)</div>
              </div>
            </div>
          )}

          <button
            type="button"
            className="btn-secondary"
            onClick={handleClearCache}
            disabled={clearingCache}
          >
            {clearingCache ? "Limpando…" : "🧹 Limpar cache exato"}
          </button>
        </div>
      </section>

      <section className="section-block mb-6">
        <div className="panel-box">
          <div className="panel-header">
            <h3>🔌 Circuit Breakers por Modelo</h3>
            {providersHealth && (
              <span className="badge-tag blue">
                {providersHealth.healthy} / {providersHealth.total} saudáveis
              </span>
            )}
          </div>

          {loading && <p className="text-xs text-muted">Carregando…</p>}
          {!loading && providersHealth?.providers.length === 0 && (
            <p className="text-xs text-muted">Nenhum modelo no catálogo.</p>
          )}

          <div className="grid grid-3">
            {providersHealth?.providers.map((p) => (
              <div key={p.model} className={`mcp-server-card ${p.circuit_open ? "border-red" : ""}`}>
                <div className="mcp-card-header">
                  <span className={`status-indicator ${p.ok && !p.circuit_open ? "online" : "offline"}`} />
                  <h3>{p.model}</h3>
                </div>
                <div className="mcp-endpoint font-mono">
                  Status:{" "}
                  <strong>
                    {p.circuit_open
                      ? `ABERTO (${p.cooldown_remaining_s ?? 0}s cooldown)`
                      : p.ok
                        ? "FECHADO (normal)"
                        : "Indisponível"}
                  </strong>
                </div>
                <div className="mcp-card-footer mt-2">
                  <span className="text-xs text-muted">
                    Falhas seguidas: {p.consecutive_fails ?? 0} · Sucesso:{" "}
                    {((p.success_rate ?? 0) * 100).toFixed(0)}%
                  </span>
                  {p.circuit_open && (
                    <button
                      type="button"
                      className="btn-secondary-sm"
                      onClick={() => handleResetCircuit(p.model)}
                      disabled={resettingModel === p.model}
                    >
                      {resettingModel === p.model ? "Resetando…" : "🔁 Resetar"}
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="section-block mb-6">
        <div className="panel-box">
          <div className="panel-header">
            <h3>📈 Spans Recentes (Ferramentas & RAG)</h3>
            <span className="badge-tag blue">{traces.length} recentes</span>
          </div>

          {loading && <p className="text-xs text-muted">Carregando…</p>}
          {!loading && traces.length === 0 && (
            <p className="text-xs text-muted">
              Nenhum span registrado ainda — rode uma sessão do agente ou uma busca em RAG/Segundo
              Cérebro.
            </p>
          )}

          {traces.length > 0 && (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Tipo</th>
                    <th>Nome</th>
                    <th className="num">Latência</th>
                    <th>Status</th>
                    <th>Quando</th>
                  </tr>
                </thead>
                <tbody>
                  {traces.map((t, i) => (
                    <tr key={`${t.ts}-${i}`}>
                      <td>{t.kind === "tool" ? "🛠️ Tool" : "📚 RAG"}</td>
                      <td>
                        <code>{t.name}</code>
                      </td>
                      <td className="num">{t.latency_ms.toFixed(0)} ms</td>
                      <td>
                        <span className={`badge-tag ${t.status === "ok" ? "green" : "red"}`}>
                          {t.status === "ok" ? "OK" : "Erro"}
                        </span>
                      </td>
                      <td className="text-xs text-muted">
                        {new Date(t.ts * 1000).toLocaleTimeString("pt-BR")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
