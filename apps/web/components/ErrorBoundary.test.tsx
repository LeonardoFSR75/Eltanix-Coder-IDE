import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi, afterEach } from "vitest";
import { ErrorBoundary } from "./ErrorBoundary";

function Boom({ explode }: { explode: boolean }): React.ReactElement {
  if (explode) throw new Error("kaboom");
  return <div>conteúdo ok</div>;
}

describe("ErrorBoundary", () => {
  afterEach(() => vi.restoreAllMocks());

  it("renderiza os filhos quando não há erro", () => {
    render(
      <ErrorBoundary label="Editor">
        <Boom explode={false} />
      </ErrorBoundary>,
    );
    expect(screen.getByText("conteúdo ok")).toBeInTheDocument();
  });

  it("mostra o fallback com o label e a mensagem quando um filho lança", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary label="Editor">
        <Boom explode={true} />
      </ErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Editor falhou");
    expect(screen.getByRole("alert")).toHaveTextContent("kaboom");
  });

  it("recupera quando o pai re-renderiza com filhos que não lançam mais", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const onReset = vi.fn();

    function Pai() {
      const [explode, setExplode] = useState(true);
      return (
        <ErrorBoundary
          label="Editor"
          onReset={() => {
            setExplode(false);
            onReset();
          }}
        >
          <Boom explode={explode} />
        </ErrorBoundary>
      );
    }

    render(<Pai />);
    expect(screen.getByRole("alert")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Tentar novamente" }));

    expect(onReset).toHaveBeenCalledOnce();
    expect(screen.getByText("conteúdo ok")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("usa o fallback custom quando fornecido", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary fallback={(err) => <p>custom: {err.message}</p>}>
        <Boom explode={true} />
      </ErrorBoundary>,
    );
    expect(screen.getByText("custom: kaboom")).toBeInTheDocument();
  });
});
