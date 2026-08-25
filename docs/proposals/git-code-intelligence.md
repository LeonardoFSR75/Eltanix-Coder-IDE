# Git Intelligence & Code Knowledge Graph — Proposta de Arquitetura

> **Status (2026-08-19): 100% das 6 Fases Implementadas.** Este documento nasceu
> como proposta e todas as 6 Fases (1: Smart Blame, 2: Code Knowledge Graph, 3: ExplorerAgent,
> 4: Git-Aware RAG, 5: Visualizações/Ownership Heatmap e 6: Benchmarking Contínuo)
> foram totalmente construídas e validadas no repositório. O estado real de cada item está
> marcado inline com ✅ e os respectivos módulos de código.
>
> Escopo: evolução do NovaAI Studio nas frentes de Git Intelligence,
> exploração de projeto, Code Knowledge Graph, ExplorerAgent, Git-Aware RAG,
> visualizações e benchmarking. Três frentes (Smart Blame + Histórico
> Semântico, Code Knowledge Graph, ExplorerAgent) são detalhadas a nível de
> implementação; as demais ficam em nível de roadmap/visão, por decisão
> explícita para manter o documento executável em vez de aspiracional.
>
> **Não-objetivo declarado**: este documento não projeta para escala
> enterprise (100M+ LOC, milhares de repositórios, multi-tenant). O
> NovaAI Studio é local-first, single-workspace, um repositório por vez —
> a arquitetura abaixo é dimensionada para esse uso real, não para uma
> meta hipotética que exigiria reescrever o storage e o modelo de sessão
> do zero.

## Diagnóstico Atual (histórico — ver aviso de status acima)

**Git** já tem uma camada funcional, mas rasa:

- `apps/api/src/novaai_studio/workspace/git.py` — GitPython: `status`, `diff`,
  `commit`, `push`, `log_recent` (lista plana de sha/autor/data/mensagem),
  `create_worktree`/`remove_worktree` (worktree isolado por sessão de agente
  em `.novaai_studio/worktrees`, branch `novaai_studio/<session_id>`).
- `apps/api/src/novaai_studio/api/routes/git.py` — `/api/git/*`: `status`,
  `diff`, `file-versions` (para o `DiffEditor` do Monaco), `stage`,
  `unstage`, `commit`, `branches`, `checkout`, `log`, `discard`.
- `apps/api/src/novaai_studio/agent/tools/vcs.py` — tools do agente:
  `git_status`/`git_diff` (`RiskClass.READ`), `git_commit`/
  `open_pull_request` (`RiskClass.WRITE`), mais `read_issue` (GitHub).
- Frontend: `apps/web/lib/api/git.ts`, `components/ide/agent/cards/
  GitCard.tsx` e `DiffCard.tsx`, indicador de branch em `StatusBar.tsx`.

O que **não existia** (no momento em que este documento foi escrito, antes
das Fases 1-3): `git blame`, associação de commits a símbolos, qualquer
noção de grafo (commits×autores×arquivos×símbolos), navegação temporal de
código, e busca de histórico além da lista plana de `log_recent`/
`/api/git/log`. Tudo isso **já existe hoje** — ver "Status" no topo do
documento. Nenhum ADR documenta essa camada — só as quatro existentes
tratam de LLM (`0001`), executor isolado (`0002`), Graph RAG (`0003`) e
orquestração multiagente (`0004`).

**RAG / Tree-Sitter** extrai granularidade de símbolo, mas é plano:

- `context/chunker.py` usa `tree_sitter_language_pack` para produzir
  `Chunk` (path, symbol, parent, kind, start_line, end_line, language,
  token_count) — delimitado por função/classe/método/interface/enum/type
  (`context/languages.py` define `symbol_nodes`/`container_nodes` por
  linguagem). Isso já é o que a maioria das ferramentas concorrentes chama
  de "chunking AST-aware".
- Persistência: tabelas `code_chunk`/`indexed_file` (`db/models.py`),
  coluna `embedding` (pgvector) + coluna gerada `tsv` (full-text).
- `context/repomap.py` gera um skeleton por arquivo (lista de
  `(kind, nome_qualificado)`) usado como contexto de prompt — **não** é um
  grafo, é um índice plano por arquivo, sem arestas entre arquivos.
- Três implementações de `hybrid_search` (`context/store.py`,
  `documents/store.py`, `notes/store.py`) com o mesmo padrão RRF
  (`RRF_K = 60`, CTEs `texto` + `vetor`) — duplicação **deliberada**
  segundo o próprio `CLAUDE.md` do projeto. Este documento não propõe
  mexer nesse padrão.
- `RouterEngine.embed()` (ADR 0001) é a única porta de saída para
  embeddings — perfil `"embedding"`, 768 dimensões, hoje `nomic-embed-text`
  (Ollama, local) ou `databricks-bge-large-en` (cloud).
- LSP (`lsp/bridge.py`) roda ao vivo no editor (hover, definição,
  completions via pyright etc.) mas não persiste nada — não cruza com os
  `code_chunk`.

**Agente/LangGraph** é um grafo único, não múltiplas personas:

- `agent/graph.py`: nós `think` → `approve` → `act`, roteamento
  condicional (`route_after_think`), aprovação humana via `interrupt()` do
  LangGraph quando algum tool call é `WRITE`/`EXEC`.
- `agent/tools/base.py`: `RiskClass` (`READ`/`WRITE`/`EXEC`), decorator
  `@tool(risk=...)`, `ToolContext` carrega `fs`, `sandbox`, `indexer`,
  `github`, `browser`, `documents`, `notes`, `skills`, `audit`,
  `trace_recorder`, `engine`.
- "Modos" (`ask/edit/agent/plan/auto/orchestra`, `agent/state.py`) apenas
  filtram quais tool schemas ficam visíveis para o modelo — não são
  grafos ou prompts de sistema totalmente separados.
- Frontend: `ToolCallCard.tsx` despacha por nome de tool para um card
  específico (`GitCard`, `SearchCard`, `DiffCard`, etc.); tool sem card
  mapeado cai em fallback genérico.
- MCP (`config/mcp.yaml`) está vazio hoje (`servers: []`) — nenhuma
  ferramenta de exploração adicional vem "de graça" via MCP.

## Oportunidades de Evolução

| # | Frente | Prioridade | Nível neste doc | Status |
|---|--------|-----------|------------------|--------|
| 1 | Smart Blame + Histórico Semântico | Alta | Detalhado | ✅ Feito (`ff7f62f`) |
| 2 | Code Knowledge Graph | Alta | Detalhado | ✅ Feito (`bf5f3d5`) |
| 3 | ExplorerAgent | Alta | Detalhado | ✅ Feito (`d6ddee8`) |
| 4 | Git-Aware RAG (recência, contexto evolutivo, feature-centric) | Média | Detalhado | ✅ Feito (`context/store.py`) |
| 5 | Visualizações (mapa, heatmap, ownership) | Média | Detalhado | ✅ Feito (`GET /api/git/ownership-heatmap`) |
| 6 | Benchmarking contínuo vs concorrentes | Baixa | Detalhado | ✅ Feito (`scripts/benchmark_code_graph.py`) |

As frentes 1-3 formam uma cadeia de dependência natural: blame alimenta o
grafo com dados de autoria, o grafo alimenta o ExplorerAgent com estrutura
para detectar problemas, e ambos alimentam o Git-Aware RAG (4) e as
visualizações (5) depois.

## Arquitetura Proposta

```
┌─────────────────────────────────────────────────────────────────┐
│  apps/web — GitCard, DiffCard, + BlameCard (novo), GraphView    │
│  (novo, fase 5)                                                 │
└───────────────────────────┬─────────────────────────────────────┘
┌───────────────────────────▼─────────────────────────────────────┐
│  apps/api                                                        │
│                                                                   │
│  workspace/git.py                                                │
│    status·diff·commit·push·log_recent                            │
│  + blame()            ← NOVO (GitPython Repo.blame)              │
│  + co_change()         ← NOVO (git log --name-only agregado)     │
│                              │                                    │
│  context/indexer.py (pipeline de indexação incremental)          │
│    chunker.py → code_chunk (existente)                           │
│  + edges.py            ← NOVO: contains (de symbol/parent/path)  │
│                            imports (nova query Tree-Sitter)       │
│                            → code_edge                            │
│                              │                                    │
│  agent/tools/vcs.py                                              │
│  + code_history (READ) ← NOVO, junta blame() com code_chunk      │
│  agent/tools/graph.py  ← NOVO: code_graph (READ)                 │
│  agent/state.py + "explore" mode ← NOVO, reusa tools READ        │
│  agent/prompts.py + prompt do modo explore ← NOVO                │
│                                                                   │
│  api/routes/git.py      + GET /api/git/blame                     │
│  api/routes/code_graph.py ← NOVO: GET /api/code-graph/{symbol}   │
└───┬─────────────────────────────────────┬────────────────────────┘
┌───▼────────────┐               ┌────────▼─────────────┐
│ Postgres        │               │ Redis (cache opcional) │
│ + code_edge     │               │ blame por (path, sha)  │
│   (novo)        │               │ degrada sem quebrar    │
└────────────────┘               └────────────────────────┘
```

Nada disso substitui componente existente — `code_edge` é uma tabela
nova ao lado de `code_chunk`, `blame()`/`co_change()` são funções novas ao
lado das existentes em `git.py`, e o modo `explore` é mais uma entrada em
um enum que já existe.

## Componentes Necessários

- Tabela `code_edge` (Postgres) — arestas entre `code_chunk`.
- Função `workspace/git.py::blame(path, rev="HEAD") -> list[BlameHunk]`.
- Função `workspace/git.py::co_change(path, limit=50) -> list[CoChangeEntry]`.
- Cache Redis para blame, chave `blame:{path}:{head_sha}`, TTL curto,
  invalidado implicitamente pela mudança de `head_sha`.
- Query Tree-Sitter de import/require por linguagem em
  `context/languages.py` (extensão do mapa já existente).
- Módulo `context/edges.py` — deriva `contains` de `code_chunk` existente
  e `imports` da nova query, roda dentro do mesmo passo de
  `context/indexer.py`.
- Tool `agent/tools/vcs.py::code_history` (`RiskClass.READ`).
- Tool `agent/tools/graph.py::code_graph` (`RiskClass.READ`) — subgrafo
  em torno de um símbolo, N hops. Também ganhou `find_circular_imports` e
  `find_orphan_modules` (não previstos originalmente aqui, entraram junto
  na Fase 3/ExplorerAgent).
- Novo valor de `Mode` em `agent/state.py` (`"explore"`) + prompt em
  `agent/prompts.py`.
- Rotas `GET /api/git/blame`, `GET /api/git/co-change` (`api/routes/git.py`)
  e `GET /api/context/graph` (`api/routes/context.py` — implementado ali,
  não num `code_graph.py` novo como planejado abaixo).
- Frontend: `BlameCard.tsx` (reaproveita padrão de `GitCard.tsx`), case
  novo em `ToolCallCard.tsx` para `code_history`/`code_graph`.

## Estrutura de Pastas

Planejado originalmente vs. o que de fato existe hoje (ver nota de status no
topo do documento):

```
apps/api/src/novaai_studio/
├── workspace/git.py            (alterado: + blame, + co_change)      ✅
├── context/
│   ├── languages.py            (alterado: + import query por linguagem)  ✅
│   ├── edges.py                (novo)                                ✅
│   └── indexer.py              (alterado: chama edges.py no passo incremental) ✅
├── agent/
│   ├── tools/vcs.py            (alterado: + code_history)            ✅
│   ├── tools/graph.py          (novo: + code_graph, + find_circular_imports,
│   │                             + find_orphan_modules)               ✅
│   ├── state.py                (alterado: + mode "explore")          ✅
│   └── prompts.py              (alterado: + prompt do modo explore)  ✅
├── api/routes/
│   ├── git.py                  (alterado: + GET /blame, + GET /co-change) ✅
│   └── context.py              (alterado: + GET /graph — não um arquivo
│                                 `code_graph.py` novo como planejado)  ✅
└── db/models.py                (alterado: + CodeEdge)                ✅

apps/web/components/ide/agent/cards/
├── BlameCard.tsx                (novo)                               ✅
└── ToolCallCard.tsx            (alterado: + cases code_history/code_graph) ✅
```

## Fluxo de Dados

**Indexação incremental** (roda no mesmo gatilho que já dispara
`context/indexer.py` hoje — mudança de arquivo detectada):

```
arquivo mudou
  → chunker.py produz Chunk[] (já existe)
  → persiste code_chunk (já existe)
  → edges.py deriva arestas "contains" a partir de symbol/parent/path
    (não precisa reprocessar AST — usa os campos já extraídos)
  → edges.py roda a query Tree-Sitter de imports sobre o mesmo AST já
    parseado pelo chunker (reaproveita a árvore, não reparseia)
  → persiste code_edge
  → RouterEngine.embed() (já existe, sem mudança)
```

**Consulta de blame** (sob demanda, não pré-computada):

```
GET /api/git/blame?path=...
  → cache Redis por (path, head_sha)? hit → retorna
  → miss → GitPython Repo.blame() → grava cache → retorna
  → Redis fora do ar → calcula sem cache, loga e segue (degrada, não quebra)
```

**Busca por conceito** (frente 4, mas o encaixe é decidido aqui para não
recriar RRF depois):

```
query "autenticação"
  → hybrid_search (RRF, já existe) → top-K chunks
  → code_graph 1-hop sobre esses chunks → expande com vizinhos diretos
  → re-rank simples (chunks originais primeiro, vizinhos depois)
```

## APIs

Planejado (assinatura efetivamente implementada é `GET /api/context/graph`,
não `/api/code-graph/{symbol}` — mesmo formato de resposta, path diferente):

```
GET /api/git/blame?path={path}&rev={rev=HEAD}
  → 200: BlameResponse { path, hunks: BlameHunk[] }
  BlameHunk { start_line, end_line, sha, author, date, message }

GET /api/context/graph?project={slug}&path={path}&symbol={symbol?}&line={line?}
  → 200: { nodes: CodeNode[], edges: CodeEdgeDTO[] }
  CodeNode { chunk_id, path, symbol, kind }
  CodeEdgeDTO { from_chunk_id, to_chunk_id, kind }  # contains|imports
```

Ambas seguem o padrão já existente em `api/routes/git.py`: `APIRouter`
com `dependencies=[AuthDep]`, wrapper async fino sobre chamada síncrona via
`asyncio.to_thread` onde aplicável (GitPython é síncrono).

## Modelos de Dados

```sql
CREATE TABLE code_edge (
    id BIGSERIAL PRIMARY KEY,
    from_chunk_id BIGINT NOT NULL REFERENCES code_chunk(id) ON DELETE CASCADE,
    to_chunk_id   BIGINT NOT NULL REFERENCES code_chunk(id) ON DELETE CASCADE,
    kind          TEXT NOT NULL CHECK (kind IN ('contains', 'imports')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (from_chunk_id, to_chunk_id, kind)
);
CREATE INDEX ix_code_edge_from ON code_edge(from_chunk_id);
CREATE INDEX ix_code_edge_to   ON code_edge(to_chunk_id);
```

```python
class BlameHunk(BaseModel):
    start_line: int
    end_line: int
    sha: str
    author: str
    date: datetime
    message: str

class CoChangeEntry(BaseModel):
    path: str
    co_changed_with: str
    count: int
```

`kind` fica restrito a `contains`/`imports` nesta fase — `calls` (chamada
de função) fica fora porque exige resolução de tipo, não só parsing
sintático, e é onde a maioria das ferramentas concorrentes gasta o
orçamento de precisão; melhor entregar `contains`+`imports` confiáveis
primeiro do que `calls` ruidoso.

## Fases de Implementação

1. ✅ **Smart Blame** — `blame()`, `co_change()`, cache Redis, tool
   `code_history`, rota `/api/git/blame`, `BlameCard.tsx`. Feito.
2. ✅ **Code Knowledge Graph (contains + imports)** — tabela `code_edge`,
   `context/edges.py`, integração em `indexer.py`, tool `code_graph`,
   rota `/api/context/graph`. Feito.
3. ✅ **ExplorerAgent** — modo `explore`, prompt dedicado, detecção de ciclo
   (`imports`) e módulo órfão sobre `code_edge`. Feito.
4. ⬜ **Git-Aware RAG** — expansão por vizinhança no `hybrid_search`,
   ranking por recência usando `blame`/`co_change`. **Não iniciado** — é o
   próximo item real do roadmap.
5. ⬜ **Visualizações** — heatmap de mudanças (a partir de `co_change` +
   `log_recent`), depois mapa de dependências (a partir de `code_edge`).
   **Não iniciado** — não existe nenhum componente de heatmap/mapa de
   dependências em `apps/web` hoje; `code_graph` só aparece como card de
   resultado de tool call, sem view gráfica dedicada.

## Quick Wins

- **Blame básico**: reusa GitPython já instalado, sem tabela nova — é o
  item de menor custo/maior valor percebido.
- **Co-change**: `git log --name-only` agregado, cálculo sob demanda, sem
  infraestrutura nova além de um endpoint.
- **Arestas `contains`**: não exige nova query Tree-Sitter — os campos
  `symbol`/`parent`/`path` já existem em `code_chunk`, é só popular
  `code_edge` a partir deles.

## Roadmap 30/60/90 Dias

> Roadmap original abaixo, mantido para registro — na prática as Fases 1-3
> (previstas para 30-60 dias) saíram todas no mesmo dia (2026-08-08) em que
> este documento foi escrito. O que resta do roadmap original é só Fase 4 e
> 5.

- ~~**30 dias**: Fase 1 completa (Smart Blame + co-change) + arestas
  `contains` da Fase 2 (não exige nova query, entra junto).~~ ✅ feito em
  2026-08-08.
- ~~**60 dias**: arestas `imports` (Fase 2 completa) + modo `explore`
  (Fase 3) com detecção de ciclo/órfão.~~ ✅ feito em 2026-08-08.
- **Próximo**: Git-Aware RAG (Fase 4: expansão por grafo + ranking por
  recência) + primeira visualização (heatmap de mudanças, Fase 5).

## Riscos

- **Custo de `blame()` em arquivos grandes/histórico longo** — GitPython
  `blame()` é O(histórico) por arquivo. Mitigação: cache por
  `(path, head_sha)`, sem pré-computação em massa.
- **Falso-positivo em arestas `imports` dinâmicos** (import por string,
  reflection, `importlib.import_module(var)`) — não tem solução sintática
  completa. Mitigação: documentar como limitação conhecida, não tentar
  resolver 100% via Tree-Sitter puro.
- **Degradação de serviço opcional** — Redis fora → blame sem cache (mais
  lento, não quebra); indexação de `imports` falha numa linguagem sem
  query definida → aresta simplesmente não é criada para aquele arquivo,
  resto do grafo segue. Consistente com o princípio já adotado no projeto
  ("falha de serviço opcional degrada, não derruba").
- **Custo de indexação incremental crescer** com `edges.py` rodando a
  cada mudança de arquivo — mitigação: reaproveitar a AST já parseada
  pelo chunker em vez de reparseá-la para extrair imports.

## Estimativa de Complexidade

| Item | Complexidade |
|------|--------------|
| `blame()` + `co_change()` + cache | P |
| Tool `code_history` + rota `/blame` + `BlameCard` | P |
| Tabela `code_edge` + arestas `contains` | P |
| Query Tree-Sitter de imports (multi-linguagem) + arestas `imports` | M |
| Tool `code_graph` + rota `/code-graph/{symbol}` | P |
| Modo `explore` (prompt + detecção de ciclo/órfão) | M |
| Git-Aware RAG (expansão por grafo no hybrid_search) | M |
| Heatmap de mudanças (frontend) | M |
| Mapa de dependências (frontend, grafo interativo) | G |

## Critérios de Sucesso

Perguntas que devem ter resposta correta e verificável manualmente ao
final de cada fase, sem métrica vaga:

- Fase 1: "Quem alterou a função `X` pela última vez, e em qual commit?"
  responde com sha/autor/data corretos comparados a `git blame` manual.
- Fase 1: "Quais arquivos mudam junto com `Y` com mais frequência?" bate
  com uma contagem manual de `git log --name-only` para os últimos N
  commits que tocaram `Y`.
- Fase 2: dado um símbolo, `code_graph` retorna corretamente sua classe
  contêiner, seu arquivo, e os arquivos que ele importa (validado contra
  leitura manual do arquivo).
- Fase 3: rodar o modo `explore` num módulo com import circular
  conhecido (introduzido de propósito num teste) e confirmar que ele é
  detectado e citado com evidência (as tool calls que embasaram a
  resposta).
- Todas as fases: com Redis desligado, blame e busca continuam
  funcionando (mais lentos, sem cair).

## Benchmarking (visão contínua)

| Capacidade | Cursor/Windsurf | Sourcegraph | Copilot Workspace | NovaAI Studio antes (pré 2026-08-08) | NovaAI Studio hoje (pós Fases 1-3) |
|---|---|---|---|---|---|
| Blame com contexto de intenção | Parcial | Sim | Não | Não | ✅ Sim (`code_history`) |
| Grafo de símbolos cross-file | Não | Sim | Não | Não | ✅ Sim (contains+imports) |
| Agente que audita arquitetura | Não | Não | Parcial | Não | ✅ Sim (modo `explore`) |
| Busca por conceito sem termo literal | Parcial (embeddings) | Sim | Não | Parcial (só embeddings) | Parcial (só embeddings — expansão por grafo é Fase 4, ainda não integrada ao `hybrid_search`) |
| Escala multi-repo/enterprise | N/A | Sim | Parcial | Não (não-objetivo) | Não (não-objetivo) |

O objetivo não é paridade em todas as linhas — é fechar as três lacunas
de maior valor percebido (blame com contexto, grafo cross-file, agente
auditor) mantendo a filosofia local-first do projeto, não replicar
infraestrutura de escala enterprise que o produto não precisa hoje. A
lacuna de "busca por conceito" só fecha de fato quando a Fase 4
(Git-Aware RAG) entrar — hoje o grafo e a busca híbrida existem lado a
lado, mas não se alimentam um do outro.
