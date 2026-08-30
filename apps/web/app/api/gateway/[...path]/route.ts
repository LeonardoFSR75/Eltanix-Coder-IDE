/**
 * Proxy autenticado para o backend.
 *
 * O IDE precisa de interatividade no cliente (Monaco, SSE do agente). Toda
 * chamada do cliente passa por aqui.
 *
 * A UI web autentica por SESSÃO (cookie httpOnly `eltanix_session`, ver
 * `app/api/session/route.ts`), nunca pela `ELTANIX_API_KEY` do ambiente —
 * de propósito: essa chave é um segredo de servidor-para-servidor para
 * integrações externas (CI, cline, cursor, aider), e anexá-la automaticamente
 * em toda chamada do browser tornaria o login opcional na prática, por mais
 * que o backend exija sessão (`require_session`). Só repassamos a credencial
 * que o PRÓPRIO cliente mandou explicitamente — nunca inventamos uma.
 *
 * Respostas de streaming são repassadas sem bufferizar — o agente emite eventos
 * ao longo de minutos, e acumulá-los destruiria a razão de existir do stream.
 */

const BASE_URL = process.env.ELTANIX_API_URL ?? "http://localhost:8000";

type Params = { params: Promise<{ path: string[] }> };

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

async function proxy(request: Request, { params }: Params): Promise<Response> {
  const { path } = await params;
  const url = new URL(request.url);
  const target = `${BASE_URL}/${path.join("/")}${url.search}`;

  // Backstop de CSRF (F-2 da revisão): o cookie de sessão já é SameSite=Strict,
  // mas aqui também recusamos qualquer método que muda estado vindo de uma
  // origem diferente da própria app. Navegadores só mandam `Origin` cross-site
  // em requisições CORS — same-origin não dispara isto; requisições sem
  // `Origin` (GET, server-to-server) passam direto.
  if (UNSAFE_METHODS.has(request.method)) {
    const origin = request.headers.get("origin");
    if (origin) {
      let originHost: string;
      try {
        originHost = new URL(origin).host;
      } catch {
        return Response.json({ error: "Origin inválida." }, { status: 403 });
      }
      if (originHost !== url.host) {
        return Response.json({ error: "Origem não permitida." }, { status: 403 });
      }
    }
  }

  const headers = new Headers();

  // Chave de API explícita do próprio chamador (ferramenta externa que fala
  // direto com o gateway) — nunca a chave de ambiente do servidor Next.
  const clientAuth = request.headers.get("authorization") || request.headers.get("x-api-key");
  if (clientAuth) {
    headers.set("Authorization", clientAuth.startsWith("Bearer ") ? clientAuth : `Bearer ${clientAuth}`);
  }

  // Sessão de usuário: o cookie httpOnly setado por `app/api/session/route.ts`
  // segue para o backend, que o lê nativamente via `Cookie()` do FastAPI.
  const cookie = request.headers.get("cookie");
  if (cookie) headers.set("cookie", cookie);

  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  // Identifica a origem no dashboard de custo, separando o IDE das ferramentas
  // externas que também apontam para o gateway.
  headers.set("X-Eltanix-Source", "ide");

  const init: RequestInit = { method: request.method, headers };
  // Propaga o cancelamento do cliente para o backend: sem isto, um fetch
  // abortado no browser (ex.: Cmd+K cancelado no editor) deixava a chamada
  // upstream — e o `engine.complete()` por trás dela — correndo até o fim.
  init.signal = request.signal;
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
