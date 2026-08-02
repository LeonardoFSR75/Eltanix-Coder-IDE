"use client";

import React, { useEffect, useState } from "react";
import { LocalDB, MCPServer } from "@/lib/db";
import { useToast } from "@/components/Toast";

export default function MCPPage() {
  const { addToast } = useToast();
  const [servers, setServers] = useState<MCPServer[]>([]);
  const [selectedServer, setSelectedServer] = useState<MCPServer | null>(null);

  // Form states for new server
  const [serverName, setServerName] = useState("");
  const [serverType, setServerType] = useState<"stdio" | "sse">("stdio");
  const [endpoint, setEndpoint] = useState("");

  // Console state
  const [selectedTool, setSelectedTool] = useState("fs_read_file");
  const [jsonRpcRequest, setJsonRpcRequest] = useState(
    '{\n  "jsonrpc": "2.0",\n  "id": 1,\n  "method": "tools/call",\n  "params": {\n    "name": "fs_read_file",\n    "arguments": {\n      "path": "/workspace/README.md"\n    }\n  }\n}'
  );
  const [jsonRpcResponse, setJsonRpcResponse] = useState("");
  const [isExecutingRpc, setIsExecutingRpc] = useState(false);

  useEffect(() => {
    const loaded = LocalDB.getMCP();
    setServers(loaded);
    if (loaded.length > 0) {
      setSelectedServer(loaded[0]);
    }
  }, []);

  const handleAddServer = (e: React.FormEvent) => {
    e.preventDefault();
    if (!serverName || !endpoint) return;

    const newServer: MCPServer = {
      id: `mcp-${Date.now()}`,
      name: serverName,
      type: serverType,
      endpoint,
      status: "online",
      latencyMs: Math.floor(Math.random() * 20 + 8),
      toolsCount: 4,
      resourcesCount: 6,
      promptsCount: 2,
      lastPing: new Date().toISOString(),
    };

    const updated = [newServer, ...servers];
    setServers(updated);
    setSelectedServer(newServer);
    LocalDB.saveMCP(updated);
    setServerName("");
    setEndpoint("");
    addToast(`Servidor MCP "${newServer.name}" registrado no banco com sucesso!`, "success");
  };

  const handlePingServer = (server: MCPServer) => {
    addToast(`Testando latência com ${server.name}...`, "info");
    setTimeout(() => {
      const newLatency = Math.floor(Math.random() * 15 + 5);
      const updated = servers.map((s) =>
        s.id === server.id ? { ...s, latencyMs: newLatency, lastPing: new Date().toISOString() } : s
      );
      setServers(updated);
      LocalDB.saveMCP(updated);
      addToast(`Servidor ${server.name} respondeu em ${newLatency}ms!`, "success");
    }, 400);
  };

  const handleExecuteJsonRpc = () => {
    setIsExecutingRpc(true);
    setJsonRpcResponse("⌛ Enviando requisição JSON-RPC 2.0 via protocolo MCP...");

    setTimeout(() => {
      setIsExecutingRpc(false);
      try {
        const parsed = JSON.parse(jsonRpcRequest);
        const responsePayload = {
          jsonrpc: "2.0",
          id: parsed.id || 1,
          result: {
            content: [
              {
                type: "text",
                text: `[MCP EXECUTION SUCCESS] Executada a ferramenta "${selectedTool}" no servidor "${selectedServer?.name || "Filesystem Local"}".\n\nConteúdo lido: SicoobitoCode Platform v2.0 - Local-first agentic environment.`,
              },
            ],
            isError: false,
          },
        };
        setJsonRpcResponse(JSON.stringify(responsePayload, null, 2));

        // ✅ INTEGRAÇÃO AUDITORIA: Registro de Chamada MCP
        LocalDB.addAuditLog({
          actor: `Agente MCP (${selectedServer?.name || "STDIO Local"})`,
          module: "MCP",
          action: `Execução de Ferramenta (${selectedTool})`,
          details: `Invocada ferramenta ${selectedTool} via JSON-RPC 2.0. Resposta: 200 OK.`,
          riskLevel: "low",
          ipAddress: "127.0.0.1",
          status: "success",
        });

        addToast("Resposta JSON-RPC 2.0 recebida do servidor MCP!", "success");
      } catch (err) {
        setJsonRpcResponse(
          JSON.stringify({ jsonrpc: "2.0", id: null, error: { code: -32700, message: "Parse error em JSON" } }, null, 2)
        );

        LocalDB.addAuditLog({
          actor: "Cliente JSON-RPC",
          module: "MCP",
          action: "Erro de Sintaxe JSON-RPC",
          details: "Tentativa de envio com payload JSON malformado.",
          riskLevel: "medium",
          ipAddress: "127.0.0.1",
          status: "warning",
        });

        addToast("Erro no formato JSON da requisição.", "error");
      }
    }, 600);
  };

  return (
    <div className="shell">
      <div className="page-header">
        <div>
          <span className="page-badge">🚧 MCP — Roteiro (ainda não implementado)</span>
          <h1>Preview: Conectores & Servidores MCP</h1>
          <p>
            Esta tela é uma demonstração interativa do desenho da futura integração MCP —
            os servidores, ferramentas e respostas abaixo são simulados, não uma conexão real.
            O agente do IDE já tem um registro de ferramentas real (<code className="inline-code">agent/tools</code>)
            pronto para receber ferramentas MCP quando essa integração existir de verdade.
          </p>
        </div>
        <div className="header-actions">
          <span className="badge-tag blue">Demo — dados simulados</span>
        </div>
      </div>

      {/* Grid de Servidores MCP */}
      <div className="grid grid-3">
        {servers.map((s) => (
          <div
            key={s.id}
            className={`mcp-server-card ${selectedServer?.id === s.id ? "active" : ""}`}
            onClick={() => setSelectedServer(s)}
          >
            <div className="mcp-card-header">
              <span className={`status-indicator ${s.status}`} />
              <h3>{s.name}</h3>
              <span className="mcp-type-badge">{s.type.toUpperCase()}</span>
            </div>

            <div className="mcp-endpoint font-mono">{s.endpoint}</div>

            <div className="mcp-capabilities-grid">
              <div className="cap-box">
                <span className="cap-num">{s.toolsCount}</span>
                <span className="cap-label">Tools</span>
              </div>
              <div className="cap-box">
                <span className="cap-num">{s.resourcesCount}</span>
                <span className="cap-label">Resources</span>
              </div>
              <div className="cap-box">
                <span className="cap-num">{s.promptsCount}</span>
                <span className="cap-label">Prompts</span>
              </div>
            </div>

            <div className="mcp-card-footer">
              <span>Latência: <strong>{s.latencyMs}ms</strong></span>
              <button
                type="button"
                className="btn-secondary-sm"
                onClick={(e) => {
                  e.stopPropagation();
                  handlePingServer(s);
                }}
              >
                ⚡ Ping
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* Form Adicionar Servidor & Console JSON-RPC */}
      <div className="grid grid-2">
        {/* Adicionar Novo Servidor MCP */}
        <div className="panel-box">
          <div className="panel-header">
            <h3>+ Registrar Novo Servidor MCP</h3>
          </div>

          <form onSubmit={handleAddServer} className="config-form">
            <div className="form-group">
              <label htmlFor="mcp-name">Nome do Servidor</label>
              <input
                id="mcp-name"
                type="text"
                className="input-text"
                value={serverName}
                onChange={(e) => setServerName(e.target.value)}
                placeholder="Ex: Slack Notifier MCP"
                required
              />
            </div>

            <div className="form-group">
              <label htmlFor="mcp-type">Tipo de Transporte</label>
              <select
                id="mcp-type"
                value={serverType}
                onChange={(e) => setServerType(e.target.value as "stdio" | "sse")}
                className="input-select"
              >
                <option value="stdio">STDIO (Subprocesso Local)</option>
                <option value="sse">SSE (Server-Sent Events HTTP)</option>
              </select>
            </div>

            <div className="form-group">
              <label htmlFor="mcp-endpoint">Comando / Endpoint URL</label>
              <input
                id="mcp-endpoint"
                type="text"
                className="input-text font-mono"
                value={endpoint}
                onChange={(e) => setEndpoint(e.target.value)}
                placeholder="npx -y @modelcontextprotocol/server-..."
                required
              />
            </div>

            <button type="submit" className="btn-primary btn-block">
              💾 Cadastrar Servidor no BD
            </button>
          </form>
        </div>

        {/* Inspeção e Invocador de Ferramentas MCP */}
        <div className="panel-box">
          <div className="panel-header">
            <h3>Console JSON-RPC 2.0</h3>
            <span className="text-sm text-muted">
              Alvo: {selectedServer ? selectedServer.name : "Nenhum selecionado"}
            </span>
          </div>

          <div className="config-form">
            <div className="form-group">
              <label htmlFor="tool-select">Ferramenta Disponível</label>
              <select
                id="tool-select"
                value={selectedTool}
                onChange={(e) => setSelectedTool(e.target.value)}
                className="input-select"
              >
                <option value="fs_read_file">fs_read_file (Ler Arquivo)</option>
                <option value="fs_write_file">fs_write_file (Escrever Arquivo)</option>
                <option value="db_query_pg">db_query_pg (Consulta SQL Postgres)</option>
                <option value="chroma_query_vector">chroma_query_vector (Busca Vetores)</option>
              </select>
            </div>

            <div className="form-group">
              <label htmlFor="rpc-req-area">Payload JSON-RPC Request</label>
              <textarea
                id="rpc-req-area"
                value={jsonRpcRequest}
                onChange={(e) => setJsonRpcRequest(e.target.value)}
                className="input-textarea font-mono"
                rows={5}
              />
            </div>

            <button
              type="button"
              className="btn-primary glow-button btn-block"
              onClick={handleExecuteJsonRpc}
              disabled={isExecutingRpc}
            >
              {isExecutingRpc ? "Enviando RPC..." : "▶ Executar Chamada MCP"}
            </button>
          </div>
        </div>
      </div>

      {/* Visualizador da Resposta RPC */}
      <section className="section-block">
        <div className="panel-box">
          <div className="panel-header">
            <h3>Response Payload Inspector (JSON-RPC 2.0 Output)</h3>
          </div>
          <textarea
            value={jsonRpcResponse}
            readOnly
            className="input-textarea font-mono text-blue"
            rows={7}
            placeholder="Aguardando envio de chamadas JSON-RPC 2.0..."
          />
        </div>
      </section>
    </div>
  );
}
