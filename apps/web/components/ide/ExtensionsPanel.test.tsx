import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { ExtensionsPanel } from "./ExtensionsPanel";
import * as extensionsApi from "@/lib/api/extensions";
import type { ExtensionItem, ExtensionsCatalogResponse } from "@/lib/api/extensions";

vi.mock("@/lib/api/extensions", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/extensions")>("@/lib/api/extensions");
  return {
    ...actual,
    getExtensionsCatalog: vi.fn(),
    syncExtensions: vi.fn(),
    toggleExtension: vi.fn(),
    updateExtension: vi.fn(),
    updateAllExtensions: vi.fn(),
    setAutoUpdate: vi.fn(),
    searchMarketplace: vi.fn(),
  };
});

const mockedApi = vi.mocked(extensionsApi);

function ext(overrides: Partial<ExtensionItem> = {}): ExtensionItem {
  return {
    id: "ruff",
    name: "Ruff",
    publisher: "Astral",
    version: "1.0.0",
    description: "Linter Python ultrarrápido",
    category: "LSP & Linguagens",
    icon: "🐍",
    installed: true,
    active: true,
    ...overrides,
  };
}

function catalog(overrides: Partial<ExtensionsCatalogResponse> = {}): ExtensionsCatalogResponse {
  return {
    extensions: [ext()],
    total_count: 1,
    pending_updates_count: 0,
    last_sync_timestamp: 0,
    auto_update_enabled: true,
    ...overrides,
  };
}

describe("ExtensionsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("mostra as extensões instaladas depois de carregar", async () => {
    mockedApi.getExtensionsCatalog.mockResolvedValue(catalog());
    render(<ExtensionsPanel />);

    expect(await screen.findByText("Ruff")).toBeInTheDocument();
  });

  it("mostra erro com opção de retry quando o catálogo falha ao carregar", async () => {
    mockedApi.getExtensionsCatalog.mockRejectedValueOnce(new Error("Backend fora do ar"));
    render(<ExtensionsPanel />);

    expect(await screen.findByText(/Não foi possível carregar o catálogo do backend/)).toBeInTheDocument();

    mockedApi.getExtensionsCatalog.mockResolvedValueOnce(catalog());
    await userEvent.click(screen.getByRole("button", { name: "Tentar novamente" }));

    expect(await screen.findByText("Ruff")).toBeInTheDocument();
  });

  it("alterna o estado ativo/desativado ao clicar em Desabilitar/Habilitar", async () => {
    mockedApi.getExtensionsCatalog.mockResolvedValue(catalog());
    mockedApi.toggleExtension.mockResolvedValue({ id: "ruff", active: false });
    render(<ExtensionsPanel />);

    await screen.findByText("Ruff");
    await userEvent.click(screen.getByRole("button", { name: "Desabilitar" }));

    await waitFor(() => {
      expect(mockedApi.toggleExtension).toHaveBeenCalledWith("ruff", false);
    });
    expect(await screen.findByRole("button", { name: "Habilitar" })).toBeInTheDocument();
  });

  it("recarrega quando o evento novaai_studio:extensions:changed é disparado (ex.: ferramenta do agente)", async () => {
    mockedApi.getExtensionsCatalog.mockResolvedValue(catalog());
    render(<ExtensionsPanel />);
    await screen.findByText("Ruff");

    mockedApi.getExtensionsCatalog.mockResolvedValue(
      catalog({ extensions: [ext(), ext({ id: "biome", name: "Biome" })], total_count: 2 })
    );
    window.dispatchEvent(new CustomEvent("novaai_studio:extensions:changed"));

    expect(await screen.findByText("Biome")).toBeInTheDocument();
  });
});
