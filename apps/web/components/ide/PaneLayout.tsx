"use client";

/**
 * Renderiza a árvore de split (`ide.layout`) recursivamente: folha vira um
 * `EditorGroupView`, split vira duas células lado a lado (ou empilhadas) com
 * um divisor arrastável entre elas. Só dois filhos por split — é tudo que
 * `splitGroup`/`insertSplit` produzem hoje.
 */

import { useEffect, useRef, useState } from "react";
import { useIde, type PaneNode } from "@/lib/ide-store";
import { EditorGroupView } from "./EditorGroupView";

export function PaneLayout({
  onCursorPositionChange,
}: {
  onCursorPositionChange?: (pos: { line: number; column: number }) => void;
}) {
  const { layout } = useIde();
  return <PaneNodeView node={layout} onCursorPositionChange={onCursorPositionChange} />;
}

function PaneNodeView({
  node,
  onCursorPositionChange,
}: {
  node: PaneNode;
  onCursorPositionChange?: (pos: { line: number; column: number }) => void;
}) {
  if (node.type === "leaf") {
    return <EditorGroupView groupId={node.groupId} onCursorPositionChange={onCursorPositionChange} />;
  }
  return <SplitView node={node} onCursorPositionChange={onCursorPositionChange} />;
}

function SplitView({
  node,
  onCursorPositionChange,
}: {
  node: Extract<PaneNode, { type: "split" }>;
  onCursorPositionChange?: (pos: { line: number; column: number }) => void;
}) {
  const [ratio, setRatio] = useState(50);
  const [resizing, setResizing] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!resizing) return;
    const onMove = (e: MouseEvent) => {
      const el = containerRef.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const pct =
        node.direction === "row"
          ? ((e.clientX - rect.left) / rect.width) * 100
          : ((e.clientY - rect.top) / rect.height) * 100;
      setRatio(Math.min(80, Math.max(20, pct)));
    };
    const onUp = () => setResizing(false);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [resizing, node.direction]);

  const [first, second] = node.children;

  return (
    <div ref={containerRef} className={`pane-split pane-split-${node.direction}`}>
      <div className="pane-split-cell" style={{ flexBasis: `${ratio}%` }}>
        <PaneNodeView node={first} onCursorPositionChange={onCursorPositionChange} />
      </div>
      <div
        className={`pane-split-resizer pane-split-resizer-${node.direction}`}
        onMouseDown={() => setResizing(true)}
      />
      <div className="pane-split-cell" style={{ flexBasis: `${100 - ratio}%` }}>
        <PaneNodeView node={second} onCursorPositionChange={onCursorPositionChange} />
      </div>
    </div>
  );
}
