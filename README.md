# SicoobitoCode

Plataforma local-first de codificação agêntica: um IDE web completo estilo VS Code com chat e agente
autônomo sobre o repositório, integração com Git/GitHub, **Navegador Interno Híbrido com Tela Cheia**,
**RAG Multi-Formato Universal (AnyDoc + PDF Inspector)**, **Scraping e Deep Research via Firecrawl** e um
**gateway multi-modelo** que roteia entre Ollama (local), Azure AI Foundry, Databricks, Anthropic e OpenAI
com contabilidade estrita de custos e otimização de tokens.

O princípio que sustenta tudo: **nenhum módulo fala com um provedor de LLM diretamente**.
Toda chamada passa pelo router (`RouterEngine`), e cada provedor entra como adaptador plugável — trocar de
modelo ou de nuvem é mudança de configuração, não de código (ADR 0001).

---

## 🌟 Recursos & Módulos Principais

| Módulo | Escopo & Capacidades | Status |
|---|---|---|
| **Navegador Interno Completo** | Modo **Tela Cheia (`F11`)**, múltiplas abas dinâmicas, histórico completo, emuladores de dispositivos (Desktop, Tablet, Mobile SE, Mobile Max), favoritos rápidos (`:3000`, `:5173`, `:8000/docs`, `:5000`), modo híbrido **Live Iframe** + **Headless CDP** compatível com **Lightpanda** | ✅ Validado |
| **RAG Multi-Formato Universal** | Extração ultrarrápida em Rust via **AnyDoc** (com motor **Calamine**) para Word (`.docx`, `.odt`), Excel (`.xlsx`, `.xls`, `.xlsb`, `.ods`), PowerPoint (`.pptx`, `.odp`), EPUB, RTF e CSV + classificação inteligente de PDFs via **PDF Inspector** | ✅ Validado |
| **Web Scraping & Deep Research (Firecrawl)** | Web scrape limpo em Markdown, crawling recursivo de documentações, clonagem de UI React (`clone_web_ui`), pesquisa profunda com citações (`deep_research`) e **proteção anti-SSRF** | ✅ Validado |
| **Gateway Multi-Modelo** | Roteamento unificado (Ollama, Azure, Databricks, Anthropic, Groq, OpenAI), fallback automático, circuit breaker e contabilidade de tokens/custos | ✅ Validado |
| **Agente LangGraph** | Loop autônomo (*think → approve → act*), sandbox isolado de execução, ferramentas por classe de risco (`RiskClass`), modos `ask`, `edit`, `agent`, `plan`, `auto` e `orchestra` | ✅ Validado |
| **IDE Web Agêntica** | Editor Monaco (split-pane), explorador de arquivos com drag-and-drop, terminal integrado, cards de ferramentas estruturados e Agent Dock | ✅ Validado |
| **Segundo Cérebro & Obsidian** | Base de notas interligadas com `[[wikilinks]]`, busca híbrida vetorial + BM25 e Graph View 2D/3D interativo | ✅ Validado |
| **GraphRAG (Graphify)** | Base de conhecimento em grafo de código (nós/arestas L1-L3), expansão semântica CTE/GQL e visualização 360° | ✅ Validado |
| **Catálogo de Agent Skills** | Habilidades declarativas (`SKILL.md`) cobrindo WordPress moderno (Gutenberg, REST API, Performance), FastAPI, Playwright e Firecrawl com auto-aprimoramento | ✅ Validado |
| **Auditoria & Segurança** | Trilha imutável no Postgres para aprovações `WRITE`/`EXEC`, RBAC por projeto e autenticação segura com cookies httpOnly | ✅ Validado |
| **MCP (Model Context Protocol)** | Suporte completo a servidores MCP (stdio/HTTP), com scanner de segurança integrado (Cisco MCP Scanner) | ✅ Validado |

---

## 🚀 Início Rápido

Toda a stack roda em contêineres Docker isolados — basta um único comando `docker compose up`.

### 1. Configurar Variáveis de Ambiente
Copie o arquivo de exemplo e configure suas chaves de API:
```bash
cp .env.example .env
```

Gere as chaves de segurança da aplicação:
```bash
python -c "import secrets;print(secrets.token_urlsafe(32))"
```

Fixe no `.env`:
- `SICOOBITO_API_KEY`: Chave para integrações externas (Cline, Continue, Aider).
- `EXECUTOR_TOKEN`: Chave de comunicação com o sandbox do executor.
- `SICOOBITO_ADMIN_USERNAME` e `SICOOBITO_ADMIN_PASSWORD`: Credenciais para acesso à interface web.
- `FIRECRAWL_API_KEY`: (Opcional) Chave da API do Firecrawl para scraping e deep research na web pública.

### 2. Subir a Stack via Docker Compose
```bash
docker compose up -d --build
```

Execute as migrações do banco de dados:
```bash
docker compose exec api alembic upgrade head
```

### 3. Acessar os Serviços

| Serviço | Porta Local | URL de Acesso |
|---|---|---|
| **IDE & Dashboard (Next.js Web)** | `5400` | [http://localhost:5400](http://localhost:5400) |
| **Navegador Interno Dedicado** | `5400` | [http://localhost:5400/browser](http://localhost:5400/browser) |
| **API & Gateway (FastAPI)** | `5401` | [http://localhost:5401/docs](http://localhost:5401/docs) |
| **IDE Desktop Preview (Svelte 5)** | `5409` | [http://localhost:5409](http://localhost:5409) |
| **MinIO Console (Storage)** | `5408` | [http://localhost:5408](http://localhost:5408) |

---

## 🌐 Navegador Interno & Verificação Visual

O SicoobitoCode conta com um navegador de desenvolvimento integrado completo:
- **Modo Tela Cheia (`F11`)**: Expande a visualização para 100% da tela do monitor para testes visuais imersivos.
- **Múltiplas Abas**: Abra e gerencie múltiplas sessões com URLs e históricos independentes.
- **Emulador de Dispositivos**: Teste em tempo real layouts em **Desktop (1280px)**, **Tablet (768x1024)** e **Mobile (375x667 / 390x844)** com rotação e controle de zoom.
- **Modo Live (⚡ Live)**: Iframe em sandbox com Hot Module Replacement (HMR) e WebSockets em tempo real.
- **Modo Headless (🤖 Agente)**: Conexão CDP com motores headless (Playwright / Lightpanda) para screenshots, inspeção do DOM e telemetria de rede.

---

## 📚 RAG Multi-Formato & Documentos

Faça upload direto de qualquer formato corporativo no painel `/rag`:
- 📕 **PDFs**: Classificação inteligente via `pdf-inspector` (Rust) com detecção de scans sem OCR.
- 📘 **Word**: `.docx`, `.doc`, `.docm`, `.odt`.
- 📊 **Excel & Planilhas**: `.xlsx`, `.xls`, `.xlsb`, `.ods`, `.csv`, `.tsv` (processados pelo motor Rust `calamine`).
- 📙 **PowerPoint**: `.pptx`, `.ppt`, `.ppsx`, `.odp`.
- 📗 **E-books & Rich Text**: `.epub`, `.rtf`, `.md`, `.txt`.

---

## 🕷️ Scraping & Deep Research com Firecrawl

O Agente possui ferramentas especializadas para interação com a web pública:
- `web_scrape`: Extração de Markdown limpo e sem anúncios.
- `web_search`: Pesquisa rápida na web com sumarização.
- `crawl_and_index_docs`: Indexação recursiva de árvores completas de documentação técnica.
- `clone_web_ui`: Blueprint estruturado para recriação de interfaces em React.
- `deep_research`: Pesquisa autônoma multi-etapa com decomposição de consultas e relatório citado (`[[1]]`, `[[2]]`).
- **Guardião Anti-SSRF**: Validador rigoroso bloqueando loopback, redes privadas (RFC 1918), metadados de nuvem e hosts de contêineres internos.

---

## 🧪 Testes & Qualidade de Código

Executar a suíte completa de testes:
```bash
# Testes do Backend (FastAPI + RAG + Firecrawl + Tools)
docker compose exec api uv run pytest -q

# Testes de Tipos e Build do Frontend (Next.js)
cd apps/web && bun run build
```

---

## 📖 Documentação de Arquitetura

Para mais detalhes sobre as decisões de design, consulte:
- [Visão Geral de Arquitetura](file:///c:/Users/leona/Documents/Projetos/SicoobitoCode/docs/architecture.md)
- [ADR 0001: Camada Única de LLM](file:///c:/Users/leona/Documents/Projetos/SicoobitoCode/docs/adr/0001-camada-unica-de-llm.md)
- [ADR 0006: Integração Firecrawl Web & RAG](file:///c:/Users/leona/Documents/Projetos/SicoobitoCode/docs/adr/0006-integracao-firecrawl-web-rag.md)
- [ADR 0007: Navegador Interno e Emulação Visual](file:///c:/Users/leona/Documents/Projetos/SicoobitoCode/docs/adr/0007-navegador-interno-e-emulacao-visual.md)
- [ADR 0008: RAG Multi-Formato Universal com AnyDoc e PDF Inspector](file:///c:/Users/leona/Documents/Projetos/SicoobitoCode/docs/adr/0008-rag-multi-formato-anydoc-e-pdf-inspector.md)
