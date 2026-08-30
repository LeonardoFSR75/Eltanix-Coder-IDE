/**
 * Regressão do identificador de projeto.
 *
 * O IDE guardava o `name` de exibição ("Meu Dash") onde a API espera o `slug`
 * ("meu-dash"), então todo request saía como `?project=Meu Dash` e voltava
 * 400 "Projeto não encontrado" — Explorer, busca, git, LSP e agente quebravam
 * juntos. O bug ficou escondido enquanto todo projeto vinha da descoberta de
 * disco (`slug === name`); o primeiro projeto criado pela Central, que
 * slugifica o nome, expôs a divergência.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { IdeProvider, useIde } from "@/lib/ide-store";
import { ProjectProvider } from "@/components/providers/ProjectContext";
import * as client from "@/lib/client";

vi.mock("@/lib/client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/client")>("@/lib/client");
  return { ...actual, get: vi.fn(), post: vi.fn() };
});

vi.mock("@/components/providers/AuthContext", () => ({
  useAuth: () => ({ user: { username: "leo" } }),
}));

vi.mock("next/navigation", () => ({ usePathname: () => "/ide" }));

const mockedGet = vi.mocked(client.get);
const mockedPost = vi.mocked(client.post);

function projeto(slug: string, name: string, extra: Record<string, unknown> = {}) {
  return {
    id: slug,
    slug,
    name,
    description: "",
    local_path: `/projects/${slug}`,
    local_path_exists: true,
    git_url: null,
    default_branch: "main",
    budget_limit_usd: null,
    settings: {},
    ...extra,
  };
}

function Sonda() {
  const { project, projectName } = useIde();
  return (
    <>
      <span data-testid="slug">{project ?? "—"}</span>
      <span data-testid="nome">{projectName ?? "—"}</span>
    </>
  );
}

function montar() {
  return render(
    <ProjectProvider>
      <IdeProvider>
        <Sonda />
      </IdeProvider>
    </ProjectProvider>,
  );
}

describe("ide-store · identificador de projeto", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    mockedPost.mockResolvedValue({} as never);
    mockedGet.mockImplementation(async (url: string) => {
      if (url.startsWith("/api/projects")) {
        return { projects: [projeto("meu-dash", "Meu Dash")] } as never;
      }
      return { files: [], matches: [] } as never;
    });
  });

  it("seleciona o projeto pelo slug, não pelo nome de exibição", async () => {
    montar();
    await waitFor(() => expect(screen.getByTestId("slug")).toHaveTextContent("meu-dash"));
    expect(screen.getByTestId("nome")).toHaveTextContent("Meu Dash");
  });

  it("manda o slug em `?project=` — nunca o nome com espaço/maiúscula", async () => {
    montar();
    await waitFor(() =>
      expect(mockedGet).toHaveBeenCalledWith(expect.stringContaining("/api/workspace/files")),
    );
    const urls = mockedGet.mock.calls.map(([url]) => String(url));
    const doWorkspace = urls.filter((u) => u.includes("project="));
    expect(doWorkspace.length).toBeGreaterThan(0);
    for (const url of doWorkspace) {
      expect(url).toContain("project=meu-dash");
      expect(url).not.toContain("Meu");
    }
  });

  it("migra um `name` já persistido no localStorage para o slug correspondente", async () => {
    // Estado deixado pela versão quebrada no navegador de quem já usou a IDE.
    window.localStorage.setItem(
      "eltanix.ide",
      JSON.stringify({ project: "Meu Dash", tabs: [], active: null }),
    );
    montar();
    await waitFor(() => expect(screen.getByTestId("slug")).toHaveTextContent("meu-dash"));
  });

  it("não abre automaticamente num projeto cuja pasta sumiu do disco", async () => {
    mockedGet.mockImplementation(async (url: string) => {
      if (url.startsWith("/api/projects")) {
        return {
          projects: [
            projeto("fantasma", "Fantasma", { local_path_exists: false }),
            projeto("meu-dash", "Meu Dash"),
          ],
        } as never;
      }
      return { files: [] } as never;
    });
    montar();
    await waitFor(() => expect(screen.getByTestId("slug")).toHaveTextContent("meu-dash"));
  });
});
