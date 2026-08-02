"use client";

// Interface para dados do Segundo Cérebro (Obsidian style)
export interface Note {
  id: string;
  title: string;
  content: string;
  tags: string[];
  links: string[]; // IDs de outras notas ligadas via [[wikilink]]
  createdAt: string;
  updatedAt: string;
}

// Interface para PDFs e RAG no ChromaDB
export interface PDFDocument {
  id: string;
  filename: string;
  sizeBytes: number;
  uploadedAt: string;
  pageCount: number;
  chunkCount: number;
  chromaCollection: string;
  rawText: string;
}

// Interface para Skills
export interface Skill {
  id: string;
  name: string;
  description: string;
  category: "automation" | "analysis" | "code" | "web" | "database";
  systemPrompt: string;
  parametersJson: string;
  enabled: boolean;
  usageCount: number;
}

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
  module: "RAG" | "MCP" | "Skills" | "SecondBrain" | "Neural" | "Auth" | "Settings" | "IDE";
  action: string;
  details: string;
  riskLevel: "low" | "medium" | "critical";
  ipAddress: string;
  status: "success" | "warning" | "denied";
}

// Interface para Modelos de Rede Neural
export interface NeuralModel {
  id: string;
  name: string;
  architecture: {
    inputNodes: number;
    hiddenLayers: number[];
    outputNodes: number;
    activation: "relu" | "sigmoid" | "tanh" | "softmax";
  };
  accuracy: number;
  epochsTrained: number;
  savedAt: string;
}

// Interface para Configurações Globais
export interface SystemSettings {
  chromaHost: string;
  chromaPort: number;
  dbType: "postgresql" | "sqlite" | "local_storage";
  dbConnectionString: string;
  defaultEmbeddingModel: string;
  ragChunkSize: number;
  ragChunkOverlap: number;
  theme: "dark" | "light";
  auditLoggingEnabled: boolean;
  maxTokensPerRequest: number;
}

// Chaves do localStorage
const KEYS = {
  NOTES: "sicoobito_db_notes",
  PDFS: "sicoobito_db_pdfs",
  SKILLS: "sicoobito_db_skills",
  MCP: "sicoobito_db_mcp",
  AUDIT: "sicoobito_db_audit",
  NEURAL: "sicoobito_db_neural",
  SETTINGS: "sicoobito_db_settings",
};

// Dados padrão iniciais
const DEFAULT_NOTES: Note[] = [
  {
    id: "note-1",
    title: "Arquitetura do SicoobitoCode",
    content: "O SicoobitoCode é uma plataforma local-first combinando RAG com [[ChromaDB]], visualização de [[Redes Neurais]], e uma infraestrutura flexível de [[MCP]] e [[Skills]].",
    tags: ["#arquitetura", "#sicoobito", "#ia"],
    links: ["note-2", "note-3"],
    createdAt: new Date(Date.now() - 86400000 * 3).toISOString(),
    updatedAt: new Date(Date.now() - 86400000 * 1).toISOString(),
  },
  {
    id: "note-2",
    title: "Visão Geral do ChromaDB",
    content: "O [[ChromaDB]] gerencia os embeddings dos PDFs armazenados. Cada PDF é fatiado em chunks de 512 tokens com sobreposição de 64 tokens para otimizar busca semântica em [[RAG]].",
    tags: ["#chromadb", "#rag", "#vetores"],
    links: ["note-1"],
    createdAt: new Date(Date.now() - 86400000 * 2).toISOString(),
    updatedAt: new Date(Date.now() - 3600000 * 5).toISOString(),
  },
  {
    id: "note-3",
    title: "Protocolo MCP e Ferramentas",
    content: "Os servidores [[MCP]] expõem rotinas executáveis diretamente para agentes de IA através dos protocolos STDIO e SSE. Integra-se perfeitamente com o catálogo de [[Skills]].",
    tags: ["#mcp", "#skills", "#agentes"],
    links: ["note-1"],
    createdAt: new Date(Date.now() - 86400000 * 1).toISOString(),
    updatedAt: new Date(Date.now() - 1800000).toISOString(),
  },
];

const DEFAULT_PDFS: PDFDocument[] = [
  {
    id: "pdf-1",
    filename: "Relatorio_Tecnico_IA_2026.pdf",
    sizeBytes: 2458900,
    uploadedAt: new Date(Date.now() - 86400000 * 2).toISOString(),
    pageCount: 18,
    chunkCount: 142,
    chromaCollection: "relatorios_tecnicos",
    rawText: "Este documento aborda a implementação de agentes autônomos locais, uso de ChromaDB para busca semântica em documentos confidenciais e auditoria de segurança.",
  },
  {
    id: "pdf-2",
    filename: "Manual_Protocolo_MCP_v2.pdf",
    sizeBytes: 1120400,
    uploadedAt: new Date(Date.now() - 86400000 * 1).toISOString(),
    pageCount: 9,
    chunkCount: 68,
    chromaCollection: "mcp_docs",
    rawText: "Especificação do Model Context Protocol (MCP): suporte a JSON-RPC 2.0, streaming SSE, transporte STDIO e controle de permissões por agente.",
  },
];

const DEFAULT_SKILLS: Skill[] = [
  {
    id: "skill-1",
    name: "Extrator de Texto PDF & OCR",
    description: "Extrai texto estruturado de PDFs e executa OCR em imagens digitalizadas antes do fatiamento para ChromaDB.",
    category: "automation",
    systemPrompt: "Você é um especialista em OCR. Processe o documento e converta o layout em Markdown mantendo tabelas e títulos.",
    parametersJson: '{\n  "targetCollection": "string",\n  "maxPages": "number"\n}',
    enabled: true,
    usageCount: 42,
  },
  {
    id: "skill-2",
    name: "Consultor de SQL para Postgres",
    description: "Gera consultas SQL otimizadas e seguras para a base PostgreSQL do Sicoobito, prevenindo SQL Injection.",
    category: "database",
    systemPrompt: "Escreva apenas queries SQL ANSI compatíveis com PostgreSQL 17 e pgvector.",
    parametersJson: '{\n  "queryIntent": "string",\n  "schema": "string"\n}',
    enabled: true,
    usageCount: 128,
  },
  {
    id: "skill-3",
    name: "Sintetizador RAG com Citações",
    description: "Busca trechos no ChromaDB e redige respostas técnicas acompanhadas de referências de página exatas.",
    category: "analysis",
    systemPrompt: "Formate as respostas usando Markdown e adicione citações [Doc X - Pág Y] ao final de cada parágrafo.",
    parametersJson: '{\n  "userPrompt": "string",\n  "topK": "number"\n}',
    enabled: true,
    usageCount: 89,
  },
];

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

const DEFAULT_NEURAL: NeuralModel[] = [
  {
    id: "model-1",
    name: "Classificador de Relevância RAG",
    architecture: {
      inputNodes: 128,
      hiddenLayers: [64, 32],
      outputNodes: 2,
      activation: "relu",
    },
    accuracy: 94.8,
    epochsTrained: 50,
    savedAt: new Date(Date.now() - 86400000 * 1).toISOString(),
  },
  {
    id: "model-2",
    name: "Mapeador de Atenção LLM",
    architecture: {
      inputNodes: 512,
      hiddenLayers: [256, 128, 64],
      outputNodes: 16,
      activation: "tanh",
    },
    accuracy: 98.2,
    epochsTrained: 120,
    savedAt: new Date(Date.now() - 3600000 * 6).toISOString(),
  },
];

const DEFAULT_SETTINGS: SystemSettings = {
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
};

// Funções de acesso (Getter / Setter com fallback para dados padrão)
export const LocalDB = {
  getNotes(): Note[] {
    if (typeof window === "undefined") return DEFAULT_NOTES;
    const item = localStorage.getItem(KEYS.NOTES);
    return item ? JSON.parse(item) : DEFAULT_NOTES;
  },
  saveNotes(notes: Note[]): void {
    if (typeof window !== "undefined") {
      localStorage.setItem(KEYS.NOTES, JSON.stringify(notes));
    }
  },

  getPDFs(): PDFDocument[] {
    if (typeof window === "undefined") return DEFAULT_PDFS;
    const item = localStorage.getItem(KEYS.PDFS);
    return item ? JSON.parse(item) : DEFAULT_PDFS;
  },
  savePDFs(pdfs: PDFDocument[]): void {
    if (typeof window !== "undefined") {
      localStorage.setItem(KEYS.PDFS, JSON.stringify(pdfs));
    }
  },

  getSkills(): Skill[] {
    if (typeof window === "undefined") return DEFAULT_SKILLS;
    const item = localStorage.getItem(KEYS.SKILLS);
    return item ? JSON.parse(item) : DEFAULT_SKILLS;
  },
  saveSkills(skills: Skill[]): void {
    if (typeof window !== "undefined") {
      localStorage.setItem(KEYS.SKILLS, JSON.stringify(skills));
    }
  },

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

  getNeuralModels(): NeuralModel[] {
    if (typeof window === "undefined") return DEFAULT_NEURAL;
    const item = localStorage.getItem(KEYS.NEURAL);
    return item ? JSON.parse(item) : DEFAULT_NEURAL;
  },
  saveNeuralModels(models: NeuralModel[]): void {
    if (typeof window !== "undefined") {
      localStorage.setItem(KEYS.NEURAL, JSON.stringify(models));
    }
  },

  getSettings(): SystemSettings {
    if (typeof window === "undefined") return DEFAULT_SETTINGS;
    const item = localStorage.getItem(KEYS.SETTINGS);
    return item ? JSON.parse(item) : DEFAULT_SETTINGS;
  },
  saveSettings(settings: SystemSettings): void {
    if (typeof window !== "undefined") {
      localStorage.setItem(KEYS.SETTINGS, JSON.stringify(settings));
    }
  },
};
