"use client";

/**
 * Popover de Personalizações, ancorado no ícone de engrenagem do cabeçalho.
 *
 * Não reaproveita o `Overlay` de `Overlays.tsx` — aquele é um modal de fundo
 * cheio, centralizado, certo pra QuickOpen/CommandPalette que querem atenção
 * total. Aqui o popover precisa ficar perto do botão que o abriu, e
 * `position: fixed` (calculado do botão) evita ser cortado pelo
 * `overflow: hidden` do `.agent-dock` — `position: absolute` sofreria esse
 * corte se o conteúdo for mais alto que o espaço restante do dock.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { get } from "@/lib/client";
import { MODE_HINT, MODES, type Mode } from "./modes";

interface ToolInfo {
  name: string;
  description: string;
  risk: string;
  requires_approval: boolean;
}

type CategoriaId = "overview" | "agents" | "skills" | "instructions" | "hooks" | "mcp" | "tools";

const CATEGORIAS: { id: CategoriaId; label: string; enabled: boolean }[] = [
  { id: "overview", label: "Visão geral", enabled: true },
  { id: "agents", label: "Agentes", enabled: true },
  { id: "skills", label: "Habilidades", enabled: false },
  { id: "instructions", label: "Instruções", enabled: false },
  { id: "hooks", label: "Hooks", enabled: false },
  { id: "mcp", label: "Servidores MCP", enabled: false },
  { id: "tools", label: "Ferramentas", enabled: true },
];

export function CustomizationsPopover({
  anchorRef,
  onClose,
  mode,
  setMode,
}: {
  anchorRef: React.RefObject<HTMLButtonElement | null>;
  onClose: () => void;
  mode: Mode;
  setMode: (mode: Mode) => void;
}) {
  const popoverRef = useRef<HTMLDivElement>(null);
  const [categoria, setCategoria] = useState<CategoriaId>("overview");
  const [tools, setTools] = useState<ToolInfo[] | null>(null);
  const [toolsErro, setToolsErro] = useState<string | null>(null);

  const posicao = useMemo(() => {
    const r = anchorRef.current?.getBoundingClientRect();
    if (!r) return { top: 60, right: 12 };
    return { top: r.bottom + 8, right: Math.max(12, window.innerWidth - r.right) };
  }, [anchorRef]);

  useEffect(() => {
    const onPointerDown = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node) && e.target !== anchorRef.current) {
        onClose();
      }
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [anchorRef, onClose]);

  useEffect(() => {
    if (categoria !== "tools" || tools !== null) return;
    get<{ tools: ToolInfo[] }>("/api/agent/tools")
      .then((r) => setTools(r.tools))
      .catch((err) => setToolsErro(err instanceof Error ? err.message : String(err)));
  }, [categoria, tools]);

  return (
    <div
      ref={popoverRef}
      className="customizations-popover"
      style={{ top: posicao.top, right: posicao.right }}
    >
      <nav className="customizations-nav">
        {CATEGORIAS.map((c) => (
          <button
            key={c.id}
            type="button"
            className={`customizations-nav-item${categoria === c.id ? " active" : ""}`}
            disabled={!c.enabled}
            onClick={() => c.enabled && setCategoria(c.id)}
          >
            {c.label}
            {!c.enabled && <span className="pill warn">em breve</span>}
          </button>
        ))}
      </nav>

      <div className="customizations-pane">
        {categoria === "overview" && (
          <div className="customizations-overview">
            <p>
              O agente roda sobre um gateway multi-modelo local-first: cada tarefa vira uma sessão isolada
              num worktree Git próprio, com sandbox de execução e aprovação humana para ações de risco.
            </p>
            <p>Use as abas ao lado para ver os modos disponíveis e o catálogo de ferramentas do agente.</p>
          </div>
        )}

        {categoria === "agents" && (
          <div className="customizations-list">
            {MODES.map((m) => (
              <button
                key={m}
                type="button"
                className={`customizations-item customizations-item-button${m === mode ? " active" : ""}`}
                onClick={() => {
                  setMode(m);
                  onClose();
                }}
              >
                <div className="customizations-item-title">
                  {m}
                  {m === mode && <span className="pill ok">atual</span>}
                </div>
                <div className="customizations-item-desc">{MODE_HINT[m]}</div>
              </button>
            ))}
          </div>
        )}

        {categoria === "tools" && (
          <div className="customizations-list">
            {toolsErro && <div className="panel-error">{toolsErro}</div>}
            {!tools && !toolsErro && <div className="tree-hint">carregando…</div>}
            {(tools ?? []).map((t) => (
              <div key={t.name} className="customizations-item">
                <div className="customizations-item-title">
                  {t.name} <span className={`pill ${t.risk === "exec" ? "bad" : t.risk === "write" ? "warn" : "ok"}`}>{t.risk}</span>
                </div>
                <div className="customizations-item-desc">{t.description}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
