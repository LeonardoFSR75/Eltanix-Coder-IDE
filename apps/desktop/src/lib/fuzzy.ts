/**
 * Casamento fuzzy de caminho/texto — porta de `apps/web/lib/ide-store.tsx::fuzzyScore`.
 * Usado por Quick Open e Command Palette para ordenar por relevância sem round-trip
 * ao servidor a cada tecla.
 */
export function fuzzyScore(alvo: string, consulta: string): number | null {
  if (!consulta) return 0;
  const alvoBaixo = alvo.toLowerCase();
  const consultaBaixa = consulta.toLowerCase();

  let pontos = 0;
  let indice = 0;
  let anterior = -1;

  for (const caractere of consultaBaixa) {
    const encontrado = alvoBaixo.indexOf(caractere, indice);
    if (encontrado === -1) return null;

    if (encontrado === anterior + 1) pontos += 8;
    if (encontrado === 0 || "/._-".includes(alvoBaixo[encontrado - 1] ?? "")) pontos += 6;
    // Penaliza a distância percorrida: casamentos espalhados valem menos.
    pontos -= Math.min(encontrado - indice, 10);

    anterior = encontrado;
    indice = encontrado + 1;
  }

  // Empate entre dois caminhos: o mais curto costuma ser o procurado.
  return pontos - alvo.length * 0.1;
}
