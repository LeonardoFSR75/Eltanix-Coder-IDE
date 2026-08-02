"use client";

// Nota: notas do Segundo Cérebro (Note), documentos de RAG (PDFDocument) e
// skills (Skill) saíram daqui — agora são dados reais, servidos por
// `lib/api/notes.ts`, `lib/api/documents.ts` e `lib/api/skills.ts`.

// Interface para Servidores MCP
export interface MCPServer {
  id: string;
  name: string;
  type: "stdio" | "sse";
  endpoint: string;
  status: "online" | "offline" | "connecting";
  latencyMs: number;
  toolsCount: number;
  resourcesCount: number;
  promptsCount: number;
  lastPing: string;
}

// Interface para Auditoria
export interface AuditLog {
  id: string;
  timestamp: string;
  actor: string;
  module: "RAG" | "MCP" | "Skills" | "SecondBrain" | "Auth" | "Settings" | "IDE";
  action: string;
  details: string;
  riskLevel: "low" | "medium" | "critical";
  ipAddress: string;
  status: "success" | "warning" | "denied";
}

// Chaves do localStorage
const KEYS = {
  MCP: "sicoobito_db_mcp",
  AUDIT: "sicoobito_db_audit",
};

// Dados padrão iniciais
const DEFAULT_MCP: MCPServer[] = [
  {
    id: "mcp-1",
    name: "Filesystem Local MCP",
    type: "stdio",
    endpoint: "npx -y @modelcontextprotocol/server-filesystem /workspace",
    status: "online",
    latencyMs: 12,
    toolsCount: 8,
    resourcesCount: 12,
    promptsCount: 4,
    lastPing: new Date().toISOString(),
  },
  {
    id: "mcp-2",
    name: "PostgreSQL Database MCP",
    type: "stdio",
    endpoint: "node dist/mcp-postgres.js --db=sicoobito",
    status: "online",
    latencyMs: 18,
    toolsCount: 6,
    resourcesCount: 15,
    promptsCount: 2,
    lastPing: new Date().toISOString(),
  },
  {
    id: "mcp-3",
    name: "ChromaDB Vector Gateway",
    type: "sse",
    endpoint: "http://127.0.0.1:8000/sse",
    status: "online",
    latencyMs: 25,
    toolsCount: 5,
    resourcesCount: 8,
    promptsCount: 3,
    lastPing: new Date().toISOString(),
  },
];

const DEFAULT_AUDIT: AuditLog[] = [
  {
    id: "audit-1",
    timestamp: new Date(Date.now() - 3600000 * 2).toISOString(),
    actor: "Engenheiro de IA (Leonardo)",
    module: "RAG",
    action: "Indexação de PDF no ChromaDB",
    details: "Arquivo Relatorio_Tecnico_IA_2026.pdf indexado em 142 chunks.",
    riskLevel: "low",
    ipAddress: "127.0.0.1",
    status: "success",
  },
  {
    id: "audit-2",
    timestamp: new Date(Date.now() - 3600000 * 1).toISOString(),
    actor: "Agente MCP Auto-Bot",
    module: "MCP",
    action: "Execução de ferramenta fs_write",
    details: "Gravado arquivo de configuração em /workspace/config.json.",
    riskLevel: "medium",
    ipAddress: "127.0.0.1",
    status: "success",
  },
  {
    id: "audit-3",
    timestamp: new Date(Date.now() - 1800000).toISOString(),
    actor: "Filtro de Segurança Guardrail",
    module: "Auth",
    action: "Bloqueio de Tentativa de Injeção de Prompt",
    details: "Detectado padrão 'Ignore todas as instruções anteriores' na requisição RAG.",
    riskLevel: "critical",
    ipAddress: "192.168.1.45",
    status: "denied",
  },
];

// Funções de acesso (Getter / Setter com fallback para dados padrão)
export const LocalDB = {
  getMCP(): MCPServer[] {
    if (typeof window === "undefined") return DEFAULT_MCP;
    const item = localStorage.getItem(KEYS.MCP);
    return item ? JSON.parse(item) : DEFAULT_MCP;
  },
  saveMCP(servers: MCPServer[]): void {
    if (typeof window !== "undefined") {
      localStorage.setItem(KEYS.MCP, JSON.stringify(servers));
    }
  },

  getAudit(): AuditLog[] {
    if (typeof window === "undefined") return DEFAULT_AUDIT;
    const item = localStorage.getItem(KEYS.AUDIT);
    return item ? JSON.parse(item) : DEFAULT_AUDIT;
  },
  saveAudit(logs: AuditLog[]): void {
    if (typeof window !== "undefined") {
      localStorage.setItem(KEYS.AUDIT, JSON.stringify(logs));
    }
  },
  addAuditLog(log: Omit<AuditLog, "id" | "timestamp">): AuditLog {
    const newLog: AuditLog = {
      ...log,
      id: `audit-${Date.now()}-${Math.random().toString(36).substring(2, 6)}`,
      timestamp: new Date().toISOString(),
    };
    const current = this.getAudit();
    const updated = [newLog, ...current];
    this.saveAudit(updated);
    return newLog;
  },
};
