"use client";

import { useEffect } from "react";

/**
 * Fronteira de erro no nível da rota `/ide` — pega o que escapou das
 * `<ErrorBoundary>` de painel (erros durante o render inicial do Shell, no
 * `IdeProvider`, etc.) e evita a tela branca do Next.
 */
export default function IdeError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[ide/error]", error);
  }, [error]);

  return (
    <div className="ide-container">
      <div className="error-boundary-fallback" style={{ margin: 40, maxWidth: 640 }}>
        <div className="error-boundary-title">O IDE não pôde carregar</div>
        <div className="error-boundary-message">{error.message || "Erro desconhecido."}</div>
        <button type="button" className="error-boundary-retry" onClick={reset}>
          Recarregar o IDE
        </button>
      </div>
    </div>
  );
}
