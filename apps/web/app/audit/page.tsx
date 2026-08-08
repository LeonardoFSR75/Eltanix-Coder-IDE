"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AuditEntry, listAudit } from "@/lib/api/audit";
import { useToast } from "@/components/Toast";

export default function AuditPage() {
  const { addToast } = useToast();
  const [logs, setLogs] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedLog, setSelectedLog] = useState<AuditEntry | null>(null);

  const [moduleFilter, setModuleFilter] = useState<string>("ALL");
  const [riskFilter, setRiskFilter] = useState<string>("ALL");
  const [searchQuery, setSearchQuery] = useState("");

  const refresh = useCallback(async () => {
    try {
      setLogs(await listAudit());
    } catch (err) {
      addToast(err instanceof Error ? err.message : "Falha ao carregar auditoria.", "error");
    } finally {
      setLoading(false);
    }
  }, [addToast]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const filteredLogs = logs.filter((log) => {
    const matchesModule = moduleFilter === "ALL" || log.module === moduleFilter;
    const matchesRisk = riskFilter === "ALL" || log.risk_level === riskFilter;
    const matchesSearch =
      log.action.toLowerCase().includes(searchQuery.toLowerCase()) ||
      log.actor.toLowerCase().includes(searchQuery.toLowerCase()) ||
      log.details.toLowerCase().includes(searchQuery.toLowerCase());

    return matchesModule && matchesRisk && matchesSearch;
  });

  const allModules = Array.from(new Set(logs.map((l) => l.module))).sort();

  const handleExportJSON = () => {
    const jsonString = `data:text/json;charset=utf-8,${encodeURIComponent(JSON.stringify(filteredLogs, null, 2))}`;
    const downloadAnchor = document.createElement("a");
    downloadAnchor.setAttribute("href", jsonString);
    downloadAnchor.setAttribute("download", `sicoobito_audit_logs_${Date.now()}.json`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
    addToast("Relatório de Auditoria exportado em formato JSON!", "success");
  };

  const handleExportCSV = () => {
    const headers = "ID,CreatedAt,Actor,Module,Action,RiskLevel,Status,Details\n";
    const rows = filteredLogs
      .map(
        (l) =>
          `"${l.id}","${l.created_at}","${l.actor}","${l.module}","${l.action}","${l.risk_level}","${l.status}","${l.details.replace(/"/g, '""')}"`,
      )
      .join("\n");

    const csvString = `data:text/csv;charset=utf-8,${encodeURIComponent(headers + rows)}`;
    const downloadAnchor = document.createElement("a");
    downloadAnchor.setAttribute("href", csvString);
    downloadAnchor.setAttribute("download", `sicoobito_audit_logs_${Date.now()}.csv`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
    addToast("Relatório de Auditoria exportado em formato CSV!", "success");
  };

  return (
    <div className="shell">
      <div className="page-header">
        <div>
          <span className="page-badge">🛡️ Governança & Segurança</span>
          <h1>Trilha de Auditoria & Logs de Eventos</h1>
          <p>
            Decisões de aprovação do agente (WRITE/EXEC), CRUD de documentos/notas/skills e
            eventos de UI relevantes, persistidos no backend.
          </p>
        </div>
        <div className="header-actions">
          <Link href="/settings" className="btn-secondary-sm">
            ⚙️ Configurações
          </Link>
          <Link href="/projects" className="btn-secondary-sm">
            🚀 Central do Projeto
          </Link>
          <button type="button" className="btn-secondary" onClick={handleExportCSV}>
            📊 Exportar CSV
          </button>
          <button type="button" className="btn-primary glow-button" onClick={handleExportJSON}>
            📥 Exportar JSON
          </button>
        </div>
      </div>

      <div className="panel-box">
        <div className="audit-filters-bar">
          <div className="form-group flex-1">
            <input
              type="text"
              className="input-text"
              placeholder="🔍 Pesquisar ator, ação ou detalhe do log..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>

          <div className="form-group">
            <select
              value={moduleFilter}
              onChange={(e) => setModuleFilter(e.target.value)}
              className="input-select"
            >
              <option value="ALL">Todos os Módulos</option>
              {allModules.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>

          <div className="form-group">
            <select
              value={riskFilter}
              onChange={(e) => setRiskFilter(e.target.value)}
              className="input-select"
            >
              <option value="ALL">Todos os Níveis de Risco</option>
              <option value="low">Risco Baixo (Low)</option>
              <option value="medium">Risco Médio (Medium)</option>
              <option value="critical">Risco Crítico (Critical)</option>
            </select>
          </div>
        </div>
      </div>

      <div className="panel-box">
        <div className="panel-header">
          <h3>Registros de Auditoria ({filteredLogs.length} Encontrados)</h3>
          <span className="badge-tag green">Backend</span>
        </div>

        <div className="table-responsive">
          <table className="audit-table">
            <thead>
              <tr>
                <th>Status</th>
                <th>Horário</th>
                <th>Ator</th>
                <th>Módulo</th>
                <th>Ação Executada</th>
                <th>Risco</th>
                <th>Ações</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td colSpan={7} className="text-xs text-muted">
                    Carregando…
                  </td>
                </tr>
              )}
              {!loading && filteredLogs.length === 0 && (
                <tr>
                  <td colSpan={7} className="text-xs text-muted">
                    Nenhum registro encontrado.
                  </td>
                </tr>
              )}
              {filteredLogs.map((log) => (
                <tr key={log.id} className={`status-row-${log.status}`}>
                  <td>
                    <span className={`status-pill ${log.status}`}>
                      {log.status === "success"
                        ? "✓ Ok"
                        : log.status === "warning"
                          ? "⚠️ Alerta"
                          : "🚫 Bloqueado"}
                    </span>
                  </td>
                  <td className="font-mono text-sm">
                    {new Date(log.created_at).toLocaleString("pt-BR")}
                  </td>
                  <td>
                    <strong>{log.actor}</strong>
                  </td>
                  <td>
                    <span className="module-badge-tag">{log.module}</span>
                  </td>
                  <td>{log.action}</td>
                  <td>
                    <span className={`risk-badge risk-${log.risk_level}`}>
                      {log.risk_level.toUpperCase()}
                    </span>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="btn-secondary-sm"
                      onClick={() => setSelectedLog(log)}
                    >
                      👁️ Detalhes
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {selectedLog && (
        <div className="modal-overlay" onClick={() => setSelectedLog(null)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Detalhes do Evento de Auditoria</h3>
              <button type="button" className="close-btn" onClick={() => setSelectedLog(null)}>
                ✖
              </button>
            </div>
            <div className="modal-body">
              <div className="grid grid-2">
                <div>
                  <strong>Módulo:</strong> {selectedLog.module}
                </div>
                <div>
                  <strong>Status:</strong> {selectedLog.status}
                </div>
                <div>
                  <strong>Nível de Risco:</strong> {selectedLog.risk_level.toUpperCase()}
                </div>
                <div>
                  <strong>Sessão:</strong> {selectedLog.session_id || "—"}
                </div>
              </div>

              <div className="modal-section">
                <strong>Ação:</strong>
                <p>{selectedLog.action}</p>
              </div>

              <div className="modal-section">
                <strong>Detalhes:</strong>
                <pre className="log-payload-box font-mono">{selectedLog.details}</pre>
              </div>

              {Object.keys(selectedLog.metadata).length > 0 && (
                <div className="modal-section">
                  <strong>Metadados:</strong>
                  <pre className="log-payload-box font-mono">
                    {JSON.stringify(selectedLog.metadata, null, 2)}
                  </pre>
                </div>
              )}
            </div>
            <div className="modal-footer">
              <button type="button" className="btn-primary" onClick={() => setSelectedLog(null)}>
                Fechar
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
