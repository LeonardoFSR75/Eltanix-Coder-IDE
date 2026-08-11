/**
 * Motor de uma sessão do agente, sem hook do React.
 *
 * `useAgentSession` (versão anterior a esta fase) prendia todo o estado da
 * sessão a `useState` — o que funciona para uma sessão só, mas hooks não
 * podem ser instanciados dinamicamente em quantidade variável (uma por
 * sessão aberta). Para o Agent Manager rodar N sessões em paralelo na mesma
 * aba, o estado precisa viver fora de componente: `AgentSessionRuntime` é um
 * objeto plano com os mesmos campos de antes, e quem quiser reagir a
 * mudanças assina `onChange`. `useAgentSessions` (o hook) só guarda um mapa
 * desses objetos e força um re-render quando qualquer um muda.
 */

import { get, post, streamEvents } from "@/lib/client";
import type { Mode } from "./modes";
import type { LogLine, PendingAction, Session, TodoItem } from "./sessionTypes";

export type { LogLine, PendingAction, Session, TodoItem };

export type NotifyKind = "approval" | "done" | "error";

interface RuntimeOptions {
  project: string;
  onFileTouched?: (path: string) => void;
  onChange: () => void;
  // Hooks mínimos (client-side, sem execução de código): quem monta o
  // runtime decide se/como avisar o usuário sobre estes três eventos.
  onNotify?: (kind: NotifyKind, message: string) => void;
}

export class AgentSessionRuntime {
  session: Session | null = null;
  task = "";
  log: LogLine[] = [];
  pending: PendingAction[] = [];
  running = false;
  todos: TodoItem[] = [];
  // Sessão carregada do histórico (via /messages), sem stream ativo — o
  // card de aprovação e o input de chat ficam desabilitados para ela.
  readOnly = false;
  finished = false;
  errored = false;

  private readonly project: string;
  private readonly onFileTouched?: (path: string) => void;
  private readonly onChange: () => void;
  private readonly onNotify?: (kind: NotifyKind, message: string) => void;
  private abortController: AbortController | null = null;

  constructor(opts: RuntimeOptions) {
    this.project = opts.project;
    this.onFileTouched = opts.onFileTouched;
    this.onChange = opts.onChange;
    this.onNotify = opts.onNotify;
  }

  private append(line: LogLine) {
    this.log = [...this.log, line];
    this.onChange();
  }

  private consume = (event: unknown) => {
    const { node, update } = (event ?? {}) as { node?: string; update?: Record<string, unknown> };
    if (!node || !update) return;

    if (node === "error") {
      this.errored = true;
      const mensagem = String(update.message ?? "erro desconhecido");
      this.append({ kind: "error", text: mensagem });
      this.onNotify?.("error", mensagem);
      return;
    }

    if (node === "interrupt" || update.type === "approval_required") {
      this.pending = (update.actions ?? []) as PendingAction[];
      this.running = false;
      this.onChange();
      if (this.pending.length > 0) {
        this.onNotify?.("approval", `${this.pending.length} ação(ões) aguardando aprovação`);
      }
      return;
    }

    if (node === "think") {
      const messages = (update.messages ?? []) as Array<Record<string, unknown>>;
      for (const message of messages) {
        const content = message.content;
        if (typeof content === "string" && content.trim()) {
          this.append({ kind: "assistant", text: content });
        }
      }
      if (typeof update.total_cost_usd === "number") {
        this.append({
          kind: "cost",
          text: `${update.total_tokens ?? 0} tokens · $${Number(update.total_cost_usd).toFixed(4)}`,
        });
      }
      const acoes = (update.pending ?? []) as PendingAction[];
      if (acoes.length > 0) {
        this.pending = acoes;
        this.onChange();
        this.onNotify?.("approval", `${acoes.length} ação(ões) aguardando aprovação`);
      }
      if (update.finished === true) {
        this.finished = true;
        this.onChange();
        this.onNotify?.("done", `Sessão concluída: ${this.task || this.session?.session_id || ""}`);
      }
    }

    if (node === "act") {
      const messages = (update.messages ?? []) as Array<Record<string, unknown>>;
      for (const message of messages) {
        const content = String(message.content ?? "");
        this.append({
          kind: "tool",
          text: `${message.name}: ${content.slice(0, 1200)}`,
          tool: String(message.name ?? ""),
          toolCallId: String(message.tool_call_id ?? ""),
          toolOk: message.ok !== false,
          toolData: (message.data ?? {}) as Record<string, unknown>,
          toolContent: content,
        });
      }
      for (const path of (update.files_changed ?? []) as string[]) {
        this.onFileTouched?.(path);
      }
      if (Array.isArray(update.todos)) {
        this.todos = update.todos as TodoItem[];
        this.onChange();
      }
    }
  };

  async run(approvals?: Record<string, { approved: boolean; reason: string }>) {
    // Mesma guarda de `sendMessage`: sem isso, um duplo clique em "Aprovar
    // Tudo" (ou aprovar seguido de recusar antes do card sumir) dispara duas
    // chamadas concorrentes, e a segunda sobrescreve `abortController` da
    // primeira, órfãozando o stream anterior sem forma de abortá-lo.
    if (!this.session || this.running) return;
    this.running = true;
    this.pending = [];
    this.onChange();
    this.abortController = new AbortController();

    try {
      await streamEvents(
        `/api/agent/sessions/${this.session.session_id}/run`,
        approvals ? { approvals } : {},
        this.consume,
        this.abortController.signal,
      );
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        this.errored = true;
        this.append({ kind: "error", text: err instanceof Error ? err.message : String(err) });
      }
    } finally {
      this.running = false;
      this.onChange();
    }
  }

  async decide(decisions: Record<string, boolean>) {
    if (!this.session || this.running) return;
    const approvals = Object.fromEntries(
      this.pending.map((action) => {
        const approved = decisions[action.tool_call_id] ?? false;
        return [action.tool_call_id, { approved, reason: approved ? "" : "recusado pelo usuário" }];
      }),
    );
    const aprovadas = this.pending.filter((a) => decisions[a.tool_call_id]).length;
    this.append({ kind: "info", text: `${aprovadas}/${this.pending.length} ação(ões) aprovada(s)` });
    await this.run(approvals);
  }

  async sendMessage(text: string) {

    if (!this.session || this.running) return;
    this.append({ kind: "user", text });
    this.finished = false;
    this.errored = false;
    this.running = true;
    this.pending = [];
    this.onChange();
    this.abortController = new AbortController();

    try {
      await streamEvents(
        `/api/agent/sessions/${this.session.session_id}/run`,
        { message: text },
        this.consume,
        this.abortController.signal,
      );
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        this.errored = true;
        this.append({ kind: "error", text: err instanceof Error ? err.message : String(err) });
      }
    } finally {
      this.running = false;
      this.onChange();
    }
  }

  abort() {
    this.abortController?.abort();
  }


  /** Cria a sessão no backend e devolve o runtime já com `session` preenchido — sem esperar o turno terminar. */
  static async start(
    opts: RuntimeOptions,
    task: string,
    mode: Mode,
    profile?: string | null,
    focusFiles?: string[],
    focusFolder?: string | null,
  ): Promise<AgentSessionRuntime> {
    const runtime = new AgentSessionRuntime(opts);
    runtime.task = task;
    // ── Exibe a mensagem do usuário imediatamente, antes de ir ao backend ──
    runtime.append({ kind: "user", text: task });
    const created = await post<Session>("/api/agent/sessions", {
      task,
      mode,
      project: opts.project,
      profile: profile || undefined,
      focus_files: focusFiles ?? [],
      focus_folder: focusFolder ?? undefined,
    });
    runtime.session = created;
    runtime.append({
      kind: "info",
      text: `sessão ${created.session_id} · branch ${created.branch || "(nenhum)"}`,
    });
    for (const aviso of created.warnings ?? []) {
      runtime.append({ kind: "error", text: aviso });
    }
    // Não aguardamos o turno inteiro aqui: o chamador já registra o runtime
    // no mapa assim que `session` existe, e o primeiro `run()` continua em
    // segundo plano, notificando via `onChange` a cada evento SSE.
    void runtime.run();
    return runtime;
  }

  /** Carrega o transcript real de uma sessão encerrada (sem stream, somente leitura). */
  static async loadClosed(
    sessionId: string,
    opts: Omit<RuntimeOptions, "project"> & { project: string },
    task = "",
  ): Promise<AgentSessionRuntime> {
    const runtime = new AgentSessionRuntime(opts);
    runtime.readOnly = true;
    runtime.finished = true;
    runtime.task = task;
    try {
      const data = await get<{
        session_id: string;
        branch: string;
        messages: Array<Record<string, unknown>>;
      }>(`/api/agent/sessions/${sessionId}/messages`);
      runtime.session = {
        session_id: data.session_id,
        branch: data.branch ?? "",
        worktree_path: "",
        sandbox_available: false,
        sandbox_error: null,
        github_available: false,
        warnings: [],
      };
      for (const message of data.messages ?? []) {
        runtime.log.push(...messageToLogLines(message));
      }
    } catch (err) {
      runtime.append({
        kind: "error",
        text: err instanceof Error ? err.message : "não foi possível carregar o transcript",
      });
    }
    return runtime;
  }
}

function messageToLogLines(message: Record<string, unknown>): LogLine[] {
  const role = message.role;
  if (role === "user") {
    const content = message.content;
    if (typeof content === "string" && content.trim()) {
      return [{ kind: "user", text: content }];
    }
    return [];
  }
  if (role === "assistant") {
    const content = message.content;
    if (typeof content === "string" && content.trim()) {
      return [{ kind: "assistant", text: content }];
    }
    return [];
  }
  if (role === "tool") {
    const content = String(message.content ?? "");
    return [
      {
        kind: "tool",
        text: `${message.name}: ${content.slice(0, 1200)}`,
        tool: String(message.name ?? ""),
        toolCallId: String(message.tool_call_id ?? ""),
        toolOk: message.ok !== false,
        toolData: (message.data ?? {}) as Record<string, unknown>,
        toolContent: content,
      },
    ];
  }
  return [];
}
