"use client";

/**
 * Faixa de abas de UM grupo do editor: rolável, arrastável para reordenar
 * dentro do grupo (e para servir de origem do drag-to-split entre grupos —
 * ver EditorGroupView), com distinção visual entre aba "preview" (itálico) e
 * aba fixada (duplo-clique ou edição promove).
 */

import { useRef } from "react";
import { useIde } from "@/lib/ide-store";
import { FileIcon } from "@/components/ide/FileIcons";

// Payload usado tanto para reordenar dentro do grupo quanto para o
// drag-to-split entre grupos (EditorGroupView lê o mesmo formato).
export const TAB_DRAG_MIME = "application/x-sicoobito-tab";

export function TabStrip({ groupId }: { groupId: string }) {
  const { groups, setActive, closeTab, pinTab, reorderTabs } = useIde();
  const group = groups[groupId];
  const dragPath = useRef<string | null>(null);

  if (!group) return null;

  return (
    <div
      className="tabs"
      onWheel={(e) => {
        // A maioria dos mouses só manda scroll vertical; a faixa de abas é
        // horizontal, então convertemos em vez de depender de shift+scroll.
        if (e.deltaY === 0) return;
        e.currentTarget.scrollLeft += e.deltaY;
      }}
    >
      {group.tabs.map((tab) => {
        const filename = tab.split("/").pop() ?? tab;
        return (
          <div
            key={tab}
            className={`tab${group.active === tab ? " active" : ""}${group.previewTab === tab ? " preview" : ""}`}
            draggable
            onDragStart={(e) => {
              dragPath.current = tab;
              e.dataTransfer.effectAllowed = "move";
              e.dataTransfer.setData(TAB_DRAG_MIME, JSON.stringify({ path: tab, groupId }));
            }}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              e.stopPropagation();
              if (dragPath.current) reorderTabs(dragPath.current, tab, groupId);
              dragPath.current = null;
            }}
          >
            <button
              type="button"
              onClick={() => setActive(tab, groupId)}
              onDoubleClick={() => pinTab(tab, groupId)}
              title={tab}
            >
              <FileIcon filename={filename} className="tab-file-icon" />
              {filename}
              {group.dirty.has(tab) && <span className="dot" />}
            </button>
            <button
              type="button"
              className="tab-close"
              onClick={() => closeTab(tab, groupId)}
              title="Fechar aba"
              aria-label={`Fechar ${filename}`}
            >
              <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <line x1="2" y1="2" x2="10" y2="10" />
                <line x1="10" y1="2" x2="2" y2="10" />
              </svg>
            </button>
          </div>
        );
      })}
      {group.tabs.length === 0 && (
        <div className="tabs-empty">
          Pressione <kbd className="editor-kbd">Ctrl+P</kbd> para abrir um arquivo
        </div>
      )}
    </div>
  );
}
