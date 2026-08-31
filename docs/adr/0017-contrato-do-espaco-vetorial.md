# ADR 0017 — Contrato do Espaço Vetorial

- **Status**: Aceito
- **Data**: 2026-08-30
- **Contexto**: Onda 0 da [revisão de ML](../proposals/revisao-estrutura-ml-50-melhorias.md) (itens 1–6)
- **Relacionado**: [ADR 0001](0001-camada-unica-de-llm.md), [ADR 0003](0003-grafo-de-conhecimento-graphify.md), [ADR 0008](0008-rag-multi-formato-anydoc-e-pdf-inspector.md)

## Contexto

O RAG guarda vetores em cinco tabelas (`code_chunk`, `document_chunk`,
`note_chunk`, `graph_node`, `skill`), todas com coluna `Vector(EMBEDDING_DIM)`
e índice HNSW de cosseno. Duas propriedades disso nunca estiveram escritas em
lugar nenhum, e as duas foram violadas na prática:

1. **A dimensão da coluna é fixa.** `EMBEDDING_DIM` valia 768 (nomic) enquanto
   o perfil `embedding` do `routes.yaml` listava `databricks/bge-large-en`
   (1024 dimensões) como **primeiro** candidato. Com credencial Databricks
   presente, a indexação começava a falhar arquivo por arquivo, no INSERT do
   vetor — longe da causa, que estava em dois arquivos de configuração que
   ninguém compara entre si.

2. **Distância de cosseno só significa algo dentro do mesmo modelo.** Nenhuma
   linha registrava qual modelo gerou seu vetor. Trocar `EMBEDDING_PROFILE`,
   ou simplesmente o fallback do perfil entrar em ação, misturava espaços
   vetoriais na mesma tabela. A busca continuava respondendo — pior, sem
   nenhum sinal de que estava comparando coisas incomparáveis.

Havia ainda um sintoma menor da mesma ausência de contrato:
`databricks/databricks-qwen3-embedding-0-6b` estava cadastrado com
`capabilities: [chat]`, ou seja, um modelo de embedding dentro do pool de chat.

## Decisão

### 1. Todo modelo de embedding declara `embedding_dim`

`ModelSpec.embedding_dim` passa a existir e é **obrigatório** para quem tem a
capability `embedding`. `router/catalog.py::validate_catalog()` roda na carga
do catálogo e classifica cada problema como fatal ou não:

| Situação | Fatal? | Efeito |
| :--- | :--- | :--- |
| `embedding_dim` ≠ `EMBEDDING_DIM` | sim | modelo desabilitado, com o motivo em `unavailable_reason` |
| capability `embedding` sem `embedding_dim` | sim | modelo desabilitado |
| id parece de embedding mas declara `chat` | sim | modelo desabilitado |
| `embedding` + `chat` no mesmo modelo | não | log de aviso |
| modelo de embedding num perfil de chat (ou o contrário) | não | log de aviso |

Fatal **desabilita**, não derruba a aplicação: o perfil `embedding` degrada
para o próximo candidato compatível (na prática, o Ollama local) e a IDE
continua indexando. `ELTANIX_CATALOG_STRICT=1` torna o boot fatal — é o modo
esperado em produção, onde subir sem embedding é subir sem RAG.

A ordem no `routes.yaml` continua declarando **preferência**, não
compatibilidade: `databricks/bge-large-en` segue listado primeiro, e volta a
ser usado no dia em que `EMBEDDING_DIM=1024` + migração das colunas
acontecerem.

### 2. Todo vetor gravado carrega a proveniência

Coluna `embedding_model` (migração `0031`) nas cinco tabelas. Ela é preenchida
com o **modelo resolvido** que atendeu — nunca com o nome do perfil, porque o
perfil tem fallback e é justamente o fallback que troca o espaço vetorial.

Regras que caem disso:

- Vetor nulo ⇒ `embedding_model` nulo. Etiquetar um chunk que ficou fora do
  ramo vetorial seria mentira sobre ele.
- Se o modelo mudar **no meio** de um arquivo ou documento (fallback entre
  lotes), os vetores daquele arquivo são descartados e ele fica pendente para
  a próxima passagem. Meio arquivo num espaço e meio em outro é exatamente o
  que esta ADR existe para impedir.
- A busca filtra o ramo vetorial por `embedding_model = <modelo da query>`.
  Chunk de outro modelo, ou anterior a esta migração (`NULL`), continua
  encontrável por full-text e volta ao ramo vetorial na próxima reindexação.

### 3. O top-k vetorial é declarado, não inferido

As três `hybrid_search` passaram a calcular o `ORDER BY … LIMIT` numa subquery,
com o `ROW_NUMBER()` por fora.

**Registro de uma hipótese que a medição derrubou:** a revisão supôs que a
forma anterior (função de janela na mesma consulta do `LIMIT`) impedia o uso do
índice HNSW. `EXPLAIN ANALYZE` contra pgvector, nas duas formas de consulta
(com e sem JOIN), mostra o contrário — o planner empurra o `LIMIT` através do
`WindowAgg`, usa `Index Scan using ix_*_embedding` e para cedo. Os dois planos
custam praticamente o mesmo.

A mudança fica, por um motivo menor e verdadeiro: `LIMIT` depois de uma função
de janela, sem `ORDER BY` externo, devolve as linhas na ordem em que o
`WindowAgg` as emitiu — comportamento real, não garantia da linguagem. A forma
nova declara o top-k. Quem for otimizar recuperação daqui para frente deve
procurar em outro lugar; este caminho já está no plano certo.

### 4. `hnsw.ef_search` é ajustável por busca

`HNSW_EF_SEARCH` (padrão 100) é aplicado com
`SELECT set_config('hnsw.ef_search', :ef, true)` na transação da busca —
`set_config` porque `SET LOCAL` não aceita parâmetro ligado. O default do
pgvector (40) devolve menos vizinhos do que o `candidate_pool` de 50 pede, o
que trunca a metade vetorial da fusão antes de ela chegar ao RRF.

### 5. Vetor pendente tem quem o recupere

Um arquivo cujo embedding falhou já era gravado com `content_hash` prefixado
por `pendente:` — o que garante que a próxima indexação o reprocesse. O que
faltava era alguém **disparar** essa indexação: na prática ninguém pedia, e o
sintoma (busca pior) não aponta para a causa.

`ContextIndexer.run_embedding_backfill_reaper` roda a cada
`EMBEDDING_BACKFILL_INTERVAL_SECONDS` (padrão 1800; `0` desliga) e reindexa só
os workspaces que têm arquivo pendente. `index_stats` passa a expor
`embedding_coverage`, `files_pending_embedding` e `by_embedding_model`.

## Consequências

**Ganhos**

- O erro de dimensão vira erro de configuração no boot, com o nome do modelo e
  os dois números, em vez de falha de INSERT no meio de uma indexação.
- Trocar de modelo de embedding deixa de degradar a busca em silêncio: os
  vetores antigos saem do ramo vetorial até serem regerados.
- Cobertura vetorial vira número observável, e há um processo que a persegue.

**Custos aceitos**

- Uma coluna a mais em cinco tabelas e três índices parciais.
- Trocar de modelo passa a exigir reindexação consciente — antes "funcionava"
  na hora, com resultado ruim que ninguém atribuía à troca.
- O filtro por `embedding_model` é pós-filtro sobre o resultado do HNSW: com
  índice muito misturado o recall cai até a reindexação terminar. O
  `ef_search` maior compensa parcialmente; o backfill resolve de vez.

## Alternativas descartadas

- **Uma tabela de vetores por modelo.** Resolveria o pós-filtro, mas
  multiplicaria o schema e as migrações por modelo, para um produto que roda
  com um modelo de cada vez.
- **Derivar a dimensão perguntando ao provedor no boot.** Transformaria a
  subida da API em dependência de rede, contra o princípio local-first.
- **Recusar subir com qualquer inconsistência.** É o comportamento com
  `ELTANIX_CATALOG_STRICT=1`; como padrão, deixaria a IDE local inutilizável
  por um modelo mal cadastrado que ela nem usa.
