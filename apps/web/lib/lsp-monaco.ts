/**
 * Liga o cliente LSP às APIs nativas do Monaco.
 *
 * O trabalho aqui é quase todo conversão de coordenadas e de enums. Duas
 * armadilhas que o código trata explicitamente:
 *
 * - **Base das posições.** O LSP conta linhas e colunas a partir de zero; o
 *   Monaco, a partir de um. Um erro de um aqui não quebra nada de forma
 *   visível: o autocomplete só fica sutilmente deslocado, e ninguém desconfia
 *   da conversão.
 * - **Numeração dos enums.** `CompletionItemKind` existe nos dois lados com
 *   valores diferentes. Sem a tabela, "função" aparece como "texto" e os
 *   ícones ficam todos errados.
 */

import type * as Monaco from "monaco-editor";
import type { Diagnostic, LspConnection, Range as LspRange } from "@/lib/lsp";

type MonacoNs = typeof Monaco;

// ── conversões ────────────────────────────────────────────────────────────

function paraPosicaoLsp(posicao: Monaco.IPosition) {
  return { line: posicao.lineNumber - 1, character: posicao.column - 1 };
}

function paraRangeMonaco(range: LspRange): Monaco.IRange {
  return {
    startLineNumber: range.start.line + 1,
    startColumn: range.start.character + 1,
    endLineNumber: range.end.line + 1,
    endColumn: range.end.character + 1,
  };
}

// LSP CompletionItemKind (1..25) → Monaco. Índice 0 não é usado.
const KIND_COMPLETION = [
  0, 18, 0, 1, 2, 3, 4, 5, 7, 8, 9, 12, 13, 15, 17, 27, 19, 20, 21, 23, 16, 14, 6, 10, 11, 24,
];

// LSP DiagnosticSeverity → MarkerSeverity do Monaco (Hint 1, Info 2, Warning 4, Error 8).
const SEVERIDADE = [8, 8, 4, 2, 1];

function textoDeDocumentacao(valor: unknown): Monaco.IMarkdownString | string | undefined {
  if (!valor) return undefined;
  if (typeof valor === "string") return valor;
  const objeto = valor as { kind?: string; value?: string };
  if (typeof objeto.value !== "string") return undefined;
  return objeto.kind === "markdown" ? { value: objeto.value, isTrusted: false } : objeto.value;
}

// ── documento ativo ───────────────────────────────────────────────────────

/**
 * O editor lado a lado (Fase 6) pode ter N modelos do Monaco vivos ao mesmo
 * tempo, um por painel — daí o registro ser por modelo, e não uma única
 * variável "documento atual". Cada `<Editor>` só troca o conteúdo do SEU
 * próprio modelo ao mudar de aba, então o modelo em si já é uma chave estável
 * por painel: usar um único slot global faria o segundo painel a abrir um
 * arquivo emitir `didClose` no documento que o primeiro painel ainda mostra
 * em tela, sem que a UI dele saiba.
 */
interface DocumentoAtivo {
  model: Monaco.editor.ITextModel;
  path: string;
  connection: LspConnection;
  version: number;
}

const documentos = new Map<Monaco.editor.ITextModel, DocumentoAtivo>();

function documentoDe(model: Monaco.editor.ITextModel): DocumentoAtivo | null {
  return documentos.get(model) ?? null;
}

if (typeof window !== "undefined") {
  // Janela de diagnóstico. Sem ela, "o autocomplete não aparece" tem meia dúzia
  // de causas indistinguíveis de fora — documento não anunciado, modelo
  // trocado, conexão caída — e todas produzem exatamente a mesma tela vazia.
  (window as unknown as Record<string, unknown>).__sicoobitoLsp = () => ({
    abertos: Array.from(documentos.values()).map((d) => ({
      path: d.path,
      pronto: d.connection.ready,
      erro: d.connection.error,
      versao: d.version,
      sync: d.connection.syncKind,
      stats: d.connection.stats,
    })),
    provedores: [...registrados],
  });
}

// ── sincronização de documento ────────────────────────────────────────────

export function openDocument(
  connection: LspConnection,
  model: Monaco.editor.ITextModel,
  path: string,
  languageId: string,
): void {
  closeDocument(model);
  documentos.set(model, { model, path, connection, version: 1 });
  connection.notify("textDocument/didOpen", {
    textDocument: { uri: path, languageId, version: 1, text: model.getValue() },
  });
}

export function closeDocument(model: Monaco.editor.ITextModel): void {
  const documento = documentos.get(model);
  if (!documento) return;
  documento.connection.notify("textDocument/didClose", { textDocument: { uri: documento.path } });
  documentos.delete(model);
}

export function documentChanged(
  model: Monaco.editor.ITextModel,
  evento: Monaco.editor.IModelContentChangedEvent,
): void {
  const documento = documentoDe(model);
  if (!documento) return;

  documento.version += 1;
  // O servidor declara no `initialize` como quer receber mudanças. Mandar o
  // texto inteiro para quem pediu incremental faz o pyright descartar a
  // alteração em silêncio — os diagnósticos simplesmente param de atualizar.
  const contentChanges =
    documento.connection.syncKind === 2
      ? evento.changes.map((mudanca) => ({
          range: {
            start: {
              line: mudanca.range.startLineNumber - 1,
              character: mudanca.range.startColumn - 1,
            },
            end: { line: mudanca.range.endLineNumber - 1, character: mudanca.range.endColumn - 1 },
          },
          rangeLength: mudanca.rangeLength,
          text: mudanca.text,
        }))
      : [{ text: model.getValue() }];

  documento.connection.notify("textDocument/didChange", {
    textDocument: { uri: documento.path, version: documento.version },
    contentChanges,
  });
}

export function documentSaved(model: Monaco.editor.ITextModel): void {
  const documento = documentoDe(model);
  if (!documento) return;
  documento.connection.notify("textDocument/didSave", {
    textDocument: { uri: documento.path },
    text: model.getValue(),
  });
}

// ── diagnósticos ──────────────────────────────────────────────────────────

export function applyDiagnostics(
  monaco: MonacoNs,
  model: Monaco.editor.ITextModel,
  path: string,
  itens: Diagnostic[],
): void {
  const documento = documentoDe(model);
  // Diagnósticos chegam para qualquer arquivo do projeto que o servidor tenha
  // analisado, não só o aberto. Marcar o modelo errado colocaria sublinhados
  // vermelhos em linhas de outro arquivo.
  if (!documento || documento.path !== path) return;

  monaco.editor.setModelMarkers(
    model,
    "sicoobito-lsp",
    itens.map((item) => ({
      ...paraRangeMonaco(item.range),
      message: item.message,
      severity: SEVERIDADE[item.severity ?? 1] ?? 8,
      source: item.source,
      code: item.code === undefined ? undefined : String(item.code),
    })),
  );
}

export function clearDiagnostics(monaco: MonacoNs, model: Monaco.editor.ITextModel): void {
  monaco.editor.setModelMarkers(model, "sicoobito-lsp", []);
}

// ── provedores ────────────────────────────────────────────────────────────

const registrados = new Set<string>();

/**
 * Registra os provedores para uma linguagem, uma vez por instância do Monaco.
 *
 * Registrar de novo a cada abertura de arquivo duplicaria os itens do
 * autocomplete — cada provedor responde, e o Monaco concatena.
 */
export function registerProviders(monaco: MonacoNs, monacoLanguage: string): void {
  if (registrados.has(monacoLanguage)) return;
  registrados.add(monacoLanguage);

  monaco.languages.registerCompletionItemProvider(monacoLanguage, {
    triggerCharacters: [".", "(", "[", '"', "'", "/", "@", "<", ":"],
    async provideCompletionItems(model, position) {
      const documento = documentoDe(model);
      if (!documento?.connection.ready) return { suggestions: [] };

      const bruto = (await documento.connection
        .request("textDocument/completion", {
          textDocument: { uri: documento.path },
          position: paraPosicaoLsp(position),
          context: { triggerKind: 1 },
        })
        .catch(() => null)) as { items?: unknown[] } | unknown[] | null;

      const itens = (Array.isArray(bruto) ? bruto : (bruto?.items ?? [])) as Array<{
        label: string;
        kind?: number;
        detail?: string;
        documentation?: unknown;
        insertText?: string;
        insertTextFormat?: number;
        filterText?: string;
        sortText?: string;
        textEdit?: { range?: LspRange; newText: string };
      }>;

      const palavra = model.getWordUntilPosition(position);
      const rangePadrao: Monaco.IRange = {
        startLineNumber: position.lineNumber,
        endLineNumber: position.lineNumber,
        startColumn: palavra.startColumn,
        endColumn: palavra.endColumn,
      };

      return {
        suggestions: itens.map((item) => ({
          label: item.label,
          kind: KIND_COMPLETION[item.kind ?? 1] ?? monaco.languages.CompletionItemKind.Text,
          detail: item.detail,
          documentation: textoDeDocumentacao(item.documentation),
          insertText: item.textEdit?.newText ?? item.insertText ?? item.label,
          insertTextRules:
            item.insertTextFormat === 2
              ? monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet
              : undefined,
          filterText: item.filterText,
          sortText: item.sortText,
          range: item.textEdit?.range ? paraRangeMonaco(item.textEdit.range) : rangePadrao,
        })),
      };
    },
  });

  monaco.languages.registerHoverProvider(monacoLanguage, {
    async provideHover(model, position) {
      const documento = documentoDe(model);
      if (!documento?.connection.ready) return null;

      const resposta = (await documento.connection
        .request("textDocument/hover", {
          textDocument: { uri: documento.path },
          position: paraPosicaoLsp(position),
        })
        .catch(() => null)) as { contents?: unknown; range?: LspRange } | null;

      if (!resposta?.contents) return null;
      const conteudo = normalizarHover(resposta.contents);
      if (!conteudo.length) return null;

      return {
        range: resposta.range ? paraRangeMonaco(resposta.range) : undefined,
        contents: conteudo,
      };
    },
  });

  monaco.languages.registerSignatureHelpProvider(monacoLanguage, {
    signatureHelpTriggerCharacters: ["(", ","],
    async provideSignatureHelp(model, position) {
      const documento = documentoDe(model);
      if (!documento?.connection.ready) return null;

      const resposta = (await documento.connection
        .request("textDocument/signatureHelp", {
          textDocument: { uri: documento.path },
          position: paraPosicaoLsp(position),
        })
        .catch(() => null)) as Monaco.languages.SignatureHelp | null;

      if (!resposta?.signatures?.length) return null;
      return { value: resposta, dispose: () => {} };
    },
  });

  monaco.languages.registerDocumentSymbolProvider(monacoLanguage, {
    async provideDocumentSymbols(model) {
      const documento = documentoDe(model);
      if (!documento?.connection.ready) return [];

      const resposta = (await documento.connection
        .request("textDocument/documentSymbol", { textDocument: { uri: documento.path } })
        .catch(() => null)) as unknown[] | null;

      return converterSimbolos(resposta ?? []);
    },
  });

  monaco.languages.registerDocumentFormattingEditProvider(monacoLanguage, {
    async provideDocumentFormattingEdits(model, options) {
      const documento = documentoDe(model);
      if (!documento?.connection.ready) return [];

      const edicoes = (await documento.connection
        .request("textDocument/formatting", {
          textDocument: { uri: documento.path },
          options: { tabSize: options.tabSize, insertSpaces: options.insertSpaces },
        })
        .catch(() => null)) as Array<{ range: LspRange; newText: string }> | null;

      return (edicoes ?? []).map((edicao) => ({
        range: paraRangeMonaco(edicao.range),
        text: edicao.newText,
      }));
    },
  });
}

function normalizarHover(contents: unknown): Monaco.IMarkdownString[] {
  const partes = Array.isArray(contents) ? contents : [contents];
  const resultado: Monaco.IMarkdownString[] = [];
  for (const parte of partes) {
    if (typeof parte === "string") {
      if (parte.trim()) resultado.push({ value: parte });
      continue;
    }
    const objeto = parte as { value?: string; language?: string };
    if (typeof objeto?.value !== "string" || !objeto.value.trim()) continue;
    // `MarkedString` com `language` é código puro: sem a cerca ele apareceria
    // como texto corrido, sem realce.
    resultado.push({
      value: objeto.language ? `\`\`\`${objeto.language}\n${objeto.value}\n\`\`\`` : objeto.value,
    });
  }
  return resultado;
}

function converterSimbolos(itens: unknown[]): Monaco.languages.DocumentSymbol[] {
  return itens.flatMap((bruto) => {
    const item = bruto as {
      name: string;
      detail?: string;
      kind: number;
      range?: LspRange;
      selectionRange?: LspRange;
      location?: { range: LspRange };
      children?: unknown[];
    };
    // `SymbolInformation` (plano) traz `location`; `DocumentSymbol` (hierárquico)
    // traz `range`. Servidores diferentes escolhem um dos dois.
    const range = item.range ?? item.location?.range;
    if (!range) return [];
    return [
      {
        name: item.name,
        detail: item.detail ?? "",
        // As duas enumerações são iguais, deslocadas de um.
        kind: (item.kind - 1) as Monaco.languages.SymbolKind,
        tags: [],
        range: paraRangeMonaco(range),
        selectionRange: paraRangeMonaco(item.selectionRange ?? range),
        children: converterSimbolos(item.children ?? []),
      },
    ];
  });
}

// ── ir para definição ─────────────────────────────────────────────────────

export interface Destino {
  path: string;
  line: number;
  column: number;
  /** Fora do projeto (biblioteca, stub): dá para mostrar, não dá para abrir. */
  external: boolean;
}

export async function definitionAt(
  model: Monaco.editor.ITextModel,
  position: Monaco.IPosition,
): Promise<Destino | null> {
  const documento = documentoDe(model);
  if (!documento?.connection.ready) return null;

  const resposta = await documento.connection
    .request("textDocument/definition", {
      textDocument: { uri: documento.path },
      position: paraPosicaoLsp(position),
    })
    .catch(() => null);

  const lista = Array.isArray(resposta) ? resposta : resposta ? [resposta] : [];
  const primeiro = lista[0] as
    | { uri?: string; range?: LspRange; targetUri?: string; targetSelectionRange?: LspRange }
    | undefined;
  if (!primeiro) return null;

  // `LocationLink` usa `targetUri`; `Location`, `uri`. O servidor escolhe com
  // base no `linkSupport` que anunciamos.
  const uri = primeiro.targetUri ?? primeiro.uri;
  const range = primeiro.targetSelectionRange ?? primeiro.range;
  if (!uri || !range) return null;

  return {
    path: uri,
    line: range.start.line + 1,
    column: range.start.character + 1,
    // A ponte devolve caminho relativo para o que está dentro do projeto e
    // deixa o `file://` intacto para o resto.
    external: uri.includes("://"),
  };
}

export async function referencesAt(
  model: Monaco.editor.ITextModel,
  position: Monaco.IPosition,
): Promise<Destino[]> {
  const documento = documentoDe(model);
  if (!documento?.connection.ready) return [];

  const resposta = (await documento.connection
    .request("textDocument/references", {
      textDocument: { uri: documento.path },
      position: paraPosicaoLsp(position),
      context: { includeDeclaration: false },
    })
    .catch(() => null)) as Array<{ uri: string; range: LspRange }> | null;

  return (resposta ?? []).map((item) => ({
    path: item.uri,
    line: item.range.start.line + 1,
    column: item.range.start.character + 1,
    external: item.uri.includes("://"),
  }));
}
