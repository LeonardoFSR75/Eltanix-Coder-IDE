import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SearchPanel } from "./Panels";
import * as semanticApi from "@/lib/api/searchSemantic";

const openFile = vi.fn();

vi.mock("@/lib/ide-store", () => ({
  useIde: () => ({ project: "meu-projeto", openFile, bumpRevision: vi.fn() }),
}));

vi.mock("@/lib/api/workspace", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/workspace")>(
    "@/lib/api/workspace",
  );
  return { ...actual, searchWorkspace: vi.fn(), replaceInWorkspace: vi.fn() };
});

vi.mock("@/lib/api/searchSemantic", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/searchSemantic")>(
    "@/lib/api/searchSemantic",
  );
  return {
    ...actual,
    semanticSearch: vi.fn(),
    contextIndexStatus: vi.fn(),
    indexContext: vi.fn(),
  };
});

const mockedSem = vi.mocked(semanticApi);

function hit(overrides: Partial<semanticApi.SemanticHit> = {}): semanticApi.SemanticHit {
  return {
    path: "src/eltanix/auth/service.py",
    citation: "src/eltanix/auth/service.py:40",
    symbol: "_verify_second_factor",
    parent: "AuthService",
    kind: "function",
    start_line: 40,
    end_line: 58,
    language: "python",
    token_count: 120,
    score: 0.83,
    vector_rank: 1,
    text_rank: 2,
    content: "def _verify_second_factor(self, ...):\n    ...",
    ...overrides,
  };
}

describe("SearchPanel — busca semântica (Onda 1.4)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("mostra os trechos e abre o arquivo na linha inicial ao clicar", async () => {
    mockedSem.semanticSearch.mockResolvedValue({
      query: "validação do segundo fator",
      hits: [hit()],
    });
    render(<SearchPanel />);

    await userEvent.click(screen.getByRole("button", { name: /Semântica/ }));
    await userEvent.type(
      screen.getByPlaceholderText(/Descreva o que procura/),
      "validação do segundo fator",
    );
    await userEvent.click(screen.getByRole("button", { name: "Localizar" }));

    expect(await screen.findByText("service.py")).toBeInTheDocument();
    expect(screen.getByText("function _verify_second_factor")).toBeInTheDocument();

    await userEvent.click(screen.getByText("service.py"));
    expect(openFile).toHaveBeenCalledWith("src/eltanix/auth/service.py", {
      line: 40,
      column: 1,
    });
  });

  it("oferece indexar quando não há trechos e o projeto não está indexado", async () => {
    mockedSem.semanticSearch.mockResolvedValue({ query: "x", hits: [] });
    mockedSem.contextIndexStatus.mockResolvedValue({
      workspace: "meu-projeto",
      files: 0,
      chunks: 0,
      total_tokens: 0,
      chunks_with_embedding: 0,
      files_line_chunked: 0,
      by_language: [],
    });
    mockedSem.indexContext.mockResolvedValue({
      workspace: "meu-projeto",
      scanned: 10,
      indexed: 10,
      skipped_unchanged: 0,
      removed: 0,
      chunks: 42,
      embedded: 42,
      embedding_failures: 0,
      duration_ms: 1200,
      errors: [],
    });

    render(<SearchPanel />);
    await userEvent.click(screen.getByRole("button", { name: /Semântica/ }));
    await userEvent.type(screen.getByPlaceholderText(/Descreva o que procura/), "qualquer");
    await userEvent.click(screen.getByRole("button", { name: "Localizar" }));

    const indexar = await screen.findByRole("button", { name: "Indexar agora" });
    mockedSem.semanticSearch.mockResolvedValue({ query: "qualquer", hits: [hit()] });
    await userEvent.click(indexar);

    await waitFor(() => expect(mockedSem.indexContext).toHaveBeenCalledWith("meu-projeto"));
    expect(await screen.findByText("service.py")).toBeInTheDocument();
  });

  it("não mostra o campo de substituição no modo semântico", async () => {
    render(<SearchPanel />);
    // modo texto: o toggle de substituir existe
    expect(screen.getByTitle("Alternar campo de Substituir")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Semântica/ }));
    expect(screen.queryByTitle("Alternar campo de Substituir")).not.toBeInTheDocument();
  });
});
