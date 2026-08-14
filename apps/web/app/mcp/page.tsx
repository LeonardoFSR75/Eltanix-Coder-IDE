"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  MCPCatalogTemplate,
  MCPScanResult,
  MCPScannerStatus,
  MCPServerRecord,
  MCPTransport,
  createMcpServer,
  deleteMcpServer,
  getMcpScannerStatus,
  listMcpCatalog,
  listMcpServers,
  scanAllMcpServers,
  scanMcpServer,
  toggleMcpServer,
} from "@/lib/api/mcp";
import { useToast } from "@/components/Toast";

const STATUS_LABEL: Record<MCPServerRecord["status"], string> = {
  connected: "Conectado",
  connecting: "Conectando…",
  disabled: "Desabilitado",
  error: "Erro",
};

export default function MCPPage() {
  const { addToast } = useToast();
  const router = useRouter();

  const [servers, setServers] = useState<MCPServerRecord[]>([]);
  const [catalog, setCatalog] = useState<MCPCatalogTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedServer, setSelectedServer] = useState<MCPServerRecord | null>(null);
  const [creating, setCreating] = useState(false);

  const [scannerStatus, setScannerStatus] = useState<MCPScannerStatus | null>(null);
  const [scanResults, setScanResults] = useState<Record<string, MCPScanResult>>({});
  const [scanningServer, setScanningServer] = useState<string | null>(null);
  const [selectedAnalyzer, setSelectedAnalyzer] = useState<"yara" | "yara,llm">("yara");

  const [name, setName] = useState("");
  const [transport, setTransport] = useState<MCPTransport>("stdio");
  const [command, setCommand] = useState("");
  const [args, setArgs] = useState("");
  const [url, setUrl] = useState("");
  const [trustAnnotations, setTrustAnnotations] = useState(false);

  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null);
  const [envValues, setEnvValues] = useState<Record<string, string>>({});
  const [argValues, setArgValues] = useState<Record<string, string>>({});

  const refresh = useCallback(async () => {
    try {
      const [loaded, templates, scanner] = await Promise.all([
        listMcpServers(),
        listMcpCatalog(),
        getMcpScannerStatus().catch(() => ({ available: false, mode: "none" as const })),
      ]);
      setServers(loaded);
      setCatalog(templates);
      setScannerStatus(scanner);
      if (loaded.length > 0 && !selectedServer) {
        setSelectedServer(loaded[0]);
      }
    } catch (err) {
      addToast(err instanceof Error ? err.message : "Falha ao carregar servidores MCP.", "error");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [addToast]);

  const handleScanSingle = async (serverName: string) => {
    try {
      setScanningServer(serverName);
      addToast(`Iniciando escaneamento de "${serverName}" com Cisco MCP Scanner...`, "info");
      const analyzers = selectedAnalyzer.split(",");
      const result = await scanMcpServer(serverName, analyzers);
      setScanResults((prev) => ({ ...prev, [serverName]: result }));
      if (result.status === "safe") {
        addToast(`✅ Servidor "${serverName}" escaneado: Seguro! Nenhuma vulnerabilidade encontrada.`, "success");
      } else if (result.status === "threat") {
        addToast(`🚨 Ameaça detectada em "${serverName}"! Verifique o relatório.`, "error");
      } else if (result.status === "warning") {
        addToast(`⚠️ Alertas de segurança encontrados em "${serverName}".`, "info");
      } else if (result.status === "error") {
        addToast(`Erro ao escanear "${serverName}": ${result.error || "Falha na execução"}`, "error");
      }
    } catch (err) {
      addToast(err instanceof Error ? err.message : "Falha ao executar escaneamento.", "error");
    } finally {
      setScanningServer(null);
    }
  };

  const handleScanAll = async () => {
    try {
      setScanningServer("ALL");
      addToast("Escaneando todos os servidores MCP...", "info");
      const analyzers = selectedAnalyzer.split(",");
      const results = await scanAllMcpServers(analyzers);
      const mapped: Record<string, MCPScanResult> = {};
      for (const r of results) {
        mapped[r.server_name] = r;
      }
      setScanResults((prev) => ({ ...prev, ...mapped }));
      addToast("Escaneamento concluído para todos os servidores!", "success");
    } catch (err) {
      addToast(err instanceof Error ? err.message : "Falha ao escanear servidores.", "error");
    } finally {
      setScanningServer(null);
    }
  };

  useEffect(() => {
    refresh();
  }, [refresh]);

  const applyTemplate = (template: MCPCatalogTemplate) => {
    setSelectedTemplateId(template.id);
    setTransport(template.transport);
    setCommand(template.command ?? "");
    setArgs(template.args.join(" "));
    setUrl(template.url ?? "");
    setEnvValues(Object.fromEntries(template.required_env.map((k) => [k, ""])));
    setArgValues(Object.fromEntries(template.required_args.map((k) => [k, ""])));
  };

  const clearTemplate = () => {
    setSelectedTemplateId(null);
    setEnvValues({});
    setArgValues({});
  };

  const selectedTemplate = catalog.find((t) => t.id === selectedTemplateId) ?? null;

  const handleAddServer = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    if (transport === "stdio" && !command.trim()) {
      addToast("Informe o comando para transporte stdio.", "error");
      return;
    }
    if (transport === "http" && !url.trim()) {
      addToast("Informe a URL para transporte HTTP.", "error");
      return;
    }
    if (selectedTemplate) {
      const missing = [
        ...selectedTemplate.required_env.filter((k) => !envValues[k]?.trim()),
        ...selectedTemplate.required_args.filter((k) => !argValues[k]?.trim()),
      ];
      if (missing.length > 0) {
        addToast(`Preencha os campos do template: ${missing.join(", ")}.`, "error");
        return;
      }
    }

    // Placeholders `{nome}` nos args do template (ex.: `{path}`) são
    // substituídos aqui pelo valor que o usuário informou nos campos extras.
    let finalArgs = args.split(" ").filter(Boolean);
    if (selectedTemplate) {
      finalArgs = finalArgs.map((token) => {
        let out = token;
        for (const [key, value] of Object.entries(argValues)) {
          out = out.replace(`{${key}}`, value.trim());
        }
        return out;
      });
    }
    const finalEnv = selectedTemplate ? envValues : {};

    setCreating(true);
    try {
      const updated = await createMcpServer({
        name: name.trim(),
        transport,
        command: transport === "stdio" ? command.trim() : undefined,
        args: transport === "stdio" ? finalArgs : undefined,
        env: Object.keys(finalEnv).length > 0 ? finalEnv : undefined,
        url: transport === "http" ? url.trim() : undefined,
        enabled: true,
        trust_annotations: trustAnnotations,
      });
      setServers(updated);
      const created = updated.find((s) => s.name === name.trim());
      if (created) setSelectedServer(created);
      setName("");
      setCommand("");
      setArgs("");
      setUrl("");
      setTrustAnnotations(false);
      clearTemplate();
      addToast(`Servidor MCP "${name}" conectado.`, "success");
    } catch (err) {
      addToast(err instanceof Error ? err.message : "Falha ao criar servidor MCP.", "error");
    } finally {
      setCreating(false);
    }
  };

  const handleToggle = async (server: MCPServerRecord) => {
    try {
      const updated = await toggleMcpServer(server.name);
      setServers(updated);
      const refreshed = updated.find((s) => s.name === server.name);
      if (refreshed) setSelectedServer(refreshed);
      addToast(`Servidor "${server.name}" ${server.enabled ? "desabilitado" : "habilitado"}.`, "info");
    } catch (err) {
      addToast(err instanceof Error ? err.message : "Falha ao alternar servidor.", "error");
    }
  };

  const handleDelete = async (server: MCPServerRecord) => {
    try {
      const updated = await deleteMcpServer(server.name);
      setServers(updated);
      setSelectedServer(updated.length > 0 ? updated[0] : null);
      addToast(`Servidor "${server.name}" removido.`, "info");
    } catch (err) {
      addToast(err instanceof Error ? err.message : "Falha ao remover servidor.", "error");
    }
  };

  const testInAgent = (server: MCPServerRecord) => {
    if (server.status !== "connected") {
      addToast("Conecte o servidor antes de testar no agente.", "error");
      return;
    }
    router.push(
      `/ide?agentPrompt=${encodeURIComponent(
        `Liste e use as ferramentas do servidor MCP "${server.name}" (prefixo mcp__${server.name}__) para: `,
      )}`,
    );
  };

  return (
    <div className="shell">
      <div className="page-header">
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
            <span className="page-badge">🔌 Servidores MCP</span>
            {scannerStatus?.available ? (
              <span className="badge badge-success" style={{ fontSize: 11 }}>
                🛡️ Cisco AI Defense Scanner: Ativo ({scannerStatus.mode === "docker_or_cli" ? "Docker" : "API"})
              </span>
            ) : (
              <span className="badge badge-muted" style={{ fontSize: 11 }}>
                🛡️ Cisco MCP Scanner: Docker Standby
              </span>
            )}
          </div>
          <h1>Conectores MCP do Agente</h1>
          <p>
            Servidores conectados aqui viram ferramentas reais do agente (prefixo{" "}
            <code className="inline-code">mcp__servidor__ferramenta</code>). Por padrão toda
            ferramenta MCP exige aprovação antes de rodar — só servidores marcados como
            confiáveis abaixo têm suas ferramentas somente-leitura liberadas direto.
          </p>
        </div>
        <div className="header-actions" style={{ display: "flex", gap: 8 }}>
          <button
            type="button"
            className="btn-secondary-sm"
            onClick={handleScanAll}
            disabled={scanningServer !== null || servers.length === 0}
          >
            {scanningServer === "ALL" ? "⏳ Escaneando..." : "🛡️ Escanear Todos (Cisco Scanner)"}
          </button>
          <Link href="/skills" className="btn-secondary-sm">
            ⚡ Skills do Agente
          </Link>
        </div>
      </div>

      <div className="grid grid-3">
        {loading && <p className="text-xs text-muted">Carregando…</p>}
        {!loading && servers.length === 0 && (
          <p className="text-xs text-muted">Nenhum servidor MCP cadastrado ainda.</p>
        )}
        {servers.map((s) => {
          const scan = scanResults[s.name];
          const isScanning = scanningServer === s.name || scanningServer === "ALL";

          return (
            <div
              key={s.name}
              className={`mcp-server-card ${selectedServer?.name === s.name ? "active" : ""}`}
              onClick={() => setSelectedServer(s)}
            >
              <div className="mcp-card-header">
                <span className={`status-indicator ${s.status === "connected" ? "online" : "offline"}`} />
                <h3>{s.name}</h3>
                <span className="mcp-type-badge">{s.transport.toUpperCase()}</span>
              </div>

              <div className="mcp-endpoint font-mono">
                {s.transport === "stdio" ? `${s.command} ${s.args.join(" ")}` : s.url}
              </div>

              <div className="mcp-capabilities-grid">
                <div className="cap-box">
                  <span className="cap-num">{s.tools_count}</span>
                  <span className="cap-label">Tools</span>
                </div>
                <div className="cap-box">
                  <span className="cap-num">{STATUS_LABEL[s.status]}</span>
                  <span className="cap-label">Status</span>
                </div>
              </div>

              {scan && (
                <div style={{ marginTop: 8, padding: "4px 8px", borderRadius: 4, fontSize: 11, background: scan.status === "safe" ? "rgba(16,185,129,0.1)" : scan.status === "threat" ? "rgba(239,68,68,0.15)" : "rgba(245,158,11,0.15)", color: scan.status === "safe" ? "#10b981" : scan.status === "threat" ? "#ef4444" : "#f59e0b" }}>
                  {scan.status === "safe" && "🛡️ Cisco Scanner: Seguro (0 ameaças)"}
                  {scan.status === "threat" && `🚨 Cisco Scanner: ${scan.findings_count} Ameaça(s)`}
                  {scan.status === "warning" && `⚠️ Cisco Scanner: ${scan.findings_count} Alerta(s)`}
                  {scan.status === "error" && "❌ Erro no scan"}
                </div>
              )}

              {s.status === "error" && s.error && (
                <p className="text-xs" style={{ color: "var(--danger)" }}>
                  {s.error}
                </p>
              )}

              <div className="mcp-card-footer">
                <span>{s.trust_annotations ? "Confiável" : "Sempre pede aprovação"}</span>
                <div style={{ display: "flex", gap: 6 }}>
                  <button
                    type="button"
                    className="btn-secondary-sm"
                    title="Escanear com Cisco AI Defense MCP Scanner"
                    disabled={isScanning}
                    onClick={(e) => {
                      e.stopPropagation();
                      handleScanSingle(s.name);
                    }}
                  >
                    {isScanning ? "⏳..." : "🛡️ Scan"}
                  </button>
                  <button
                    type="button"
                    className="btn-secondary-sm"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleToggle(s);
                    }}
                  >
                    {s.enabled ? "Desabilitar" : "Habilitar"}
                  </button>
                  <button
                    type="button"
                    className="btn-danger-sm"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDelete(s);
                    }}
                  >
                    Remover
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Painel de Auditoria de Segurança Cisco MCP Scanner */}
      {selectedServer && (
        <div className="panel-box mb-6" style={{ borderLeft: "4px solid var(--primary, #0284c7)" }}>
          <div className="panel-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <h3>🛡️ Auditoria de Segurança Cisco AI Defense ({selectedServer.name})</h3>
              <span className="badge badge-info" style={{ fontSize: 11 }}>Cisco MCP Scanner</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <select
                className="input-select"
                style={{ width: "auto", padding: "4px 8px", fontSize: 12 }}
                value={selectedAnalyzer}
                onChange={(e) => setSelectedAnalyzer(e.target.value as "yara" | "yara,llm")}
              >
                <option value="yara">Motor YARA (Regras Estáticas)</option>
                <option value="yara,llm">YARA + LLM-as-a-Judge (Semântico)</option>
              </select>
              <button
                type="button"
                className="btn-primary-sm"
                onClick={() => handleScanSingle(selectedServer.name)}
                disabled={scanningServer === selectedServer.name}
              >
                {scanningServer === selectedServer.name ? "⏳ Escaneando..." : "▶ Iniciar Scan Agora"}
              </button>
            </div>
          </div>

          {scanResults[selectedServer.name] ? (
            <div style={{ marginTop: 12 }}>
              {(() => {
                const res = scanResults[selectedServer.name];
                return (
                  <div>
                    <div style={{ display: "flex", gap: 16, marginBottom: 12, fontSize: 13 }}>
                      <div>
                        <strong>Status: </strong>
                        <span style={{ fontWeight: 600, color: res.status === "safe" ? "#10b981" : res.status === "threat" ? "#ef4444" : "#f59e0b" }}>
                          {res.status.toUpperCase()}
                        </span>
                      </div>
                      <div><strong>Ferramentas Analisadas:</strong> {res.tools_scanned}</div>
                      <div><strong>Achados de Segurança:</strong> {res.findings_count}</div>
                      <div><strong>Data/Hora:</strong> {new Date(res.scanned_at).toLocaleTimeString()}</div>
                    </div>

                    {res.error && (
                      <div className="alert alert-danger" style={{ padding: "8px 12px", marginBottom: 12, borderRadius: 6, background: "rgba(239,68,68,0.1)", color: "#ef4444", fontSize: 12 }}>
                        {res.error}
                      </div>
                    )}

                    {res.findings.length > 0 ? (
                      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                        {res.findings.map((f, idx) => (
                          <div key={idx} style={{ padding: "10px 12px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 6 }}>
                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                              <span style={{ fontWeight: 600, fontSize: 13 }}>{f.tool_name} — {f.rule_id}</span>
                              <span className={`badge ${f.severity === "high" || f.severity === "critical" ? "badge-danger" : "badge-warning"}`} style={{ fontSize: 10 }}>
                                {f.severity.toUpperCase()} ({f.analyzer})
                              </span>
                            </div>
                            <p style={{ margin: 0, fontSize: 12, color: "var(--text-muted)" }}>{f.message || f.description}</p>
                          </div>
                        ))}
                      </div>
                    ) : (
                      !res.error && (
                        <p style={{ color: "#10b981", fontSize: 12, margin: 0 }}>
                          ✅ Nenhuma vulnerabilidade, injeção de prompt ou comportamento malicioso detectado neste servidor MCP.
                        </p>
                      )
                    )}
                  </div>
                );
              })()}
            </div>
          ) : (
            <p className="text-xs text-muted" style={{ marginTop: 8 }}>
              Clique em &quot;Iniciar Scan Agora&quot; para inspecionar este servidor com os analisadores de segurança Cisco AI Defense (YARA / LLM).
            </p>
          )}
        </div>
      )}

      {catalog.length > 0 && (
        <div className="panel-box mb-6">
          <div className="panel-header">
            <h3>📦 Catálogo de conectores conhecidos</h3>
          </div>
          <p className="text-xs text-muted mb-2">
            Escolha um servidor conhecido para pré-preencher o formulário abaixo — só falta dar um
            nome e informar o que o template pedir (token, caminho, etc).
          </p>
          <div className="grid grid-3">
            {catalog.map((t) => (
              <div
                key={t.id}
                className={`mcp-server-card ${selectedTemplateId === t.id ? "active" : ""}`}
                onClick={() => applyTemplate(t)}
              >
                <div className="mcp-card-header">
                  <h3>{t.label}</h3>
                  <span className="mcp-type-badge">{t.transport.toUpperCase()}</span>
                </div>
                <p className="text-xs text-muted">{t.description}</p>
                {t.note && <p className="text-xs text-muted">⚠️ {t.note}</p>}
              </div>
            ))}
          </div>
          {selectedTemplateId && (
            <button type="button" className="btn-secondary-sm mt-2" onClick={clearTemplate}>
              Limpar template selecionado
            </button>
          )}
        </div>
      )}

      <div className="grid grid-2">
        <div className="panel-box">
          <div className="panel-header">
            <h3>+ Conectar Servidor MCP</h3>
          </div>

          <form onSubmit={handleAddServer} className="config-form">
            {selectedTemplate && (
              <>
                {selectedTemplate.required_env.map((key) => (
                  <div className="form-group" key={key}>
                    <label htmlFor={`mcp-env-${key}`}>{key}</label>
                    <input
                      id={`mcp-env-${key}`}
                      type="text"
                      className="input-text font-mono"
                      value={envValues[key] ?? ""}
                      onChange={(e) => setEnvValues((v) => ({ ...v, [key]: e.target.value }))}
                      placeholder={key}
                    />
                  </div>
                ))}
                {selectedTemplate.required_args.map((key) => (
                  <div className="form-group" key={key}>
                    <label htmlFor={`mcp-arg-${key}`}>{key}</label>
                    <input
                      id={`mcp-arg-${key}`}
                      type="text"
                      className="input-text font-mono"
                      value={argValues[key] ?? ""}
                      onChange={(e) => setArgValues((v) => ({ ...v, [key]: e.target.value }))}
                      placeholder={key}
                    />
                  </div>
                ))}
              </>
            )}
            <div className="form-group">
              <label htmlFor="mcp-name">Nome do Servidor</label>
              <input
                id="mcp-name"
                type="text"
                className="input-text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Ex: filesystem-local"
                required
              />
            </div>

            <div className="form-group">
              <label htmlFor="mcp-type">Tipo de Transporte</label>
              <select
                id="mcp-type"
                value={transport}
                onChange={(e) => setTransport(e.target.value as MCPTransport)}
                className="input-select"
              >
                <option value="stdio">STDIO (Subprocesso Local)</option>
                <option value="http">Streamable HTTP (Remoto)</option>
              </select>
            </div>

            {transport === "stdio" ? (
              <>
                <div className="form-group">
                  <label htmlFor="mcp-command">Comando</label>
                  <input
                    id="mcp-command"
                    type="text"
                    className="input-text font-mono"
                    value={command}
                    onChange={(e) => setCommand(e.target.value)}
                    placeholder="npx"
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="mcp-args">Argumentos (separados por espaço)</label>
                  <input
                    id="mcp-args"
                    type="text"
                    className="input-text font-mono"
                    value={args}
                    onChange={(e) => setArgs(e.target.value)}
                    placeholder="-y @modelcontextprotocol/server-filesystem /projects"
                  />
                </div>
              </>
            ) : (
              <div className="form-group">
                <label htmlFor="mcp-url">URL</label>
                <input
                  id="mcp-url"
                  type="text"
                  className="input-text font-mono"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://exemplo.com/mcp"
                />
              </div>
            )}

            <div className="form-group">
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={trustAnnotations}
                  onChange={(e) => setTrustAnnotations(e.target.checked)}
                />
                Confio neste servidor — liberar ferramentas somente-leitura sem aprovação
              </label>
            </div>

            <button type="submit" className="btn-primary btn-block" disabled={creating}>
              {creating ? "Conectando…" : "🔌 Conectar Servidor"}
            </button>
          </form>
        </div>

        <div className="panel-box">
          <div className="panel-header">
            <h3>🤖 Testar no Agente</h3>
          </div>
          {selectedServer ? (
            <>
              <p className="text-xs text-muted mb-2">
                Abre o IDE com um prompt sugerindo o uso das ferramentas de{" "}
                <strong>{selectedServer.name}</strong> — a execução acontece de verdade, dentro
                de uma sessão do agente.
              </p>
              <button
                type="button"
                className="btn-primary glow-button btn-block"
                onClick={() => testInAgent(selectedServer)}
                disabled={selectedServer.status !== "connected"}
              >
                ▶ Abrir no Agent Panel
              </button>
            </>
          ) : (
            <p className="text-xs text-muted">Selecione um servidor na lista acima.</p>
          )}
        </div>
      </div>
    </div>
  );
}

