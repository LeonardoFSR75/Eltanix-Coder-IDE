import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApprovalCard } from "./AgentPanel";
import type { PendingAction } from "./agent/sessionTypes";

function planAction(overrides: Partial<PendingAction> = {}): PendingAction {
  return {
    tool_call_id: "call-1",
    tool: "write_todos",
    risk: "write",
    arguments: {
      items: [
        { content: "Diagnóstico de ambiente", status: "completed" },
        { content: "Implementar endpoint", status: "in_progress" },
        { content: "Escrever testes", status: "pending" },
      ],
    },
    summary: "atualizar plano (3 itens)",
    ...overrides,
  };
}

function writeFileAction(overrides: Partial<PendingAction> = {}): PendingAction {
  return {
    tool_call_id: "call-2",
    tool: "write_file",
    risk: "write",
    arguments: { path: "app.py" },
    summary: "escrever app.py",
    ...overrides,
  };
}

describe("ApprovalCard — revisão de plano (Fase 3, write_todos)", () => {
  it("mostra o corpo especial de revisão de plano para write_todos", () => {
    render(
      <ApprovalCard
        pending={[planAction()]}
        decisions={{}}
        onDecide={vi.fn()}
        onDecision={vi.fn()}
      />,
    );

    expect(screen.getByText("📐 Revisar plano antes de executar")).toBeInTheDocument();
    expect(screen.getByText("Diagnóstico de ambiente")).toBeInTheDocument();
    expect(screen.getByText("Implementar endpoint")).toBeInTheDocument();
    expect(screen.getByText("Escrever testes")).toBeInTheDocument();
    expect(
      screen.queryByText("atualizar plano (3 itens)"),
    ).not.toBeInTheDocument();
  });

  it("cai no resumo de texto normal quando write_todos não tem itens", () => {
    render(
      <ApprovalCard
        pending={[planAction({ arguments: { items: [] } })]}
        decisions={{}}
        onDecide={vi.fn()}
        onDecision={vi.fn()}
      />,
    );

    expect(screen.getByText("📐 Revisar plano antes de executar")).toBeInTheDocument();
    expect(screen.getByText("atualizar plano (3 itens)")).toBeInTheDocument();
  });

  it("outras ferramentas continuam mostrando o resumo genérico, sem o corpo de plano", () => {
    render(
      <ApprovalCard
        pending={[writeFileAction()]}
        decisions={{}}
        onDecide={vi.fn()}
        onDecision={vi.fn()}
      />,
    );

    expect(screen.getByText("escrever app.py")).toBeInTheDocument();
    expect(screen.queryByText("📐 Revisar plano antes de executar")).not.toBeInTheDocument();
  });

  it("Aprovar/Rejeitar por item continua funcionando para a ação write_todos", () => {
    const onDecision = vi.fn();
    render(
      <ApprovalCard
        pending={[planAction()]}
        decisions={{}}
        onDecide={vi.fn()}
        onDecision={onDecision}
      />,
    );

    screen.getByTitle("Aprovar execução deste item").click();
    expect(onDecision).toHaveBeenCalledWith("call-1", true);
  });
});
