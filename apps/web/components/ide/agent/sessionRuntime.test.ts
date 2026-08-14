import { describe, expect, it, vi } from "vitest";
import { AgentSessionRuntime } from "./sessionRuntime";

describe("AgentSessionRuntime", () => {
  it("blocks sending while approval is pending", () => {
    const runtime = new AgentSessionRuntime({
      project: "demo",
      onChange: vi.fn(),
    });

    runtime.session = {
      session_id: "sess-1",
      branch: "main",
      worktree_path: "/tmp/demo",
      sandbox_available: true,
      sandbox_error: null,
      github_available: false,
      warnings: [],
    };

    runtime.pending = [
      {
        tool_call_id: "call-1",
        tool: "shell",
        risk: "exec",
        arguments: { cmd: "echo hi" },
        summary: "Executar comando de shell",
      },
    ];

    expect(runtime.canSubmit).toBe(false);
    expect(runtime.awaitingApproval).toBe(true);
  });

  it("allows sending when session is ready and idle", () => {
    const runtime = new AgentSessionRuntime({
      project: "demo",
      onChange: vi.fn(),
    });

    runtime.session = {
      session_id: "sess-2",
      branch: "main",
      worktree_path: "/tmp/demo",
      sandbox_available: true,
      sandbox_error: null,
      github_available: false,
      warnings: [],
    };

    expect(runtime.canSubmit).toBe(true);
  });

  it("blocks sending when running", () => {
    const runtime = new AgentSessionRuntime({
      project: "demo",
      onChange: vi.fn(),
    });

    runtime.session = {
      session_id: "sess-3",
      branch: "main",
      worktree_path: "/tmp/demo",
      sandbox_available: true,
      sandbox_error: null,
      github_available: false,
      warnings: [],
    };

    runtime.running = true;
    expect(runtime.canSubmit).toBe(false);
  });

  it("ignores duplicate user entries in the timeline", () => {
    const runtime = new AgentSessionRuntime({
      project: "demo",
      onChange: vi.fn(),
    });

    const append = (runtime as any).append.bind(runtime);
    append({ kind: "user", text: "repetir mensagem" });
    append({ kind: "user", text: "repetir mensagem" });

    expect(runtime.log.filter((line) => line.kind === "user")).toHaveLength(1);
  });
});
