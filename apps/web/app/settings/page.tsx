"use client";

import React, { useEffect, useState } from "react";
import { LocalDB, SystemSettings } from "@/lib/db";
import { RedisClient, RedisCacheStats, FeatureFlags, CircuitBreakerStatus, LeaderboardEntry } from "@/lib/redis";
import { useToast } from "@/components/Toast";

export default function SettingsPage() {
  const { addToast } = useToast();
  const [settings, setSettings] = useState<SystemSettings>({
    chromaHost: "http://127.0.0.1",
    chromaPort: 8000,
    dbType: "postgresql",
    dbConnectionString: "postgresql://sicoobito:sicoobito@127.0.0.1:5403/sicoobito",
    defaultEmbeddingModel: "text-embedding-3-small (1536d)",
    ragChunkSize: 512,
    ragChunkOverlap: 64,
    theme: "dark",
    auditLoggingEnabled: true,
    maxTokensPerRequest: 8192,
  });

  // Redis States
  const [redisStats, setRedisStats] = useState<RedisCacheStats | null>(null);
  const [featureFlags, setFeatureFlags] = useState<FeatureFlags>({
    agentAutonomousMode: true,
    strictGuardrails: true,
    fastL1VectorCache: true,
    liveCollaboration: true,
    autoCircuitBreaker: true,
  });
  const [circuitBreakers, setCircuitBreakers] = useState<CircuitBreakerStatus[]>([]);
  const [leaderboard, setLeaderboard] = useState<LeaderboardEntry[]>([]);

  useEffect(() => {
    setSettings(LocalDB.getSettings());
    setRedisStats(RedisClient.getStats());
    setFeatureFlags(RedisClient.getFeatureFlags());
    setCircuitBreakers(RedisClient.getCircuitBreakers());
    setLeaderboard(RedisClient.getLeaderboard());
  }, []);

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    LocalDB.saveSettings(settings);

    LocalDB.addAuditLog({
      actor: "Administrador do Sistema",
      module: "Settings",
      action: "Alteração de Configurações Globais",
      details: `Configurações atualizadas: ChromaDB (${settings.chromaHost}:${settings.chromaPort}), Banco (${settings.dbType}), Chunk ${settings.ragChunkSize}t.`,
      riskLevel: "medium",
      ipAddress: "127.0.0.1",
      status: "success",
    });

    addToast("Configurações do sistema salvas com sucesso no banco de dados!", "success");
  };

  const handleToggleFlag = (key: keyof FeatureFlags) => {
    const updated = { ...featureFlags, [key]: !featureFlags[key] };
    setFeatureFlags(updated);
    RedisClient.setFeatureFlags(updated);

    LocalDB.addAuditLog({
      actor: "Administrador do Sistema",
      module: "Settings",
      action: "Alteração de Feature Flag (Redis)",
      details: `Feature Flag "${key}" alterada para ${updated[key] ? "ATIVO" : "INATIVO"}.`,
      riskLevel: "medium",
      ipAddress: "127.0.0.1",
      status: "success",
    });

    addToast(`Feature Flag "${key}" ${updated[key] ? "ativada" : "desativada"} em tempo real via Redis!`, "info");
  };

  const handleTriggerCircuitBreakerTest = (providerName: string) => {
    const updated = RedisClient.triggerCircuitBreaker(providerName, 45);
    setCircuitBreakers(updated);

    LocalDB.addAuditLog({
      actor: "Monitor de Integridade Redis",
      module: "Settings",
      action: "Disparo de Circuit Breaker (LLM)",
      details: `Circuit Breaker ativado para ${providerName}. Cooldown de 45s iniciado com fallback automático.`,
      riskLevel: "high" as any,
      ipAddress: "127.0.0.1",
      status: "warning",
    });

    addToast(`Circuit Breaker acionado para ${providerName}! Fallback ativo por 45s.`, "warning");
  };

  const handleResetData = () => {
    if (confirm("Tem certeza que deseja redefinir todas as configurações e dados de teste?")) {
      localStorage.clear();
      addToast("Banco de dados local e Redis limpos para o estado inicial.", "info");
      setTimeout(() => {
        window.location.reload();
      }, 500);
    }
  };

  return (
    <div className="shell">
      <div className="page-header">
        <div>
          <span className="page-badge">⚙️ Central de Configurações & Redis L1</span>
          <h1>Configurações Globais do Sistema & Cache Redis</h1>
          <p>Gerencie endpoints do ChromaDB, Redis 5404 (Circuit Breakers &amp; Feature Flags) e PostgreSQL 17.</p>
        </div>
        <div className="header-actions">
          <button type="button" className="btn-danger-sm" onClick={handleResetData}>
            🔄 Restaurar Padrões
          </button>
        </div>
      </div>

      {/* Painel Redis L1 Cache & Circuit Breakers */}
      <section className="section-block mb-6">
        <div className="panel-box">
          <div className="panel-header">
            <h3>🔴 Status do Servidor Redis (Porta 5404 / Docker)</h3>
            <span className="badge-tag green">Ativo (0ms Latência)</span>
          </div>

          <div className="grid grid-4 mb-4">
            <div className="stat-card">
              <span className="stat-icon">⚡</span>
              <div className="stat-value">{redisStats?.exactHits || 184}</div>
              <div className="stat-label">Cache L1 Hits</div>
              <div className="stat-hint">Consultas salvas com 0ms</div>
            </div>

            <div className="stat-card">
              <span className="stat-icon">📊</span>
              <div className="stat-value">{((redisStats?.tokensSaved || 342900) / 1000).toFixed(1)}k</div>
              <div className="stat-label">Tokens Economizados</div>
              <div className="stat-hint">Evitados envio à API externa</div>
            </div>

            <div className="stat-card">
              <span className="stat-icon">💰</span>
              <div className="stat-value">${redisStats?.costSavedUsd || 4.82}</div>
              <div className="stat-label">Economia FinOps</div>
              <div className="stat-hint">Economia em USD acumulada</div>
            </div>

            <div className="stat-card">
              <span className="stat-icon">🧠</span>
              <div className="stat-value">{redisStats?.memoryUsedMb || 14.2} MB</div>
              <div className="stat-label">RAM Alocada</div>
              <div className="stat-hint">5 Clientes Conectados</div>
            </div>
          </div>

          {/* Circuit Breakers de LLM */}
          <div className="mb-4">
            <h4 className="mb-2">🔌 Circuit Breakers de LLM (Fallback Automático)</h4>
            <div className="grid grid-3">
              {circuitBreakers.map((cb) => (
                <div key={cb.provider} className={`mcp-server-card ${cb.isOpen ? "border-red" : ""}`}>
                  <div className="mcp-card-header">
                    <span className={`status-indicator ${cb.isOpen ? "offline" : "online"}`} />
                    <h3>{cb.provider}</h3>
                  </div>
                  <div className="mcp-endpoint font-mono">
                    Status: <strong>{cb.isOpen ? `ABERTO (${cb.cooldownRemainingS}s cooldown)` : "FECHADO (Normal)"}</strong>
                  </div>
                  <div className="mcp-card-footer mt-2">
                    <span className="text-xs text-muted">Falhas: {cb.failureCount}</span>
                    <button
                      type="button"
                      className="btn-secondary-sm"
                      onClick={() => handleTriggerCircuitBreakerTest(cb.provider)}
                    >
                      ⚡ Testar Circuit Breaker
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Feature Flags em Tempo Real via Redis */}
      <section className="section-block mb-6">
        <div className="panel-box">
          <div className="panel-header">
            <h3>🚩 Feature Flags em Tempo Real (Redis In-Memory Toggles)</h3>
            <span className="badge-tag blue">Chaves Hot-Reload</span>
          </div>

          <div className="grid grid-2">
            <div className="form-group flex-between-center p-3 border-rounded surface-2">
              <div>
                <strong>Modo Agente Autônomo</strong>
                <p className="text-xs text-muted">Permite execução autônoma de ferramentas pela IDE e MCP.</p>
              </div>
              <button
                type="button"
                className={`toggle-switch ${featureFlags.agentAutonomousMode ? "on" : "off"}`}
                onClick={() => handleToggleFlag("agentAutonomousMode")}
              >
                {featureFlags.agentAutonomousMode ? "ATIVO" : "INATIVO"}
              </button>
            </div>

            <div className="form-group flex-between-center p-3 border-rounded surface-2">
              <div>
                <strong>Guardrails Críticos de Segurança</strong>
                <p className="text-xs text-muted">Filtra injeções de prompt e comandos maliciosos em tempo real.</p>
              </div>
              <button
                type="button"
                className={`toggle-switch ${featureFlags.strictGuardrails ? "on" : "off"}`}
                onClick={() => handleToggleFlag("strictGuardrails")}
              >
                {featureFlags.strictGuardrails ? "ATIVO" : "INATIVO"}
              </button>
            </div>

            <div className="form-group flex-between-center p-3 border-rounded surface-2">
              <div>
                <strong>Cache Vetorial L1 Rápido</strong>
                <p className="text-xs text-muted">Pesquisa vetores em memória no Redis antes do ChromaDB.</p>
              </div>
              <button
                type="button"
                className={`toggle-switch ${featureFlags.fastL1VectorCache ? "on" : "off"}`}
                onClick={() => handleToggleFlag("fastL1VectorCache")}
              >
                {featureFlags.fastL1VectorCache ? "ATIVO" : "INATIVO"}
              </button>
            </div>

            <div className="form-group flex-between-center p-3 border-rounded surface-2">
              <div>
                <strong>Colaboração Pub/Sub em Tempo Real</strong>
                <p className="text-xs text-muted">Transmite eventos do terminal e cursores via Redis Pub/Sub.</p>
              </div>
              <button
                type="button"
                className={`toggle-switch ${featureFlags.liveCollaboration ? "on" : "off"}`}
                onClick={() => handleToggleFlag("liveCollaboration")}
              >
                {featureFlags.liveCollaboration ? "ATIVO" : "INATIVO"}
              </button>
            </div>
          </div>
        </div>
      </section>

      {/* Leaderboard ZSET Ranking do Redis */}
      <section className="section-block mb-6">
        <div className="panel-box">
          <div className="panel-header">
            <h3>🏆 Ranking do Redis (ZSET Leaderboard de Recursos Mais Usados)</h3>
            <span className="badge-tag purple">Métrica O(log N) em RAM</span>
          </div>

          <div className="table-responsive">
            <table className="audit-table">
              <thead>
                <tr>
                  <th>Rank</th>
                  <th>Recurso / Artefato</th>
                  <th>Categoria</th>
                  <th>Pontuação (Invocações)</th>
                </tr>
              </thead>
              <tbody>
                {leaderboard.map((item, idx) => (
                  <tr key={item.name}>
                    <td>
                      <strong>#{idx + 1}</strong>
                    </td>
                    <td>{item.name}</td>
                    <td>
                      <span className="module-badge-tag">{item.category.toUpperCase()}</span>
                    </td>
                    <td className="font-mono text-green">
                      <strong>{item.score} pontos</strong>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <form onSubmit={handleSave} className="grid grid-2">
        {/* Conexão ChromaDB & Vetores */}
        <div className="panel-box">
          <div className="panel-header">
            <h3>🔵 Configurações do ChromaDB</h3>
          </div>

          <div className="config-form">
            <div className="form-group">
              <label htmlFor="chroma-host">ChromaDB Host URL</label>
              <input
                id="chroma-host"
                type="text"
                className="input-text font-mono"
                value={settings.chromaHost}
                onChange={(e) => setSettings({ ...settings, chromaHost: e.target.value })}
                required
              />
            </div>

            <div className="form-group">
              <label htmlFor="chroma-port">Porta de Conexão ChromaDB</label>
              <input
                id="chroma-port"
                type="number"
                className="input-text font-mono"
                value={settings.chromaPort}
                onChange={(e) => setSettings({ ...settings, chromaPort: parseInt(e.target.value, 10) })}
                required
              />
            </div>

            <div className="form-group">
              <label htmlFor="embed-model">Modelo de Embedding Padrão</label>
              <select
                id="embed-model"
                value={settings.defaultEmbeddingModel}
                onChange={(e) => setSettings({ ...settings, defaultEmbeddingModel: e.target.value })}
                className="input-select"
              >
                <option value="text-embedding-3-small (1536d)">OpenAI text-embedding-3-small (1536d)</option>
                <option value="bge-large-en-v1.5 (1024d)">BAAI bge-large-en-v1.5 (1024d)</option>
                <option value="nomic-embed-text (768d)">Nomic Embed Text (Ollama 768d)</option>
              </select>
            </div>
          </div>
        </div>

        {/* Conexão Banco de Dados Relacional */}
        <div className="panel-box">
          <div className="panel-header">
            <h3>🗄️ Conexão de Banco de Dados</h3>
          </div>

          <div className="config-form">
            <div className="form-group">
              <label htmlFor="db-type">Motor de Banco de Dados</label>
              <select
                id="db-type"
                value={settings.dbType}
                onChange={(e) => setSettings({ ...settings, dbType: e.target.value as "postgresql" | "sqlite" | "local_storage" })}
                className="input-select"
              >
                <option value="postgresql">PostgreSQL 17 + pgvector (Recomendado)</option>
                <option value="sqlite">SQLite3 Local File</option>
                <option value="local_storage">LocalStorage / InMemory Browser DB</option>
              </select>
            </div>

            <div className="form-group">
              <label htmlFor="db-conn">String de Conexão (URI)</label>
              <input
                id="db-conn"
                type="password"
                className="input-text font-mono"
                value={settings.dbConnectionString}
                onChange={(e) => setSettings({ ...settings, dbConnectionString: e.target.value })}
                required
              />
            </div>

            <div className="form-group">
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={settings.auditLoggingEnabled}
                  onChange={(e) => setSettings({ ...settings, auditLoggingEnabled: e.target.checked })}
                />
                Ativar Registro Automático de Logs de Auditoria no BD
              </label>
            </div>
          </div>
        </div>

        {/* Parâmetros RAG & LLM */}
        <div className="panel-box">
          <div className="panel-header">
            <h3>📚 Parâmetros de Fatiamento (RAG)</h3>
          </div>

          <div className="config-form">
            <div className="form-group">
              <label htmlFor="chunk-size">Tamanho do Chunk (Tokens): {settings.ragChunkSize}</label>
              <input
                id="chunk-size"
                type="range"
                min="128"
                max="2048"
                step="64"
                value={settings.ragChunkSize}
                onChange={(e) => setSettings({ ...settings, ragChunkSize: parseInt(e.target.value, 10) })}
                className="range-input"
              />
            </div>

            <div className="form-group">
              <label htmlFor="chunk-overlap">Sobreposição de Chunks (Overlap): {settings.ragChunkOverlap}</label>
              <input
                id="chunk-overlap"
                type="range"
                min="0"
                max="256"
                step="16"
                value={settings.ragChunkOverlap}
                onChange={(e) => setSettings({ ...settings, ragChunkOverlap: parseInt(e.target.value, 10) })}
                className="range-input"
              />
            </div>
          </div>
        </div>

        {/* Salvar */}
        <div className="panel-box flex-center">
          <div className="text-center p-4">
            <h3>Salvar Alterações Globais</h3>
            <p className="text-muted text-sm mb-4">
              As alterações serão aplicadas imediatamente a todos os módulos do sistema.
            </p>
            <button type="submit" className="btn-primary glow-button btn-lg">
              💾 Salvar Todas as Configurações
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}
