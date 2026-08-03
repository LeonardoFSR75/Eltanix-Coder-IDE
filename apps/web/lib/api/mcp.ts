/**
 * Cliente real de servidores MCP — fala com `/api/mcp` no backend.
 *
 * Cada mutação (criar/editar/remover/alternar) reconecta os servidores no
 * backend e devolve a lista inteira já atualizada — não precisa de um
 * segundo round-trip para refletir o novo estado.
 */

import { del, get, post, put } from "@/lib/client";

export type MCPTransport = "stdio" | "http";
export type MCPStatus = "connected" | "connecting" | "disabled" | "error";

export interface MCPServerRecord {
  name: string;
  transport: MCPTransport;
  enabled: boolean;
  trust_annotations: boolean;
  command: string | null;
  args: string[];
  url: string | null;
  status: MCPStatus;
  error: string | null;
  tools_count: number;
}

export interface MCPServerInput {
  name: string;
  transport: MCPTransport;
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  url?: string;
  headers?: Record<string, string>;
  enabled: boolean;
  trust_annotations: boolean;
}

export interface MCPCatalogTemplate {
  id: string;
  label: string;
  description: string;
  transport: MCPTransport;
  command: string | null;
  args: string[];
  url: string | null;
  required_env: string[];
  required_args: string[];
  note: string;
}

export async function listMcpServers(): Promise<MCPServerRecord[]> {
  const { servers } = await get<{ servers: MCPServerRecord[] }>("/api/mcp/servers");
  return servers;
}

export async function listMcpCatalog(): Promise<MCPCatalogTemplate[]> {
  const { templates } = await get<{ templates: MCPCatalogTemplate[] }>("/api/mcp/catalog");
  return templates;
}

export async function createMcpServer(input: MCPServerInput): Promise<MCPServerRecord[]> {
  const { servers } = await post<{ servers: MCPServerRecord[] }>("/api/mcp/servers", input);
  return servers;
}

export async function updateMcpServer(
  name: string,
  input: MCPServerInput,
): Promise<MCPServerRecord[]> {
  const { servers } = await put<{ servers: MCPServerRecord[] }>(
    `/api/mcp/servers/${encodeURIComponent(name)}`,
    input,
  );
  return servers;
}

export async function toggleMcpServer(name: string): Promise<MCPServerRecord[]> {
  const { servers } = await post<{ servers: MCPServerRecord[] }>(
    `/api/mcp/servers/${encodeURIComponent(name)}/toggle`,
  );
  return servers;
}

export async function deleteMcpServer(name: string): Promise<MCPServerRecord[]> {
  const { servers } = await del<{ servers: MCPServerRecord[] }>(
    `/api/mcp/servers/${encodeURIComponent(name)}`,
  );
  return servers;
}
