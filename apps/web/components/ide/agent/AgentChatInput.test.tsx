import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { AgentChatInput } from "./AgentChatInput";
import * as agentApi from "@/lib/api/agent";
import type { SlashCommandInfo } from "@/lib/api/agent";

const mockUseIde = vi.fn(() => ({ active: null as string | null, files: [] as { path: string }[] }));
vi.mock("@/lib/ide-store", () => ({
  useIde: () => mockUseIde(),
}));

vi.mock("@/lib/api/providers", () => ({
  getCatalog: vi.fn().mockResolvedValue({ profiles: [], models: [] }),
}));

vi.mock("@/lib/api/agent", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/agent")>("@/lib/api/agent");
  return { ...actual, listSlashCommands: vi.fn() };
});

const mockedApi = vi.mocked(agentApi);

const COMMANDS: SlashCommandInfo[] = [
  { command: "/spec", skill_name: "spec-driven-development", suggested_mode: "plan", description: "Escreve uma especificação" },
  { command: "/test", skill_name: "test-driven-development", suggested_mode: "orchestra", description: "Ciclo TDD" },
  { command: "/fix", skill_name: "debugging-and-error-recovery", suggested_mode: "agent", description: "Investiga e corrige um bug" },
  { command: "/explain", skill_name: null, suggested_mode: "ask", description: "Explica código sem alterar nada" },
];

function renderInput(overrides: Partial<Parameters<typeof AgentChatInput>[0]> = {}) {
  const setTask = vi.fn();
  const setMode = vi.fn();
  const props: Parameters<typeof AgentChatInput>[0] = {
    task: "",
    setTask,
    mode: "agent",
    setMode,
    profile: null,
    setProfile: vi.fn(),
    focusFiles: [],
    setFocusFiles: vi.fn(),
    focusFolder: null,
    setFocusFolder: vi.fn(),
    running: false,
    canSubmit: true,
    onSubmit: vi.fn(),
    ...overrides,
  };
  const utils = render(<AgentChatInput {...props} />);
  return { ...utils, setTask, setMode, onSubmit: props.onSubmit as ReturnType<typeof vi.fn> };
}

describe("AgentChatInput — slash commands reais", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApi.listSlashCommands.mockResolvedValue(COMMANDS);
    mockUseIde.mockReturnValue({ active: null, files: [] });
  });

  it("não mostra o menu quando o campo está vazio", async () => {
    renderInput({ task: "" });
    await waitFor(() => expect(mockedApi.listSlashCommands).toHaveBeenCalled());
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("mostra todos os comandos ao digitar só '/'", async () => {
    renderInput({ task: "/" });
    expect(await screen.findByRole("listbox")).toBeInTheDocument();
    for (const c of COMMANDS) {
      expect(screen.getByText(c.command)).toBeInTheDocument();
    }
  });

  it("filtra o menu conforme o texto após a barra", async () => {
    renderInput({ task: "/te" });
    await screen.findByRole("listbox");
    expect(screen.getByText("/test")).toBeInTheDocument();
    expect(screen.queryByText("/spec")).not.toBeInTheDocument();
    expect(screen.queryByText("/fix")).not.toBeInTheDocument();
  });

  it("fecha o menu depois que um espaço é digitado após o comando", async () => {
    renderInput({ task: "/test " });
    await waitFor(() => expect(mockedApi.listSlashCommands).toHaveBeenCalled());
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("clicar num item do menu preenche o comando completo no textarea", async () => {
    const { setTask } = renderInput({ task: "/te" });
    await screen.findByRole("listbox");

    await userEvent.click(screen.getByText("/test"));
    expect(setTask).toHaveBeenCalledWith("/test ");
  });

  it("Enter com o menu aberto seleciona o comando em vez de enviar a mensagem", async () => {
    const { setTask, onSubmit } = renderInput({ task: "/te" });
    const textarea = await screen.findByPlaceholderText(/Pergunte ao NovaAI Studio Agente/);
    await waitFor(() => expect(screen.getByRole("listbox")).toBeInTheDocument());

    await userEvent.type(textarea, "{Enter}");

    expect(setTask).toHaveBeenCalledWith("/test ");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("avisa quando o modo sugerido do comando diverge do modo atual, sem trocar sozinho", async () => {
    const { setMode } = renderInput({ task: "/test corrija o bug", mode: "agent" });

    expect(await screen.findByText(/normalmente roda em modo/)).toBeInTheDocument();
    expect(screen.getByText("orchestra")).toBeInTheDocument();
    expect(setMode).not.toHaveBeenCalled();
  });

  it("não mostra aviso de modo quando o modo sugerido já é o atual", async () => {
    renderInput({ task: "/test corrija o bug", mode: "orchestra" });
    await waitFor(() => expect(mockedApi.listSlashCommands).toHaveBeenCalled());
    expect(screen.queryByText(/normalmente roda em modo/)).not.toBeInTheDocument();
  });

  it("texto sem barra não aciona o menu nem o aviso de modo", async () => {
    renderInput({ task: "implemente uma função de login" });
    await waitFor(() => expect(mockedApi.listSlashCommands).toHaveBeenCalled());
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(screen.queryByText(/normalmente roda em modo/)).not.toBeInTheDocument();
  });
});

const WORKSPACE_FILES = [
  { path: "apps/api/src/novaai_studio/main.py" },
  { path: "apps/api/src/novaai_studio/agent/runner.py" },
  { path: "apps/web/components/ide/AgentPanel.tsx" },
];

describe("AgentChatInput — menções @ de contexto (Fase 5)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApi.listSlashCommands.mockResolvedValue(COMMANDS);
    mockUseIde.mockReturnValue({ active: null, files: WORKSPACE_FILES });
  });

  it("não mostra o menu de menções sem '@' no texto", async () => {
    renderInput({ task: "implemente uma função de login" });
    await waitFor(() => expect(mockedApi.listSlashCommands).toHaveBeenCalled());
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("mostra @docs, @web e arquivos que casam ao digitar '@'", async () => {
    renderInput({ task: "explique o @" });
    expect(await screen.findByRole("listbox")).toBeInTheDocument();
    expect(screen.getByText("@docs")).toBeInTheDocument();
    expect(screen.getByText("@web")).toBeInTheDocument();
    expect(screen.getByText("apps/api/src/novaai_studio/main.py")).toBeInTheDocument();
  });

  it("filtra arquivos pelo termo digitado após o '@'", async () => {
    renderInput({ task: "corrija o @runner" });
    await screen.findByRole("listbox");
    expect(screen.getByText("apps/api/src/novaai_studio/agent/runner.py")).toBeInTheDocument();
    expect(screen.queryByText("apps/web/components/ide/AgentPanel.tsx")).not.toBeInTheDocument();
    expect(screen.queryByText("@docs")).not.toBeInTheDocument();
  });

  it("clicar num arquivo insere o caminho no texto e anexa aos arquivos em foco", async () => {
    const setFocusFiles = vi.fn();
    const { setTask } = renderInput({ task: "corrija o @runner", setFocusFiles });
    await screen.findByRole("listbox");

    await userEvent.click(screen.getByText("apps/api/src/novaai_studio/agent/runner.py"));

    expect(setTask).toHaveBeenCalledWith("corrija o @apps/api/src/novaai_studio/agent/runner.py ");
    expect(setFocusFiles).toHaveBeenCalled();
    const updater = setFocusFiles.mock.calls[0][0] as (prev: string[]) => string[];
    expect(updater([])).toEqual(["apps/api/src/novaai_studio/agent/runner.py"]);
  });

  it("clicar em @docs insere o marcador de texto sem tocar em focusFiles/focusFolder", async () => {
    const setFocusFiles = vi.fn();
    const setFocusFolder = vi.fn();
    const { setTask } = renderInput({
      task: "resuma o @",
      setFocusFiles,
      setFocusFolder,
    });
    await screen.findByRole("listbox");

    await userEvent.click(screen.getByText("@docs"));

    expect(setTask).toHaveBeenCalledWith("resuma o @docs ");
    expect(setFocusFiles).not.toHaveBeenCalled();
    expect(setFocusFolder).not.toHaveBeenCalled();
  });

  it("Escape com o menu de menções aberto remove o token parcial", async () => {
    const { setTask, onSubmit } = renderInput({ task: "corrija o @run" });
    const textarea = await screen.findByPlaceholderText(/Pergunte ao NovaAI Studio Agente/);
    await waitFor(() => expect(screen.getByRole("listbox")).toBeInTheDocument());

    await userEvent.type(textarea, "{Escape}");

    expect(setTask).toHaveBeenCalledWith("corrija o ");
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
