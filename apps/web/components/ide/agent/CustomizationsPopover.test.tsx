import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CustomizationsPopover } from "./CustomizationsPopover";
import { MODE_HINT, MODES } from "./modes";

// A aba "tools" busca /api/agent/tools via lib/client::get — mockado para
// nenhum teste aqui disparar uma chamada de rede de verdade.
vi.mock("@/lib/client", () => ({
  get: vi.fn().mockResolvedValue({ tools: [] }),
}));

function renderPopover(mode: (typeof MODES)[number] = "auto") {
  const anchorRef = { current: null };
  const onClose = vi.fn();
  const setMode = vi.fn();
  render(
    <CustomizationsPopover
      anchorRef={anchorRef}
      onClose={onClose}
      mode={mode}
      setMode={setMode}
      project={null}
    />,
  );
  return { onClose, setMode };
}

describe("CustomizationsPopover — aba Agentes", () => {
  it("lista a descrição de todos os modos ao abrir a aba", async () => {
    renderPopover("auto");
    await userEvent.click(screen.getByRole("button", { name: "Agentes" }));

    for (const mode of MODES) {
      expect(screen.getByText(MODE_HINT[mode])).toBeInTheDocument();
    }
  });

  it("marca só o modo atual com o selo 'atual'", async () => {
    renderPopover("auto");
    await userEvent.click(screen.getByRole("button", { name: "Agentes" }));

    // Sem espaço entre o nome do modo e o selo — são nós de texto irmãos
    // adjacentes no DOM, sem texto de separação entre eles no JSX.
    const autoButton = screen.getByRole("button", { name: /^autoatual/ });
    expect(autoButton).toBeInTheDocument();
    // Nenhum outro item deveria carregar o selo.
    for (const mode of MODES.filter((m) => m !== "auto")) {
      expect(screen.queryByRole("button", { name: new RegExp(`^${mode}atual`) })).toBeNull();
    }
  });

  it("seleciona o modo Orquestra de verdade — setMode e onClose disparam", async () => {
    const { onClose, setMode } = renderPopover("auto");
    await userEvent.click(screen.getByRole("button", { name: "Agentes" }));

    await userEvent.click(screen.getByRole("button", { name: /orchestra/ }));

    expect(setMode).toHaveBeenCalledWith("orchestra");
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
