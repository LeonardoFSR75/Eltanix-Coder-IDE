"use client";

import { useCallback, useState } from "react";
import { AgentPanel } from "@/components/ide/AgentPanel";
import { Editor } from "@/components/ide/Editor";
import { FileTree } from "@/components/ide/FileTree";

export default function IdePage() {
  const [tabs, setTabs] = useState<string[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [dirty, setDirty] = useState<Set<string>>(new Set());

  const open = useCallback((path: string) => {
    setTabs((prev) => (prev.includes(path) ? prev : [...prev, path]));
    setActive(path);
  }, []);

  const close = useCallback(
    (path: string) => {
      setTabs((prev) => {
        const next = prev.filter((tab) => tab !== path);
        // Ao fechar a aba ativa, cai na vizinha em vez de deixar o editor vazio.
        if (active === path) setActive(next[next.length - 1] ?? null);
        return next;
      });
    },
    [active],
  );

  const markDirty = useCallback(
    (isDirty: boolean) => {
      if (!active) return;
      setDirty((prev) => {
        const next = new Set(prev);
        if (isDirty) next.add(active);
        else next.delete(active);
        return next;
      });
    },
    [active],
  );

  return (
    <div className="ide">
      <aside className="ide-sidebar">
        <div className="panel-title">Arquivos</div>
        <FileTree onOpen={open} activePath={active} />
      </aside>

      <main className="ide-main">
        <div className="tabs">
          {tabs.map((tab) => (
            <div key={tab} className={`tab${active === tab ? " active" : ""}`}>
              <button type="button" onClick={() => setActive(tab)} title={tab}>
                {tab.split("/").pop()}
                {dirty.has(tab) && <span className="dot" />}
              </button>
              <button type="button" className="tab-close" onClick={() => close(tab)}>
                ×
              </button>
            </div>
          ))}
          {tabs.length === 0 && <div className="tabs-empty">nenhum arquivo aberto</div>}
        </div>
        <Editor path={active} onDirtyChange={markDirty} />
      </main>

      <aside className="ide-agent">
        <div className="panel-title">Agente</div>
        <AgentPanel onFileTouched={open} />
      </aside>
    </div>
  );
}
