"""Segunda passagem de ordenação sobre os candidatos já recuperados.

A primeira passagem (RRF, dentro e entre fontes) é boa em *recall*: com pool de
50 o trecho certo quase sempre está lá. Ela é fraca em *precisão no topo*,
porque rank de vetor e rank de full-text não sabem o que a pergunta quer —
sabem só que o texto parece. Reordenar os 50 e ficar com 8 é o maior ganho de
qualidade disponível nesta camada, e é barato: o modelo lê trechos curtos e
devolve uma ordem, não gera resposta.

Duas passagens, nesta ordem:

1. **Léxica** (grátis, determinística): identificador citado na pergunta que
   aparece no trecho é evidência forte e verificável. Não depende de modelo, não
   falha, e sozinha já conserta o caso mais gritante — perguntar por
   `resolve_project` e receber o arquivo que só menciona "projeto".

2. **Listwise por LLM** (uma chamada barata): o modelo vê a pergunta e a lista
   numerada, e devolve as posições em ordem. Listwise em vez de pointwise porque
   pontuar cada candidato isolado custa N chamadas e produz notas incomparáveis
   entre si; o que se quer aqui é uma ordem, e ordem é exatamente o que uma
   lista comparada de uma vez produz.

Degradar é obrigação, não cortesia: se o modelo cai, responde fora do formato
ou omite candidatos, a ordem que entrou é a que sai. Um reranker que derruba a
busca é pior que nenhum.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from eltanix.logging_setup import get_logger
from eltanix.retrieval.types import RetrievedItem

log = get_logger(__name__)

# Quantos candidatos entram na chamada. Acima disto o prompt cresce mais rápido
# que o ganho: o modelo passa a comparar trechos que a primeira passagem já
# tinha colocado no fim por bons motivos.
MAX_CANDIDATOS = 40
# Caracteres de cada trecho mostrados ao reranker. O suficiente para julgar
# relevância sem transformar a chamada barata numa cara.
TRECHO_MAX_CHARS = 600
# Empurrão por identificador da pergunta encontrado no trecho, somado ao score
# de fusão. Calibrado para reordenar dentro da mesma vizinhança de RRF (os
# scores de fusão vivem na casa de 1/60) sem atropelar a ordem inteira.
PESO_IDENTIFICADOR = 0.004
# Um identificador que aparece na *assinatura* (nome do símbolo ou caminho) vale
# mais que um citado no corpo: é a diferença entre definir e usar.
PESO_IDENTIFICADOR_EM_SIMBOLO = 0.012

_PROMPT = (
    "Você ordena trechos recuperados de um repositório por utilidade para "
    "responder a uma pergunta.\n"
    "Responda APENAS com os números dos trechos, do mais útil para o menos "
    "útil, separados por vírgula. Sem explicação, sem texto extra.\n"
    "Inclua no máximo {n} números. Omita trechos irrelevantes em vez de "
    "colocá-los no fim.\n\n"
    "Pergunta: {q}\n\n"
    "Trechos:\n{lista}"
)

_NUMEROS = re.compile(r"\d+")


@dataclass(slots=True)
class RerankOutcome:
    """Resultado da segunda passagem, com o que aconteceu de fato.

    `used_llm=False` com `llm_error` preenchido é o caminho degradado — vale
    aparecer no span de RAG, porque uma busca pior por reranker fora do ar é
    indistinguível de uma busca pior por regressão de qualidade se ninguém
    registrar a diferença.
    """

    items: list[RetrievedItem]
    used_llm: bool = False
    lexical_applied: bool = False
    llm_error: str | None = None


def _texto_da_resposta(payload: dict) -> str:
    escolhas = payload.get("choices") or []
    if not escolhas:
        return ""
    return str((escolhas[0].get("message") or {}).get("content") or "")


def lexical_rerank(
    itens: Sequence[RetrievedItem], *, identifiers: Sequence[str]
) -> list[RetrievedItem]:
    """Reordena por identificador da pergunta presente no trecho.

    Estável: sem identificador citado, ou sem nenhum acerto, a ordem de entrada
    é preservada byte a byte — `sorted` do Python é estável e o empurrão é 0.
    """
    if not identifiers:
        return list(itens)

    minusculos = [i.lower() for i in identifiers]

    def empurrao(item: RetrievedItem) -> float:
        assinatura = " ".join(
            str(item.meta.get(campo) or "") for campo in ("symbol", "path", "filename", "title")
        ).lower()
        corpo = item.content.lower()
        total = 0.0
        for ident in minusculos:
            if ident in assinatura:
                total += PESO_IDENTIFICADOR_EM_SIMBOLO
            elif ident in corpo:
                total += PESO_IDENTIFICADOR
        return total

    return sorted(itens, key=lambda item: -(item.score + empurrao(item)))


def _monta_lista(itens: Sequence[RetrievedItem]) -> str:
    linhas: list[str] = []
    for posicao, item in enumerate(itens, start=1):
        trecho = item.content.strip().replace("\r\n", "\n")
        if len(trecho) > TRECHO_MAX_CHARS:
            trecho = trecho[:TRECHO_MAX_CHARS] + " […]"
        linhas.append(f"[{posicao}] {item.citation}\n{trecho}")
    return "\n\n".join(linhas)


def _ordem_da_resposta(texto: str, *, total: int, limite: int) -> list[int]:
    """Índices 0-based, sem repetição e dentro da faixa.

    O modelo erra de formas previsíveis — repete número, inventa `[12]` numa
    lista de 8, escreve "1. 3. 7". Filtrar aqui é mais barato que confiar e
    depois tratar `IndexError`.
    """
    vistos: list[int] = []
    for bruto in _NUMEROS.findall(texto):
        indice = int(bruto) - 1
        if 0 <= indice < total and indice not in vistos:
            vistos.append(indice)
        if len(vistos) >= limite:
            break
    return vistos


async def rerank(
    itens: Sequence[RetrievedItem],
    *,
    query: str,
    engine: object | None = None,
    identifiers: Sequence[str] = (),
    limit: int = 8,
    profile: str = "utility",
    use_llm: bool = True,
    max_candidates: int = MAX_CANDIDATOS,
    project_slug: str | None = None,
) -> RerankOutcome:
    """Reordena `itens` e devolve os `limit` melhores.

    Sem `engine`, ou com `use_llm=False`, fica só na passagem léxica — que é
    determinística e não custa nada, então vale sempre.
    """
    if not itens:
        return RerankOutcome(items=[])

    ordenados = lexical_rerank(itens, identifiers=identifiers)
    resultado = RerankOutcome(items=ordenados[:limit], lexical_applied=bool(identifiers))

    if engine is None or not use_llm or len(ordenados) <= 1:
        return resultado

    candidatos = ordenados[:max_candidates]
    try:
        completado = await engine.complete(  # type: ignore[attr-defined]
            requested_model=profile,
            params={
                "messages": [
                    {
                        "role": "user",
                        "content": _PROMPT.format(
                            n=limit, q=query.strip(), lista=_monta_lista(candidatos)
                        ),
                    }
                ],
                "temperature": 0,
                "max_tokens": 120,
            },
            source="retrieval:rerank",
            project_slug=project_slug,
        )
    except Exception as exc:
        log.warning("retrieval.rerank.failed", error=str(exc)[:200], candidates=len(candidatos))
        resultado.llm_error = type(exc).__name__
        return resultado

    ordem = _ordem_da_resposta(
        _texto_da_resposta(completado.payload), total=len(candidatos), limite=limit
    )
    if not ordem:
        # Resposta fora do formato. Manter a ordem léxica é o comportamento
        # correto — inventar uma ordem a partir de lixo seria pior que não
        # rerankear.
        log.warning("retrieval.rerank.unparseable", candidates=len(candidatos))
        resultado.llm_error = "unparseable"
        return resultado

    escolhidos = [candidatos[i] for i in ordem]
    # O modelo pode devolver menos que `limit` (foi instruído a omitir o
    # irrelevante). Completar com a ordem anterior mantém o orçamento cheio sem
    # contrariar o julgamento dele: o que ele omitiu vai para depois do que ele
    # escolheu, não some.
    if len(escolhidos) < limit:
        ja = {(i.source, i.key) for i in escolhidos}
        for item in ordenados:
            if (item.source, item.key) in ja:
                continue
            escolhidos.append(item)
            if len(escolhidos) >= limit:
                break

    resultado.items = escolhidos[:limit]
    resultado.used_llm = True
    return resultado
