/**
 * Cliente real de skills — fala com `/api/skills` no backend.
 */

import { del, get, post, put } from "@/lib/client";

export type SkillCategory = "automation" | "analysis" | "code" | "web" | "database";

export interface SkillRecord {
  id: string;
  name: string;
  description: string;
  category: SkillCategory;
  system_prompt: string;
  parameters_json: string;
  enabled: boolean;
  usage_count: number;
  created_at: string;
  updated_at: string;
}

export interface SkillInput {
  name: string;
  description: string;
  category: SkillCategory;
  system_prompt: string;
  parameters_json: string;
}

export async function listSkills(): Promise<SkillRecord[]> {
  const { skills } = await get<{ skills: SkillRecord[] }>("/api/skills");
  return skills;
}

export async function createSkill(input: SkillInput): Promise<SkillRecord> {
  return post<SkillRecord>("/api/skills", input);
}

export async function updateSkill(skillId: string, input: SkillInput): Promise<SkillRecord> {
  return put<SkillRecord>(`/api/skills/${skillId}`, input);
}

export async function toggleSkill(skillId: string): Promise<SkillRecord> {
  return post<SkillRecord>(`/api/skills/${skillId}/toggle`);
}

export async function deleteSkill(skillId: string): Promise<void> {
  await del(`/api/skills/${skillId}`);
}
