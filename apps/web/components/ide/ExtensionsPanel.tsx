"use client";

/**
 * O catálogo de extensões é servido pelo backend (`MASTER_EXTENSIONS_CATALOG`
 * em `extensions/catalog.py`, persistido em Postgres — ver `extensions/manager.py`).
 * Não duplicar essa lista aqui: se a busca falhar, mostrar erro + retry
 * (`PanelState kind="error"`) em vez de inventar dados desatualizados.
 */

import { useCallback, useEffect, useState } from "react";
import {
  getExtensionsCatalog,
  syncExtensions,
  toggleExtension,
  updateExtension,
  updateAllExtensions,
  setAutoUpdate,
  searchMarketplace,
  type ExtensionItem,
  type ExtensionsCatalogResponse,
} from "@/lib/api/extensions";
import { PanelState } from "@/components/ide/PanelState";

export function ExtensionsPanel() {
  const [catalog, setCatalog] = useState<ExtensionsCatalogResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [updatingAll, setUpdatingAll] = useState(false);
  const [updatingIds, setUpdatingIds] = useState<Set<string>>(new Set());
  const [filterText, setFilterText] = useState("");
  const [category, setCategory] = useState<string>("Todas");
  const [activeEngine, setActiveEngine] = useState<"pyrefly" | "pyright">("pyrefly");
  const [selectedExt, setSelectedExt] = useState<ExtensionItem | null>(null);
  const [onlineResults, setOnlineResults] = useState<ExtensionItem[]>([]);
  const [searchingOnline, setSearchingOnline] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const carregar = useCallback(async (isSync = false) => {
    try {
      if (isSync) setSyncing(true);
      else setLoading(true);
      const res = isSync ? await syncExtensions(true) : await getExtensionsCatalog();
      setCatalog(res);
      setErro(null);
    } catch (err) {
      setErro(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
      setSyncing(false);
    }
  }, []);

  useEffect(() => {
    carregar();
  }, []);

  // Mesmo mecanismo do PackagesPanel: refresco automático quando o agente
  // mexe em extensões via `manage_extensions` (toggle/update/sync), evento
  // disparado por `sessionRuntime.ts` a partir do stream SSE de tool-calls.
  useEffect(() => {
    const handleExtensionsChanged = () => void carregar();
    window.addEventListener("sicoobito:extensions:changed", handleExtensionsChanged);
    return () => window.removeEventListener("sicoobito:extensions:changed", handleExtensionsChanged);
  }, [carregar]);

  const handleToggle = async (id: string, curActive: boolean) => {
    try {
      const res = await toggleExtension(id, !curActive);
      setCatalog((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          extensions: prev.extensions.map((ext) =>
            ext.id === id ? { ...ext, active: res.active } : ext
          ),
        };
      });
    } catch {
      // Otimista fallback
      setCatalog((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          extensions: prev.extensions.map((ext) =>
            ext.id === id ? { ...ext, active: !curActive } : ext
          ),
        };
      });
    }
  };

  const handleUpdateSingle = async (id: string) => {
    setUpdatingIds((prev) => new Set(prev).add(id));
    try {
      await updateExtension(id);
      await carregar();
    } finally {
      setUpdatingIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  };

  const handleUpdateAll = async () => {
    setUpdatingAll(true);
    try {
      const res = await updateAllExtensions();
      if (res.catalog) setCatalog(res.catalog);
      else await carregar();
    } finally {
      setUpdatingAll(false);
    }
  };

  const handleToggleAutoUpdate = async () => {
    if (!catalog) return;
    const target = !catalog.auto_update_enabled;
    try {
      await setAutoUpdate(target);
      setCatalog((prev) => (prev ? { ...prev, auto_update_enabled: target } : prev));
    } catch {
      // noop
    }
  };

  const handleOnlineSearch = async (query: string) => {
    if (query.trim().length < 2) {
      setOnlineResults([]);
      return;
    }
    setSearchingOnline(true);
    try {
      const res = await searchMarketplace(query);
      setOnlineResults(res.results || []);
    } catch {
      setOnlineResults([]);
    } finally {
      setSearchingOnline(false);
    }
  };

  const extensionsList = catalog?.extensions || [];
  const pendingUpdatesCount = catalog?.pending_updates_count || 0;

  const filteredExtensions = extensionsList.filter((ext) => {
    if (category === "Atualizações") return ext.hasUpdate;
    if (category === "Marketplace Online") return false;
    const matchCat = category === "Todas" || ext.category === category;
    const matchText =
      !filterText.trim() ||
      ext.name.toLowerCase().includes(filterText.toLowerCase()) ||
      ext.publisher.toLowerCase().includes(filterText.toLowerCase()) ||
      ext.description.toLowerCase().includes(filterText.toLowerCase());
    return matchCat && matchText;
  });

  const categories = [
    "Todas",
    pendingUpdatesCount > 0 ? `Atualizações (${pendingUpdatesCount})` : "Atualizações",
    "Frontend & Visual",
    "IA & Web Scraping",
    "Bancos & RAG",
    "Segurança & Auditoria",
    "APIs & Testes",
    "Segundo Cérebro & Arquitetura",
    "LSP & Linguagens",
    "DevOps & Containers",
    "Produtividade",
    "Marketplace Online",
  ];

  return (
    <div className="extensions-panel">
      {/* Header com Ações e Sincronização */}
      <div className="extensions-header">
        <div className="extensions-title-group">
          <div className="extensions-title-icon">🧩</div>
          <div>
            <h3 className="extensions-title">Extensões & 6 Suítes</h3>
            <p className="extensions-subtitle">
              {catalog?.total_count || 0} instaladas • Auto-update VS Code & Open VSX
            </p>
          </div>
        </div>
        <div className="extensions-header-actions">
          <button
            type="button"
            className={`icon-action-btn ${syncing ? "spinning" : ""}`}
            title="Sincronizar com Open VSX / VS Code Marketplace"
            onClick={() => carregar(true)}
            disabled={syncing}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21.5 2v6h-6M2.5 22v-6h6" />
              <path d="M2 11.5a10 10 0 0 1 18.8-4.3L21.5 8M22 12.5a10 10 0 0 1-18.8 4.2L2.5 16" />
            </svg>
          </button>
        </div>
      </div>

      {erro && catalog && <div className="panel-error">{erro}</div>}

      {/* Barra de Status do Auto-Update & Ação Global de Atualização */}
      <div className="extensions-auto-update-bar">
        <button
          type="button"
          className={`ext-auto-update-pill ${catalog?.auto_update_enabled ? "active" : "inactive"}`}
          onClick={handleToggleAutoUpdate}
          title="Alternar modo de atualização automática com Open VSX"
        >
          <span className="dot" />
          <span>Auto-Update {catalog?.auto_update_enabled ? "Ativo" : "Pausado"}</span>
        </button>

        {pendingUpdatesCount > 0 && (
          <button
            type="button"
            className="ext-btn-update-all"
            onClick={handleUpdateAll}
            disabled={updatingAll}
          >
            {updatingAll ? "Atualizando..." : `🔄 Atualizar Todas (${pendingUpdatesCount})`}
          </button>
        )}
      </div>

      {/* Engine Selection Card for Python */}
      <div className="extensions-lsp-selector">
        <div className="lsp-selector-label">
          <span>Engine LSP Python Principal:</span>
          <span className="lsp-active-badge">{activeEngine === "pyrefly" ? "Meta Pyrefly" : "Pyright"}</span>
        </div>
        <div className="lsp-selector-buttons">
          <button
            type="button"
            className={`lsp-engine-btn ${activeEngine === "pyrefly" ? "active" : ""}`}
            onClick={() => setActiveEngine("pyrefly")}
          >
            🦟 Pyrefly (Meta)
          </button>
          <button
            type="button"
            className={`lsp-engine-btn ${activeEngine === "pyright" ? "active" : ""}`}
            onClick={() => setActiveEngine("pyright")}
          >
            🐍 Pyright (MS)
          </button>
        </div>
      </div>

      {/* Categories & Search */}
      <div className="extensions-search-box">
        <input
          type="text"
          className="extensions-input-search"
          placeholder={
            category === "Marketplace Online"
              ? "Pesquisar extensões públicas no Open VSX..."
              : "Buscar extensão, suíte, autor..."
          }
          value={filterText}
          onChange={(e) => {
            setFilterText(e.target.value);
            if (category === "Marketplace Online") {
              handleOnlineSearch(e.target.value);
            }
          }}
        />
      </div>

      <div className="extensions-categories">
        {categories.map((cat) => {
          const isSelected = category === cat || (cat.startsWith("Atualizações") && category === "Atualizações");
          const isUpdateCat = cat.startsWith("Atualizações");
          return (
            <button
              key={cat}
              type="button"
              className={`ext-cat-chip ${isSelected ? "active" : ""} ${isUpdateCat && pendingUpdatesCount > 0 ? "has-updates" : ""}`}
              onClick={() => {
                const cleanCat = isUpdateCat ? "Atualizações" : cat;
                setCategory(cleanCat);
                if (cleanCat === "Marketplace Online" && filterText.trim().length >= 2) {
                  handleOnlineSearch(filterText);
                }
              }}
            >
              {cat}
            </button>
          );
        })}
      </div>

      {/* Extension Items Grid */}
      <div className="extensions-scroll-list">
        {loading && !catalog ? (
          <PanelState kind="loading" message="Carregando catálogo de extensões..." />
        ) : erro && !catalog ? (
          <PanelState
            kind="error"
            message={`Não foi possível carregar o catálogo do backend: ${erro}`}
            onRetry={() => carregar()}
          />
        ) : category === "Marketplace Online" ? (
          <>
            <div className="ext-section-header">
              <span>MARKETPLACE ONLINE (OPEN VSX REGISTRY)</span>
              <span className="ext-section-count">{onlineResults.length}</span>
            </div>
            {searchingOnline && (
              <PanelState kind="loading" message="Consultando repositórios do Open VSX..." />
            )}
            {!searchingOnline && onlineResults.length === 0 && (
              <PanelState
                kind="empty"
                icon="🌐"
                message="Digite pelo menos 2 caracteres para buscar extensões no marketplace oficial."
              />
            )}
            {onlineResults.map((ext) => (
              <div key={ext.id} className="ext-card recommended-card">
                <div className="ext-card-header">
                  <span className="ext-card-icon">{ext.icon || "🧩"}</span>
                  <div className="ext-card-titles">
                    <div className="ext-card-name-row">
                      <span className="ext-card-name">{ext.name}</span>
                      {ext.downloads && (
                        <span className="ext-card-downloads">⬇️ {ext.downloads} ★ {ext.rating || 4.8}</span>
                      )}
                    </div>
                    <div className="ext-card-publisher-row">
                      <span className="ext-publisher-tag">{ext.publisher}</span>
                      <span className="ext-version-badge">v{ext.version}</span>
                    </div>
                  </div>
                </div>
                <p className="ext-card-desc">{ext.description}</p>
                <div className="ext-card-footer">
                  <span className="ext-status-pill inactive">Open VSX</span>
                  <div className="ext-card-actions">
                    <button
                      type="button"
                      className="ext-btn-primary-install"
                      onClick={() => handleToggle(ext.id, false)}
                    >
                      Instalar & Ativar
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </>
        ) : (
          <>
            <div className="ext-section-header">
              <span>{category.toUpperCase()}</span>
              <span className="ext-section-count">{filteredExtensions.length}</span>
            </div>

            {filteredExtensions.length === 0 && (
              <PanelState kind="empty" icon="🔍" message="Nenhuma extensão encontrada para o filtro atual." />
            )}

            {filteredExtensions.map((ext) => {
              const isEnabled = ext.active !== false;
              const isUpdating = updatingIds.has(ext.id);

              return (
                <div
                  key={ext.id}
                  className={`ext-card ${!isEnabled ? "disabled" : ""} ${ext.hasUpdate ? "has-update-border" : ""}`}
                >
                  <div className="ext-card-header">
                    <span className="ext-card-icon">{ext.icon}</span>
                    <div className="ext-card-titles">
                      <div className="ext-card-name-row">
                        <span className="ext-card-name">{ext.name}</span>
                        {ext.latency_ms && (
                          <span className="ext-card-latency" title="Tempo de inicialização / latência LSP">
                            ⏱️ {ext.latency_ms}ms
                          </span>
                        )}
                      </div>
                      <div className="ext-card-publisher-row">
                        <span className={`ext-publisher-tag publisher-${ext.publisher.toLowerCase().replace(/[^a-z0-9]/g, "-")}`}>
                          {ext.publisher}
                        </span>
                        <span className="ext-version-badge">v{ext.version}</span>
                        {ext.hasUpdate && ext.updateInfo && (
                          <span className="ext-update-available-badge" title="Nova versão disponível no Open VSX">
                            ↑ v{ext.updateInfo.latest_version}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  <p className="ext-card-desc">{ext.description}</p>

                  <div className="ext-card-footer">
                    <div className="ext-card-status-group">
                      <span className={`ext-status-pill ${isEnabled ? "active" : "inactive"}`}>
                        {isEnabled ? "Ativo" : "Desativado"}
                      </span>
                      <span className="ext-category-tag">{ext.category}</span>
                    </div>

                    <div className="ext-card-actions">
                      {ext.hasUpdate && (
                        <button
                          type="button"
                          className="ext-btn-update-single"
                          onClick={() => handleUpdateSingle(ext.id)}
                          disabled={isUpdating}
                          title={`Atualizar para v${ext.updateInfo?.latest_version}`}
                        >
                          {isUpdating ? "..." : "↑ Atualizar"}
                        </button>
                      )}

                      <button
                        type="button"
                        className="ext-btn-secondary"
                        onClick={() => setSelectedExt(ext)}
                        title="Ver detalhes da extensão"
                      >
                        ⚙️ Info
                      </button>
                      <button
                        type="button"
                        className={`ext-btn-toggle ${isEnabled ? "disable" : "enable"}`}
                        onClick={() => handleToggle(ext.id, isEnabled)}
                      >
                        {isEnabled ? "Desabilitar" : "Habilitar"}
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </>
        )}
      </div>

      {/* Modal / Detail Popup com Recursos e Repositório */}
      {selectedExt && (
        <div className="ext-details-overlay" onClick={() => setSelectedExt(null)}>
          <div className="ext-details-modal" onClick={(e) => e.stopPropagation()}>
            <div className="ext-details-modal-header">
              <span className="ext-card-icon">{selectedExt.icon}</span>
              <div>
                <h4>{selectedExt.name}</h4>
                <div className="ext-card-publisher-row">
                  <span className={`ext-publisher-tag publisher-${selectedExt.publisher}`}>
                    {selectedExt.publisher}
                  </span>
                  <span className="ext-version-badge">v{selectedExt.version}</span>
                </div>
              </div>
              <button type="button" className="close-btn" onClick={() => setSelectedExt(null)}>
                ✕
              </button>
            </div>

            <div className="ext-details-modal-body">
              <p><strong>Descrição:</strong> {selectedExt.description}</p>
              <p><strong>Categoria:</strong> {selectedExt.category}</p>
              <p><strong>ID do Pacote:</strong> <code>{selectedExt.id}</code></p>
              {selectedExt.upstream_id && (
                <p><strong>Upstream Open VSX:</strong> <code>{selectedExt.upstream_id}</code></p>
              )}
              {selectedExt.downloads && (
                <p><strong>Estatísticas:</strong> ⬇️ {selectedExt.downloads} • ★ {selectedExt.rating || 4.9}</p>
              )}

              {selectedExt.features && selectedExt.features.length > 0 && (
                <div className="ext-features-section">
                  <h5>Recursos Principais</h5>
                  <ul>
                    {selectedExt.features.map((feat, idx) => (
                      <li key={idx}>✓ {feat}</li>
                    ))}
                  </ul>
                </div>
              )}

              {selectedExt.repository_url && (
                <div className="ext-repo-section">
                  <a
                    href={selectedExt.repository_url}
                    target="_blank"
                    rel="noreferrer"
                    className="ext-btn-repo-link"
                  >
                    🔗 Repositório Oficial no GitHub / Open VSX
                  </a>
                </div>
              )}

              <div className="ext-config-section">
                <h5>Configurações de Execução</h5>
                <label className="ext-checkbox-label">
                  <input type="checkbox" defaultChecked /> Autostart junto com a IDE
                </label>
                <label className="ext-checkbox-label">
                  <input type="checkbox" defaultChecked /> Auto-update com o marketplace upstream
                </label>
              </div>
            </div>

            <div className="ext-details-modal-footer">
              <button type="button" className="packages-btn-primary" onClick={() => setSelectedExt(null)}>
                Concluído
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="packages-footer">
        <span className="status-dot active" />
        <span>Suítes de Extensões & Auto-Update VS Code / Open VSX Conectados</span>
      </div>
    </div>
  );
}
