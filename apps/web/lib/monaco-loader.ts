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
