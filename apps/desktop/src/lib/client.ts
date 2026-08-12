/**
 * Cliente HTTP usado pela versão Svelte / Desktop.
 * Fala com a API do SicoobitoCode via API_ORIGIN ou proxy de dev/preview.
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

/**
 * Erro lançado quando nenhuma SICOOBITO_API_KEY foi configurada — nem via
 * `VITE_SICOOBITO_API_KEY` (build/preview via Docker), nem digitada pelo usuário
 * e salva no `localStorage`. Diferente de `HttpError`: não veio do servidor,
 * então não faz sentido tentar de novo sem antes pedir a chave.
 *
 * Não existe fallback fixo aqui de propósito — um app empacotado via Tauri e
 * distribuído carrega qualquer valor hardcoded para fora da máquina de quem
 * o gerou. Sem chave configurada, o app deve pedir, nunca inventar uma.
 */
export class MissingApiKeyError extends Error {
  constructor() {
    super("Nenhuma SICOOBITO_API_KEY configurada. Configure em Configurações.");
    this.name = "MissingApiKeyError";
  }
}

export function getApiKey(): string {
  if (typeof window === "undefined") return "";
  return (
    localStorage.getItem("SICOOBITO_API_KEY") ||
    localStorage.getItem("sicoobito_api_key") ||
    (import.meta.env.VITE_SICOOBITO_API_KEY as string | undefined) ||
    ""
  );
}

export function hasApiKey(): boolean {
  return getApiKey().trim().length > 0;
}

export function setApiKey(key: string): void {
  if (typeof window !== "undefined") {
    localStorage.setItem("SICOOBITO_API_KEY", key.trim());
  }
}

export function clearApiKey(): void {
  if (typeof window !== "undefined") {
    localStorage.removeItem("SICOOBITO_API_KEY");
    localStorage.removeItem("sicoobito_api_key");
  }
}

function getHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const apiKey = getApiKey();
  const headers: Record<string, string> = { ...extra };
  if (apiKey) {
    headers["Authorization"] = `Bearer ${apiKey}`;
  }
  return headers;
}

export async function get<T>(path: string): Promise<T> {
  const url = `${API_ORIGIN}${path}`;
  const response = await fetch(url, {
    headers: getHeaders(),
    cache: "no-store",
  });
  if (!response.ok) {
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

  if (!response.ok) throw new HttpError(await describeError(response), response.status);
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
