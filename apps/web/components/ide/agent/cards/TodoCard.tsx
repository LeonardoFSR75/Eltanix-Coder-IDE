"use client";

import { useState } from "react";
import type { TodoItem } from "../sessionTypes";

const STATUS_ICON: Record<TodoItem["status"], string> = {
  pending: "○",
  in_progress: "◐",
  completed: "●",
};

// Painel fixo, não uma linha na rolagem: o checklist precisa estar visível
// o tempo todo enquanto o agente trabalha, não se perder entre os cards de
// tool-call conforme a conversa cresce.
export function TodoCard({ todos }: { todos: TodoItem[] }) {
  const [collapsed, setCollapsed] = useState(false);
  if (todos.length === 0) return null;

  const done = todos.filter((t) => t.status === "completed").length;

  return (
    <div className="todo-card">
      <button
        type="button"
        className="todo-card-header"
        onClick={() => setCollapsed((v) => !v)}
        aria-expanded={!collapsed}
      >
        <span className="todo-card-icon">📋</span>
        <span className="todo-card-title">Plano</span>
        <span className="todo-card-progress">
          {done}/{todos.length}
        </span>
        <span className="tool-card-chevron">{collapsed ? "▸" : "▾"}</span>
      </button>
      {!collapsed && (
        <ul className="todo-card-list">
          {todos.map((item, i) => (
            <li key={i} className={`todo-card-item ${item.status}`}>
              <span className="todo-card-status-icon">{STATUS_ICON[item.status]}</span>
              <span className="todo-card-content">{item.content}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
