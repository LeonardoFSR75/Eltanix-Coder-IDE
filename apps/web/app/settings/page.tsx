"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useToast } from "@/components/Toast";
import { TraceEntry, listRecentTraces } from "@/lib/api/telemetry";
import {
  clearCache as clearCacheRequest,
  getHealth,
  getProvidersHealth,
  resetCircuit,
  type HealthStatus,
  type ProvidersHealthResponse,
} from "@/lib/api/health";
import { getMetricsSummary, type Summary } from "@/lib/api/metrics";

export default function SettingsPage() {
  const { addToast } = useToast();

  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [metrics, setMetrics] = useState<Summary | null>(null);
  const [providersHealth, setProvidersHealth] = useState<ProvidersHealthResponse | null>(null);
  const [traces, setTraces] = useState<TraceEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [clearingCache, setClearingCache] = useState(false);
  const [resettingModel, setResettingModel] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [h, m, p, t] = await Promise.all([
        getHealth(),
        getMetricsSummary(),
        getProvidersHealth(),
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
      const { removed } = await clearCacheRequest();
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
      await resetCircuit(model);
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
          <span className="page-badge">⚙️ Status do Gateway & Infraestrutura</span>
          <h1>Infraestrutura, Cache & Circuit Breakers</h1>
          <p>
            Estado operacional dos bancos de dados, cache exato e disjuntores por modelo. Credenciais e perfis de
            roteamento ficam em <Link href="/providers">Provedores</Link>.
          </p>
        </div>
      </div>

      <section className="section-block mb-6">
        <div className="panel-box">
          <div className="panel-header">
            <h3>🗄️ Status da Infraestrutura & Bancos de Dados</h3>
            <span className="badge-tag green">Operacional</span>
          </div>
          <p className="text-xs text-muted mb-4">
            Serviços de armazenamento, cache e busca vetorial integrados à plataforma local.
          </p>
          <div className="grid grid-4">
            <div className="stat-card">
              <div className="flex items-center gap-2 mb-1">
                <span className="status-indicator online" />
                <strong className="text-sm">Postgres + pgvector</strong>
              </div>
              <div className="stat-hint text-xs">Banco Principal & Chunks RAG</div>
              <div className="stat-hint font-mono text-xs mt-1">Porta 5403 (pg17)</div>
            </div>

            <div className="stat-card">
              <div className="flex items-center gap-2 mb-1">
                <span className="status-indicator online" />
                <strong className="text-sm">Redis L1 Cache</strong>
              </div>
              <div className="stat-hint text-xs">Cache Exato & Breaker</div>
              <div className="stat-hint font-mono text-xs mt-1">Porta 5404 (v7-alpine)</div>
            </div>

            <div className="stat-card">
              <div className="flex items-center gap-2 mb-1">
                <span className="status-indicator online" />
                <strong className="text-sm">ChromaDB Vector Gateway</strong>
              </div>
              <div className="stat-hint text-xs">Busca Vetorial Complementar</div>
              <div className="stat-hint font-mono text-xs mt-1">Status Ativo</div>
            </div>

            <div className="stat-card">
              <div className="flex items-center gap-2 mb-1">
                <span className="status-indicator online" />
                <strong className="text-sm">MinIO S3 Storage</strong>
              </div>
              <div className="stat-hint text-xs">Armazenamento de PDFs/MDs</div>
              <div className="stat-hint font-mono text-xs mt-1">Portas 5407 / 5408</div>
            </div>
          </div>
        </div>
      </section>

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
