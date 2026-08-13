/**
 * Cliente HTTP usado pela versão Svelte / Desktop.
 * Fala com a API do SicoobitoCode via API_ORIGIN e gerencia a autenticação por usuário e senha.
 */

const API_ORIGIN = import.meta.env.VITE_API_ORIGIN || "http://localhost:5401";

export class HttpError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "HttpError";
  }
}

export class MissingApiKeyError extends Error {
  constructor() {
    super("Sessão de usuário ou chave de API não configurada. Faça login.");
    this.name = "MissingApiKeyError";
  }
}

let onUnauthorizedHandler: (() => void) | null = null;

export function onUnauthorized(handler: () => void): void {
  onUnauthorizedHandler = handler;
}

export function getAuthToken(): string {
  if (typeof window === "undefined") return "";
  return (
    localStorage.getItem("sicoobito_session_token") ||
    localStorage.getItem("SICOOBITO_API_KEY") ||
    localStorage.getItem("sicoobito_api_key") ||
    (import.meta.env.VITE_SICOOBITO_API_KEY as string | undefined) ||
    ""
  );
}

export function hasAuthToken(): boolean {
  return getAuthToken().trim().length > 0;
}

export function setAuthToken(token: string): void {
  if (typeof window !== "undefined") {
    localStorage.setItem("sicoobito_session_token", token.trim());
    localStorage.setItem("SICOOBITO_API_KEY", token.trim());
  }
}

export function clearAuthToken(): void {
  if (typeof window !== "undefined") {
    localStorage.removeItem("sicoobito_session_token");
    localStorage.removeItem("SICOOBITO_API_KEY");
    localStorage.removeItem("sicoobito_api_key");
    localStorage.removeItem("sicoobito_user");
  }
}

export function getApiKey(): string {
  return getAuthToken();
}

export function hasApiKey(): boolean {
  return hasAuthToken();
}

export function setApiKey(key: string): void {
  setAuthToken(key);
}

export function clearApiKey(): void {
  clearAuthToken();
}

export interface UserProfile {
  id: string;
  username: string;
  display_name: string;
}

export function getAuthUser(): UserProfile | null {
  if (typeof window === "undefined") return null;
  const stored = localStorage.getItem("sicoobito_user");
  if (!stored) return null;
  try {
    return JSON.parse(stored) as UserProfile;
  } catch {
    return null;
  }
}

export async function login(username: string, password: string): Promise<boolean> {
  const url = `${API_ORIGIN}/api/auth/login`;
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ username, password }),
    });

    if (!res.ok) {
      return false;
    }

    const data = (await res.json()) as { token: string; expires_at: string };
    if (!data.token) return false;

    setAuthToken(data.token);

    // Tenta buscar informações do usuário conectado
    try {
      const meRes = await fetch(`${API_ORIGIN}/api/auth/me`, {
        headers: getHeaders(),
      });
      if (meRes.ok) {
        const me = (await meRes.json()) as UserProfile;
        localStorage.setItem("sicoobito_user", JSON.stringify(me));
      } else {
        localStorage.setItem(
          "sicoobito_user",
          JSON.stringify({ id: "user", username, display_name: username }),
        );
      }
    } catch {
      localStorage.setItem(
        "sicoobito_user",
        JSON.stringify({ id: "user", username, display_name: username }),
      );
    }

    return true;
  } catch (err) {
    console.error("Erro ao realizar login:", err);
    return false;
  }
}

export function logout(): void {
  clearAuthToken();
  if (onUnauthorizedHandler) {
    onUnauthorizedHandler();
  }
}

function getHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const token = getAuthToken();
  const headers: Record<string, string> = { ...extra };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  return headers;
}

function checkUnauthorized(status: number): void {
  if (status === 401 && onUnauthorizedHandler) {
    onUnauthorizedHandler();
  }
}

export async function get<T>(path: string): Promise<T> {
  const url = `${API_ORIGIN}${path}`;
  const response = await fetch(url, {
    headers: getHeaders(),
    cache: "no-store",
  });
  if (!response.ok) {
    checkUnauthorized(response.status);
    const errText = await describeError(response);
    console.warn(`[HTTP GET ERROR ${response.status}] ${url}:`, errText);
    throw new HttpError(errText, response.status);
  }
  return (await response.json()) as T;
}

export async function post<T>(path: string, body?: unknown): Promise<T> {
  const url = `${API_ORIGIN}${path}`;
  const response = await fetch(url, {
    method: "POST",
    headers: getHeaders({ "content-type": "application/json" }),
    body: JSON.stringify(body ?? {}),
  });
  if (!response.ok) {
    checkUnauthorized(response.status);
    const errText = await describeError(response);
    console.warn(`[HTTP POST ERROR ${response.status}] ${url}:`, errText);
    throw new HttpError(errText, response.status);
  }
  return (await response.json()) as T;
}

export async function put<T>(path: string, body: unknown): Promise<T> {
  const url = `${API_ORIGIN}${path}`;
  const response = await fetch(url, {
    method: "PUT",
    headers: getHeaders({ "content-type": "application/json" }),
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    checkUnauthorized(response.status);
    const errText = await describeError(response);
    console.warn(`[HTTP PUT ERROR ${response.status}] ${url}:`, errText);
    throw new HttpError(errText, response.status);
  }
  return (await response.json()) as T;
}

export async function patch<T>(path: string, body: unknown): Promise<T> {
  const url = `${API_ORIGIN}${path}`;
  const response = await fetch(url, {
    method: "PATCH",
    headers: getHeaders({ "content-type": "application/json" }),
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    checkUnauthorized(response.status);
    const errText = await describeError(response);
    console.warn(`[HTTP PATCH ERROR ${response.status}] ${url}:`, errText);
    throw new HttpError(errText, response.status);
  }
  return (await response.json()) as T;
}

export async function del<T>(path: string, body?: unknown): Promise<T> {
  const url = `${API_ORIGIN}${path}`;
  const response = await fetch(url, {
    method: "DELETE",
    headers: getHeaders(body ? { "content-type": "application/json" } : {}),
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    checkUnauthorized(response.status);
    const errText = await describeError(response);
    console.warn(`[HTTP DELETE ERROR ${response.status}] ${url}:`, errText);
    throw new HttpError(errText, response.status);
  }
  return (await response.json()) as T;
}

export async function streamEvents(
  path: string,
  body: unknown,
  onEvent: (event: unknown) => void,
  signal?: AbortSignal,
): Promise<void> {
  const url = `${API_ORIGIN}${path}`;
  const response = await fetch(url, {
    method: "POST",
    headers: getHeaders({ "content-type": "application/json" }),
    body: JSON.stringify(body ?? {}),
    signal,
  });

  if (!response.ok) {
    checkUnauthorized(response.status);
    throw new HttpError(await describeError(response), response.status);
  }
  if (!response.body) throw new Error("Resposta sem corpo.");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";

    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith("data:")) continue;
      const payload = line.slice(5).trim();
      if (payload === "[DONE]") return;
      try {
        onEvent(JSON.parse(payload));
      } catch {
        // Ignora evento corrompido
      }
    }
  }
}

async function describeError(response: Response): Promise<string> {
  try {
    const body = await response.json();
    const detail = body?.detail ?? body?.error;

    if (Array.isArray(detail) && detail.length > 0) {
      return detail
        .map((e: { msg?: string; loc?: string[] }) => {
          const field = e.loc?.filter((p) => p !== "body").join(".") ?? "";
          const msg = e.msg?.replace(/^Value error,\s*/i, "") ?? "erro de validação";
          return field ? `${field}: ${msg}` : msg;
        })
        .join(" | ");
    }

    if (typeof detail === "string") return detail;
    if (detail?.error?.message) return detail.error.message;
    return `${response.status} ${response.statusText}`;
  } catch {
    return `${response.status} ${response.statusText}`;
  }
}
