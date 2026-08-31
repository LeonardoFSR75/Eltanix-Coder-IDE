"""Preparo da consulta antes de bater nos stores.

Três coisas acontecem aqui, em ordem de custo crescente:

1. **Normalização** (grátis): a pergunta que o usuário digita não é o texto que
   o buscador quer. "Onde é que a gente aprova ferramenta de escrita?" carrega
   pontuação, tratamento e palavras de ligação que o full-text ignora e o vetor
   dilui. Extrair os identificadores citados e limpar o resto custa uma regex.

2. **Multi-query** (uma chamada barata): a mesma pergunta feita de três formas
   recupera coisas diferentes, e a fusão por rank junta as três sem que uma
   formulação ruim afunde as outras. É o ganho de recall mais previsível desta
   camada.

3. **HyDE** (uma chamada barata, opcional): embutir um *documento hipotético* —
   o trecho de código que responderia à pergunta — em vez da pergunta. Consulta
   e documento vivem em regiões diferentes do espaço vetorial, e essa é
   exatamente a assimetria que o vetor sofre. HyDE fecha a distância pelo lado
   do texto; o prefixo assimétrico (`ModelSpec.embedding_query_prefix`) fecha
   pelo lado do modelo. Os dois são complementares, não alternativos.

O gasto é controlado por complexidade, no mesmo espírito de
`optimizer/complexity.py`: pergunta curta e cheia de identificador já é uma boa
consulta, e reescrever gasta uma chamada para chegar perto do mesmo lugar. Toda
saída de LLM aqui passa por `RouterEngine.complete()` no perfil `utility` — não
existe porta própria (ADR 0001).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field

from eltanix.logging_setup import get_logger

log = get_logger(__name__)

# Palavras que só carregam a pergunta, não o assunto dela. Deliberadamente
# curta e bilíngue: a lista existe para tirar ruído da perna lexical, não para
# ser um stopword list completo — o `websearch_to_tsquery('simple', ...)` não
# tem dicionário, então o que sobra aqui é o que ele vai procurar.
_RUIDO = frozenset(
    """
    a as o os um uma uns umas de do da dos das em no na nos nas por para pelo
    pela com sem sobre entre ate que qual quais quando onde como porque pq e ou
    mas se eu voce voces nos meu minha seu sua isso isto aquilo la aqui ai
    quero preciso gostaria favor pode poderia me mostrar ver saber entender
    the a an of in on at to for from with about how what where when why which
    is are was were do does did can could should would please show me tell
    """.split()
)

_PALAVRA = re.compile(r"[^\W\d_]+|\d+", re.UNICODE)
# Identificador de código citado na pergunta: `snake_case`, `camelCase`,
# `Caminho/De/Arquivo`, `modulo.funcao`, `Classe::metodo`.
_IDENTIFICADOR = re.compile(
    r"\b(?:[A-Za-z_][A-Za-z0-9_]*(?:[./:]{1,2}[A-Za-z_][A-Za-z0-9_]*)+"
    r"|[a-z0-9]+_[a-z0-9_]+"
    r"|[a-z]+[A-Z][A-Za-z0-9]*"
    r"|[A-Z][a-z0-9]+[A-Z][A-Za-z0-9]*)\b"
)

# Acima disto a pergunta já tem material suficiente; reescrever é gastar uma
# chamada para reordenar palavras.
_TERMOS_SUFICIENTES = 6
# Número de reformulações pedidas ao modelo. Três é o ponto onde o ganho de
# recall ainda paga a latência somada das buscas extras.
_VARIANTES_PADRAO = 3


@dataclass(slots=True)
class PreparedQuery:
    """O que os stores vão receber.

    `lexical` vai para a perna full-text/trigrama, `variants` para as buscas
    vetoriais (uma por variante), e `embed_text` é o texto efetivamente
    embutido — igual ao original, ou o documento hipotético do HyDE.
    """

    original: str
    lexical: str
    variants: list[str] = field(default_factory=list)
    embed_text: str = ""
    identifiers: list[str] = field(default_factory=list)
    hyde: str | None = None
    expanded: bool = False

    def __post_init__(self) -> None:
        if not self.embed_text:
            self.embed_text = self.original
        if not self.variants:
            self.variants = [self.original]


def extract_identifiers(query: str) -> list[str]:
    """Identificadores de código citados na pergunta, sem repetir.

    Eles são o sinal mais forte que uma pergunta pode dar: quem escreve
    `resolve_project` sabe o nome da função, e o buscador tem obrigação de
    achar o arquivo que a define. É esse trecho que a perna de trigrama usa.
    """
    vistos: dict[str, None] = {}
    for termo in _IDENTIFICADOR.findall(query):
        vistos.setdefault(termo, None)
    return list(vistos)


def _sem_acento(palavra: str) -> str:
    """Forma comparável com a lista de ruído.

    A lista é escrita sem acento de propósito: escrevê-la duas vezes (`e` e
    `é`, `ate` e `até`) é convite a esquecer metade. Dobrar aqui custa uma
    normalização por token e não deixa `é` sobrar na consulta lexical.
    """
    return unicodedata.normalize("NFKD", palavra.lower()).encode("ascii", "ignore").decode()


def normalize(query: str) -> str:
    """Versão da pergunta para a perna lexical.

    Tira o ruído de pergunta e preserva os identificadores **inteiros**. Duas
    coisas importam aqui:

    - Identificador citado não é quebrado em palavras. Quebrar `agent/graph.py`
      em `agent graph py` do lado da consulta desfaz o que
      `eltanix_split_identifiers` (migração 0032) faz do lado do índice — e
      pior, injeta termos como `py`, que casam com o repositório inteiro.
    - O texto ao redor do identificador continua sendo limpo normalmente.
    """
    fora: list[str] = []
    identificadores: list[str] = []
    fim_anterior = 0
    for achado in _IDENTIFICADOR.finditer(query):
        fora.append(query[fim_anterior : achado.start()])
        if achado.group(0) not in identificadores:
            identificadores.append(achado.group(0))
        fim_anterior = achado.end()
    fora.append(query[fim_anterior:])

    mantidos: list[str] = []
    for pedaco in fora:
        for token in _PALAVRA.findall(pedaco):
            if _sem_acento(token) in _RUIDO:
                continue
            mantidos.append(token)
    mantidos.extend(identificadores)

    limpo = " ".join(mantidos).strip()
    # Pergunta que era só ruído ("por que isso?") sobra vazia — nesse caso a
    # original ainda é melhor que nada para o `websearch_to_tsquery`.
    return limpo or query.strip()


def should_expand(query: str, *, identifiers: Sequence[str] | None = None) -> bool:
    """Vale a pena gastar uma chamada reescrevendo esta pergunta?

    Não vale quando a pergunta já cita identificador (o alvo é explícito) nem
    quando já tem termos suficientes. Vale quando é curta e vaga, que é
    justamente onde a busca de uma consulta só erra.
    """
    idents = list(identifiers) if identifiers is not None else extract_identifiers(query)
    if idents:
        return False
    termos = [t for t in _PALAVRA.findall(query) if _sem_acento(t) not in _RUIDO]
    return len(termos) < _TERMOS_SUFICIENTES


_PROMPT_VARIANTES = (
    "Reescreva a pergunta abaixo de {n} formas diferentes, para buscar num "
    "repositório de código e na documentação dele.\n"
    "Cada variante deve manter a intenção e trocar o vocabulário: uma mais "
    "técnica (nomes prováveis de função, módulo ou classe), uma mais direta, "
    "uma mais conceitual.\n"
    "Responda apenas com as variantes, uma por linha, sem numerar e sem "
    "comentar.\n\n"
    "Pergunta: {q}"
)

_PROMPT_HYDE = (
    "Escreva um trecho curto (no máximo 8 linhas) que pareça o conteúdo real "
    "que responderia à pergunta abaixo, como se fosse extraído do repositório: "
    "código, docstring ou parágrafo de documentação.\n"
    "Não responda à pergunta nem explique — escreva apenas o trecho, sem cercas "
    "de código e sem preâmbulo. Invente nomes plausíveis quando não souber.\n\n"
    "Pergunta: {q}"
)


def _linhas_uteis(texto: str, *, limite: int) -> list[str]:
    saida: list[str] = []
    for linha in texto.splitlines():
        limpa = linha.strip().lstrip("-*•").strip()
        # Modelo pequeno numera mesmo quando você pede para não numerar.
        limpa = re.sub(r"^\d+[.)]\s*", "", limpa)
        if len(limpa) < 3:
            continue
        if limpa not in saida:
            saida.append(limpa)
        if len(saida) >= limite:
            break
    return saida


def _texto_da_resposta(payload: dict) -> str:
    escolhas = payload.get("choices") or []
    if not escolhas:
        return ""
    return str((escolhas[0].get("message") or {}).get("content") or "")


async def prepare(
    query: str,
    *,
    engine: object | None = None,
    profile: str = "utility",
    expand: bool = True,
    hyde: bool = False,
    variants: int = _VARIANTES_PADRAO,
    project_slug: str | None = None,
) -> PreparedQuery:
    """Prepara a consulta, gastando LLM só quando isso muda o resultado.

    Sem `engine`, ou com a chamada falhando, devolve a versão normalizada — a
    expansão é melhoria de recall, não pré-requisito, e uma busca sem ela ainda
    é a busca que existia antes desta camada.
    """
    identificadores = extract_identifiers(query)
    preparada = PreparedQuery(
        original=query.strip(),
        lexical=normalize(query),
        identifiers=identificadores,
    )

    if engine is None or not preparada.original:
        return preparada

    quer_expandir = expand and should_expand(preparada.original, identifiers=identificadores)
    if not quer_expandir and not hyde:
        return preparada

    if quer_expandir:
        try:
            resultado = await engine.complete(  # type: ignore[attr-defined]
                requested_model=profile,
                params={
                    "messages": [
                        {
                            "role": "user",
                            "content": _PROMPT_VARIANTES.format(n=variants, q=preparada.original),
                        }
                    ],
                    "temperature": 0.3,
                    "max_tokens": 200,
                },
                source="retrieval:expand",
                project_slug=project_slug,
            )
            linhas = _linhas_uteis(_texto_da_resposta(resultado.payload), limite=variants)
        except Exception as exc:
            log.warning("retrieval.expand.failed", error=str(exc)[:200])
            linhas = []
        if linhas:
            # A original vai primeiro e sempre: ela é a única formulação que
            # com certeza representa o que foi perguntado.
            preparada.variants = [preparada.original, *[ln for ln in linhas if ln != query]]
            preparada.expanded = True

    if hyde:
        try:
            resultado = await engine.complete(  # type: ignore[attr-defined]
                requested_model=profile,
                params={
                    "messages": [
                        {"role": "user", "content": _PROMPT_HYDE.format(q=preparada.original)}
                    ],
                    "temperature": 0.2,
                    "max_tokens": 300,
                },
                source="retrieval:hyde",
                project_slug=project_slug,
            )
            texto = _texto_da_resposta(resultado.payload).strip()
        except Exception as exc:
            log.warning("retrieval.hyde.failed", error=str(exc)[:200])
            texto = ""
        if texto:
            preparada.hyde = texto
            # O documento hipotético substitui a pergunta **só no embedding**.
            # A perna lexical continua com os termos reais: um documento
            # inventado enche o full-text de identificadores que não existem.
            preparada.embed_text = texto

    return preparada
