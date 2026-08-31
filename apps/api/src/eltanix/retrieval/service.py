"""Orquestração da recuperação: preparo → fontes → fusão → rerank → diversidade → packing.

O que esta camada **não** é: uma abstração por cima dos quatro stores. Eles
continuam independentes, cada um dono do seu SQL, e a duplicação entre os três
`hybrid_search` segue deliberada (CLAUDE.md). O que existe aqui é o pipeline
que roda *depois* que eles devolveram — e antes disto ele não existia em lugar
nenhum: cada chamador pegava `limit=8` de uma fonte só e colava no prompt.

A direção da dependência é única e vale como invariante: `retrieval/` importa
dos stores, os stores nunca importam de `retrieval/`.

Ordem das etapas, e por que nesta ordem:

- **Preparo antes de tudo**: a normalização muda o texto que vai para a perna
  lexical, e a expansão muda quantas buscas serão feitas.
- **Fusão antes do rerank**: rerankear cada fonte separadamente e depois juntar
  reintroduz o problema de comparar escalas incomparáveis. Fundir por rank
  primeiro dá uma lista única, e é sobre ela que o reranker julga.
- **Rerank antes da diversidade**: MMR trabalha com o `score` da posição; se ele
  rodar antes, diversifica uma ordem que o reranker vai desmanchar.
- **Packing por último**: é o único ponto que sabe quanto cabe, e é o único que
  pode cortar. Todas as etapas anteriores reordenam e rebaixam, nenhuma
  descarta pensando em orçamento.

Cada etapa degrada sozinha. Sem embedding, a busca cai para as pernas lexicais;
sem reranker, fica a ordem da fusão; sem expansão, uma consulta só. Uma busca
degradada continua sendo uma busca — o que não pode acontecer é a camada
derrubar o que funcionava antes dela.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eltanix.config import Settings
from eltanix.context import store as context_store
from eltanix.context.git_aware import git_aware_search
from eltanix.db.session import session_scope
from eltanix.documents import store as documents_store
from eltanix.logging_setup import get_logger
from eltanix.notes import store as notes_store
from eltanix.retrieval import query as query_prep
from eltanix.retrieval.diversity import diversify
from eltanix.retrieval.fusion import SignalWeights, SourceWeights, fuse
from eltanix.retrieval.pack import PackedContext, pack
from eltanix.retrieval.policy import SourcePlan, plan_sources
from eltanix.retrieval.rerank import rerank
from eltanix.retrieval.types import RetrievedItem, Source

log = get_logger(__name__)


@dataclass(slots=True)
class RetrievalRequest:
    query: str
    # Sem `root`, a fonte `context` sai do plano: não há workspace de código
    # para buscar, e insistir devolveria hits de outro projeto.
    root: Path | None = None
    project_slug: str | None = None
    limit: int = 8
    token_budget: int | None = None
    path_prefix: str | None = None
    # `None` deixa a política decidir; uma tupla explícita manda nela.
    sources: tuple[Source, ...] | None = None
    expand: bool | None = None
    hyde: bool | None = None
    use_rerank: bool | None = None
    session_id: str | None = None


@dataclass(slots=True)
class RetrievalResult:
    items: list[RetrievedItem]
    packed: PackedContext
    plan: SourcePlan
    prepared: query_prep.PreparedQuery
    stats: dict[str, Any] = field(default_factory=dict)

    @property
    def citations(self) -> list[str]:
        return [item.citation for item in self.items]


def _do_codigo(hit: context_store.SearchHit) -> RetrievedItem:
    return RetrievedItem(
        source="context",
        key=f"{hit.path}:{hit.start_line}-{hit.end_line}",
        citation=hit.citation,
        content=hit.content,
        score=hit.score,
        token_count=hit.token_count,
        vector_rank=hit.vector_rank,
        text_rank=hit.text_rank,
        trigram_rank=hit.trigram_rank,
        meta={
            "path": hit.path,
            "symbol": hit.symbol,
            "kind": hit.kind,
            "language": hit.language,
            "start_line": hit.start_line,
            "end_line": hit.end_line,
        },
    )


def _do_documento(hit: documents_store.DocumentSearchHit) -> RetrievedItem:
    pagina = f", p.{hit.page_number}" if hit.page_number else ""
    return RetrievedItem(
        source="documents",
        key=f"{hit.document_id}#{hit.chunk_index}",
        citation=f"{hit.filename} (trecho {hit.chunk_index}{pagina})",
        content=hit.content,
        score=hit.score,
        token_count=hit.token_count,
        vector_rank=hit.vector_rank,
        text_rank=hit.text_rank,
        meta={
            # `path` é o agrupador da diversidade: dois trechos do mesmo
            # documento competem entre si, como dois do mesmo arquivo.
            "path": hit.filename,
            "filename": hit.filename,
            "document_id": hit.document_id,
            "page_number": hit.page_number,
        },
    )


def _de_nota(hit: notes_store.NoteSearchHit) -> RetrievedItem:
    return RetrievedItem(
        source="notes",
        key=f"{hit.note_id}#{hit.chunk_index}",
        citation=f"nota: {hit.title} (trecho {hit.chunk_index})",
        content=hit.content,
        score=hit.score,
        token_count=hit.token_count,
        vector_rank=hit.vector_rank,
        text_rank=hit.text_rank,
        meta={"path": hit.title, "title": hit.title, "note_id": hit.note_id},
    )


class RetrievalService:
    """Pipeline de recuperação, instanciado uma vez no `lifespan`.

    Recebe o `RouterEngine` (única porta de LLM, ADR 0001) e o `IndexerService`
    — este último só para resolver a chave de workspace, que é dele. Não guarda
    sessão de banco: cada busca abre a sua, como os stores esperam.
    """

    def __init__(
        self,
        *,
        engine: Any,
        settings: Settings,
        indexer: Any | None = None,
        trace_recorder: Any | None = None,
    ) -> None:
        self.engine = engine
        self.settings = settings
        self.indexer = indexer
        self.trace_recorder = trace_recorder

    # ── pesos ────────────────────────────────────────────────────────────────

    def _signal_weights(self) -> SignalWeights:
        s = self.settings
        return SignalWeights(
            vector=s.retrieval_weight_vector,
            text=s.retrieval_weight_text,
            trigram=s.retrieval_weight_trigram,
            k=s.retrieval_rrf_k,
        )

    def _source_weights(self) -> SourceWeights:
        s = self.settings
        return SourceWeights(
            context=s.retrieval_source_weight_context,
            documents=s.retrieval_source_weight_documents,
            notes=s.retrieval_source_weight_notes,
        )

    # ── embedding ────────────────────────────────────────────────────────────

    async def _embed(self, textos: list[str]) -> tuple[list[list[float] | None], str | None]:
        """Embute as variantes num lote só.

        Um lote em vez de uma chamada por variante: o custo do embedding é
        dominado pelo round-trip, e três variantes numa chamada custam quase o
        mesmo que uma. Falhar aqui não é erro — devolve vetores nulos e a busca
        segue pelas pernas lexicais.
        """
        if not textos:
            return [], None
        try:
            resultado = await self.engine.embed(
                requested_model=self.settings.embedding_profile,
                inputs=textos,
                source="retrieval",
                purpose="query",
            )
        except Exception as exc:
            log.warning("retrieval.embed.failed", error=str(exc)[:200])
            return [None] * len(textos), None

        dados = resultado.payload.get("data") or []
        por_indice = {
            int(item.get("index", i)): item.get("embedding") for i, item in enumerate(dados)
        }
        vetores = [por_indice.get(i) for i in range(len(textos))]
        modelo = resultado.provenance_tag if any(v is not None for v in vetores) else None
        return vetores, modelo

    # ── fontes ───────────────────────────────────────────────────────────────

    async def _buscar(
        self,
        *,
        source: Source,
        session: Any,
        texto_lexical: str,
        vetor: list[float] | None,
        embedding_model: str | None,
        pool: int,
        pedido: RetrievalRequest,
    ) -> list[RetrievedItem]:
        pesos = self._signal_weights()
        ef = self.settings.hnsw_ef_search

        if source == "context":
            if pedido.root is None or self.indexer is None:
                return []
            workspace = self.indexer.workspace_key(pedido.root)
            if self.settings.context_git_aware_search:
                # O git-aware (Fase 4) não some por causa desta camada: ele é a
                # perna de código quando está ligado, e o pipeline continua por
                # cima dele. Trocar um pelo outro seria desligar um recurso já
                # entregue de lado, sem ninguém pedir.
                hits = await git_aware_search(
                    session,
                    root=pedido.root,
                    workspace=workspace,
                    query_text=texto_lexical,
                    query_embedding=vetor,
                    limit=pool,
                    path_prefix=pedido.path_prefix,
                    embedding_model=embedding_model,
                    ef_search=ef,
                    vector_weight=pesos.vector,
                    text_weight=pesos.text,
                    trigram_weight=pesos.trigram,
                    rrf_k=pesos.k,
                )
            else:
                hits = await context_store.hybrid_search(
                    session,
                    workspace=workspace,
                    query_text=texto_lexical,
                    query_embedding=vetor,
                    limit=pool,
                    candidate_pool=pool,
                    path_prefix=pedido.path_prefix,
                    embedding_model=embedding_model,
                    ef_search=ef,
                    vector_weight=pesos.vector,
                    text_weight=pesos.text,
                    trigram_weight=pesos.trigram,
                    rrf_k=pesos.k,
                )
            return [_do_codigo(h) for h in hits]

        if source == "documents":
            hits = await documents_store.hybrid_search(
                session,
                query_text=texto_lexical,
                query_embedding=vetor,
                limit=pool,
                candidate_pool=pool,
                project_slug=pedido.project_slug,
                embedding_model=embedding_model,
                ef_search=ef,
                vector_weight=pesos.vector,
                text_weight=pesos.text,
                rrf_k=pesos.k,
            )
            return [_do_documento(h) for h in hits]

        if source == "notes":
            hits = await notes_store.hybrid_search(
                session,
                query_text=texto_lexical,
                query_embedding=vetor,
                limit=pool,
                candidate_pool=pool,
                project_slug=pedido.project_slug,
                embedding_model=embedding_model,
                ef_search=ef,
                vector_weight=pesos.vector,
                text_weight=pesos.text,
                rrf_k=pesos.k,
            )
            return [_de_nota(h) for h in hits]

        return []

    # ── pipeline ─────────────────────────────────────────────────────────────

    async def retrieve(self, pedido: RetrievalRequest) -> RetrievalResult:
        inicio = time.perf_counter()
        s = self.settings
        status = "ok"

        expandir = s.retrieval_expansion_enabled if pedido.expand is None else pedido.expand
        usar_hyde = s.retrieval_hyde_enabled if pedido.hyde is None else pedido.hyde
        usar_rerank = s.retrieval_rerank_enabled if pedido.use_rerank is None else pedido.use_rerank
        orcamento = pedido.token_budget or s.retrieval_token_budget

        preparada = await query_prep.prepare(
            pedido.query,
            engine=self.engine,
            profile=s.retrieval_utility_profile,
            expand=expandir,
            hyde=usar_hyde,
            project_slug=pedido.project_slug,
        )

        if pedido.sources is not None:
            plano = SourcePlan(sources=pedido.sources, reason="fontes explícitas no pedido")
        else:
            plano = plan_sources(
                pedido.query,
                allow_documents=s.retrieval_documents_enabled,
                allow_notes=s.retrieval_notes_enabled,
            )
        fontes = tuple(f for f in plano.sources if f != "context" or pedido.root is not None)

        # Cada variante vira uma busca por fonte. O teto existe porque o produto
        # `variantes × fontes` cresce rápido e cada célula é uma query ao banco.
        variantes = preparada.variants[: max(1, s.retrieval_max_variants)]
        # HyDE substitui o texto embutido da consulta original; as variantes
        # seguem como elas mesmas.
        textos_para_embutir = [preparada.embed_text, *variantes[1:]]
        vetores, embedding_model = await self._embed(textos_para_embutir)

        pool = max(pedido.limit, s.retrieval_candidate_pool)
        grupos: list[list[RetrievedItem]] = []
        try:
            async with session_scope() as session:
                for indice, variante in enumerate(variantes):
                    # A variante original usa o texto lexical normalizado; as
                    # reformulações do modelo já vêm sem ruído de pergunta.
                    lexical = preparada.lexical if indice == 0 else variante
                    vetor = vetores[indice] if indice < len(vetores) else None
                    for fonte in fontes:
                        encontrados = await self._buscar(
                            source=fonte,
                            session=session,
                            texto_lexical=lexical,
                            vetor=vetor,
                            embedding_model=embedding_model,
                            pool=pool,
                            pedido=pedido,
                        )
                        if encontrados:
                            grupos.append(encontrados)
        except Exception:
            status = "error"
            self._registrar_span(
                inicio=inicio,
                status=status,
                pedido=pedido,
                preparada=preparada,
                plano=plano,
                fontes=fontes,
                embedding_model=embedding_model,
                bruto=0,
                fundidos=0,
                itens=[],
                rerank_llm=False,
                rerank_erro=None,
                packed=None,
            )
            raise

        fundidos = fuse(grupos, weights=self._source_weights(), k=s.retrieval_rrf_k)
        bruto = sum(len(g) for g in grupos)

        # Sobreamostragem antes de diversificar: MMR só tem o que diversificar
        # se receber mais candidatos do que vai devolver.
        alvo = max(pedido.limit, 1)
        resultado_rerank = await rerank(
            fundidos[: s.retrieval_rerank_candidates],
            query=preparada.original,
            engine=self.engine if usar_rerank else None,
            identifiers=preparada.identifiers,
            limit=alvo * s.retrieval_oversample,
            profile=s.retrieval_utility_profile,
            use_llm=usar_rerank,
            project_slug=pedido.project_slug,
        )

        diversos = diversify(
            resultado_rerank.items,
            limit=alvo,
            lambda_=s.retrieval_mmr_lambda,
        )
        empacotado = pack(diversos, token_budget=orcamento, max_items=alvo)

        self._registrar_span(
            inicio=inicio,
            status=status,
            pedido=pedido,
            preparada=preparada,
            plano=plano,
            fontes=fontes,
            embedding_model=embedding_model,
            bruto=bruto,
            fundidos=len(fundidos),
            itens=empacotado.items,
            rerank_llm=resultado_rerank.used_llm,
            rerank_erro=resultado_rerank.llm_error,
            packed=empacotado,
        )

        return RetrievalResult(
            items=empacotado.items,
            packed=empacotado,
            plan=plano,
            prepared=preparada,
            stats={
                "sources": list(fontes),
                "searches": len(grupos),
                "raw_hits": bruto,
                "fused": len(fundidos),
                "reranked_by_llm": resultado_rerank.used_llm,
                "expanded": preparada.expanded,
                "hyde": preparada.hyde is not None,
                "degraded_to_lexical": embedding_model is None,
                "tokens_used": empacotado.tokens_used,
                "tokens_budget": empacotado.tokens_budget,
                "dropped": empacotado.dropped,
            },
        )

    def _registrar_span(
        self,
        *,
        inicio: float,
        status: str,
        pedido: RetrievalRequest,
        preparada: query_prep.PreparedQuery,
        plano: SourcePlan,
        fontes: tuple[Source, ...],
        embedding_model: str | None,
        bruto: int,
        fundidos: int,
        itens: list[RetrievedItem],
        rerank_llm: bool,
        rerank_erro: str | None,
        packed: PackedContext | None,
    ) -> None:
        if self.trace_recorder is None:
            return
        self.trace_recorder.record(
            kind="rag",
            name="retrieval",
            latency_ms=(time.perf_counter() - inicio) * 1000.0,
            status=status,
            attributes={
                "query_chars": len(pedido.query),
                "sources": ",".join(fontes),
                "plan_reason": plano.reason,
                "variants": len(preparada.variants),
                "expanded": preparada.expanded,
                "hyde": preparada.hyde is not None,
                "raw_hits": bruto,
                "fused": fundidos,
                "returned": len(itens),
                "reranked_by_llm": rerank_llm,
                "rerank_error": rerank_erro or "",
                "embedding_model": embedding_model or "",
                # A distinção que o span de Onda 0 já registra por fonte, agora
                # para o pipeline inteiro: busca sem vetor não é a mesma busca.
                "degraded_to_lexical": embedding_model is None,
                "tokens_used": packed.tokens_used if packed else 0,
                "tokens_budget": packed.tokens_budget if packed else 0,
                "dropped": packed.dropped if packed else 0,
            },
        )
