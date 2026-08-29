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

// Força o `loader` a resolver `/vs/loader.js` AGORA, no import deste módulo —
// que roda antes de `<MonacoEditor>`/`<DiffEditor>` montar. Sem isto, quem
// dispara o `loader.init()` é o `useEffect` de dentro do componente; o
// `@monaco-editor/loader` lê `config.paths.vs` no instante do `init()`, então
// qualquer `init()` que escape antes desta linha cai no default (CDN
// jsdelivr). Numa stack sem internet garantida (E2E no CI, deploy
// local-first) esse fetch nunca volta e a área do editor fica eternamente em
// "Loading…". `init()` é idempotente e o wrapper é cancelável — o
// componente reaproveita esta mesma Promise.
if (typeof window !== "undefined") {
  loader.init().catch(() => {
    // Erro real de carregamento (ex.: `/vs` ausente) aparece no próprio
    // <Editor>, que também chama `init()` e loga o motivo — não duplicar aqui.
  });
}

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

    const isDiffModelError = (msg?: string | null) =>
      Boolean(msg && msg.includes("TextModel got disposed before DiffEditorWidget model got reset"));

    const origConsoleError = console.error;
    console.error = (...args: unknown[]) => {
      const msg = args.map((a) => (typeof a === "string" ? a : (a as any)?.message || "")).join(" ");
      if (isDiffModelError(msg)) {
        return;
      }
      origConsoleError.apply(console, args);
    };

    window.addEventListener("error", (event) => {
      if (isDiffModelError(event.message) || isDiffModelError(event.error?.message)) {
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    });

    window.addEventListener("unhandledrejection", (event) => {
      const reason = event.reason;
      const msg = typeof reason === "string" ? reason : reason?.message || String(reason || "");
      if (isDiffModelError(msg)) {
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    });
  }
}
