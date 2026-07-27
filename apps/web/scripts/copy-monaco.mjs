#!/usr/bin/env node
/**
 * Copia os assets estáticos do Monaco (`monaco-editor/min/vs`) para
 * `public/vs`, servidos pelo próprio Next.js.
 *
 * Sem isto, `@monaco-editor/react` busca esses arquivos num CDN externo
 * (jsdelivr) em tempo de execução no browser. Numa implantação local-first —
 * sem internet garantida, ou atrás de uma rede restrita — isso deixa o editor
 * de código completamente em branco: a barra e o breadcrumb renderizam
 * (são React puro), mas a área do editor nunca monta, porque o loader do
 * Monaco trava esperando um recurso que a rede nunca entrega.
 *
 * Roda no `postinstall`, então tanto `npm install` local quanto `npm ci` no
 * Dockerfile deixam `public/vs` pronto antes de qualquer `npm run dev/build`.
 */

import { cpSync, existsSync, rmSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const source = path.join(here, "..", "node_modules", "monaco-editor", "min", "vs");
const destino = path.join(here, "..", "public", "vs");

if (!existsSync(source)) {
  console.warn("[copy-monaco] monaco-editor/min/vs não encontrado — pulando cópia.");
  process.exit(0);
}

rmSync(destino, { recursive: true, force: true });
cpSync(source, destino, { recursive: true });
console.log(`[copy-monaco] assets copiados para ${path.relative(process.cwd(), destino)}`);
