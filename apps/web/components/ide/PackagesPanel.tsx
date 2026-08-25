"use client";

import { useCallback, useEffect, useState } from "react";
import {
  getProjectPackages,
  installProjectPackage,
  uninstallProjectPackage,
  syncProjectRequirements,
  resolvePackagesSyncStatus,
  type PackageItem,
} from "@/lib/api/packages";
import { useIde } from "@/lib/ide-store";
import { ConfirmDialog } from "@/components/ide/Overlays";
import { PanelState } from "@/components/ide/PanelState";

export function PackagesPanel() {
  const { project, openFile } = useIde();
  const [packages, setPackages] = useState<PackageItem[]>([]);
  const [reqMap, setReqMap] = useState<Record<string, string>>({});
  const [reqExists, setReqExists] = useState(false);
  const [venvExists, setVenvExists] = useState(false);
  const [manifestFile, setManifestFile] = useState("requirements.txt");
  const [loading, setLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [inputPkg, setInputPkg] = useState("");
  const [filterText, setFilterText] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [msgSuccess, setMsgSuccess] = useState<string | null>(null);
  const [requirementsContent, setRequirementsContent] = useState("");
  const [syncStatus, setSyncStatus] = useState<"ok" | "warning" | "idle">("idle");
  const [activeTab, setActiveTab] = useState<"packages" | "requirements">("packages");
  const [pkgToRemove, setPkgToRemove] = useState<string | null>(null);

  const normalizePackageName = useCallback((name: string) => name.trim().toLowerCase().replace(/[_\s]+/g, "-"), []);

  const carregar = useCallback(async () => {
    if (!project) return;
    setLoading(true);
    setErro(null);
    try {
      const data = await getProjectPackages(project);
      const normalizedReqMap = Object.fromEntries(
        Object.entries(data.requirements_map ?? {}).map(([name, version]) => [normalizePackageName(name), version])
      );
      setPackages(data.packages);
      setReqMap(normalizedReqMap);
      setReqExists(data.requirements_exists);
      setVenvExists(data.venv_exists);
      setRequirementsContent(data.requirements_content ?? "");
      setSyncStatus(resolvePackagesSyncStatus(data.packages, data.requirements_map ?? {}));
      if (data.manifest_file) setManifestFile(data.manifest_file);
    } catch (err) {
      setErro(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [project]);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  // Refresco automático quando o agente instala/remove/sincroniza pacotes
  // via `manage_packages` (evento disparado por `sessionRuntime.ts` ao ver
  // essa tool no stream SSE) — sem isto o painel só atualiza no F5 mesmo
  // depois de uma ação do agente ter mudado o venv/requirements.txt.
  useEffect(() => {
    const handlePackagesChanged = () => void carregar();
    window.addEventListener("eltanix:packages:changed", handlePackagesChanged);
    return () => window.removeEventListener("eltanix:packages:changed", handlePackagesChanged);
  }, [carregar]);

  // Dispara o mesmo evento que `sessionRuntime.ts` usa quando o agente mexe
  // em pacotes, para que o indicador na StatusBar (que também escuta esse
  // evento) reflita imediatamente uma ação feita aqui pelo próprio usuário.
  const notifyPackagesChanged = () => {
    window.dispatchEvent(new CustomEvent("eltanix:packages:changed"));
  };

  const handleInstall = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!project || !inputPkg.trim() || actionLoading) return;

    const target = inputPkg.trim();
    setActionLoading(`Instalando ${target}...`);
    setErro(null);
    setMsgSuccess(null);
    try {
      const res = await installProjectPackage(project, target, true);
      setInputPkg("");
      setSyncStatus("ok");
      setMsgSuccess(`Pacote '${res.package}' instalado e gravado em ${manifestFile}!`);
      await carregar();
      notifyPackagesChanged();
    } catch (err) {
      setErro(err instanceof Error ? err.message : String(err));
    } finally {
      setActionLoading(null);
    }
  };

  const handleUninstall = async (pkgName: string) => {
    if (!project || actionLoading) return;
    setActionLoading(`Desinstalando ${pkgName}...`);
    setErro(null);
    setMsgSuccess(null);
    try {
      await uninstallProjectPackage(project, pkgName, true);
      setSyncStatus("ok");
      setMsgSuccess(`Pacote '${pkgName}' removido e atualizado em ${manifestFile}!`);
      await carregar();
      notifyPackagesChanged();
    } catch (err) {
      setErro(err instanceof Error ? err.message : String(err));
    } finally {
      setActionLoading(null);
    }
  };

  const handleSync = async () => {
    if (!project || actionLoading) return;
    setActionLoading(`Exportando .venv para ${manifestFile}...`);
    setErro(null);
    setMsgSuccess(null);
    try {
      const res = await syncProjectRequirements(project);
      setSyncStatus("ok");
      setMsgSuccess(res.message || `Ambiente exportado para ${manifestFile}!`);
      await carregar();
      notifyPackagesChanged();
    } catch (err) {
      setErro(err instanceof Error ? err.message : String(err));
    } finally {
      setActionLoading(null);
    }
  };

  const filtrados = packages.filter(
    (p) =>
      p.name.toLowerCase().includes(filterText.toLowerCase()) ||
      p.version.toLowerCase().includes(filterText.toLowerCase())
  );

  return (
    <div className="panel-body packages-panel-body">
      <div className="panel-header">
        <div className="panel-header-title-group">
          <span className="panel-header-title">📦 Pacotes do Projeto</span>
          <span className="packages-count-badge">{packages.length}</span>
        </div>
        <div className="panel-actions-bar">
          <button
            type="button"
            className="icon-action-btn"
            title="Recarregar pacotes"
            onClick={() => void carregar()}
            disabled={loading}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21.5 2v6h-6M2.5 22v-6h6" />
              <path d="M2 11.5a10 10 0 0 1 18.8-4.3L21.5 8M22 12.5a10 10 0 0 1-18.8 4.2L2.5 16" />
            </svg>
          </button>
          <button
            type="button"
            className="icon-action-btn"
            title={`Abrir ${manifestFile} no editor`}
            onClick={() => openFile(manifestFile)}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <line x1="16" y1="13" x2="8" y2="13" />
              <line x1="16" y1="17" x2="8" y2="17" />
            </svg>
          </button>
        </div>
      </div>

      <div
        className="packages-section-install"
        style={{
          padding: "4px 6px",
          background: "rgba(15, 23, 42, 0.18)",
          borderRadius: "8px",
          border: "1px solid rgba(148, 163, 184, 0.14)",
          margin: "6px 12px 0",
        }}
      >
        <form onSubmit={handleInstall} className="packages-form-row" style={{ gap: "4px" }}>
          <input
            type="text"
            className="packages-input"
            placeholder="Pacote..."
            value={inputPkg}
            onChange={(e) => setInputPkg(e.target.value)}
            disabled={!!actionLoading}
            style={{
              background: "rgba(15, 23, 42, 0.8)",
              border: "1px solid rgba(148, 163, 184, 0.2)",
              color: "#e5edf9",
              minHeight: "26px",
              fontSize: "12px",
            }}
          />
          <button
            type="submit"
            className="packages-btn-primary"
            disabled={!inputPkg.trim() || !!actionLoading}
            style={{
              minWidth: "74px",
              minHeight: "26px",
              borderRadius: "6px",
              fontWeight: 700,
              padding: "0 8px",
              fontSize: "11px",
            }}
          >
            {actionLoading ? "…" : "Instalar"}
          </button>
        </form>

        <button
          type="button"
          onClick={() => void handleSync()}
          disabled={!!actionLoading || !venvExists}
          className="packages-btn-sync"
          title={`Exportar o ambiente do projeto para ${manifestFile}`}
          style={{
            width: "100%",
            marginTop: "4px",
            minHeight: "26px",
            borderRadius: "6px",
            fontWeight: 700,
            padding: "0 8px",
            fontSize: "11px",
          }}
        >
          🔄 Sync
        </button>
      </div>

      {actionLoading && (
        <div className="packages-status-loading">
          <span className="spin-icon">⏳</span>
          <span>{actionLoading}</span>
        </div>
      )}

      {erro && <div className="panel-error">{erro}</div>}
      {msgSuccess && (
        <div
          style={{
            margin: "8px 12px 0",
            padding: "8px 10px",
            borderRadius: "10px",
            background: "rgba(34, 197, 94, 0.12)",
            border: "1px solid rgba(34, 197, 94, 0.3)",
            color: "#c8f7d3",
            fontSize: "11px",
            fontWeight: 600,
          }}
        >
          {msgSuccess}
        </div>
      )}

      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "5px",
          margin: "6px 12px 0",
          padding: "4px 7px",
          borderRadius: "7px",
          border:
            syncStatus === "warning"
              ? "1px solid rgba(245, 158, 11, 0.4)"
              : "1px solid rgba(148, 163, 184, 0.22)",
          background:
            syncStatus === "warning"
              ? "rgba(245, 158, 11, 0.10)"
              : syncStatus === "ok"
                ? "rgba(34, 197, 94, 0.10)"
                : "rgba(148, 163, 184, 0.06)",
          color: syncStatus === "warning" ? "#f9d58f" : syncStatus === "ok" ? "#baf7cc" : "#d7deea",
          fontSize: "10px",
          fontWeight: 700,
        }}
      >
        <span style={{ fontSize: "10px" }}>
          {syncStatus === "warning" ? "⚠️" : syncStatus === "ok" ? "✅" : "ℹ️"}
        </span>
        <span>
          {syncStatus === "warning"
            ? "Fora do req"
            : syncStatus === "ok"
              ? "Sincronizado"
              : "Sem pacotes"}
        </span>
      </div>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "4px",
          margin: "6px 12px 0",
          padding: "3px",
          borderRadius: "8px",
          background: "rgba(15, 23, 42, 0.42)",
          border: "1px solid rgba(148, 163, 184, 0.18)",
        }}
      >
        {([
          { key: "packages", label: "Pacotes" },
          { key: "requirements", label: "Requirements" },
        ] as const).map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setActiveTab(tab.key)}
            style={{
              flex: 1,
              border: 0,
              borderRadius: "6px",
              padding: "6px 6px",
              background: activeTab === tab.key ? "rgba(96, 165, 250, 0.18)" : "transparent",
              color: activeTab === tab.key ? "#e2ecff" : "#b3bfd3",
              cursor: "pointer",
              fontSize: "10px",
              fontWeight: 700,
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "requirements" ? (
        requirementsContent ? (
          <div
            style={{
              margin: "8px 12px 0",
              padding: "8px 10px",
              borderRadius: "8px",
              border: "1px solid rgba(148, 163, 184, 0.18)",
              background: "rgba(15, 23, 42, 0.72)",
              maxHeight: "140px",
              overflow: "auto",
            }}
          >
            <div
              style={{
                fontSize: "10px",
                fontWeight: 700,
                marginBottom: "6px",
                color: "#a9b7d0",
                letterSpacing: "0.04em",
                textTransform: "uppercase",
              }}
            >
              {manifestFile}
            </div>
            <pre
              style={{
                margin: 0,
                whiteSpace: "pre-wrap",
                fontSize: "11px",
                lineHeight: "1.5",
                color: "#dfe9f7",
                fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
              }}
            >
              {requirementsContent.trim()}
            </pre>
          </div>
        ) : (
          <PanelState kind="empty" icon="📄" message={`Nenhum conteúdo em ${manifestFile}.`} />
        )
      ) : (
        <>
          <div className="packages-filter-box">
            <input
              type="text"
              className="packages-input-filter"
              placeholder="Filtrar pacotes instalados..."
              value={filterText}
              onChange={(e) => setFilterText(e.target.value)}
            />
          </div>

          <div className="packages-list-scroll">
            {loading ? (
              <PanelState kind="loading" message="Carregando ambiente virtual do projeto..." />
            ) : filtrados.length === 0 ? (
              <PanelState
                kind="empty"
                icon={packages.length === 0 ? "📦" : "🔍"}
                message={
                  packages.length === 0
                    ? "Nenhum pacote instalado no .venv do projeto ainda. Digite o nome do pacote acima para instalar!"
                    : "Nenhum pacote encontrado com este filtro."
                }
              />
            ) : (
              <div className="packages-items-grid">
                {filtrados.map((pkg) => {
                  const normName = normalizePackageName(pkg.name);
                  const inReq = reqMap[normName] !== undefined || Object.keys(reqMap).some((key) => normalizePackageName(key) === normName);
                  return (
                    <div key={pkg.name} className="package-item-card">
                      <div className="package-item-info">
                        <div className="package-item-title-row">
                          <span className="package-item-name">{pkg.name}</span>
                          {inReq && <span className="package-req-tag">req.txt</span>}
                        </div>
                        <span className="package-item-version">v{pkg.version}</span>
                      </div>
                      <button
                        type="button"
                        className="icon-action-btn danger"
                        title={`Desinstalar ${pkg.name}`}
                        onClick={() => setPkgToRemove(pkg.name)}
                        disabled={!!actionLoading}
                      >
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <polyline points="3 6 5 6 21 6" />
                          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                        </svg>
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </>
      )}

      <div className="packages-footer">
        <span className={`status-dot ${venvExists ? "active" : ""}`} />
        <span>
          {venvExists
            ? "Ambiente .venv ativado e persistente no projeto"
            : "O .venv será criado automaticamente na 1ª instalação"}
        </span>
      </div>

      {pkgToRemove && (
        <ConfirmDialog
          danger
          message={`Desinstalar o pacote '${pkgToRemove}' do ambiente do projeto?`}
          onConfirm={() => void handleUninstall(pkgToRemove)}
          onClose={() => setPkgToRemove(null)}
        />
      )}
    </div>
  );
}
