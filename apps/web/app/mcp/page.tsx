"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  MCPCatalogTemplate,
  MCPServerRecord,
  MCPTransport,
  createMcpServer,
  deleteMcpServer,
  listMcpCatalog,
  listMcpServers,
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
      const [loaded, templates] = await Promise.all([listMcpServers(), listMcpCatalog()]);
      setServers(loaded);
      setCatalog(templates);
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
          <span className="page-badge">🔌 Servidores MCP</span>
          <h1>Conectores MCP do Agente</h1>
          <p>
            Servidores conectados aqui viram ferramentas reais do agente (prefixo{" "}
            <code className="inline-code">mcp__servidor__ferramenta</code>). Por padrão toda
            ferramenta MCP exige aprovação antes de rodar — só servidores marcados como
            confiáveis abaixo têm suas ferramentas somente-leitura liberadas direto.
          </p>
        </div>
        <div className="header-actions">
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
        {servers.map((s) => (
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
        ))}
      </div>

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
