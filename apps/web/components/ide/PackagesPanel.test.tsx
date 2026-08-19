import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { PackagesPanel } from "./PackagesPanel";
import * as packagesApi from "@/lib/api/packages";

vi.mock("@/lib/ide-store", () => ({
  useIde: () => ({ project: "meu-projeto", openFile: vi.fn() }),
}));

vi.mock("@/lib/api/packages", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/packages")>("@/lib/api/packages");
  return {
    ...actual,
    getProjectPackages: vi.fn(),
    installProjectPackage: vi.fn(),
    uninstallProjectPackage: vi.fn(),
    syncProjectRequirements: vi.fn(),
  };
});

const mockedApi = vi.mocked(packagesApi);

function baseResponse(overrides: Partial<Awaited<ReturnType<typeof packagesApi.getProjectPackages>>> = {}) {
  return {
    project: "meu-projeto",
    ecosystem: "python",
    manifest_file: "requirements.txt",
    venv_exists: true,
    venv_path: "/tmp/.venv",
    installed_count: 1,
    packages: [{ name: "requests", version: "2.31.0" }],
    requirements_exists: true,
    requirements_content: "requests==2.31.0\n",
    requirements_map: { requests: "2.31.0" },
    ...overrides,
  };
}

describe("PackagesPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("mostra o pacote instalado depois de carregar", async () => {
    mockedApi.getProjectPackages.mockResolvedValue(baseResponse());
    render(<PackagesPanel />);

    expect(await screen.findByText("requests")).toBeInTheDocument();
    expect(screen.getByText("v2.31.0")).toBeInTheDocument();
  });

  it("mostra estado vazio quando não há pacotes instalados", async () => {
    mockedApi.getProjectPackages.mockResolvedValue(baseResponse({ packages: [], installed_count: 0, requirements_map: {} }));
    render(<PackagesPanel />);

    expect(await screen.findByText(/Nenhum pacote instalado/)).toBeInTheDocument();
  });

  it("mostra o erro do backend quando a listagem falha", async () => {
    mockedApi.getProjectPackages.mockRejectedValue(new Error("Falha de rede"));
    render(<PackagesPanel />);

    expect(await screen.findByText("Falha de rede")).toBeInTheDocument();
  });

  it("pede confirmação antes de desinstalar e só chama a API após confirmar", async () => {
    mockedApi.getProjectPackages.mockResolvedValue(baseResponse());
    mockedApi.uninstallProjectPackage.mockResolvedValue({
      ok: true,
      package: "requests",
      requirements_updated: true,
      requirements_content: "",
      stdout: "",
    });
    render(<PackagesPanel />);

    await screen.findByText("requests");
    await userEvent.click(screen.getByTitle("Desinstalar requests"));

    // O diálogo de confirmação aparece — a API ainda não deve ter sido chamada.
    expect(await screen.findByText(/Desinstalar o pacote 'requests'/)).toBeInTheDocument();
    expect(mockedApi.uninstallProjectPackage).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "confirmar" }));

    await waitFor(() => {
      expect(mockedApi.uninstallProjectPackage).toHaveBeenCalledWith("meu-projeto", "requests", true);
    });
  });

  it("dispara o evento sicoobito:packages:changed após instalar", async () => {
    mockedApi.getProjectPackages.mockResolvedValue(baseResponse({ packages: [], installed_count: 0 }));
    mockedApi.installProjectPackage.mockResolvedValue({
      ok: true,
      package: "flask",
      version: "3.0.0",
      requirements_updated: true,
      requirements_content: "flask==3.0.0\n",
      stdout: "",
    });
    const handler = vi.fn();
    window.addEventListener("sicoobito:packages:changed", handler);

    render(<PackagesPanel />);
    await screen.findByPlaceholderText("Pacote...");

    await userEvent.type(screen.getByPlaceholderText("Pacote..."), "flask");
    await userEvent.click(screen.getByRole("button", { name: /Instalar/ }));

    await waitFor(() => expect(handler).toHaveBeenCalledTimes(1));
    window.removeEventListener("sicoobito:packages:changed", handler);
  });

  it("recarrega quando o evento sicoobito:packages:changed é disparado externamente (ex.: ferramenta do agente)", async () => {
    mockedApi.getProjectPackages.mockResolvedValue(baseResponse());
    render(<PackagesPanel />);
    await screen.findByText("requests");

    mockedApi.getProjectPackages.mockResolvedValue(
      baseResponse({ packages: [{ name: "requests", version: "2.31.0" }, { name: "flask", version: "3.0.0" }] })
    );
    window.dispatchEvent(new CustomEvent("sicoobito:packages:changed"));

    expect(await screen.findByText("flask")).toBeInTheDocument();
  });
});
