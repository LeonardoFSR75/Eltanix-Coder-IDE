import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CustomizationsPopover } from "./CustomizationsPopover";
import { MODE_HINT, MODES } from "./modes";
import { del, get, post, put } from "@/lib/client";

// A aba "tools" busca /api/agent/tools via lib/client::get — mockado para
// nenhum teste aqui disparar uma chamada de rede de verdade. As abas
// "Regras de contexto"/"Auto-aprovação"/"Meus modos" também passam por
// `get`/`put`/`post`/`del`, então o mock precisa diferenciar pela URL em vez
// de devolver sempre a mesma forma.
vi.mock("@/lib/client", () => ({
  get: vi.fn(),
  put: vi.fn(),
  post: vi.fn(),
  del: vi.fn(),
}));

function renderPopover(mode: (typeof MODES)[number] = "auto", project: string | null = null) {
  const anchorRef = { current: null };
  const onClose = vi.fn();
  const setMode = vi.fn();
  render(
    <CustomizationsPopover
      anchorRef={anchorRef}
      onClose={onClose}
      mode={mode}
      setMode={setMode}
      project={project}
    />,
  );
  return { onClose, setMode };
}

beforeEach(() => {
  vi.mocked(get).mockReset();
  vi.mocked(put).mockReset();
  vi.mocked(post).mockReset();
  vi.mocked(del).mockReset();
  vi.mocked(get).mockImplementation(async (url: unknown) => {
    const href = String(url);
    if (href.startsWith("/api/agent/tools")) return { tools: [] };
    if (href.startsWith("/api/agent/context-rules")) return { version: 1, rules: [] };
    if (href.startsWith("/api/agent/approval-policy")) {
      return { version: 1, second_opinion: false, rules: [] };
    }
    if (href.startsWith("/api/agent/custom-modes")) return { modes: [] };
    return {};
  });
  vi.mocked(put).mockImplementation(async (_url: unknown, body: unknown) => body);
  vi.mocked(post).mockImplementation(async (_url: unknown, body: unknown) => body);
  vi.mocked(del).mockImplementation(async () => ({ deleted: true }));
});

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

describe("CustomizationsPopover — aba Regras de contexto (Fase 4)", () => {
  it("pede para selecionar um projeto quando nenhum está ativo", async () => {
    renderPopover("auto", null);
    await userEvent.click(screen.getByRole("button", { name: "Regras de contexto" }));

    expect(
      screen.getByText("Selecione um projeto para configurar regras de contexto."),
    ).toBeInTheDocument();
  });

  it("carrega e mostra uma regra existente do projeto", async () => {
    vi.mocked(get).mockImplementation(async (url: unknown) => {
      const href = String(url);
      if (href.startsWith("/api/agent/context-rules")) {
        return {
          version: 1,
          rules: [{ glob: "apps/api/**/*.py", instructions: "use pydantic v2" }],
        };
      }
      return {};
    });

    renderPopover("auto", "meu-projeto");
    await userEvent.click(screen.getByRole("button", { name: "Regras de contexto" }));

    expect(await screen.findByDisplayValue("apps/api/**/*.py")).toBeInTheDocument();
    expect(screen.getByDisplayValue("use pydantic v2")).toBeInTheDocument();
  });

  it("adiciona uma regra nova, edita os campos e salva via updateContextRules", async () => {
    vi.mocked(get).mockImplementation(async (url: unknown) => {
      const href = String(url);
      if (href.startsWith("/api/agent/context-rules")) return { version: 1, rules: [] };
      return {};
    });

    renderPopover("auto", "meu-projeto");
    await userEvent.click(screen.getByRole("button", { name: "Regras de contexto" }));

    expect(
      await screen.findByText("Nenhuma regra ainda — nenhuma instrução condicional é injetada."),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "+ regra de contexto" }));

    const globInput = screen.getByPlaceholderText("glob, ex: apps/api/**/*.py");
    const instructionsInput = screen.getByPlaceholderText(
      "instruções aplicadas quando o foco bater neste glob",
    );
    await userEvent.type(globInput, "apps/web/**");
    await userEvent.type(instructionsInput, "use Tailwind");

    await userEvent.click(screen.getByRole("button", { name: "💾 Salvar regras" }));

    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/api/agent/context-rules", {
        project: "meu-projeto",
        rules: [{ glob: "apps/web/**", instructions: "use Tailwind" }],
      }),
    );
  });
});

describe("CustomizationsPopover — aba Meus modos (Fase 6)", () => {
  it("mostra estado vazio e abre o formulário de criação", async () => {
    renderPopover("auto");
    await userEvent.click(screen.getByRole("button", { name: "Meus modos" }));

    expect(await screen.findByText("Nenhum modo customizado ainda.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "+ criar modo" }));

    expect(screen.getByPlaceholderText("nome do modo")).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText("bloco de prompt sempre injetado quando este modo estiver ativo"),
    ).toBeInTheDocument();
  });

  it("cria um modo novo com ferramentas selecionadas e salva via createCustomMode", async () => {
    vi.mocked(get).mockImplementation(async (url: unknown) => {
      const href = String(url);
      if (href.startsWith("/api/agent/tools")) {
        return {
          tools: [
            { name: "read_file", description: "lê um arquivo", risk: "READ", requires_approval: false },
            { name: "write_file", description: "escreve um arquivo", risk: "WRITE", requires_approval: true },
          ],
        };
      }
      if (href.startsWith("/api/agent/custom-modes")) return { modes: [] };
      return {};
    });
    vi.mocked(post).mockResolvedValue({
      id: "modo-123",
      name: "Revisor",
      icon: "🧩",
      description: "",
      allowed_tools: ["read_file"],
      prompt_block: "Revise só a camada de dados.",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });

    renderPopover("auto");
    await userEvent.click(screen.getByRole("button", { name: "Meus modos" }));
    await userEvent.click(await screen.findByRole("button", { name: "+ criar modo" }));

    await userEvent.type(screen.getByPlaceholderText("nome do modo"), "Revisor");
    await userEvent.click(await screen.findByLabelText("read_file"));
    await userEvent.type(
      screen.getByPlaceholderText("bloco de prompt sempre injetado quando este modo estiver ativo"),
      "Revise só a camada de dados.",
    );

    await userEvent.click(screen.getByRole("button", { name: "💾 Salvar modo" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/agent/custom-modes", {
        name: "Revisor",
        icon: "🧩",
        description: "",
        allowed_tools: ["read_file"],
        prompt_block: "Revise só a camada de dados.",
      }),
    );
    expect(await screen.findByText("🧩 Revisor")).toBeInTheDocument();
  });

  it("seleciona um modo customizado existente — setMode dispara com o id", async () => {
    vi.mocked(get).mockImplementation(async (url: unknown) => {
      const href = String(url);
      if (href.startsWith("/api/agent/custom-modes")) {
        return {
          modes: [
            {
              id: "modo-abc",
              name: "Revisor",
              icon: "🧩",
              description: "revisa só leitura",
              allowed_tools: ["read_file"],
              prompt_block: "",
              created_at: "2026-01-01T00:00:00Z",
              updated_at: "2026-01-01T00:00:00Z",
            },
          ],
        };
      }
      return {};
    });

    const { onClose, setMode } = renderPopover("auto");
    await userEvent.click(screen.getByRole("button", { name: "Meus modos" }));

    await userEvent.click(await screen.findByRole("button", { name: /Revisor/ }));

    expect(setMode).toHaveBeenCalledWith("modo-abc");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("remove um modo customizado depois de confirmar", async () => {
    vi.mocked(get).mockImplementation(async (url: unknown) => {
      const href = String(url);
      if (href.startsWith("/api/agent/custom-modes")) {
        return {
          modes: [
            {
              id: "modo-abc",
              name: "Revisor",
              icon: "🧩",
              description: "",
              allowed_tools: [],
              prompt_block: "",
              created_at: "2026-01-01T00:00:00Z",
              updated_at: "2026-01-01T00:00:00Z",
            },
          ],
        };
      }
      return {};
    });

    renderPopover("auto");
    await userEvent.click(screen.getByRole("button", { name: "Meus modos" }));
    await userEvent.click(await screen.findByRole("button", { name: "remover" }));

    expect(screen.getByText("Remover o modo customizado 'Revisor'?")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "confirmar" }));

    await waitFor(() => expect(del).toHaveBeenCalledWith("/api/agent/custom-modes/modo-abc"));
    expect(screen.queryByText("🧩 Revisor")).not.toBeInTheDocument();
  });
});
