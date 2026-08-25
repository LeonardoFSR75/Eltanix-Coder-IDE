# ADR 0006 — Integração do Firecrawl para Web Scraping, Search e Ingestão de Documentação no RAG

**Status:** aceito · **Data:** 2026-08-17

## Contexto

Até esta etapa, o NovaAI Studio contava exclusivamente com o `browser_action` para interação com navegador web. No entanto, por projeto e segurança (ADR 0002), o `browser_action` opera em um Chromium headless confinado à rede interna isolada (`browser_net`), com a finalidade exclusiva de testar visualmente e inspecionar a aplicação web local rodando no sandbox (`localhost`).

Com isso, o agente e os desenvolvedores não possuíam um canal seguro, estruturado e otimizado para:
1. Consultar referências e documentações técnicas externas (ex.: Next.js, FastAPI, LangGraph, documentação de SDKs e bibliotecas no npm/PyPI);
2. Realizar pesquisas técnicas na web para resolver bugs com soluções recentes;
3. Importar árvores inteiras de documentação online diretamente para o RAG do projeto (pgvector + busca híbrida RRF).

Tentar usar web scrapers rudimentares traria HTML bruto, propagandas, menus de navegação ruidosos e desperdício massivo de tokens de contexto do modelo.

## Decisão

**Adotar o [Firecrawl](https://github.com/firecrawl) como motor oficial de web scraping, busca, rastreamento (crawling) e ingestão de páginas para o Agente e o RAG.**

### 1. Separação de Responsabilidades e Camada de LLM
- **Camada Única de LLM (ADR 0001) preservada**: Qualquer geração de embeddings para chunks extraídos de páginas da web passa obrigatoriamente por `RouterEngine.embed()`, mantendo contabilidade de custos, telemetria e troca plugável de modelos.
- **Suporte Híbrido**: Compatibilidade transparente com **Firecrawl Cloud** (`FIRECRAWL_API_KEY` em `https://api.firecrawl.dev`) e instâncias **self-hosted** (`FIRECRAWL_API_URL`).

### 2. Ferramentas do Agente e Classificação de Risco
Três novas ferramentas são disponibilizadas no catálogo do agente:
- `web_scrape`: `RiskClass.READ` — extrai Markdown limpo e metadados de uma URL pública;
- `web_search`: `RiskClass.READ` — executa buscas na web e extrai o conteúdo dos principais resultados em Markdown;
- `crawl_and_index_docs`: `RiskClass.WRITE` — rastreia recursivamente uma documentação online e grava os documentos/chunks no Postgres do projeto, exigindo aprovação humana prévia no grafo (`interrupt()`).

### 3. Ingestão Web no RAG (Segundo Cérebro & Documentos)
- A ingestão via Firecrawl grava registros na tabela `document` (com `content_type="text/markdown"` e prefixo `[Web]`) e quebra o conteúdo em parágrafos semânticos através de `chunk_text()`.
- Os vetores gerados são indexados no pgvector e combinados com tsvector em busca híbrida (RRF, `k=60`).
- Usuários podem importar páginas individuais ou rastrear sites inteiros através do painel de RAG (`/rag`).

### 4. Proteções de Segurança contra SSRF
- Todas as URLs fornecidas passam por validação estrita em `validate_target_url()`.
- São bloqueados:
  - Endereços de loopback (`localhost`, `127.0.0.1`, `0.0.0.0`);
  - Faixas de IP privado e reservado (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`);
  - Endpoints de metadados de cloud (`169.254.169.254`, `metadata.google.internal`);
  - Hostnames internos dos serviços do docker-compose (`postgres`, `redis`, `executor`, `minio`, `browser`, `api`, `web`).

### 5. Degradação Graciosa
- Caso o Firecrawl não esteja configurado ou fique inacessível, a API e as demais ferramentas do agente não quebram; as ferramentas respondem com avisos informativos orientando a configuração de `FIRECRAWL_API_KEY` na tela de Provedores.

## Consequências

- **Positivas**: O agente adquire inteligência web real para consultar documentações de terceiros; a base de RAG do projeto pode ser enriquecida com sites de documentação oficiais; economia de tokens através do Markdown limpo gerado pelo Firecrawl.
- **Segurança**: Risco de SSRF mitigado por validação estrita no backend antes de qualquer chamada HTTP externa.
