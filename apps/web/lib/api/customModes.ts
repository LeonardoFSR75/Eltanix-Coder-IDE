/**
 * Modos customizáveis pelo usuário (Fase 6 do upgrade do agente) — fala com
 * `/api/agent/custom-modes`.
 *
 * Um modo customizado é identificado pelo próprio `id` (UUID em string) —
 * `setMode(id)` funciona igual a `setMode("agent")`: o backend resolve o que
 * não é um dos 7 modos embutidos como id de modo customizado
 * (`agent/state.py::BUILTIN_MODES`).
 */

import { del, get, post, put } from "@/lib/client";

export interface CustomMode {
  id: string;
  name: string;
  icon: string;
  description: string;
  allowed_tools: string[];
  prompt_block: string;
  created_at: string;
  updated_at: string;
}

export interface CustomModeInput {
  name: string;
  icon: string;
  description: string;
  allowed_tools: string[];
  prompt_block: string;
}

export async function listCustomModes(): Promise<CustomMode[]> {
  const { modes } = await get<{ modes: CustomMode[] }>("/api/agent/custom-modes");
  return modes;
}

export function createCustomMode(input: CustomModeInput): Promise<CustomMode> {
  return post<CustomMode>("/api/agent/custom-modes", input);
}

export function updateCustomMode(id: string, input: CustomModeInput): Promise<CustomMode> {
  return put<CustomMode>(`/api/agent/custom-modes/${encodeURIComponent(id)}`, input);
}

export function deleteCustomMode(id: string): Promise<{ deleted: boolean }> {
  return del<{ deleted: boolean }>(`/api/agent/custom-modes/${encodeURIComponent(id)}`);
}

export function newCustomMode(): CustomModeInput {
  return { name: "", icon: "🧩", description: "", allowed_tools: [], prompt_block: "" };
}
