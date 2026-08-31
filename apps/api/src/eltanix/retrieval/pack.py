"""Empacotamento por orçamento de tokens.

O corte do contexto era por número de hits (`limit=8`), o que não tem relação
com o espaço que eles ocupam: oito funções pequenas cabem folgado, oito classes
grandes estouram a janela e o provedor corta pelo meio — perdendo o fim do
último trecho sem avisar ninguém.

Aqui o corte é por token, e é o empacotador que decide o que não cabe. Duas
propriedades que o chamador pode confiar:

- **Nada entra pela metade.** Ou o trecho cabe inteiro, ou não entra. Meio
  trecho de código é pior que nenhum: parece completo e mente sobre onde a
  função termina.
- **A citação sobrevive ao corte.** O que entrou é sempre rastreável até
  arquivo e linha, para o agente conseguir abrir o original.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from eltanix.optimizer.tokens import count_text
from eltanix.retrieval.types import RetrievedItem

# Custo do cabeçalho de citação + separador de cada bloco.
_OVERHEAD_POR_BLOCO = 12


@dataclass(slots=True)
class PackedContext:
    text: str
    items: list[RetrievedItem] = field(default_factory=list)
    tokens_used: int = 0
    tokens_budget: int = 0
    dropped: int = 0

    @property
    def citations(self) -> list[str]:
        return [item.citation for item in self.items]


def _tokens_do_item(item: RetrievedItem) -> int:
    # `token_count` vem do chunker e já foi contado na indexação; recontar aqui
    # seria gastar CPU para chegar ao mesmo número.
    base = item.token_count or count_text(item.content)
    return base + _OVERHEAD_POR_BLOCO


def pack(
    itens: Sequence[RetrievedItem],
    *,
    token_budget: int,
    max_items: int | None = None,
) -> PackedContext:
    """Monta o bloco de contexto respeitando `token_budget`.

    Percorre na ordem recebida (que já é a ordem de relevância depois de
    fusão, rerank e diversidade) e **pula** o que não cabe em vez de parar:
    um trecho grande demais na terceira posição não deve impedir que os três
    seguintes, pequenos, entrem.
    """
    resultado = PackedContext(text="", tokens_budget=token_budget)
    if token_budget <= 0:
        resultado.dropped = len(itens)
        return resultado

    blocos: list[str] = []
    usados = 0
    for item in itens:
        if max_items is not None and len(resultado.items) >= max_items:
            resultado.dropped += 1
            continue
        custo = _tokens_do_item(item)
        if usados + custo > token_budget:
            resultado.dropped += 1
            continue
        usados += custo
        resultado.items.append(item)
        blocos.append(f"--- {item.citation}\n{item.content}")

    resultado.text = "\n\n".join(blocos)
    resultado.tokens_used = usados
    return resultado
