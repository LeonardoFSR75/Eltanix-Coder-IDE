# Arquitetura — Eltanix Coder IDE

## Visão Geral

```
┌─────────────────────────────────────────────────────────────────┐
│  apps/web — Next.js 15                                          │
│  IDE Monaco · Dashboard · Agent Dock · Second Brain · MCP UI   │
│  Navegador Interno (Live Iframe + Headless + Fullscreen)        │
│  RAG Multi-Formato (PDF, Word, Excel, PPT, OpenDoc, EPUB, CSV)  │
│  Login obrigatório (cookie httpOnly) · Central de Projetos      │
└───────────────────────────┬─────────────────────────────────────┘
                            │ HTTP/WS/SSE (cookie de sessão do usuário;
                            │ API key só para ferramenta externa — ADR 0005)
┌───────────────────────────▼─────────────────────────────────────┐
│  apps/api — FastAPI (Python 3.12)                               │
│                                                                 │
│  /v1/*        ← fachada OpenAI-compatible (Cline, Continue)     │
│  /api/*       ← gestão, métricas, auditoria, IDE, agente        │
│  /api/firecrawl/* ← scraping, crawling, search & deep research  │
│  toda rota: AuthDep = require_session (ADR 0005)                │
│                                                                 │
│  ┌──── router (ADR 0001: ÚNICA porta de saída para LLM) ──────┐ │
│  │ catalog → policy → engine → adapters                       │ │
│  │              ↑        ↓                                     │ │
│  │           health   pricing → telemetry → request_log        │ │
│  │           (Redis)                                           │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                 │
│  auth:       AppUser/AuthSession, scrypt, rate limit (ADR 0005)│
│  optimizer:  cache exato + semântico (Redis) · compressor      │
│  context:    chunker (tree-sitter) · indexer · store (pgvector)│
│  firecrawl:  FirecrawlService · anti-SSRF guard · RAG ingest   │
│  documents:  AnyDoc (Rust Calamine) + pdf-inspector (Rust)     │
│  agent:      LangGraph (think→approve→act) · tools (RiskClass) │
│              + coordinator.py (spawn/inbox/wait — ADR 0004)    │
│              + tools/firecrawl.py (scrape/clone_ui/research)   │
│              + tools/skills.py (Self-Improving Skills)         │
│  workspace:  WorkspaceFS · git (+ blame/co-change) · projects  │
│  mcp:        MCPManager · conexões stdio/HTTP · scanner cisco  │
│  lsp:        ponte WebSocket ↔ language server                 │
│  rag:        4x RAG: documents + notes + context + graphify    │
│  analytics:  ML analytics, clustering (K-Means) & auto-diagnóstico │
│  audit:      registro de aprovações WRITE/EXEC                 │
│  browser:    sessão CDP / Playwright / Lightpanda isolado      │
│                                                                 │
└───┬─────────────┬────────────────────────────────┬─────────────┘
    │             │                                │
┌───▼────┐  ┌────▼────────────────────────┐  ┌───▼──────────────┐
│Postgres│  │  Provedores de LLM          │  │services/executor  │
│pgvector│  │  Ollama · Azure · Databricks│  │(único c/ docker.  │
│Redis   │  │  Anthropic · Groq · OpenAI  │  │sock — ADR 0002)   │
│MinIO   │  └─────────────────────────────┘  └──────────────────┘
└────────┘                                   services/browser
                                             (Chromium/Lightpanda
                                              em browser_net)
```

---

## Principais Módulos & Responsabilidades

### 1. Roteamento Unificado de IA (RouterEngine)
- **ADR 0001**: Ponto único de saída para chamadas LLM e Embeddings.
- Suporte multi-provedor (Ollama, Azure OpenAI, Databricks, Anthropic, Groq, OpenAI).
- Circuit breaker resiliente baseado em Redis e contabilidade estrita de tokens/custos.

### 2. Ingestão Multi-Formato RAG (AnyDoc + Calamine + PDF Inspector)
- **ADR 0008**: Motor de extração em Rust nativo.
- **`firecrawl-anydoc`**: Conversão de `.docx`, `.xlsx`, `.pptx`, `.odt`, `.ods`, `.odp`, `.rtf`, `.epub`, `.csv` em Markdown em <5ms.
- **Motor `calamine`**: Leitura ultrarrápida de planilhas Excel e OpenDocument.
- **`pdf-inspector`**: Classificação de PDFs vetorizados vs escaneados e extração de Markdown.

### 3. Ecossistema Web & Scraping (Firecrawl)
- **ADR 0006**: Cliente assíncrono para extração limpa de dados da web para RAG.
- **Guardião Anti-SSRF (`validate_target_url`)**: Bloqueio estrito de redes privadas (RFC 1918), loopback, metadados cloud (`169.254.169.254`) e nomes de contêineres Docker.
- **Ferramentas do Agente**:
  - `web_scrape`: Extração de Markdown limpo (`only_main_content=True`).
  - `web_search`: Pesquisa rápida na web com sumarização.
  - `crawl_and_index_docs`: Indexação recursiva de árvores de documentação técnica.
  - `clone_web_ui`: Extração de blueprint visual para recriação de UIs em React.
  - `deep_research`: Pesquisa autônoma multi-etapa com validação e citações (`[[1]]`, `[[2]]`).

### 4. Navegador Interno Híbrido & Fullscreen
- **ADR 0007**: Ambiente de navegação integrado no IDE e página standalone `/browser`.
- **Modo Live**: Iframe interativo em sandbox para testes rápidos com HMR e WebSockets.
- **Modo Headless / Agente**: Comunicação via CDP compatível com **Playwright** e **Lightpanda** (`lightpanda-io/browser`).
- **Modo Tela Cheia**: Expansão total via `F11` ou botão dedicado `⛶`.
- **Emulador de Dispositivos**: Presets responsivos com moldura de Desktop, Laptop, Tablet e Mobile.

### 5. Catálogo de Agent Skills & Auto-Aprimoramento
- Skills declarativas em `.agents/agent-skills/` e `.eltanix/skills/` com padrão aberto `SKILL.md`.
- Conhecimento especializado para WordPress moderno (Gutenberg, REST API, Performance), FastAPI, Playwright e Firecrawl.
- Ferramentas `list_skills`, `get_skill` e `propose_skill` para descoberta e evolução autônoma de convenções técnicas.

### 6. Sistema de 6 Suítes de Extensões & Auto-Update Open VSX
- **ADR 0009**: Ecossistema dinâmico de extensões cobrindo todo o ciclo de vida do desenvolvimento.
- **6 Suítes Nativas**: Frontend/Design System (Shadcn, DaisyUI, Lucide, Live Server, Chart.js), IA/Scraping (Firecrawl Workflow Builder, Data Connectors, MCP Marketplace), Bancos/RAG (pgvector Studio, Redis Commander, MinIO Explorer), Segurança (SAST Semgrep, Dependency CVEs, Token Profiler), Testes/APIs (Playwright Studio, Bruno Runner, Coverage Gutters) e Segundo Cérebro (Graphify Live Canvas, ADR Assistant, Git Smart Blame).
- **Auto-Update Contínuo**: Sincronização periódica com a API pública do **Open VSX Registry** e VS Code Marketplace, detecção de atualizações em lote e aplicação de updates com 1 clique.

---

## Trilha de Decisões de Arquitetura (ADRs)

1. [ADR 0001: Camada Única de LLM](adr/0001-camada-unica-de-llm.md)
2. [ADR 0002: Executor Isolado de Comandos](adr/0002-executor-isolado.md)
3. [ADR 0003: Grafo de Conhecimento e Graphify](adr/0003-grafo-de-conhecimento-graphify.md)
4. [ADR 0004: Orquestração Multiagente](adr/0004-orquestracao-multiagente.md)
5. [ADR 0005: Login Obrigatório e Sessão Segura](adr/0005-login-obrigatorio.md)
6. [ADR 0006: Integração Firecrawl Web & RAG](adr/0006-integracao-firecrawl-web-rag.md)
7. [ADR 0007: Navegador Interno e Emulação Visual](adr/0007-navegador-interno-e-emulacao-visual.md)
8. [ADR 0008: RAG Multi-Formato Universal com AnyDoc e PDF Inspector](adr/0008-rag-multi-formato-anydoc-e-pdf-inspector.md)
9. [ADR 0009: Sistema de 6 Suítes de Extensões e Auto-Update Open VSX](adr/0009-sistema-de-extensoes-e-auto-update-open-vsx.md)
10. [ADR 0010: Segurança de Servidores MCP e Cisco AI Defense Scanner](adr/0010-seguranca-mcp-e-cisco-scanner.md)
11. [ADR 0011: Sanitização Dinâmica de Prompts e Mascaramento PII](adr/0011-sanitizacao-dinamica-pii.md)
12. [ADR 0012: Modos Customizáveis do Agente e o Gate de Ferramentas por Nome](adr/0012-modos-customizaveis-e-gate-de-ferramentas.md)
13. [ADR 0013: `apps/desktop` Congelado até a IDE Web Cruzar a Onda 1](adr/0013-apps-desktop-congelado.md)

