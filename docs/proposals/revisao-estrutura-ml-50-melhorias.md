# Revisão da Estrutura de Machine Learning — 50 Melhorias

> Status: **Ondas 0 e 1 entregues** · Ondas 2–4 pendentes · Data: 2026-08-31
> · Escopo: `apps/api/src/eltanix/{router,retrieval,context,graphify,optimizer,analytics,evals,agent}` + `config/*.yaml`
>
> A Onda 0 (itens 1–6, 45, 46, 49) está em
> [ADR 0017](../adr/0017-contrato-do-espaco-vetorial.md) e
> [ADR 0018](../adr/0018-gate-de-qualidade-de-recuperacao.md); a Onda 1
> (itens 7–15, 47) em [ADR 0019](../adr/0019-camada-de-recuperacao.md). Ver
> [§6 — O que a Onda 0 entregou](#6--o-que-a-onda-0-entregou) e
> [§7 — O que a Onda 1 entregou](#7--o-que-a-onda-1-entregou).
>
> Este documento revisa toda a superfície de ML/IA da IDE e propõe 50 melhorias priorizadas.
> Nenhum item viola os invariantes de arquitetura do [CLAUDE.md](../../CLAUDE.md) — em particular,
> a **camada única de LLM** (ADR 0001) e a **duplicação deliberada entre as fontes de RAG**
> (`context/store.py`, `documents/store.py`, `notes/store.py`, `graphify/store.py`), que
> permanecem independentes.

---

## 1. Diagnóstico

### O que já está maduro

| Camada | Estado |
| :--- | :--- |
| **Gateway LLM** (`router/`) | Porta única real. Catálogo declarativo, política por `priority`/`cost`/`latency`/`score`, circuit breaker com cooldown exponencial, `BudgetGuard`, tabela de preços, telemetria por request. Melhor que a média de IDEs agênticas. |
| **RAG de código** (`context/`) | Chunking simbólico com tree-sitter + chunks de lacuna + split de excedente; pgvector HNSW + `tsvector` fundidos por RRF; arestas de import/containment; rerank git-aware. |
| **Otimização** (`optimizer/`) | Compressor de histórico com medição de tokens economizados, cache de resposta, cache semântico, classificador de complexidade para rebaixar tarefa trivial. |
| **Editor** (`context/completions.py`, `next_edit.py`) | Ghost text e next-edit com kill switch, rate limit, perfil de rota próprio e telemetria de aceitação (`completion_event`). |
| **Testes** | 106 arquivos em `apps/api/tests`, cobrindo chunker, hybrid search, complexity, compressor, evals, next-edit, graphify. |

### Onde a estrutura falha

1. **Recuperação para na fusão.** O RRF é a ordenação final — não há segunda passagem de rerank. É o maior ganho de precisão disponível e não está sendo colhido.
2. **A avaliação é decorativa.** `config/eval_dataset.yaml` tem **2 casos** apontando para caminho placeholder. Sem baseline, nenhuma das 49 melhorias restantes é mensurável.
3. **Espaço vetorial sem contrato.** Não existe coluna dizendo qual modelo gerou cada vetor, e o perfil `embedding` mistura modelos de dimensões diferentes.
4. **O grafo entrega menos do que promete.** O schema tem `layer` 1/2/3; o pipeline só grava `layer=1`. O CLAUDE.md anuncia *community detection*; `GraphAnalytics` só calcula densidade, órfãos e PageRank.
5. **Não há loop fechado.** Aceitação de completion, propostas de correção do analytics e telemetria de roteamento são gravadas e não realimentam nada.

---

## 2. Estrutura-alvo

A mudança estrutural é **uma camada nova**, `retrieval/`, que fica *acima* dos quatro stores sem
fundi-los. Cada store continua dono do seu SQL; a camada nova só recebe `SearchHit` e decide
fusão, rerank, diversidade e empacotamento.

```
eltanix/
├── router/                 # porta única de LLM (ADR 0001) — inalterada no contrato
│   ├── engine.py           # + cascata especulativa, saída estruturada, cache de embedding
│   └── catalog.py          # + embedding_dim por ModelSpec, validação no boot
│
├── retrieval/              ◀ NOVO — orquestra, não substitui os stores
│   ├── query.py            # reescrita, multi-query, prefixo assimétrico, HyDE
│   ├── fusion.py           # RRF ponderado + normalização de score + trigram
│   ├── rerank.py           # cross-encoder local ou rerank listwise via perfil `utility`
│   ├── diversity.py        # MMR + supressão de near-duplicate
│   ├── pack.py             # montagem por orçamento de tokens com citação estável
│   └── policy.py           # qual fonte consultar por intenção (código/doc/nota/grafo)
│
├── context/                # RAG de código — store permanece independente
├── documents/  notes/      # idem (duplicação deliberada, ver CLAUDE.md)
├── graphify/               # + camadas L2/L3, Leiden, PageRank incremental
├── optimizer/              # inalterado no contrato
├── analytics/              # + loop fechado: proposta → skill/prompt → medição
└── evals/                  ◀ passa a ser gate de CI, não script manual
    ├── suites/retrieval.py     # recall@k, MRR, nDCG
    ├── suites/completion.py    # ghost text e next-edit offline
    ├── suites/agent.py         # tarefas agênticas do próprio repo
    └── judge.py                # juiz calibrado, com concordância medida
```

---

## 3. As 50 melhorias

### A — Riscos imediatos (bugs latentes e inconsistências)

| # | Melhoria | Evidência | Ação |
| :--- | :--- | :--- | :--- |
| 1 | **Dimensão de embedding incompatível no perfil `embedding`** | `config.py:107` fixa `EMBEDDING_DIM=768` (nomic); `config/routes.yaml` põe `databricks/bge-large-en` (1024 dims) como **primeiro** candidato do perfil | Declarar `embedding_dim` no `ModelSpec`, validar em `load_catalog()` e falhar no boot se um modelo do perfil não bater com `EMBEDDING_DIM` |
| 2 | **Modelo de embedding rotulado como chat** | `config/providers.yaml:399-406` — `databricks/qwen3-embedding-0-6b` com `capabilities: [chat]` | Corrigir `capabilities`/`tags`; validar no catálogo que id contendo `embedding` não entra em pool de chat |
| 3 | **Vetor sem proveniência** | Nenhuma tabela com `embedding` guarda o modelo gerador (`db/models.py`) | Migração: `embedding_model` + `embedding_dim` em `code_chunk`, `document_chunk`, `note_chunk`, `graph_node`, `skill`; filtrar na busca; job de re-embed ao trocar modelo |
| 4 | ~~**Top-k vetorial não usa o índice HNSW**~~ — **hipótese derrubada pela medição** | `EXPLAIN ANALYZE` contra pgvector mostra que a forma original **já usava** `Index Scan using ix_*_embedding`, nas duas variantes (com e sem JOIN): o planner empurra o `LIMIT` através do `WindowAgg`. Os planos custam o mesmo | A subquery explícita foi mantida por correção (o `LIMIT` após janela dependia da ordem de emissão do `WindowAgg`), não por desempenho. **Não há ganho de latência a colher aqui** |
| 5 | **`hnsw.ef_search` nunca ajustado** | Nenhuma ocorrência em `src/` nem em `alembic/versions/` | `SET LOCAL hnsw.ef_search = :ef` por query de busca, com valor configurável e medido contra recall |
| 6 | **Nada dispara o reprocessamento do embedding que falhou** | O arquivo já é gravado com `content_hash` prefixado por `pendente:`, o que garante que a *próxima* indexação o reprocesse — mas nada pede essa indexação, e o sintoma (busca pior) não aponta para a causa | Reaper de backfill que reindexa só os workspaces com pendência + `embedding_coverage` e `files_pending_embedding` no `index_stats` |

### B — Recuperação e RAG

| # | Melhoria | Por quê |
| :--- | :--- | :--- |
| 7 | **Reranker de segunda passagem** (`retrieval/rerank.py`) | A ordenação final é o próprio RRF. Cross-encoder local (`bge-reranker` via Ollama/ONNX) ou rerank listwise no perfil `utility` sobre top-50 → top-8 é o maior ganho de precisão disponível |
| 8 | **RRF ponderado e normalizado** | `RRF_K` é constante global e vetor/texto pesam igual (`context/store.py:155+`). Peso por fonte e por intenção, afinado pelas evals |
| 9 | **MMR + supressão de near-duplicate** | Hoje 8 hits podem ser 8 trechos do mesmo arquivo; diversidade vale mais que redundância dentro do orçamento |
| 10 | **Tokenização code-aware no full-text** | `to_tsvector('simple', content)` não quebra `camelCase`/`snake_case` — buscar `getUserById` não acha `get_user_by_id` |
| 11 | **`pg_trgm` como terceiro sinal** | Similaridade trigram sobre `symbol`/`path` resolve nome parcial e erro de digitação, que nem vetor nem full-text pegam bem |
| 12 | **Prefixo assimétrico de query** | `Chunk.as_embedding_text()` é usado nos dois lados; nomic/BGE exigem prefixos distintos (`search_query:` vs `search_document:`) para não perder recall |
| 13 | **Reescrita e expansão de query** | Multi-query + HyDE opcional no perfil `utility`, com custo controlado por complexidade |
| 14 | **Camada `retrieval/`** | Fusão, rerank, diversidade e packing num só lugar — os quatro stores continuam independentes, como manda o CLAUDE.md |
| 15 | **Packing por orçamento de tokens** | Corte por chunk com citação estável, não truncamento de lista |
| 16 | **Pool adaptativo** | `candidate_pool=50` fixo; escalar com o tamanho do índice e com o recall medido |
| 17 | **Repomap por PageRank do `CodeEdge`** | `context/repomap.py:79` ordena por densidade de símbolos; o grafo de imports já existe e dá um mapa melhor (estilo aider) |
| 18 | **Reindex incremental por arquivo** | Só existe `POST /api/context/index` do workspace inteiro; o save do editor deveria reindexar um arquivo |
| 19 | **Overlap e cabeçalho de símbolo no chunking** | `_split_oversized` corta em `MAX_CHUNK_TOKENS=900` sem overlap nem prefixo com a assinatura do símbolo pai |

### C — Roteamento e serving

| # | Melhoria | Por quê |
| :--- | :--- | :--- |
| 20 | **Cascata especulativa** | Modelo pequeno primeiro, escalando por validação/confiança — o `_apply_complexity` só decide *antes*, nunca reage ao resultado |
| 21 | **Cache de embedding de query** | Reaproveitar `ResponseCache`/Redis: a mesma query é embutida repetidamente em busca, skill routing e cache semântico |
| 22 | **Concorrência no batch de embedding** | `context/indexer.py:86-99` percorre batches sequencialmente; indexar repositório grande fica limitado por RTT |
| 23 | **Classificador de complexidade orientado a dados** | `optimizer/complexity.py` é regex PT-BR sem medição. Montar dataset a partir de `request_log` e medir; heurística vira baseline, não verdade |
| 24 | **Saída estruturada + loop de reparo** | JSON schema / validação de tool-call no router, com uma retentativa de reparo antes do fallback de modelo |
| 25 | **TTFT como métrica de primeira classe** | Para `completion`/`next-edit` o que importa é o primeiro token, não a latência total que a política usa hoje |
| 26 | **Prompt cache além do Anthropic** | `_apply_prompt_cache` (`router/engine.py:264-295`) só marca `provider == "anthropic"`; Databricks/Bedrock/Gemini têm mecanismos próprios |
| 27 | **Cache semântico por fonte** | `semantic_cache_max_cosine_distance` é global; ghost text e chat toleram limiares diferentes. Ligar por padrão para `utility` |

### D — Inteligência do editor

| # | Melhoria | Por quê |
| :--- | :--- | :--- |
| 28 | **FIM nativo por modelo** | `context/completions.py` pede completion em linguagem natural; Qwen2.5-Coder tem tokens FIM (`<\|fim_prefix\|>`) que produzem resultado melhor e mais curto |
| 29 | **Vizinhança semântica na completion** | Hoje só prefixo/sufixo do arquivo; injetar top-3 chunks do RAG e as assinaturas importadas |
| 30 | **Cache e prefetch de completions** | Chave `(arquivo, hash do prefixo)`; digitação volta a posições já vistas o tempo todo |
| 31 | **Loop fechado de aceitação** | `/completions/stats` existe e não realimenta nada: usar para ajustar debounce/limiar e desligar por linguagem com aceitação baixa |
| 32 | **Next-edit com histórico de edições** | O sinal mais forte para "próximo edit" é a sequência dos últimos diffs, hoje ausente do prompt |
| 33 | **Suite offline de ghost text e next-edit** | Exact match, distância de edição e aceitação simulada sobre commits reais do repo |

### E — Agente e orquestração

| # | Melhoria | Por quê |
| :--- | :--- | :--- |
| 34 | **Compactação explícita de sessão** | `agent/graph.py:373-380` corta em `DEFAULT_MAX_ITERATIONS=25` com mensagem de desistência; falta "compactar e continuar" |
| 35 | **`max_iterations` por modo** | Constante em `graph.py:40`; um modo de revisão e um de refactor não têm o mesmo teto |
| 36 | **Nó verificador antes de `finished`** | Rodar lint/teste sobre `files_changed` e realimentar a falha, em vez de declarar sucesso |
| 37 | **Orçamento por agente filho** | `agent/coordinator.py` spawna sem partição de custo; o `BudgetGuard` é global |
| 38 | **Detecção de loop orientada a telemetria** | `_is_stuck_repeat` usa limiares fixos; os spans de ferramenta já têm os dados para calibrar |
| 39 | **Memória episódica de sessão** | `ChatTrajectory.embedding` já existe e não é usado para recuperar trajetórias parecidas no início de uma tarefa |
| 40 | **Harness de eval agêntico** | Mini-suite de tarefas do próprio repositório, com taxa de sucesso, custo e passos por tarefa |

### F — Grafo de conhecimento

| # | Melhoria | Por quê |
| :--- | :--- | :--- |
| 41 | **Camadas L2 e L3 do grafo** | `GraphEdge.layer` documenta `1=Explicit, 2=Vector, 3=LLM`, mas `graphify/pipeline/indexer.py` só grava `layer=1` |
| 42 | **Detecção de comunidade (Leiden/Louvain)** | O CLAUDE.md anuncia *community detection*; `GraphAnalytics.compute_all` só faz densidade, órfãos e PageRank |
| 43 | **PageRank incremental** | `graphify/store.py:226-264` carrega todos os nós e arestas em memória e itera em Python a cada execução |
| 44 | **Decaimento por hop no Graph RAG** | `graph_rag.py:78-91` expande com `weight >= 0.5` fixo e não pondera pela distância do hop |

### G — Avaliação e observabilidade

| # | Melhoria | Por quê |
| :--- | :--- | :--- |
| 45 | **Dataset de eval real** | `config/eval_dataset.yaml` tem 2 casos com `root` placeholder. Alvo: 80–120 casos derivados de buscas reais e de issues do repositório |
| 46 | **Gate de CI para recall@k / MRR / nDCG** | Baseline versionado; PR que degrada recuperação falha, como já falha em lint |
| 47 | **Juiz calibrado** | `evals/ragas.py` é juiz próprio sem calibração nem concordância inter-juiz — hoje um número sem intervalo de confiança |
| 48 | **A/B e experiment tracking** | Flags para prompt/rota/limiar com análise no `request_log`; hoje toda mudança de prompt é fé |
| 49 | **Spans de RAG no Langfuse** | `telemetry/langfuse_tracer.py` cobre o agente; fusão, rerank e packing precisam de span próprio para depurar recuperação ruim |
| 50 | **Loop fechado do analytics** | `CorrectionProposal` é gerado e nada o aplica; ligar a skills/prompts e medir o efeito na taxa de falha por categoria |

---

## 4. Sequenciamento

| Onda | Itens | Entrega |
| :--- | :--- | :--- |
| **0 — Base mensurável** | 1–6, 45, 46, 49 | Sem dataset e sem gate, nenhuma melhoria de recuperação é verificável. Os seis riscos da seção A entram junto porque falseiam qualquer medição |
| **1 — Recuperação** | 7–15, 47 | Camada `retrieval/`, reranker, fusão ponderada, MMR, packing. O ganho de qualidade mais visível ao usuário |
| **2 — Editor e serving** | 20–22, 25–33 | Latência e aceitação: FIM nativo, cache/prefetch, TTFT, cascata |
| **3 — Agente e grafo** | 34–44 | Compactação, verificador, camadas L2/L3, comunidades |
| **4 — Loop fechado** | 16–19, 23, 24, 48, 50 | Pool adaptativo, reindex incremental, classificador orientado a dados, A/B, analytics realimentando o produto |

### Critérios de aceite por onda

- **Onda 0:** dataset com ≥ 80 casos; `recall@8` e `MRR` publicados no CI; nenhum modelo de embedding com dimensão divergente passa no boot.
- **Onda 1:** `+15 pp` de `recall@8` sobre o baseline da Onda 0, com custo por busca dentro de 1,3× do atual.
- **Onda 2:** `TTFT p95 < 300 ms` no ghost text; aceitação medida por linguagem.
- **Onda 3:** sessões que hoje morrem no limite de 25 iterações concluem via compactação; `layer=2` e `layer=3` populados.
- **Onda 4:** proposta de correção do analytics medida em queda de falha na categoria alvo.

---

## 5. ADRs a criar ou atualizar

| ADR | Motivo |
| :--- | :--- |
| ~~**Novo — Camada de Recuperação (`retrieval/`)**~~ **Escrito**: [ADR 0019](../adr/0019-camada-de-recuperacao.md) | Diz explicitamente que a camada orquestra sem fundir os quatro stores, e fixa a direção da dependência (`retrieval/` importa dos stores, nunca o contrário) |
| ~~**Novo — Contrato do Espaço Vetorial**~~ **Escrito**: [ADR 0017](../adr/0017-contrato-do-espaco-vetorial.md) | `embedding_model`/`embedding_dim` por linha, validação no boot, política de re-embed ao trocar modelo |
| **Atualizar 0003 (Graphify)** | Camadas L2/L3 e detecção de comunidade passam de promessa a implementação |
| **Atualizar 0014 / 0015** | FIM nativo e contexto de vizinhança mudam como ghost text e next-edit montam o prompt |
| ~~**Novo — Gate de Qualidade de Recuperação no CI**~~ **Escrito**: [ADR 0018](../adr/0018-gate-de-qualidade-de-recuperacao.md) | Formaliza o baseline versionado e o critério de falha |

---

## 6. O que a Onda 0 entregou

Implementado em 2026-08-30. ADRs: [0017](../adr/0017-contrato-do-espaco-vetorial.md)
(itens 1–6) e [0018](../adr/0018-gate-de-qualidade-de-recuperacao.md) (45, 46, 49).

| Item | Entrega |
| :--- | :--- |
| 1, 2 | `ModelSpec.embedding_dim` + `router/catalog.py::validate_catalog()`. Modelo de embedding com dimensão incompatível ou capability trocada é **desabilitado na carga**, com o motivo em `unavailable_reason` e em `GET /api/health` (`catalog_issues`). `ELTANIX_CATALOG_STRICT=1` faz o boot falhar. `providers.yaml` declara `embedding_dim` nos três modelos e corrige `qwen3-embedding` de `chat` para `embedding` |
| 3 | Migração `0031`: `embedding_model` em `code_chunk`, `document_chunk`, `note_chunk`, `graph_node` e `skill`, gravada com o **modelo resolvido**. As buscas de código, documentos, notas e skills filtram o ramo vetorial por ela. Fallback de modelo no meio de um arquivo descarta os vetores e deixa o arquivo pendente |
| 4 | As três `hybrid_search` passam o `ORDER BY … LIMIT` para uma subquery e calculam `ROW_NUMBER()` por fora. **A hipótese original estava errada**: medido com `EXPLAIN ANALYZE` contra pgvector, a forma anterior já usava o índice HNSW. A mudança ficou por correção (não depender da ordem de emissão do `WindowAgg`), sem ganho de latência |
| 5 | `HNSW_EF_SEARCH` (padrão 100) aplicado por transação de busca via `set_config('hnsw.ef_search', …, true)` |
| 6 | `ContextIndexer.run_embedding_backfill_reaper` (`EMBEDDING_BACKFILL_INTERVAL_SECONDS`, padrão 1800) + `embedding_coverage`, `files_pending_embedding` e `by_embedding_model` no `index_stats` |
| 45 | `config/eval_dataset.yaml` com **96 casos** e `tags`, `defaults.root` expandindo `${ELTANIX_EVAL_ROOT}`. Teste garante ≥80 casos, ≥10 tags, nenhuma query duplicada e nenhuma query que entregue o próprio identificador esperado |
| 46 | `evals/metrics.py` (recall@k, MRR, nDCG), `eltanix-eval-gate` contra `config/eval_baseline.json`, e `.github/workflows/rag-quality.yml` (noturno + sob demanda, com pgvector e Ollama) |
| 49 | `TraceEntry.attributes`: os spans de RAG carregam `hits`, `vector_hits`, `text_hits`, `top_score`, `embedding_model` e `degraded_to_fulltext`, no log estruturado e no JSON OTLP |

### O que falta para fechar a onda

O baseline (`config/eval_baseline.json`) ainda **não existe**: gerá-lo exige uma
execução real com Postgres+pgvector e o modelo de embedding no ar — números
escritos à mão seriam uma régua inventada. Rode uma vez no ambiente de
referência e promova:

```bash
export ELTANIX_EVAL_ROOT=$(pwd)
uv run python -m eltanix.evals.index_workspace "$ELTANIX_EVAL_ROOT"
uv run eltanix-eval-rag --json /tmp/eval.json
uv run eltanix-eval-gate --report /tmp/eval.json --write
```

Até o baseline entrar em commit, o gate sai com código 2 e a mensagem de como
gerá-lo — não com falso verde.

---

## 7. O que a Onda 1 entregou

Implementado em 2026-08-31. ADR: [0019](../adr/0019-camada-de-recuperacao.md) (itens 7–15, 47).

| Item | Entrega |
| :--- | :--- |
| 7 | `retrieval/rerank.py`: duas passagens. A **léxica** é determinística e grátis — identificador citado na pergunta que aparece no trecho empurra o item, com peso maior quando aparece na assinatura (`symbol`/`path`) do que no corpo: definir vale mais que mencionar. A **listwise por LLM** compara os top-40 de uma vez no perfil `utility` e devolve uma ordem. Resposta fora do formato, índice fora da faixa ou modelo caído mantêm a ordem de entrada; `RerankOutcome.llm_error` registra qual foi o caso |
| 8 | Pesos das pernas (`RETRIEVAL_WEIGHT_VECTOR/TEXT/TRIGRAM`) e `RETRIEVAL_RRF_K` saíram de constante de módulo para configuração e chegam ao SQL das três `hybrid_search` e ao `git_aware_search`. Peso por **fonte** (`RETRIEVAL_SOURCE_WEIGHT_*`) na fusão entre fontes: código pesa 1,0 numa IDE; documento e nota, 0,7 |
| 9 | `retrieval/diversity.py`: `drop_near_duplicates` (limiar 0,92) roda **antes** do MMR, senão o MMR gasta escolhas comparando cópias. Similaridade por vetor quando as duas pontas têm, com fallback para Jaccard de identificadores — o chunk sem embedding é o caso degradado e não pode escapar da dedupe justamente por isso. `path_penalty` cobre a redundância que a similaridade de conteúdo não pega: dois trechos *diferentes* do mesmo arquivo |
| 10 | Migração `0032`: função SQL `eltanix_split_identifiers()` (IMMUTABLE) e coluna `tsv` `GENERATED ALWAYS AS STORED` que indexa o conteúdo **mais** a versão com `camelCase`/`snake_case` separados. As três buscas usam a mesma função no lado da consulta — deliberadamente a função do banco, não um helper Python que poderia divergir do que está gravado no índice |
| 11 | `pg_trgm` + índices GIN sobre `code_chunk.symbol` e `.path`. Terceira perna na fusão de código, com peso 0,5: trigrama acerta nome parcial e erro de digitação, que é sinal de apoio, não par do vetor |
| 12 | `embedding_prefixes` por modelo em `providers.yaml`, aplicados dentro de `RouterEngine.embed()` pelo argumento `purpose="query"|"document"`. `CompletionResult.provenance_tag` carrega `#prefixed`, e o filtro do ADR 0017 tira os vetores antigos do ramo vetorial sozinho. **Desligado por padrão** (`EMBEDDING_PREFIXES_ENABLED`): ligar muda o espaço vetorial, e forçar reindexação automática destruiria um índice funcionando se o modelo estivesse fora do ar |
| 13 | `retrieval/query.py`: normalização (ruído de pergunta fora, identificador citado preservado **inteiro** — quebrá-lo injetaria termos como `py`), multi-query e HyDE. A expansão só dispara em pergunta curta e **sem** identificador citado, então não cobra latência da busca típica do agente. HyDE troca só o texto embutido; a perna lexical fica com os termos reais |
| 14 | `retrieval/`: `types.py`, `fusion.py`, `rerank.py`, `diversity.py`, `pack.py`, `policy.py`, `service.py`. Ligada em `main.py::lifespan`, `ToolContext`, `agent/tools/files.py::search_code` e `POST /api/context/retrieve`. `RETRIEVAL_ENABLED=false` devolve todo mundo ao caminho antigo, que continua existindo |
| 15 | `retrieval/pack.py`: corte por `RETRIEVAL_TOKEN_BUDGET`, não por número de itens. Nada entra pela metade, e o item que não cabe é **pulado** em vez de parar a montagem — um trecho grande na terceira posição não pode barrar os três seguintes |
| 47 | `evals/judge.py` + `eltanix-eval-judge` + `config/judge_labels.yaml` (12 casos rotulados, cobrindo fiel / alucinado / fora do tópico / parcial / recusa correta). Mede MAE, Pearson e kappa de Cohen contra o rótulo humano, mais o desvio do juiz entre execuções repetidas — o **piso de ruído** da métrica. Ajusta calibração afim com intervalo de confiança por bootstrap. Calibração com menos de 8 pontos é gravada mas não corrige nada |

### Não entregue nesta onda, e por quê

- **Cross-encoder local (`bge-reranker` via ONNX)**, citado no item 7 como
  alternativa ao rerank listwise. Entra um runtime de modelo no container da API
  e um segundo caminho de versionamento de peso; a interface de
  `retrieval/rerank.py` não muda quando ele chegar, só a implementação da
  segunda passagem.
- **A fonte `graph`** existe no `Source` e no `SourceWeights` mas não é
  consultada por `RetrievalService`: o `graphify/graph_rag.py` tem forma de
  resposta própria (expansão em N-hops), e encaixá-la merece a sua própria
  passagem, não um adaptador apressado no fim de uma onda.

### O que falta para fechar a onda

O critério de aceite — `+15 pp` de `recall@8` sobre o baseline da Onda 0 — não
pode ser verificado enquanto **o baseline da Onda 0 não existir** (ver o fim da
§6). A ordem é: gerar o baseline no ambiente de referência com a camada
desligada (`RETRIEVAL_ENABLED=false`), promovê-lo, e só então medir a Onda 1
contra ele:

```bash
export ELTANIX_EVAL_ROOT=$(pwd)
uv run python -m eltanix.evals.index_workspace "$ELTANIX_EVAL_ROOT"

# baseline: caminho antigo
RETRIEVAL_ENABLED=false uv run eltanix-eval-rag --json /tmp/base.json
uv run eltanix-eval-gate --report /tmp/base.json --write

# onda 1: caminho novo, comparado contra o baseline recém-promovido
uv run eltanix-eval-rag --json /tmp/onda1.json
uv run eltanix-eval-gate --report /tmp/onda1.json
```

Os pesos padrão (`RETRIEVAL_WEIGHT_*`, `RETRIEVAL_SOURCE_WEIGHT_*`,
`RETRIEVAL_MMR_LAMBDA`) são **pontos de partida documentados, não valores
medidos**. Foram escolhidos por raciocínio sobre o que cada sinal significa; o
ajuste é justamente o que o gate do ADR 0018 existe para fazer.
