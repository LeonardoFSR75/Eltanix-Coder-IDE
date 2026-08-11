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

// Chave inclui o projeto: dois projetos com um arquivo de mesmo caminho
// relativo (ex. "README.md", comuníssimo) não podem compartilhar entrada —
// senão trocar de projeto reexibiria (e poderia salvar por cima) o conteúdo
// do projeto anterior sob o nome de arquivo certo do projeto errado.
function key(project: string, path: string): string {
  return `${project}::${path}`;
}

export function getBuffer(project: string, path: string): Buffer | undefined {
  return cache.get(key(project, path));
}

export function setBuffer(project: string, path: string, buffer: Buffer): void {
  cache.set(key(project, path), buffer);
}

export function updateBufferContent(project: string, path: string, content: string): void {
  const k = key(project, path);
  const atual = cache.get(k);
  cache.set(k, { content, original: atual?.original ?? content, language: atual?.language ?? null });
}

export function clearBuffer(project: string, path: string): void {
  cache.delete(key(project, path));
}
