import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { InlineEditHunkReview } from "@/components/ide/InlineEditHunkReview";
import type { InlineEditHunk } from "@/lib/api/inlineEdit";

const hunks: InlineEditHunk[] = [
  {
    id: "h1",
    before_start: 2,
    before_lines: ["b\n"],
    after_lines: ["B\n"],
    context_before: ["a\n"],
    context_after: ["c\n"],
  },
  {
    id: "h2",
    before_start: 5,
    before_lines: ["e\n", "f\n"],
    after_lines: ["E\n", "EE\n"],
    context_before: ["d\n"],
    context_after: ["g\n"],
  },
];

describe("InlineEditHunkReview", () => {
  it("starts with every hunk accepted", () => {
    render(
      <InlineEditHunkReview hunks={hunks} onApply={() => {}} onCancel={() => {}} />,
    );
    expect(screen.getByText("Aplicar 2 de 2")).toBeInTheDocument();
    for (const box of screen.getAllByRole("checkbox")) {
      expect(box).toBeChecked();
    }
  });

  it("only reports the still-checked hunk ids on apply", () => {
    const onApply = vi.fn();
    render(
      <InlineEditHunkReview hunks={hunks} onApply={onApply} onCancel={() => {}} />,
    );
    fireEvent.click(screen.getAllByRole("checkbox")[0]);
    expect(screen.getByText("Aplicar 1 de 2")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Aplicar 1 de 2"));
    expect(onApply).toHaveBeenCalledWith(["h2"]);
  });

  it("disables controls and calls onCancel", () => {
    const onCancel = vi.fn();
    render(
      <InlineEditHunkReview
        hunks={hunks}
        busy
        onApply={() => {}}
        onCancel={onCancel}
      />,
    );
    expect(screen.getByText("aplicando…")).toBeDisabled();
    const cancel = screen.getByText("cancelar");
    expect(cancel).toBeDisabled();
    fireEvent.click(cancel);
    expect(onCancel).not.toHaveBeenCalled();
  });
});
