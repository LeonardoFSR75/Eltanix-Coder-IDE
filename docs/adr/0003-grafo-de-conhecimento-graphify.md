# ADR 0003 — Grafo de Conhecimento e Graph RAG (Graphify)

## Contexto

O SicoobitoCode gerencia quatro fontes de conhecimento de projeto: código-fonte, documentos (PDFs/MDs), notas do Segundo Cérebro e metadados de repositório.

Modelos RAG planos baseados unicamente em busca por similaridade vetorial (embeddings) ou busca por palavra-chave (full-text) ignoram as **relações estruturais e semânticas** inerentes a um repositório, como:
- Relações sintáticas diretas (Wikilinks `[[Nota]]`, `#tags`, imports AST de Python e TypeScript/JavaScript).
- Relações hierárquicas e de vizinhança entre módulos, classes, métodos e ADRs.
- Conexões conceituais identificadas por LLMs ou proximidade vetorial.

## Decisão

Adicionar um módulo dedicado de **Grafo de Conhecimento e Graph RAG (`sicoobito.graphify`)**, estruturado em 3 camadas de arestas e exposto via API (`/api/graphify/*`) e ferramenta do agente (`graph_search`).

### Camadas de Arestas:
1. **Camada 1 (Sintática - Explícita)**: Extração determinística de Wikilinks `[[Nota]]`, `#tags`, imports AST em Python e imports de módulos em TypeScript/JavaScript (`weight=1.0`).
2. **Camada 2 (Vetorial - Similaridade)**: Arestas derivadas de alta similaridade no espaço de embeddings (`weight >= 0.75`).
3. **Camada 3 (Semântica - LLM)**: Relações inferidas via análise de dependência e impacto.

### Armazenamento, Expansão e Cofre Obsidian:
- Grafo mantido em PostgreSQL (`graph_node` e `graph_edge`).
- Expansão de vizinhança $N$-hops via **queries CTE recursivas** em SQL (`store.py` e `graph_rag.py`).
- Métricas de centralidade e densidade computadas via `GraphAnalytics`.
- **Cofre Obsidian Integrado**: Exportação e estruturação do cofre em `graphify-out/obsidian/` com taxonomia por pastas, MOCs temáticos, visualizador Canvas e cores por categoria no Graph View.

### Protocolo para Agentes de IA:
- O Grafo de Conhecimento e o cofre Obsidian são de **consulta obrigatória** por qualquer agente de IA autônomo antes de propor ou executar refatorações de código e mudanças de arquitetura.

## Consequências

### Positivas
- Agente e usuários conseguem navegar e consultar dependências e impactos entre arquivos e notas em até 2 hops sem necessidade de múltiplos prompts manuais.
- Integração nativa no painel de resumo 360° do projeto (`GET /api/projects/{slug}/summary`).
- Qualidade de recuperação RAG aprimorada com a combinação de RRF e expansão de grafo.
- Navegabilidade visual rica via aplicativo Obsidian e tela `/second-brain`.

### Negativas / Mitigações
- Custo computacional adicional no momento de indexação L1. Mitigado com expressões regulares eficientes e parsers AST leves.
