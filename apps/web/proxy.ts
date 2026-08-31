import { NextRequest, NextResponse } from "next/server";

/**
 * Redireciona para /login sem sessão — checagem no proxy (presença do cookie,
 * não validação real, que ficaria cara aqui) para evitar o flash de
 * conteúdo protegido que um redirect só no client teria. `AuthContext`
 * ainda valida a sessão de verdade contra `GET /api/auth/me`.
 *
 * Renomeado de `middleware.ts` no upgrade para Next.js 16 (a convenção
 * `middleware` virou `proxy`, runtime `nodejs` fixo — sem edge aqui).
 */
const PUBLIC_PATHS = ["/login"];
const COOKIE_NAME = "eltanix_session";

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (PUBLIC_PATHS.some((path) => pathname.startsWith(path)) || pathname.startsWith("/api/")) {
    return NextResponse.next();
  }

  if (!request.cookies.get(COOKIE_NAME)) {
    const loginUrl = new URL("/login", request.url);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
