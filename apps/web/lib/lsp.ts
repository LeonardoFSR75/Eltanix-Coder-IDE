/**
 * Cliente LSP mínimo, escrito à mão.
 *
 * A rota conhecida seria `monaco-languageclient` + `@codingame/monaco-vscode-api`,
 * que reimplementa parte da camada de serviços do VS Code para reaproveitar o
 * cliente oficial. Custa uma árvore de dependências grande, exige substituir o
 * carregamento do Monaco e é notoriamente sensível ao empacotador — num app
 * Next.js com App Router, cada atualização vira um dia de depuração de build.
 *
 * O que o editor precisa de fato é um punhado de requisições (completar, hover,
 * definição, referências, símbolos, formatar) e uma notificação (diagnósticos).
 * Falar JSON-RPC direto e converter para as APIs nativas do Monaco cabe neste
 * arquivo, não tem dependência nova, e o dia em que quebrar é um dia que eu
 * consigo depurar.
 *
 * O que se perde: recursos que o cliente oficial traz de graça — code actions,
 * renomear em vários arquivos, semantic tokens, call hierarchy. São adições
 * incrementais aqui, não um redesenho.
 */

import { get, post } from "@/lib/client";

type Json = Record<string, unknown>;

export interface Position {
  line: number;
  character: number;
}

export interface Range {
  start: Position;
  end: Position;
}

export interface Diagnostic {
  range: Range;
  severity?: number;
  code?: string | number;
  source?: string;
  message: string;
}

interface Pendente {
  resolve: (valor: unknown) => void;
  reject: (erro: Error) => void;
  timer: ReturnType<typeof setTimeout>;
}

/** Requisições que o servidor faz ao cliente e que exigem resposta.
 *
 * Ignorá-las não é inofensivo: o pyright bloqueia esperando `workspace/configuration`
 * antes de emitir o primeiro diagnóstico, e o sintoma é um editor que conecta,
 * não dá erro, e simplesmente nunca responde nada.
 */
const RESPOSTAS_AUTOMATICAS: Record<string, (params: Json) => unknown> = {
  "client/registerCapability": () => null,
  "client/unregisterCapability": () => null,
  "window/workDoneProgress/create": () => null,
  "workspace/semanticTokens/refresh": () => null,
  "workspace/diagnostic/refresh": () => null,
  "workspace/inlayHint/refresh": () => null,
  // Um item de configuração por pedido; `null` significa "use o padrão".
  "workspace/configuration": (params) => ((params?.items as unknown[]) ?? []).map(() => null),
};

const TIMEOUT_MS = 20_000;

export class LspConnection {
  private socket: WebSocket | null = null;
  private proximoId = 1;
  private pendentes = new Map<number, Pendente>();
  private fila: string[] = [];
  private diagnosticListeners = new Set<(path: string, itens: Diagnostic[]) => void>();
  private estadoListeners = new Set<(pronto: boolean, erro: string | null) => void>();
  private fechando = false;

  /** Contadores de diagnóstico, lidos pela janela `__novaai_studioLsp`. */
  readonly stats = { enviadas: 0, recebidas: 0, diagnosticos: 0, ouvintes: 0 };

  /** Capacidades anunciadas pelo servidor no `initialize`. */
  capabilities: Json = {};
  ready = false;
  error: string | null = null;

  constructor(
    readonly project: string,
    readonly language: string,
  ) {}

  // ── ciclo de vida ──────────────────────────────────────────────────────

  async connect(): Promise<void> {
    const { ticket } = await post<{ ticket: string }>(
      `/api/lsp/ticket?project=${encodeURIComponent(this.project)}&language=${encodeURIComponent(this.language)}`,
    );

    const origem =
      process.env.NEXT_PUBLIC_API_ORIGIN ??
      `${window.location.protocol}//${window.location.hostname}:5401`;
    const url =
      `${origem.replace(/^http/, "ws")}/api/lsp/${encodeURIComponent(this.project)}/` +
      `${encodeURIComponent(this.language)}?ticket=${encodeURIComponent(ticket)}`;

    await new Promise<void>((resolve, reject) => {
      const socket = new WebSocket(url);
      this.socket = socket;
      socket.onopen = () => resolve();
      socket.onerror = () => reject(new Error("não foi possível abrir o canal do language server"));
      socket.onmessage = (evento) => this.receber(evento.data as string);
      socket.onclose = () => this.aoFechar();
    });

    const resultado = (await this.request("initialize", {
      // A ponte preenche rootUri e workspaceFolders: só ela conhece o caminho
      // do projeto dentro do container.
      capabilities: CAPACIDADES_DO_CLIENTE,
      clientInfo: { name: "NovaAI Studio", version: "0.1.0" },
    })) as Json;

    this.capabilities = (resultado?.capabilities as Json) ?? {};
    this.notify("initialized", {});
    this.ready = true;
    this.emitirEstado();
  }

  close(): void {
    this.fechando = true;
    this.socket?.close();
    this.socket = null;
    for (const pendente of this.pendentes.values()) {
      clearTimeout(pendente.timer);
      pendente.reject(new Error("conexão encerrada"));
    }
    this.pendentes.clear();
  }

  /** Definido por `getConnection` para tirar a conexão morta do cache. */
  onClosed: (() => void) | null = null;

  private aoFechar(): void {
    this.ready = false;
    if (!this.fechando) this.error = "o language server caiu";
    this.emitirEstado();
    this.onClosed?.();
  }

  // ── JSON-RPC ───────────────────────────────────────────────────────────

  request(method: string, params?: unknown): Promise<unknown> {
    const id = this.proximoId++;
    const promessa = new Promise<unknown>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pendentes.delete(id);
        reject(new Error(`${method} não respondeu em ${TIMEOUT_MS / 1000}s`));
      }, TIMEOUT_MS);
      this.pendentes.set(id, { resolve, reject, timer });
    });
    this.enviar({ jsonrpc: "2.0", id, method, params: params ?? {} });
    return promessa;
  }

  notify(method: string, params?: unknown): void {
    this.enviar({ jsonrpc: "2.0", method, params: params ?? {} });
  }

  private enviar(mensagem: Json): void {
    this.stats.enviadas += 1;
    const texto = JSON.stringify(mensagem);
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(texto);
      return;
    }
    // Enfileirar em vez de descartar: o `didOpen` do arquivo que já estava
    // aberto costuma sair antes de o socket terminar de abrir, e perdê-lo
    // deixaria o servidor sem saber que o documento existe.
    this.fila.push(texto);
    if (this.socket?.readyState === WebSocket.CONNECTING) {
      this.socket.addEventListener("open", () => this.drenar(), { once: true });
    }
  }

  private drenar(): void {
    const pendentes = this.fila.splice(0);
    for (const texto of pendentes) this.socket?.send(texto);
  }

  private receber(bruto: string): void {
    this.stats.recebidas += 1;
    let mensagem: Json;
    try {
      mensagem = JSON.parse(bruto) as Json;
    } catch {
      return;
    }

    const id = mensagem.id as number | undefined;
    const method = mensagem.method as string | undefined;

    // Resposta a algo que pedimos.
    if (id !== undefined && method === undefined) {
      const pendente = this.pendentes.get(id);
      if (!pendente) return;
      clearTimeout(pendente.timer);
      this.pendentes.delete(id);
      if (mensagem.error) {
        const erro = mensagem.error as { message?: string };
        pendente.reject(new Error(erro.message ?? "erro do language server"));
      } else {
        pendente.resolve(mensagem.result);
      }
      return;
    }

    if (!method) return;

    // Requisição do servidor para nós.
    if (id !== undefined) {
      const responder = RESPOSTAS_AUTOMATICAS[method];
      this.enviar(
        responder
          ? { jsonrpc: "2.0", id, result: responder((mensagem.params as Json) ?? {}) }
          : { jsonrpc: "2.0", id, error: { code: -32601, message: `sem suporte: ${method}` } },
      );
      return;
    }

    // Notificação.
    if (method === "textDocument/publishDiagnostics") {
      const params = (mensagem.params as Json) ?? {};
      const path = String(params.uri ?? "");
      const itens = (params.diagnostics as Diagnostic[]) ?? [];
      this.stats.diagnosticos += 1;
      this.stats.ouvintes = this.diagnosticListeners.size;
      for (const ouvinte of this.diagnosticListeners) ouvinte(path, itens);
      return;
    }

    if (method === "novaai_studio/error") {
      this.error = String(mensagem.params ?? "falha no language server");
      this.emitirEstado();
    }
  }

  // ── assinaturas ────────────────────────────────────────────────────────

  onDiagnostics(ouvinte: (path: string, itens: Diagnostic[]) => void): () => void {
    this.diagnosticListeners.add(ouvinte);
    return () => this.diagnosticListeners.delete(ouvinte);
  }

  onStateChange(ouvinte: (pronto: boolean, erro: string | null) => void): () => void {
    this.estadoListeners.add(ouvinte);
    ouvinte(this.ready, this.error);
    return () => this.estadoListeners.delete(ouvinte);
  }

  private emitirEstado(): void {
    for (const ouvinte of this.estadoListeners) ouvinte(this.ready, this.error);
  }

  /** Como o servidor quer receber mudanças: 0 nenhuma, 1 texto inteiro, 2 incremental. */
  get syncKind(): number {
    const sync = this.capabilities.textDocumentSync;
    if (typeof sync === "number") return sync;
    if (sync && typeof sync === "object") {
      const change = (sync as Json).change;
      if (typeof change === "number") return change;
    }
    return 1;
  }

  supports(capability: string): boolean {
    return Boolean(this.capabilities[capability]);
  }
}

const CAPACIDADES_DO_CLIENTE = {
  textDocument: {
    synchronization: { dynamicRegistration: false, didSave: true },
    publishDiagnostics: { relatedInformation: false },
    completion: {
      dynamicRegistration: false,
      completionItem: {
        snippetSupport: true,
        documentationFormat: ["markdown", "plaintext"],
        insertReplaceSupport: false,
        resolveSupport: { properties: ["documentation", "detail"] },
      },
      contextSupport: true,
    },
    hover: { dynamicRegistration: false, contentFormat: ["markdown", "plaintext"] },
    definition: { dynamicRegistration: false, linkSupport: true },
    references: { dynamicRegistration: false },
    documentSymbol: { dynamicRegistration: false, hierarchicalDocumentSymbolSupport: true },
    signatureHelp: {
      dynamicRegistration: false,
      signatureInformation: { documentationFormat: ["markdown", "plaintext"] },
    },
    formatting: { dynamicRegistration: false },
  },
  workspace: {
    // `workspaceFolders` está deliberadamente **ausente**.
    //
    // Declará-lo faz o pyright parar de publicar diagnósticos: ele passa a
    // tratar o workspace como multi-raiz e nunca chega a analisar nada. Não há
    // erro, não há log — o editor conecta, responde ao `initialize` e fica
    // mudo. Isolado por bisseção das capacidades; com `rootUri` sozinho, os
    // diagnósticos chegam em ~7s.
    //
    // Não perdemos nada: uma conexão serve a um projeto, então uma raiz é
    // tudo de que precisamos.
    configuration: true,
    didChangeConfiguration: { dynamicRegistration: false },
  },
  // Sem isto o pyright emite `$/progress` para um token que nunca criamos.
  window: { workDoneProgress: true },
};

/** Uma conexão por (projeto, linguagem) — é o escopo natural do protocolo. */
const conexoes = new Map<string, Promise<LspConnection>>();

export function getConnection(project: string, language: string): Promise<LspConnection> {
  const chave = `${project}::${language}`;
  const existente = conexoes.get(chave);
  if (existente) return existente;

  const promessa = (async () => {
    const conexao = new LspConnection(project, language);
    // Uma conexão morta não pode continuar em cache: sem isto, um servidor que
    // caiu deixaria o editor sem inteligência de código até recarregar a
    // página, porque toda abertura de arquivo receberia o cadáver de volta.
    conexao.onClosed = () => {
      if (conexoes.get(chave) === promessa) conexoes.delete(chave);
    };
    await conexao.connect();
    return conexao;
  })().catch((erro) => {
    // Falha não pode ficar em cache: a próxima abertura de arquivo tentaria de
    // novo e receberia a mesma rejeição para sempre.
    conexoes.delete(chave);
    throw erro;
  });

  conexoes.set(chave, promessa);
  return promessa;
}

export function closeConnectionsFor(project: string | null): void {
  for (const [chave, promessa] of conexoes) {
    if (project !== null && !chave.startsWith(`${project}::`)) continue;
    conexoes.delete(chave);
    void promessa.then((c) => c.close()).catch(() => {});
  }
}

/** Linguagens com servidor instalado na imagem. Vazio = nenhuma. */
let suportadas: Promise<Record<string, string>> | null = null;

export function supportedLanguages(): Promise<Record<string, string>> {
  if (!suportadas) {
    suportadas = get<{ languages: Record<string, string> }>("/api/lsp/languages")
      .then((r) => r.languages)
      .catch(() => ({}));
  }
  return suportadas;
}
