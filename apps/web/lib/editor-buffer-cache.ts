/**
 * Cache de conteúdo em memória, fora do React, por caminho de arquivo.
 *
 * O `Editor` guarda `content`/`dirty` em estado local para digitação
 * responsiva — refletir cada tecla no Context do IDE re-renderizaria todo
 * consumidor de `useIde()` a cada caractere digitado. Mas estado local some
 * quando o componente desmonta, e isso acontece por motivo que nada tem a ver
 * com o arquivo em si: fechar um painel vizinho reorganiza a árvore de
 * splits (`ide.layout`), e a posição do painel sobrevivente na árvore de
 * componentes muda — React o desmonta e remonta do zero. Sem este cache,
 * isso jogava fora uma edição não salva.
 *
 * Sobrevive fora do React pelo mesmo motivo que a conexão LSP (`lsp.ts`) e o
 * documento ativo (`lsp-monaco.ts`) sobrevivem: o dado pertence ao arquivo,
 * não ao componente que o está exibindo agora.
 */

interface Buffer {
  content: string;
  original: string;
  language: string | null;
}

const cache = new Map<string, Buffer>();

export function getBuffer(path: string): Buffer | undefined {
  return cache.get(path);
}

export function setBuffer(path: string, buffer: Buffer): void {
  cache.set(path, buffer);
}

export function updateBufferContent(path: string, content: string): void {
  const atual = cache.get(path);
  cache.set(path, { content, original: atual?.original ?? content, language: atual?.language ?? null });
}

export function clearBuffer(path: string): void {
  cache.delete(path);
}
