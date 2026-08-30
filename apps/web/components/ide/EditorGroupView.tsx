"use client";

/**
 * Um painel do split view: sua própria faixa de abas, breadcrumbs e
 * instância de `Editor`. A zona de borda (20% de cada lado) detecta
 * drag-to-split — soltar uma aba perto de uma borda cria um novo grupo ali;
 * soltar no centro só move a aba para este grupo, sem dividir.
 */

import { useState } from "react";
import { useIde } from "@/lib/ide-store";
import { Editor } from "./Editor";
import { EditorBrowserView } from "./EditorBrowserView";
import { TabStrip, TAB_DRAG_MIME } from "./TabStrip";

const BROWSER_PREFIX = "browser:";
const BROWSER_AGENT_PREFIX = "browser-agent:";

type DropZone = "left" | "right" | "top" | "bottom" | "center";

function zoneFromEvent(e: React.DragEvent, rect: DOMRect): DropZone {
  const x = (e.clientX - rect.left) / rect.width;
  const y = (e.clientY - rect.top) / rect.height;
  const EDGE = 0.25;
  if (x < EDGE) return "left";
  if (x > 1 - EDGE) return "right";
  if (y < EDGE) return "top";
  if (y > 1 - EDGE) return "bottom";
  return "center";
}

export function EditorGroupView({
  groupId,
  onCursorPositionChange,
}: {
  groupId: string;
  onCursorPositionChange?: (pos: { line: number; column: number }) => void;
}) {
  const {
    groups,
    activeGroupId,
    setActiveGroup,
    closeGroup,
    splitGroup,
    moveTabToGroup,
    openFile,
    activeSessionId,
  } = useIde();
  const [dropZone, setDropZone] = useState<DropZone | null>(null);
  const group = groups[groupId];
  const isMultiGroup = Object.keys(groups).length > 1;

  if (!group) return null;

  const active = group.active;
  // Abas de browser (`browser:`/`browser-agent:`) são roteadas para
  // `EditorBrowserView` aqui, ANTES de montar `Editor` — decidir qual
  // componente instanciar neste nível evita que a mesma instância do
  // `Editor` troque de "arquivo" para "browser" sem remount, o que quebraria
  // as Rules of Hooks (dezenas de hooks abaixo do antigo early-return).
  const isBrowserTab = !!active && active.startsWith(BROWSER_PREFIX);
  const isBrowserAgentTab = !!active && active.startsWith(BROWSER_AGENT_PREFIX);
  const trilha = active && !isBrowserTab && !isBrowserAgentTab ? active.split("/") : [];

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const zone = dropZone;
    setDropZone(null);
    const raw = e.dataTransfer.getData(TAB_DRAG_MIME);
    if (!raw) return;
    let payload: { path: string; groupId: string };
    try {
      payload = JSON.parse(raw);
    } catch {
      return;
    }
    if (!zone || zone === "center") {
      moveTabToGroup(payload.path, payload.groupId, groupId);
      return;
    }
    const direction = zone === "left" || zone === "right" ? "row" : "column";
    splitGroup(groupId, payload.path, direction, payload.groupId);
  };

  return (
    <div
      className={`editor-group${groupId === activeGroupId ? " active" : ""}`}
      onMouseDownCapture={() => setActiveGroup(groupId)}
    >
      <div className="editor-group-tabs-row">
        <TabStrip groupId={groupId} />
        {isMultiGroup && (
          <button
            type="button"
            className="editor-group-close"
            title="Fechar este painel"
            onClick={() => closeGroup(groupId)}
          >
            ×
          </button>
        )}
      </div>

      {trilha.length > 1 && (
        <div className="breadcrumbs">
          {trilha.map((parte, i) => (
            <span key={`${parte}-${i}`}>
              {i > 0 && <span className="crumb-sep">›</span>}
              <span className={i === trilha.length - 1 ? "crumb current" : "crumb"}>{parte}</span>
            </span>
          ))}
        </div>
      )}

      <div
        className="editor-area"
        onDragOver={(e) => {
          e.preventDefault();
          setDropZone(zoneFromEvent(e, e.currentTarget.getBoundingClientRect()));
        }}
        onDragLeave={(e) => {
          if (e.target === e.currentTarget) setDropZone(null);
        }}
        onDrop={handleDrop}
      >
        {dropZone && <div className={`pane-drop-indicator pane-drop-${dropZone}`} />}
        {isBrowserTab ? (
          <EditorBrowserView
            initialUrl={active!.slice(BROWSER_PREFIX.length)}
            sessionId={activeSessionId || undefined}
          />
        ) : isBrowserAgentTab ? (
          // Força o modo 🤖 Agente na primeira aba — usado para URLs que só
          // o serviço de navegador consegue resolver (ex.: porta de um
          // sandbox via `eltanix-<sessionId>`), nunca alcançáveis por um
          // iframe direto no navegador real (ver StatusBar.tsx, botões de
          // porta do sandbox).
          <EditorBrowserView
            initialUrl={active!.slice(BROWSER_AGENT_PREFIX.length)}
            sessionId={activeSessionId || undefined}
            initialMode="headless"
          />
        ) : (
          <Editor
            groupId={groupId}
            onNavigate={(destino, linha, coluna) => openFile(destino, { line: linha, column: coluna }, groupId)}
            onCursorPositionChange={onCursorPositionChange}
          />
        )}
      </div>
    </div>
  );
}
