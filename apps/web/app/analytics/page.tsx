"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  AnalyticsDashboardSummary,
  AutoCorrectionProposal,
  applyProposal,
  getAnalyticsDashboard,
  listPendingProposals,
} from "@/lib/api/analytics";
import { useToast } from "@/components/Toast";

export default function AnalyticsPage() {
  const { addToast } = useToast();
  const [dashboard, setDashboard] = useState<AnalyticsDashboardSummary | null>(null);
  const [proposals, setProposals] = useState<AutoCorrectionProposal[]>([]);
  const [loading, setLoading] = useState(true);
  const [applyingId, setApplyingId] = useState<string | null>(null);
  const [selectedProposal, setSelectedProposal] = useState<AutoCorrectionProposal | null>(null);

  const refreshData = useCallback(async () => {
    try {
      setLoading(true);
      const [dashData, propData] = await Promise.all([
        getAnalyticsDashboard(),
        listPendingProposals(),
      ]);
      setDashboard(dashData);
      setProposals(propData.proposals || []);
    } catch (err) {
      addToast(
        err instanceof Error ? err.message : "Falha ao carregar métricas de Analytics ML.",
        "error"
      );
    } finally {
      setLoading(false);
    }
  }, [addToast]);

  useEffect(() => {
    refreshData();
  }, [refreshData]);

  const handleApply = async (id: string) => {
    try {
      setApplyingId(id);
      await applyProposal(id);
      addToast("Proposta de auto-correção aplicada com sucesso!", "success");
      setSelectedProposal(null);
      await refreshData();
    } catch (err) {
      addToast(
        err instanceof Error ? err.message : "Erro ao aplicar proposta de correção.",
        "error"
      );
    } finally {
      setApplyingId(null);
    }
  };

  const getCategoryBadgeClass = (category: string) => {
    switch (category) {
      case "TOOL_EXECUTION_FAILURE":
        return "badge-danger";
      case "SYNTAX_OR_LINT_ERROR":
        return "badge-warning";
      case "AGENT_HALLUCINATION_OR_LOOP":
        return "badge-purple";
      case "TEST_ASSERTION_FAILURE":
        return "badge-info";
      default:
        return "badge-neutral";
    }
  };

  return (
    <div className="shell">
      <div className="page-header">
        <div>
          <div className="breadcrumb">
            <Link href="/projects">Projetos</Link> &gt; <span>Analytics ML</span>
          </div>
          <h1 className="page-title">
            <span className="icon">🧠</span> Dashboard de Analytics ML & Auto-Diagnósticos
          </h1>
          <p className="page-subtitle">
            Telemetria preditiva, classificação não supervisionada de trajetórias, Root Cause Analysis (RCA) e geração autônoma de correções.
          </p>
        </div>
        <button onClick={refreshData} className="btn-secondary-sm" disabled={loading}>
          {loading ? "Atualizando..." : "🔄 Atualizar Métricas"}
        </button>
      </div>

      {loading && !dashboard ? (
        <div className="card text-center p-8">
          <p className="text-secondary">Carregando modelos e telemetria ML...</p>
        </div>
      ) : (
        <>
          {/* Métricas Principais */}
          <div className="metrics-grid mb-6">
            <div className="metric-card">
              <div className="metric-icon bg-primary-soft">📊</div>
              <div>
                <div className="metric-label">Trajetórias Analisadas</div>
                <div className="metric-value">{dashboard?.total_trajectories || 0}</div>
              </div>
            </div>

            <div className="metric-card">
              <div className="metric-icon bg-danger-soft">⚠️</div>
              <div>
                <div className="metric-label">Falhas Classificadas</div>
                <div className="metric-value">{dashboard?.total_failures || 0}</div>
              </div>
            </div>

            <div className="metric-card">
              <div className="metric-icon bg-info-soft">🧬</div>
              <div>
                <div className="metric-label">Clusters Cosine (DBSCAN)</div>
                <div className="metric-value">{dashboard?.total_clusters || 0}</div>
              </div>
            </div>

            <div className="metric-card">
              <div className="metric-icon bg-warning-soft">✨</div>
              <div>
                <div className="metric-label">Propostas Pendentes</div>
                <div className="metric-value">{proposals.length}</div>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
            {/* Categorias de Falhas Detectadas por ML */}
            <div className="card p-6">
              <h2 className="text-lg font-bold mb-4 flex items-center gap-2">
                <span>🏷️</span> Categorias de Falha (Classificação ML)
              </h2>
              {dashboard?.failure_categories &&
              Object.keys(dashboard.failure_categories).length > 0 ? (
                <div className="flex flex-col gap-3">
                  {Object.entries(dashboard.failure_categories).map(([cat, count]) => (
                    <div key={cat} className="flex justify-between items-center p-3 bg-surface rounded-lg border border-border">
                      <span className={`badge ${getCategoryBadgeClass(cat)}`}>{cat}</span>
                      <span className="font-mono font-bold text-sm">{count} ocorrência(s)</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-secondary">Nenhuma falha registrada no histórico recente de trajetórias.</p>
              )}
            </div>

            {/* Arquivos Mais Afetados */}
            <div className="card p-6">
              <h2 className="text-lg font-bold mb-4 flex items-center gap-2">
                <span>📂</span> Arquivos com Maior Incidência de Falhas
              </h2>
              {dashboard?.top_failing_files && dashboard.top_failing_files.length > 0 ? (
                <div className="flex flex-col gap-3">
                  {dashboard.top_failing_files.map((item, idx) => (
                    <div key={idx} className="flex justify-between items-center p-3 bg-surface rounded-lg border border-border">
                      <code className="text-xs text-primary font-mono">{item.file}</code>
                      <span className="badge badge-warning">{item.failures} falhas</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-secondary">Nenhum arquivo crítico com falhas recorrentes.</p>
              )}
            </div>
          </div>

          {/* Propostas de Auto-Correção Geradas por ML */}
          <div className="card p-6 mb-8">
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-lg font-bold flex items-center gap-2">
                <span>🔧</span> Propostas Autônomas de Auto-Correção ({proposals.length})
              </h2>
            </div>

            {proposals.length === 0 ? (
              <p className="text-sm text-secondary">Nenhuma proposta de correção pendente no momento.</p>
            ) : (
              <div className="flex flex-col gap-4">
                {proposals.map((proposal) => (
                  <div key={proposal.id} className="p-4 bg-surface rounded-xl border border-border flex flex-col gap-3">
                    <div className="flex justify-between items-start">
                      <div>
                        <h3 className="font-semibold text-base">{proposal.title}</h3>
                        <p className="text-xs text-secondary mt-1">{proposal.explanation}</p>
                      </div>
                      <span className="badge badge-purple font-mono">
                        Confiança ML: {(proposal.confidence_score * 100).toFixed(0)}%
                      </span>
                    </div>

                    <div className="flex justify-between items-center text-xs text-secondary pt-2 border-t border-border">
                      <span>Alvo: <code className="font-mono text-primary">{proposal.target_file}</code></span>
                      <div className="flex gap-2">
                        <button
                          onClick={() => setSelectedProposal(proposal)}
                          className="btn-secondary-sm"
                        >
                          👁️ Ver Diff
                        </button>
                        <button
                          onClick={() => handleApply(proposal.id)}
                          className="btn-primary-sm"
                          disabled={applyingId === proposal.id}
                        >
                          {applyingId === proposal.id ? "Aplicando..." : "✅ Aplicar Correção"}
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Recentes Trajetórias & RCA Feed */}
          <div className="card p-6">
            <h2 className="text-lg font-bold mb-4 flex items-center gap-2">
              <span>🚀</span> Histórico de Trajetórias & Diagnósticos RCA
            </h2>
            {dashboard?.recent_trajectories && dashboard.recent_trajectories.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-border text-secondary">
                      <th className="p-3">ID Sessão</th>
                      <th className="p-3">Categoria de Falha</th>
                      <th className="p-3">Hipótese RCA (Causa Raiz)</th>
                      <th className="p-3">Status</th>
                      <th className="p-3">Data</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dashboard.recent_trajectories.map((traj) => (
                      <tr key={traj.id} className="border-b border-border hover:bg-surface-hover">
                        <td className="p-3 font-mono text-primary">{traj.session_id.slice(0, 8)}...</td>
                        <td className="p-3">
                          <span className={`badge ${getCategoryBadgeClass(traj.failure_category)}`}>
                            {traj.failure_category}
                          </span>
                        </td>
                        <td className="p-3 font-mono max-w-xs truncate">{traj.root_cause_hypothesis || "—"}</td>
                        <td className="p-3">
                          <span className={traj.status === "success" ? "text-success" : "text-danger"}>
                            {traj.status}
                          </span>
                        </td>
                        <td className="p-3 text-secondary">{new Date(traj.created_at).toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-sm text-secondary">Nenhuma trajetória ingerida recentemente.</p>
            )}
          </div>

          {/* Modal de Diff */}
          {selectedProposal && (
            <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
              <div className="card max-w-3xl w-full p-6 max-h-[80vh] flex flex-col">
                <div className="flex justify-between items-center mb-4">
                  <h3 className="text-lg font-bold">Diff da Proposta: {selectedProposal.title}</h3>
                  <button onClick={() => setSelectedProposal(null)} className="btn-secondary-sm">✕ Fechar</button>
                </div>
                <div className="bg-background p-4 rounded-lg font-mono text-xs overflow-y-auto mb-4 border border-border whitespace-pre">
                  {selectedProposal.diff_content}
                </div>
                <div className="flex justify-end gap-2">
                  <button onClick={() => setSelectedProposal(null)} className="btn-secondary-sm">Cancelar</button>
                  <button
                    onClick={() => handleApply(selectedProposal.id)}
                    className="btn-primary-sm"
                    disabled={applyingId === selectedProposal.id}
                  >
                    {applyingId === selectedProposal.id ? "Aplicando..." : "✅ Aplicar Alteração"}
                  </button>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
