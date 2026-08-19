"use client";

import { ToolCardShell } from "./ToolCardShell";
import type { ToolCardProps } from "./types";

interface InstalledPackage {
  name: string;
  version: string;
}

interface Vulnerability {
  package?: string;
  id?: string;
  severity?: string;
  fix_versions?: string[];
  fix_available?: boolean;
}

type PackagesAction = "list" | "install" | "uninstall" | "sync" | "audit" | "clean";

// `manage_packages` é uma única ferramenta com 6 ações — ao contrário de
// `read_file`/`write_file` (uma ferramenta por ação), o card recebe sempre o
// mesmo `tool` e precisa inferir a ação pela forma do `data` devolvido (ver
// `agent/tools/packages.py`, cada `return ToolResult(...)` tem um shape
// diferente). Falhas zeram `data` (`ToolResult.failure`), então a inferência
// só roda no caminho de sucesso — falha usa sempre o ícone/risco genérico.
function inferAction(data: Record<string, unknown>): PackagesAction {
  if ("packages" in data && "installed_count" in data) return "list";
  if ("vulnerabilities" in data || "supported" in data) return "audit";
  if ("removed_packages" in data) return "clean";
  if ("version" in data && "package" in data) return "install";
  if ("package" in data) return "uninstall";
  return "sync";
}

const ICON: Record<PackagesAction, string> = {
  list: "📋",
  install: "⬇️",
  uninstall: "🗑️",
  sync: "🔄",
  audit: "🛡️",
  clean: "🧹",
};

// Espelha `_packages_risk` em `agent/tools/packages.py`: list/audit são
// RiskClass.READ (baixo risco, sem aprovação), o resto é WRITE.
const RISK: Record<PackagesAction, "low" | "medium"> = {
  list: "low",
  audit: "low",
  install: "medium",
  uninstall: "medium",
  sync: "medium",
  clean: "medium",
};

function titleFor(action: PackagesAction, data: Record<string, unknown>): string {
  switch (action) {
    case "list":
      return `pacotes (${String(data.ecosystem ?? "?")})`;
    case "install": {
      const version = data.version ? `@${data.version}` : "";
      return `instalar ${String(data.package ?? "?")}${version}`;
    }
    case "uninstall":
      return `desinstalar ${String(data.package ?? "?")}`;
    case "sync":
      return "sincronizar pacotes";
    case "audit":
      return `auditoria de CVE${data.tool ? ` (${data.tool})` : ""}`;
    case "clean":
      return "limpar pacotes órfãos";
  }
}

function metaFor(action: PackagesAction, data: Record<string, unknown>): string | undefined {
  switch (action) {
    case "list":
      return `${data.installed_count ?? 0} instalado(s)`;
    case "audit":
      if (data.supported === false) return "não suportado";
      if (data.tool_available === false) return "ferramenta ausente";
      return `${(data as { count?: number }).count ?? 0} vulnerabilidade(s)`;
    case "clean":
      return `${(data as { removed_count?: number }).removed_count ?? 0} removido(s)`;
    case "install":
    case "uninstall":
      return data.requirements_updated ? "manifesto atualizado" : undefined;
    default:
      return undefined;
  }
}

function PackagesListBody({ data }: { data: Record<string, unknown> }) {
  const packages = (data.packages as InstalledPackage[] | undefined) ?? [];
  if (packages.length === 0) return <pre className="tool-card-pre">Nenhum pacote instalado.</pre>;
  return (
    <ul className="tool-card-list">
      {packages.map((p) => (
        <li key={p.name}>
          {p.name} == {p.version}
        </li>
      ))}
    </ul>
  );
}

function AuditBody({ data, content }: { data: Record<string, unknown>; content: string }) {
  const vulns = (data.vulnerabilities as Vulnerability[] | undefined) ?? [];
  if (data.supported === false || data.tool_available === false || vulns.length === 0) {
    return <pre className="tool-card-pre">{content}</pre>;
  }
  return (
    <ul className="tool-card-list">
      {vulns.map((v, i) => (
        <li key={`${v.package}-${v.id ?? i}`}>
          {v.package}: {v.id ?? v.severity ?? "N/A"}
          {v.fix_versions && v.fix_versions.length > 0 && ` (corrige em ${v.fix_versions.join(", ")})`}
        </li>
      ))}
    </ul>
  );
}

function CleanBody({ data, content }: { data: Record<string, unknown>; content: string }) {
  const removed = (data.removed_packages as string[] | undefined) ?? [];
  if (removed.length === 0) return <pre className="tool-card-pre">{content}</pre>;
  return (
    <ul className="tool-card-list">
      {removed.map((name) => (
        <li key={name}>{name}</li>
      ))}
    </ul>
  );
}

export function PackagesCard({ content, data, ok }: ToolCardProps) {
  if (!ok) {
    return (
      <ToolCardShell icon="📦" title="pacotes — falhou" ok={false} defaultOpen>
        <pre className="tool-card-pre">{content}</pre>
      </ToolCardShell>
    );
  }

  const action = inferAction(data);

  return (
    <ToolCardShell
      icon={ICON[action]}
      title={titleFor(action, data)}
      meta={metaFor(action, data)}
      riskLevel={RISK[action]}
      ok={ok}
    >
      {action === "list" && <PackagesListBody data={data} />}
      {action === "audit" && <AuditBody data={data} content={content} />}
      {action === "clean" && <CleanBody data={data} content={content} />}
      {(action === "install" || action === "uninstall" || action === "sync") && (
        <pre className="tool-card-pre">{content}</pre>
      )}
    </ToolCardShell>
  );
}
