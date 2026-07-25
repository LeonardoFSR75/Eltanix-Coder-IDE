/**
 * Proxy autenticado para o backend.
 *
 * O IDE precisa de interatividade no cliente (Monaco, SSE do agente), mas a
 * chave da API não pode chegar ao browser. Toda chamada do cliente passa por
 * aqui, e é o servidor Next que anexa a credencial.
 *
 * Respostas de streaming são repassadas sem bufferizar — o agente emite eventos
 * ao longo de minutos, e acumulá-los destruiria a razão de existir do stream.
 */

const BASE_URL = process.env.SICOOBITO_API_URL ?? "http://localhost:8000";
const API_KEY = process.env.SICOOBITO_API_KEY ?? "";

type Params = { params: Promise<{ path: string[] }> };

async function proxy(request: Request, { params }: Params): Promise<Response> {
  const { path } = await params;
  const url = new URL(request.url);
  const target = `${BASE_URL}/${path.join("/")}${url.search}`;

  const headers = new Headers();
  if (API_KEY) headers.set("Authorization", `Bearer ${API_KEY}`);
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  // Identifica a origem no dashboard de custo, separando o IDE das ferramentas
  // externas que também apontam para o gateway.
  headers.set("X-Sicoobito-Source", "ide");

  const init: RequestInit = { method: request.method, headers };
  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = await request.text();
  }

  let upstream: Response;
  try {
    upstream = await fetch(target, init);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return Response.json(
      { error: `Backend inacessível em ${BASE_URL}: ${message}` },
      { status: 502 },
    );
  }

  const responseHeaders = new Headers();
  const upstreamType = upstream.headers.get("content-type");
  if (upstreamType) responseHeaders.set("content-type", upstreamType);

  if (upstreamType?.includes("text/event-stream")) {
    responseHeaders.set("cache-control", "no-cache");
    responseHeaders.set("connection", "keep-alive");
    responseHeaders.set("x-accel-buffering", "no");
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const DELETE = proxy;
export const PATCH = proxy;

// Streaming do agente pode durar minutos; o padrão do Next cortaria antes.
export const maxDuration = 600;
export const dynamic = "force-dynamic";
