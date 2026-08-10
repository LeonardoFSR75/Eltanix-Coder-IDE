/**
 * Liga o Monaco ao language server do projeto aberto.
 *
 * Concentra o ciclo de vida num lugar só: conectar, anunciar o documento,
 * propagar mudanças, aplicar diagnósticos e desligar. O `Editor` fica sabendo
 * apenas que existe um estado (`ready`, `error`) para mostrar na barra.
 */

"use client";

import type * as Monaco from "monaco-editor";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  applyDiagnostics,
  clearDiagnostics,
  closeDocument,
  definitionAt,
  documentChanged,
  documentSaved,
  openDocument,
  registerProviders,
  type Destino,
} from "@/lib/lsp-monaco";
import { closeConnectionsFor, getConnection, supportedLanguages } from "@/lib/lsp";

/** Nome no nosso catálogo → languageId do protocolo. */
const LSP_LANGUAGE: Record<string, string> = {
  python: "python",
  typescript: "typescript",
  tsx: "typescriptreact",
  javascript: "javascript",
  json: "json",
  yaml: "yaml",
  css: "css",
  scss: "scss",
  html: "html",
  bash: "shellscript",
};

/** languageId do protocolo → id da linguagem no Monaco. */
const MONACO_DE_LSP: Record<string, string> = {
  python: "python",
  typescript: "typescript",
  typescriptreact: "typescript",
  javascript: "javascript",
  javascriptreact: "javascript",
  json: "json",
  yaml: "yaml",
  css: "css",
  scss: "scss",
  html: "html",
  shellscript: "shell",
};

export interface LspStatus {
  language: string | null;
  ready: boolean;
  error: string | null;
}

interface Opcoes {
  project: string | null;
  path: string | null;
  /** Linguagem detectada pelo backend, no vocabulário do nosso catálogo. */
  language: string | null;
  /** Chamado quando "ir para definição" aponta para outro arquivo. */
  onNavigate: (path: string, line: number, column: number) => void;
}

export function useLsp({ project, path, language, onNavigate }: Opcoes) {
  const [status, setStatus] = useState<LspStatus>({ language: null, ready: false, error: null });
  // Estado, e não apenas ref: o efeito de conexão roda antes do `onMount` do
  // Monaco, quando ainda não há editor. Guardar isso só numa ref não
  // reagendaria o efeito, e o language server nunca conectaria — sem erro
  // nenhum, porque o caminho de saída é o mesmo de "linguagem sem servidor".
  const [montado, setMontado] = useState(false);
  const monacoRef = useRef<typeof Monaco | null>(null);
  const editorRef = useRef<Monaco.editor.IStandaloneCodeEditor | null>(null);
  // O callback de navegação costuma vir como arrow inline; guardá-lo numa ref
  // evita religar o language server a cada render do editor.
  const navigateRef = useRef(onNavigate);
  useEffect(() => {
    navigateRef.current = onNavigate;
  }, [onNavigate]);

  const lspLanguage = language ? (LSP_LANGUAGE[language] ?? null) : null;

  const irParaDefinicao = useCallback(async () => {
    const editor = editorRef.current;
    const model = editor?.getModel();
    const posicao = editor?.getPosition();
    if (!editor || !model || !posicao) return;

    let destino: Destino | null = null;
    try {
      destino = await definitionAt(model, posicao);
    } catch {
      return;
    }
    if (!destino || destino.external) return;

    navigateRef.current(destino.path, destino.line, destino.column);
  }, []);

  const onMount = useCallback(
    (editor: Monaco.editor.IStandaloneCodeEditor, monaco: typeof Monaco) => {
      editorRef.current = editor;
      monacoRef.current = monaco;
      setMontado(true);

      editor.addAction({
        id: "sicoobito.gotoDefinition",
        label: "Ir para definição",
        keybindings: [monaco.KeyCode.F12],
        contextMenuGroupId: "navigation",
        contextMenuOrder: 1,
        run: () => void irParaDefinicao(),
      });

      // Ctrl+clique é a memória muscular de quem vem do VS Code. O provedor
      // nativo do Monaco abriria o alvo por conta própria, mas ele só sabe
      // navegar para modelos que já existem — e aqui só existe o do arquivo
      // aberto. Interceptar o clique deixa a navegação passar pelo IDE, que
      // sabe abrir uma aba nova.
      editor.onMouseDown((evento) => {
        if (!evento.event.ctrlKey && !evento.event.metaKey) return;
        if (evento.target.type !== monaco.editor.MouseTargetType.CONTENT_TEXT) return;
        evento.event.preventDefault();
        void irParaDefinicao();
      });
    },
    [irParaDefinicao],
  );

  // Conecta e anuncia o documento. Roda de novo a cada troca de arquivo.
  useEffect(() => {
    const monaco = monacoRef.current;
    const editor = editorRef.current;
    const model = editor?.getModel();
    if (!monaco || !editor || !model || !project || !path || !lspLanguage) {
      setStatus({ language: lspLanguage, ready: false, error: null });
      return;
    }

    let cancelado = false;
    let desassinar: (() => void) | null = null;

    (async () => {
      const suportadas = await supportedLanguages();
      if (cancelado) return;
      if (!(lspLanguage in suportadas)) {
        // Degradar em silêncio: a imagem pode não ter o servidor, e um erro
        // vermelho para "markdown não tem autocomplete" é ruído.
        setStatus({ language: lspLanguage, ready: false, error: null });
        return;
      }

      let conexao;
      try {
        conexao = await getConnection(project, lspLanguage);
      } catch (erro) {
        if (!cancelado) {
          setStatus({
            language: lspLanguage,
            ready: false,
            error: erro instanceof Error ? erro.message : String(erro),
          });
        }
        return;
      }
      if (cancelado || !model || model.isDisposed()) return;

      const monacoLanguage = MONACO_DE_LSP[lspLanguage] ?? lspLanguage;
      registerProviders(monaco, monacoLanguage);

      clearDiagnostics(monaco, model);
      openDocument(conexao, model, path, lspLanguage);

      const pararDiagnosticos = conexao.onDiagnostics((arquivo, itens) => {
        applyDiagnostics(monaco, model, arquivo, itens);
      });
      const pararEstado = conexao.onStateChange((pronto, erro) => {
        setStatus({ language: lspLanguage, ready: pronto, error: erro });
      });
      desassinar = () => {
        pararDiagnosticos();
        pararEstado();
      };
    })();

    return () => {
      cancelado = true;
      desassinar?.();
      if (model && !model.isDisposed()) {
        closeDocument(model);
      }
    };
  }, [project, path, lspLanguage, montado]);


  // Trocar de projeto invalida os servidores: eles indexaram outra raiz.
  const projetoAnterior = useRef(project);
  useEffect(() => {
    if (projetoAnterior.current !== null && projetoAnterior.current !== project) {
      closeConnectionsFor(projetoAnterior.current);
    }
    projetoAnterior.current = project;
  }, [project]);

  const onChange = useCallback((evento: Monaco.editor.IModelContentChangedEvent) => {
    const model = editorRef.current?.getModel();
    if (model) documentChanged(model, evento);
  }, []);

  const onSave = useCallback(() => {
    const model = editorRef.current?.getModel();
    if (model) documentSaved(model);
  }, []);

  const revealAt = useCallback((line: number, column: number) => {
    const editor = editorRef.current;
    if (!editor) return;

    // Reaplicada, e não aplicada uma vez.
    //
    // Quando o arquivo é aberto por "ir para definição", o React entrega o novo
    // conteúdo e a posição pedida no mesmo commit. O wrapper do Monaco troca o
    // buffer com `executeEdits` sobre o range inteiro, e isso **reposiciona o
    // cursor** — inclusive depois de nós o termos colocado onde deveria ficar.
    // O sintoma é o cursor parar na linha 1, como se a posição pedida tivesse
    // sido ignorada.
    //
    // Ordenar isso pelos efeitos do React não resolve: a troca do buffer não
    // acontece num ponto fixo do ciclo. Insistir por alguns quadros é
    // imperceptível para quem usa e não depende dessa ordem.
    const posicao = { lineNumber: line, column };
    const aplicar = () => {
      editor.revealPositionInCenter(posicao);
      editor.setPosition(posicao);
    };
    aplicar();
    let restantes = 12;
    const insistir = () => {
      const atual = editor.getPosition();
      if (atual?.lineNumber !== line) aplicar();
      if (--restantes > 0) requestAnimationFrame(insistir);
      else editor.focus();
    };
    requestAnimationFrame(insistir);
  }, []);

  return { status, onMount, onChange, onSave, revealAt };
}
