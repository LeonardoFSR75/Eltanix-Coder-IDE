/**
 * Aponta o `@monaco-editor/react` para os assets locais em `/vs` (copiados de
 * `monaco-editor/min/vs` pelo script `postinstall`) em vez do CDN público que
 * a biblioteca usa por padrão.
 *
 * Precisa rodar antes do primeiro `<MonacoEditor>` montar — por isso é um
 * módulo com efeito colateral no import, e não uma função chamada de dentro
 * de um componente.
 */
import { loader } from "@monaco-editor/react";

loader.config({ paths: { vs: "/vs" } });

// Bug conhecido do @monaco-editor/react: em dev, o Strict Mode do React monta
// → desmonta → remonta cada componente de propósito (para expor efeitos não
// idempotentes). O DiffEditor kicka o carregamento assíncrono do Monaco no
// primeiro mount; quando esse mount sintético já foi desfeito antes da
// Promise resolver, o wrapper tenta configurar o TextModel do editor que o
// próprio desmonte já descartou — lança "TextModel got disposed before
// DiffEditorWidget model got reset" fora do ciclo do React (não é um erro de
// render, não quebra nada na tela), só polui o overlay de erro do Next em
// dev. Sem fix corrigido a montante (github.com/suren-atoyan/monaco-react),
// então filtramos só esse erro específico — qualquer outro segue passando.
if (typeof window !== "undefined") {
  const win = window as unknown as Record<string, boolean | undefined>;
  if (!win.__monaco_loader_installed__) {
    win.__monaco_loader_installed__ = true;
    window.addEventListener("error", (event) => {
      if (event.message?.includes("TextModel got disposed before DiffEditorWidget model got reset")) {
        event.preventDefault();
      }
    });
  }
}
