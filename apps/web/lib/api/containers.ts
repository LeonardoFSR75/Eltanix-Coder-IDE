/**
 * Cliente API de gerenciamento de Containers Docker (`/api/containers/*`).
 */

import { get, post } from "@/lib/client";

export interface ContainerItem {
  id: string;
  name: string;
  image: string;
  state: "running" | "exited" | "paused" | "restarting" | string;
  status: string;
  compose_project: string;
  ports: string[];
  created_at: string;
}

export interface ImageItem {
  id: string;
  name: string;
  tag: string;
  size: string;
}

export interface RegistryItem {
  name: string;
  url: string;
}

export interface NetworkItem {
  name: string;
  driver: string;
}

export interface VolumeItem {
  name: string;
  driver: string;
}

export interface ContextItem {
  name: string;
  current: boolean;
}

export interface HelpLinkItem {
  title: string;
  url: string;
}

export interface ContainerTreeResponse {
  connected: boolean;
  daemon_info?: { server_version: string };
  containers_by_project: Record<string, ContainerItem[]>;
  images: ImageItem[];
  registries: RegistryItem[];
  networks: NetworkItem[];
  volumes: VolumeItem[];
  contexts: ContextItem[];
  help_and_feedback: HelpLinkItem[];
}

export async function getContainerTree(): Promise<ContainerTreeResponse> {
  return get<ContainerTreeResponse>("/api/containers/tree");
}

export async function runContainerAction(
  containerId: string,
  action: "start" | "stop" | "restart" | "remove"
): Promise<{ ok: boolean; message?: string }> {
  return post<{ ok: boolean; message?: string }>(`/api/containers/${encodeURIComponent(containerId)}/action`, {
    action,
  });
}

export async function getContainerLogs(containerId: string): Promise<{ container_id: string; logs: string }> {
  return get<{ container_id: string; logs: string }>(`/api/containers/${encodeURIComponent(containerId)}/logs`);
}
