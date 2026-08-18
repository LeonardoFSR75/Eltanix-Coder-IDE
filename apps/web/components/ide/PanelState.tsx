"use client";

/**
 * Estado de loading/vazio padrão para os painéis da barra lateral.
 *
 * Antes disso cada painel (Packages, Extensions, Containers, Trello...)
 * reinventava seu próprio placeholder — alguns com spinner, a maioria sem,
 * alguns sem estado nenhum quando a lista vinha vazia. Um componente só
 * evita essa deriva visual painel a painel.
 */
export function PanelState({
  kind,
  message,
  icon,
  onRetry,
}: {
  kind: "loading" | "empty" | "error";
  message: string;
  icon?: string;
  onRetry?: () => void;
}) {
  return (
    <div className={`panel-state panel-state-${kind}`}>
      {kind === "loading" ? (
        <span className="panel-state-spinner" aria-hidden />
      ) : (
        <span className="panel-state-icon" aria-hidden>{icon ?? (kind === "error" ? "⚠️" : "📭")}</span>
      )}
      <p className="panel-state-message">{message}</p>
      {kind === "error" && onRetry && (
        <button type="button" className="panel-state-retry" onClick={onRetry}>
          Tentar novamente
        </button>
      )}
    </div>
  );
}
