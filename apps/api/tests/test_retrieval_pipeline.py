"""Camada `retrieval/`: preparo de consulta, fusão, diversidade, packing e rerank.

Tudo aqui é puro ou usa um `engine` falso — nada toca banco nem modelo. O que
depende de Postgres de verdade (as três `hybrid_search` que o pipeline chama)
já é coberto por `test_hybrid_search.py`.
"""

from __future__ import annotations

import pytest

from eltanix.retrieval.diversity import (
    diversify,
    drop_near_duplicates,
    jaccard,
    mmr,
)
from eltanix.retrieval.fusion import SourceWeights, fuse
from eltanix.retrieval.pack import pack
from eltanix.retrieval.policy import plan_sources
from eltanix.retrieval.query import (
    PreparedQuery,
    extract_identifiers,
    normalize,
    prepare,
    should_expand,
)
from eltanix.retrieval.rerank import lexical_rerank, rerank
from eltanix.retrieval.types import RetrievedItem


def item(
    key: str,
    *,
    source: str = "context",
    content: str = "",
    score: float = 0.5,
    tokens: int = 10,
    path: str | None = None,
    symbol: str | None = None,
) -> RetrievedItem:
    return RetrievedItem(
        source=source,  # type: ignore[arg-type]
        key=key,
        citation=key,
        content=content or f"conteudo de {key}",
        score=score,
        token_count=tokens,
        meta={"path": path or key.split(":")[0], "symbol": symbol},
    )


class FakeEngine:
    """`RouterEngine` de mentira: devolve o texto combinado e conta chamadas."""

    def __init__(self, resposta: str = "", *, erro: Exception | None = None) -> None:
        self.resposta = resposta
        self.erro = erro
        self.chamadas: list[str] = []

    async def complete(self, *, requested_model, params, source, project_slug=None, **_):
        self.chamadas.append(source)
        if self.erro is not None:
            raise self.erro
        return type("R", (), {"payload": {"choices": [{"message": {"content": self.resposta}}]}})()


# ── preparo da consulta ─────────────────────────────────────────────────────


def test_normalize_preserva_identificador_inteiro():
    """Quebrar `agent/graph.py` em palavras injetaria `py`, que casa com tudo."""
    saida = normalize("onde é que a gente aprova ferramenta em agent/graph.py?")
    assert "agent/graph.py" in saida
    assert " py" not in saida
    assert "onde" not in saida and "que" not in saida


def test_normalize_tira_ruido_acentuado():
    """A lista de ruído é escrita sem acento; `é` tem de cair mesmo assim."""
    assert normalize("o que é a aprovacao de ferramenta") == "aprovacao ferramenta"


def test_normalize_de_pergunta_so_com_ruido_devolve_a_original():
    """Consulta vazia faria o `websearch_to_tsquery` não casar com nada."""
    assert normalize("por que isso?") == "por que isso?"


def test_extract_identifiers_reconhece_as_convencoes():
    achados = extract_identifiers("resolve_project, getUserById e workspace/projects.py")
    assert achados == ["resolve_project", "getUserById", "workspace/projects.py"]


def test_should_expand_so_para_pergunta_curta_e_vaga():
    assert should_expand("como funciona a aprovacao")
    assert not should_expand("quem chama resolve_project")
    assert not should_expand(
        "explique detalhadamente todo o processo de aprovacao humana no fluxo agentico"
    )


@pytest.mark.asyncio
async def test_prepare_sem_engine_nao_expande():
    preparada = await prepare("como funciona a aprovacao", engine=None)
    assert preparada.variants == ["como funciona a aprovacao"]
    assert not preparada.expanded


@pytest.mark.asyncio
async def test_prepare_expande_e_mantem_a_original_em_primeiro():
    engine = FakeEngine("1. qual o fluxo de aprovacao\n- aprovar ferramenta\nrisco e aprovacao")
    preparada = await prepare("como funciona a aprovacao", engine=engine)
    assert preparada.expanded
    assert preparada.variants[0] == "como funciona a aprovacao"
    # A numeração do modelo é limpa mesmo tendo sido proibida no prompt.
    assert "qual o fluxo de aprovacao" in preparada.variants


@pytest.mark.asyncio
async def test_prepare_nao_expande_quando_a_pergunta_cita_identificador():
    engine = FakeEngine("variante a\nvariante b")
    preparada = await prepare("quem chama resolve_project", engine=engine)
    assert not preparada.expanded
    assert engine.chamadas == []


@pytest.mark.asyncio
async def test_prepare_degrada_quando_o_modelo_falha():
    engine = FakeEngine(erro=RuntimeError("provedor fora"))
    preparada = await prepare("como funciona a aprovacao", engine=engine)
    assert preparada.variants == ["como funciona a aprovacao"]
    assert not preparada.expanded


@pytest.mark.asyncio
async def test_hyde_troca_so_o_texto_embutido():
    """O documento hipotético não pode contaminar a perna lexical."""
    engine = FakeEngine("def aprovar_ferramenta(risco): ...")
    preparada = await prepare("como funciona a aprovacao", engine=engine, expand=False, hyde=True)
    assert preparada.embed_text == "def aprovar_ferramenta(risco): ..."
    assert preparada.lexical == normalize("como funciona a aprovacao")
    assert preparada.original == "como funciona a aprovacao"


def test_prepared_query_default_embed_text_e_a_original():
    p = PreparedQuery(original="x", lexical="x")
    assert p.embed_text == "x"
    assert p.variants == ["x"]


# ── política de fontes ──────────────────────────────────────────────────────


def test_plan_sources_sinal_de_codigo_fica_so_no_contexto():
    plano = plan_sources("onde fica resolve_project em workspace/projects.py")
    assert plano.sources == ("context",)


def test_plan_sources_pergunta_sobre_decisao_inclui_conhecimento():
    plano = plan_sources("por que decidimos usar um executor isolado?")
    assert "documents" in plano and "notes" in plano


def test_plan_sources_sempre_inclui_contexto():
    assert "context" in plan_sources("qualquer coisa")


def test_plan_sources_respeita_as_fontes_desligadas():
    plano = plan_sources("por que essa decisao", allow_documents=False, allow_notes=False)
    assert plano.sources == ("context",)


# ── fusão entre fontes ──────────────────────────────────────────────────────


def test_fuse_usa_rank_e_nao_score():
    """Score de fontes diferentes vive em escalas incomparáveis."""
    codigo = [item("a.py:1", score=0.001)]
    notas = [item("n1", source="notes", score=99.0)]
    fundido = fuse([codigo, notas], weights=SourceWeights(context=1.0, notes=0.7))
    assert fundido[0].key == "a.py:1"


def test_fuse_soma_a_evidencia_de_fontes_diferentes():
    a = item("x", source="context")
    b = item("y", source="context")
    doc = item("x", source="documents")
    fundido = fuse([[a, b], [doc]])
    chaves = [f"{i.source}:{i.key}" for i in fundido]
    # `context:x` e `documents:x` são itens distintos (fontes distintas), mas
    # ambos ficam à frente de `context:y`, que só apareceu uma vez no topo.
    assert chaves.index("context:x") < chaves.index("context:y")


def test_fuse_ignora_fonte_com_peso_zero():
    fundido = fuse(
        [[item("a")], [item("n", source="notes")]],
        weights=SourceWeights(context=1.0, notes=0.0),
    )
    assert [i.key for i in fundido] == ["a"]


# ── diversidade ─────────────────────────────────────────────────────────────


def test_jaccard_compara_identificadores_e_nao_caracteres():
    a = "def resolve_project(slug):\n    return record.local_path"
    b = "def   resolve_project( slug ):\n        return record.local_path"
    assert jaccard(a, b) == pytest.approx(1.0)


def test_drop_near_duplicates_mantem_o_melhor_colocado():
    a = item("a", content="alpha beta gama delta", score=0.9)
    b = item("b", content="alpha beta gama delta", score=0.5)
    c = item("c", content="epsilon zeta eta theta", score=0.4)
    mantidos = drop_near_duplicates([a, b, c])
    assert [i.key for i in mantidos] == ["a", "c"]


def test_mmr_nao_mexe_no_primeiro_colocado():
    itens = [item(f"f{i}.py:1", score=1.0 - i * 0.1) for i in range(5)]
    assert mmr(itens, limit=3)[0].key == "f0.py:1"


def test_mmr_penaliza_trecho_do_mesmo_arquivo():
    """Oito trechos de `graph.py` gastam o orçamento repetindo o mesmo ângulo."""
    itens = [
        item("graph.py:1", path="graph.py", content="aprovacao risco write", score=0.90),
        item("graph.py:2", path="graph.py", content="aprovacao risco exec", score=0.89),
        item("base.py:1", path="base.py", content="riskclass declara ferramenta", score=0.60),
    ]
    escolhidos = [i.key for i in mmr(itens, limit=2, lambda_=0.5)]
    assert escolhidos == ["graph.py:1", "base.py:1"]


def test_diversify_deduplica_antes_de_diversificar():
    itens = [
        item("a", content="mesmo texto identico aqui", score=0.9),
        item("b", content="mesmo texto identico aqui", score=0.8),
        item("c", content="outro assunto totalmente diferente", score=0.7),
    ]
    assert [i.key for i in diversify(itens, limit=2)] == ["a", "c"]


# ── packing ─────────────────────────────────────────────────────────────────


def test_pack_respeita_o_orcamento():
    itens = [item(f"a{i}", tokens=100) for i in range(10)]
    empacotado = pack(itens, token_budget=250)
    assert len(empacotado.items) == 2
    assert empacotado.tokens_used <= 250
    assert empacotado.dropped == 8


def test_pack_pula_o_item_grande_em_vez_de_parar():
    """Um trecho enorme na segunda posição não pode barrar os pequenos."""
    itens = [item("a", tokens=10), item("gigante", tokens=10_000), item("c", tokens=10)]
    empacotado = pack(itens, token_budget=100)
    assert [i.key for i in empacotado.items] == ["a", "c"]
    assert empacotado.dropped == 1


def test_pack_nunca_trunca_conteudo():
    itens = [item("a", tokens=10, content="conteudo completo do trecho")]
    empacotado = pack(itens, token_budget=1000)
    assert "conteudo completo do trecho" in empacotado.text
    assert empacotado.citations == ["a"]


def test_pack_com_orcamento_zero_devolve_vazio():
    empacotado = pack([item("a")], token_budget=0)
    assert empacotado.items == [] and empacotado.dropped == 1


# ── rerank ──────────────────────────────────────────────────────────────────


def test_lexical_rerank_privilegia_a_definicao_sobre_a_menção():
    usa = item("usa.py:1", content="chamamos resolve_project aqui", score=0.5)
    define = item("def.py:1", content="corpo", score=0.5, symbol="resolve_project")
    ordenados = lexical_rerank([usa, define], identifiers=["resolve_project"])
    assert ordenados[0].key == "def.py:1"


def test_lexical_rerank_sem_identificador_e_estavel():
    itens = [item("b", score=0.4), item("a", score=0.9)]
    assert [i.key for i in lexical_rerank(itens, identifiers=[])] == ["b", "a"]


@pytest.mark.asyncio
async def test_rerank_aplica_a_ordem_do_modelo():
    itens = [item("a"), item("b"), item("c")]
    resultado = await rerank(itens, query="q", engine=FakeEngine("3, 1"), limit=3)
    assert resultado.used_llm
    # O modelo escolheu 3 e 1; `b` volta atrás deles, não some.
    assert [i.key for i in resultado.items] == ["c", "a", "b"]


@pytest.mark.asyncio
async def test_rerank_ignora_indice_fora_da_faixa():
    itens = [item("a"), item("b")]
    resultado = await rerank(itens, query="q", engine=FakeEngine("9, 2, 2"), limit=2)
    assert [i.key for i in resultado.items] == ["b", "a"]


@pytest.mark.asyncio
async def test_rerank_com_resposta_ilegivel_mantem_a_ordem_de_entrada():
    itens = [item("a", score=0.9), item("b", score=0.5)]
    resultado = await rerank(itens, query="q", engine=FakeEngine("nao sei dizer"), limit=2)
    assert not resultado.used_llm
    assert resultado.llm_error == "unparseable"
    assert [i.key for i in resultado.items] == ["a", "b"]


@pytest.mark.asyncio
async def test_rerank_degrada_quando_o_modelo_cai():
    itens = [item("a", score=0.9), item("b", score=0.5)]
    resultado = await rerank(itens, query="q", engine=FakeEngine(erro=TimeoutError()), limit=2)
    assert not resultado.used_llm
    assert resultado.llm_error == "TimeoutError"
    assert [i.key for i in resultado.items] == ["a", "b"]


@pytest.mark.asyncio
async def test_rerank_sem_engine_so_faz_a_passagem_lexical():
    itens = [item("a", score=0.5), item("b", score=0.5, symbol="alvo")]
    resultado = await rerank(itens, query="q", engine=None, identifiers=["alvo"], limit=2)
    assert resultado.lexical_applied and not resultado.used_llm
    assert resultado.items[0].key == "b"
