"use client";

/**
 * Menu de contexto genérico — extraído do menu de clique-direito do Explorer
 * (Panels.tsx) para ser reutilizável (ex.: TabStrip.tsx). Mesma moldura
 * visual (`menu-backdrop`/`context-menu`) em todo lugar que precisar de um.
 */
export interface ContextMenuItem {
  label: string;
  onSelect: () => void;
  danger?: boolean;
  disabled?: boolean;
}

export function ContextMenu({
  x,
  y,
  items,
  onClose,
}: {
  x: number;
  y: number;
  items: ContextMenuItem[];
  onClose: () => void;
}) {
  return (
    <>
      <div
        className="menu-backdrop"
        onClick={onClose}
        onContextMenu={(e) => {
          e.preventDefault();
          onClose();
        }}
      />
      <div className="context-menu" style={{ left: x, top: y }}>
        {items.map((item) => (
          <button
            key={item.label}
            type="button"
            className={item.danger ? "danger" : undefined}
            disabled={item.disabled}
            onClick={() => {
              item.onSelect();
              onClose();
            }}
          >
            {item.label}
          </button>
        ))}
      </div>
    </>
  );
}
