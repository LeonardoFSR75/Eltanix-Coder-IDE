"use client";

/**
 * Quick open (Ctrl+P) e command palette (Ctrl+Shift+P).
 *
 * São a mesma interação — uma lista filtrada por digitação, navegada por setas
 * e confirmada com Enter — então compartilham o componente de sobreposição. O
 * que muda é a fonte dos itens.
 */

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { fuzzyScore, useIde } from "@/lib/ide-store";

interface Item {
  id: string;
  label: string;
  hint?: string;
  run: () => void;
}

function Overlay({
  placeholder,
  items,
  onClose,
  empty,
}: {
  placeholder: string;
  items: (query: string) => Item[];
  onClose: () => void;
  empty: string;
}) {
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const visible = useMemo(() => items(query).slice(0, 60), [items, query]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Digitar filtra a lista; sem isto o cursor ficaria apontando para um índice
  // que não existe mais.
  useEffect(() => setCursor(0), [query]);

  useEffect(() => {
    listRef.current
      ?.querySelector<HTMLElement>(`[data-index="${cursor}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      setCursor((c) => Math.min(c + 1, visible.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setCursor((c) => Math.max(c - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const escolhido = visible[cursor];
      if (escolhido) {
        escolhido.run();
        onClose();
      }
    }
  };

  return (
    <div className="overlay-backdrop" onMouseDown={onClose}>
      <div className="overlay" onMouseDown={(e) => e.stopPropagation()}>
        <input
          ref={inputRef}
          value={query}
          placeholder={placeholder}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
        />
        <div className="overlay-list" ref={listRef}>
          {visible.map((item, index) => (
            <button
              key={item.id}
              type="button"
              data-index={index}
              className={`overlay-item${index === cursor ? " active" : ""}`}
              onMouseEnter={() => setCursor(index)}
              onClick={() => {
                item.run();
                onClose();
              }}
            >
              <span className="overlay-label">{item.label}</span>
              {item.hint && <span className="overlay-hint">{item.hint}</span>}
            </button>
          ))}
          {visible.length === 0 && <div className="overlay-empty">{empty}</div>}
        </div>
      </div>
    </div>
  );
}

export function QuickOpen({ onClose }: { onClose: () => void }) {
  const { files, openFile } = useIde();

  const items = useCallback(
    (query: string): Item[] => {
      if (!query) {
        return files.slice(0, 60).map((f) => ({
          id: f.path,
          label: f.name,
          hint: f.path,
          run: () => openFile(f.path),
        }));
      }
      return files
        .map((f) => ({ file: f, score: fuzzyScore(f.path, query) }))
        .filter((r): r is { file: (typeof files)[number]; score: number } => r.score !== null)
        .sort((a, b) => b.score - a.score)
        .map(({ file }) => ({
          id: file.path,
          label: file.name,
          hint: file.path,
          run: () => openFile(file.path),
        }));
    },
    [files, openFile],
  );

  return (
    <Overlay
      placeholder="Abrir arquivo por nome…"
      items={items}
      onClose={onClose}
      empty="Nenhum arquivo corresponde."
    />
  );
}

export interface Command {
  id: string;
  title: string;
  shortcut?: string;
  run: () => void;
}

export function CommandPalette({
  commands,
  onClose,
}: {
  commands: Command[];
  onClose: () => void;
}) {
  const items = useCallback(
    (query: string): Item[] =>
      commands
        .map((c) => ({ command: c, score: fuzzyScore(c.title, query) }))
        .filter((r): r is { command: Command; score: number } => r.score !== null)
        .sort((a, b) => b.score - a.score)
        .map(({ command }) => ({
          id: command.id,
          label: command.title,
          hint: command.shortcut,
          run: command.run,
        })),
    [commands],
  );

  return (
    <Overlay
      placeholder="Digite um comando…"
      items={items}
      onClose={onClose}
      empty="Nenhum comando corresponde."
    />
  );
}

/** Caixa de diálogo simples para nomear arquivo, branch, etc. */
export function PromptDialog({
  title,
  initial = "",
  confirmLabel = "confirmar",
  onConfirm,
  onClose,
}: {
  title: string;
  initial?: string;
  confirmLabel?: string;
  onConfirm: (value: string) => void;
  onClose: () => void;
}) {
  const [value, setValue] = useState(initial);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  const confirmar = () => {
    if (!value.trim()) return;
    onConfirm(value.trim());
    onClose();
  };

  return (
    <div className="overlay-backdrop" onMouseDown={onClose}>
      <div className="overlay prompt" onMouseDown={(e) => e.stopPropagation()}>
        <div className="prompt-title">{title}</div>
        <input
          ref={inputRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") { e.preventDefault(); confirmar(); }
            if (e.key === "Escape") { e.preventDefault(); onClose(); }
          }}
        />
        <div className="prompt-actions">
          <button type="button" className="primary" onClick={confirmar}>
            {confirmLabel}
          </button>
          <button type="button" onClick={onClose}>cancelar</button>
        </div>
      </div>
    </div>
  );
}

export function ConfirmDialog({
  message,
  danger = false,
  onConfirm,
  onClose,
}: {
  message: ReactNode;
  danger?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  return (
    <div className="overlay-backdrop" onMouseDown={onClose}>
      <div className="overlay prompt" onMouseDown={(e) => e.stopPropagation()}>
        <div className="prompt-title">{message}</div>
        <div className="prompt-actions">
          <button
            type="button"
            className={danger ? "danger" : "primary"}
            onClick={() => { onConfirm(); onClose(); }}
          >
            confirmar
          </button>
          <button type="button" onClick={onClose}>cancelar</button>
        </div>
      </div>
    </div>
  );
}
