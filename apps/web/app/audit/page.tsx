"use client";

import React, { useEffect, useState } from "react";
import { LocalDB, AuditLog } from "@/lib/db";
import { useToast } from "@/components/Toast";

export default function AuditPage() {
  const { addToast } = useToast();
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [selectedLog, setSelectedLog] = useState<AuditLog | null>(null);

  // Filters
  const [moduleFilter, setModuleFilter] = useState<string>("ALL");
  const [riskFilter, setRiskFilter] = useState<string>("ALL");
  const [searchQuery, setSearchQuery] = useState("");

  useEffect(() => {
    setLogs(LocalDB.getAudit());
  }, []);

  const filteredLogs = logs.filter((log) => {
    const matchesModule = moduleFilter === "ALL" || log.module === moduleFilter;
    const matchesRisk = riskFilter === "ALL" || log.riskLevel === riskFilter;
    const matchesSearch =
      log.action.toLowerCase().includes(searchQuery.toLowerCase()) ||
      log.actor.toLowerCase().includes(searchQuery.toLowerCase()) ||
      log.details.toLowerCase().includes(searchQuery.toLowerCase());

    return matchesModule && matchesRisk && matchesSearch;
  });

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
    const headers = "ID,Timestamp,Actor,Module,Action,RiskLevel,Status,IP,Details\n";
    const rows = filteredLogs
      .map(
        (l) =>
          `"${l.id}","${l.timestamp}","${l.actor}","${l.module}","${l.action}","${l.riskLevel}","${l.status}","${l.ipAddress}","${l.details.replace(/"/g, '""')}"`
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
          <p>Monitoramento de acessos, guardrails de prompt, execuções MCP e alterações persistidas no banco.</p>
        </div>
        <div className="header-actions">
          <button type="button" className="btn-secondary" onClick={handleExportCSV}>
            📊 Exportar CSV
          </button>
          <button type="button" className="btn-primary glow-button" onClick={handleExportJSON}>
            📥 Exportar JSON
          </button>
        </div>
      </div>

      {/* Bar de Filtros */}
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
              <option value="IDE">IDE Agêntica</option>
              <option value="RAG">RAG</option>
              <option value="MCP">MCP</option>
              <option value="Skills">Skills</option>
              <option value="SecondBrain">Segundo Cérebro</option>
              <option value="Neural">Rede Neural</option>
              <option value="Auth">Autenticação</option>
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

      {/* Tabela de Logs de Auditoria */}
      <div className="panel-box">
        <div className="panel-header">
          <h3>Registros de Auditoria ({filteredLogs.length} Encontrados)</h3>
          <span className="badge-tag green">Guardrails Ativos</span>
        </div>

        <div className="table-responsive">
          <table className="audit-table">
            <thead>
              <tr>
                <th>Status</th>
                <th>Horário</th>
                <th>Ator / Usuário</th>
                <th>Módulo</th>
                <th>Ação Executada</th>
                <th>Risco</th>
                <th>IP</th>
                <th>Ações</th>
              </tr>
            </thead>
            <tbody>
              {filteredLogs.map((log) => (
                <tr key={log.id} className={`status-row-${log.status}`}>
                  <td>
                    <span className={`status-pill ${log.status}`}>
                      {log.status === "success" ? "✓ Ok" : log.status === "warning" ? "⚠️ Alerta" : "🚫 Bloqueado"}
                    </span>
                  </td>
                  <td className="font-mono text-sm">
                    {new Date(log.timestamp).toLocaleString("pt-BR")}
                  </td>
                  <td>
                    <strong>{log.actor}</strong>
                  </td>
                  <td>
                    <span className="module-badge-tag">{log.module}</span>
                  </td>
                  <td>{log.action}</td>
                  <td>
                    <span className={`risk-badge risk-${log.riskLevel}`}>
                      {log.riskLevel.toUpperCase()}
                    </span>
                  </td>
                  <td className="font-mono text-xs text-muted">{log.ipAddress}</td>
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

      {/* Modal de Detalhamento do Evento */}
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
                  <strong>Nível de Risco:</strong> {selectedLog.riskLevel.toUpperCase()}
                </div>
                <div>
                  <strong>IP de Origem:</strong> {selectedLog.ipAddress}
                </div>
              </div>

              <div className="modal-section">
                <strong>Ação:</strong>
                <p>{selectedLog.action}</p>
              </div>

              <div className="modal-section">
                <strong>Payload & Detalhes Registrados:</strong>
                <pre className="log-payload-box font-mono">{selectedLog.details}</pre>
              </div>
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
