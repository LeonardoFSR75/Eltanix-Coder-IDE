# Eltanix Coder IDE

**Plataforma local-first de codificação agêntica.** Um IDE web completo estilo VS Code — editor
Monaco, terminal, navegador interno e chat com um agente autônomo que lê, edita e executa
comandos sobre o seu próprio repositório, sempre com aprovação humana nas ações de risco.

Tudo roda em Docker na sua própria máquina (ou servidor): Postgres + pgvector, Redis, MinIO e um
sandbox de execução isolado. Nenhum código nem segredo sai do seu ambiente além das chamadas que
você mesmo autorizar a um provedor de LLM.

O princípio que sustenta tudo: **nenhum módulo fala com um provedor de LLM diretamente.** Toda
chamada passa por um único router (`RouterEngine`), e cada provedor entra como adaptador
plugável — trocar de modelo ou de nuvem é mudança de configuração, não de código ([ADR
0001](docs/adr/0001-camada-unica-de-llm.md)).

---

## Índice

- [Recursos & módulos principais](#-recursos--módulos-principais)
- [Início rápido](#-início-rápido)
- [Estrutura do repositório](#-estrutura-do-repositório)
- [Navegador interno & verificação visual](#-navegador-interno--verificação-visual)
- [RAG multi-formato & documentos](#-rag-multi-formato--documentos)
- [Scraping & Deep Research com Firecrawl](#️-scraping--deep-research-com-firecrawl)
- [Segurança](#-segurança)
- [Testes & qualidade de código](#-testes--qualidade-de-código)
- [Documentação de arquitetura](#-documentação-de-arquitetura)
- [Contribuindo](#-contribuindo)
- [Licença](#-licença)

---

## 🌟 Recursos & Módulos Principais

| Módulo | Escopo & Capacidades | Maturidade |
|---|---|---|
| **Navegador Interno Completo** | Modo **Tela Cheia (`F11`)**, múltiplas abas dinâmicas, histórico completo, emuladores de dispositivos (Desktop, Tablet, Mobile SE, Mobile Max), favoritos rápidos (`:3000`, `:5173`, `:8000/docs`, `:5000`), modo híbrido **Live Iframe** + **Headless CDP** compatível com **Lightpanda** | 🟢 Stable |
| **RAG Multi-Formato Universal** | Extração ultrarrápida em Rust via **AnyDoc** (motor **Calamine**) para Word (`.docx`, `.odt`), Excel (`.xlsx`, `.xls`, `.xlsb`, `.ods`), PowerPoint (`.pptx`, `.odp`), EPUB, RTF e CSV + classificação inteligente de PDFs via **PDF Inspector** | 🟢 Stable |
| **Web Scraping & Deep Research (Firecrawl)** | Web scrape limpo em Markdown, crawling recursivo de documentações, clonagem de UI React (`clone_web_ui`), pesquisa profunda com citações (`deep_research`) e **proteção anti-SSRF** | 🟢 Stable |
| **Gateway Multi-Modelo** | Roteamento unificado (Ollama, Azure, Databricks, Anthropic, Groq, OpenAI), fallback automático, circuit breaker e contabilidade de tokens/custos | 🟢 Stable |
| **Agente LangGraph** | Loop autônomo (*think → approve → act*), sandbox isolado de execução, ferramentas por classe de risco (`RiskClass`), modos `ask`, `edit`, `agent`, `plan`, `auto` e `orchestra`, orquestração multiagente (`spawn_agent`) | 🟢 Stable |
| **Sandbox & Executor** | Isolamento de comandos em container dedicado com privilégios reduzidos (`cap_drop: ALL`, sem root, rede restrita) | 🟢 Stable |
| **IDE Web Agêntica** | Editor Monaco (split-pane), explorador de arquivos com drag-and-drop, terminal integrado, cards de ferramentas estruturados e Agent Dock/Manager | 🟡 Beta |
| **Extensões (Open VSX)** | 6 Suítes Nativas de extensões com persistência no PostgreSQL e auto-update com degradação graciosa | 🟡 Beta |
| **GraphRAG (Graphify)** | Base de conhecimento em grafo de código (nós/arestas L1–L3), expansão semântica CTE/GQL e visualização 360° | 🟡 Beta |
| **MCP (Model Context Protocol)** | Suporte completo a servidores MCP (stdio/HTTP), com scanner de segurança integrado (Cisco MCP Scanner) | 🟡 Beta |
| **Segundo Cérebro & Obsidian** | Base de notas interligadas com `[[wikilinks]]`, busca híbrida vetorial + BM25 e Graph View 2D/3D interativo | 🔴 Experimental |
| **Auto-Diagnóstico & Anomalias** | Agrupamento semântico não-supervisionado por similaridade de cosseno de embeddings e heurísticas de correção | 🔴 Experimental |
| **App Desktop (Tauri + Svelte 5)** | Shell desktop nativo com Svelte 5 e Tauri | 🔴 Experimental *(Ajuda bem-vinda)* |

---

## 🚀 Início Rápido

Toda a stack roda em contêineres Docker isolados — basta um único comando `docker compose up`.

### 1. Configurar variáveis de ambiente

Copie o arquivo de exemplo e configure suas chaves:

```bash
cp .env.example .env
```

Gere as chaves de segurança da aplicação:

```bash
python -c "import secrets;print(secrets.token_urlsafe(32))"
```

Fixe no `.env`:
- `ELTANIX_API_KEY`: chave para integrações externas (Cline, Continue, Aider).
- `EXECUTOR_TOKEN`: chave de comunicação com o sandbox do executor.
- `ELTANIX_ADMIN_USERNAME` e `ELTANIX_ADMIN_PASSWORD`: credenciais de acesso à interface web.
- `FIRECRAWL_API_KEY`: (opcional) chave da API do Firecrawl para scraping e deep research na web pública.

### 2. Subir a stack via Docker Compose

```bash
docker compose up -d --build
```

Execute as migrações do banco de dados:

```bash
docker compose exec api alembic upgrade head
```

### 3. Acessar os serviços

| Serviço | Porta local | URL de acesso |
|---|---|---|
| **IDE & Dashboard (Next.js Web)** | `5400` | [http://localhost:5400](http://localhost:5400) |
| **Navegador Interno Dedicado** | `5400` | [http://localhost:5400/browser](http://localhost:5400/browser) |
| **API & Gateway (FastAPI)** | `5401` | [http://localhost:5401/docs](http://localhost:5401/docs) |
| **IDE Desktop Preview (Svelte 5)** | `5409` | [http://localhost:5409](http://localhost:5409) |
| **MinIO Console (Storage)** | `5408` | [http://localhost:5408](http://localhost:5408) |

---

## 📂 Estrutura do Repositório

| Diretório | O quê |
|---|---|
| `apps/api` | Backend FastAPI + SQLAlchemy async + LangGraph — router de LLM, agente, RAG, Graphify, MCP |
| `apps/web` | IDE web em Next.js — Monaco, terminal, Agent Dock, navegador interno, Segundo Cérebro |
| `apps/desktop` | Preview do IDE em Svelte 5 + Tauri (desktop nativo) |
| `services/browser` | Serviço de navegador headless (Playwright/Lightpanda) usado pelo agente |
| `services/executor` | Sandbox isolado de execução de comandos (ver [ADR 0002](docs/adr/0002-executor-isolado.md)) |
| `docs/adr` | Registros de Decisões Arquiteturais |
| `docs` | Documentação de arquitetura, capacidades do IDE e roadmap |

Cada app tem seu próprio guia de desenvolvimento: [`apps/api/CLAUDE.md`](apps/api/CLAUDE.md),
[`apps/web/CLAUDE.md`](apps/web/CLAUDE.md), [`apps/desktop/CLAUDE.md`](apps/desktop/CLAUDE.md).

---

## 🌐 Navegador Interno & Verificação Visual

O Eltanix Coder IDE conta com um navegador de desenvolvimento integrado completo:
- **Modo Tela Cheia (`F11`)**: expande a visualização para 100% da tela do monitor para testes visuais imersivos.
- **Múltiplas abas**: abra e gerencie múltiplas sessões com URLs e históricos independentes.
- **Emulador de dispositivos**: teste em tempo real layouts em **Desktop (1280px)**, **Tablet (768x1024)** e **Mobile (375x667 / 390x844)** com rotação e controle de zoom.
- **Modo Live (⚡ Live)**: iframe em sandbox com Hot Module Replacement (HMR) e WebSockets em tempo real.
- **Modo Headless (🤖 Agente)**: conexão CDP com motores headless (Playwright / Lightpanda) para screenshots, inspeção do DOM e telemetria de rede.

---

## 📚 RAG Multi-Formato & Documentos

Faça upload direto de qualquer formato corporativo no painel `/rag`:
- 📕 **PDFs**: classificação inteligente via `pdf-inspector` (Rust) com detecção de scans sem OCR.
- 📘 **Word**: `.docx`, `.doc`, `.docm`, `.odt`.
- 📊 **Excel & Planilhas**: `.xlsx`, `.xls`, `.xlsb`, `.ods`, `.csv`, `.tsv` (processados pelo motor Rust `calamine`).
- 📙 **PowerPoint**: `.pptx`, `.ppt`, `.ppsx`, `.odp`.
- 📗 **E-books & Rich Text**: `.epub`, `.rtf`, `.md`, `.txt`.

---

## 🕷️ Scraping & Deep Research com Firecrawl

O agente possui ferramentas especializadas para interação com a web pública:
- `web_scrape`: extração de Markdown limpo e sem anúncios.
- `web_search`: pesquisa rápida na web com sumarização.
- `crawl_and_index_docs`: indexação recursiva de árvores completas de documentação técnica.
- `clone_web_ui`: blueprint estruturado para recriação de interfaces em React.
- `deep_research`: pesquisa autônoma multi-etapa com decomposição de consultas e relatório citado (`[[1]]`, `[[2]]`).
- **Guardião anti-SSRF**: validador rigoroso bloqueando loopback, redes privadas (RFC 1918), metadados de nuvem e hosts de contêineres internos.

---

## 🔒 Segurança

- **Login obrigatório**: toda rota HTTP exige sessão válida (cookie httpOnly) ou `ELTANIX_API_KEY` — nenhuma fica aberta por omissão ([ADR 0005](docs/adr/0005-login-obrigatorio.md)).
- **Execução isolada**: comandos do agente nunca falam direto com o daemon Docker da API — passam por um serviço `executor` separado, sem rede e sem root ([ADR 0002](docs/adr/0002-executor-isolado.md)).
- **Aprovação por classe de risco**: toda ferramenta declara `READ`/`WRITE`/`EXEC`; ações `WRITE`/`EXEC` sempre pausam para aprovação humana antes de executar.
- **Anti-SSRF**: toda requisição web externa (Firecrawl, navegador, deep research) é validada contra RFC 1918, loopback, metadados de nuvem e hostnames de contêiner.
- **Sanitização de PII**: CPF, e-mail, cartão e chaves de API são mascarados em prompts antes de saírem para modelos remotos.
- **Auditoria de segredos**: [`.gitleaks.toml`](.gitleaks.toml) audita o repositório continuamente contra vazamento de chaves.
- **Scanner MCP**: servidores MCP externos passam por varredura de segurança (Cisco MCP Scanner) antes de disponibilizar ferramentas ao agente.

---

## 🧪 Testes & Qualidade de Código

Executar a suíte completa de testes:

```bash
# Testes do backend (FastAPI + RAG + Firecrawl + Tools)
docker compose exec api uv run pytest -q

# Lint do backend
docker compose exec api uv run ruff check src

# Typecheck, testes e build do frontend (Next.js)
cd apps/web && bun run typecheck && bun run test && bun run build
```

---

## 📖 Documentação de Arquitetura

Para mais detalhes sobre as decisões de design, consulte:

- [Visão Geral de Arquitetura](docs/architecture.md)
- [Capacidades do IDE](docs/ide_capabilities.md)
- [ADR 0001 — Camada Única de LLM](docs/adr/0001-camada-unica-de-llm.md)
- [ADR 0002 — Executor Isolado](docs/adr/0002-executor-isolado.md)
- [ADR 0003 — Grafo de Conhecimento e Graph RAG (Graphify)](docs/adr/0003-grafo-de-conhecimento-graphify.md)
- [ADR 0004 — Orquestração Multiagente](docs/adr/0004-orquestracao-multiagente.md)
- [ADR 0005 — Login Obrigatório com Sessão por Cookie](docs/adr/0005-login-obrigatorio.md)
- [ADR 0006 — Integração Firecrawl para Web Scraping, Search e Ingestão de Docs no RAG](docs/adr/0006-integracao-firecrawl-web-rag.md)
- [ADR 0007 — Navegador Interno Híbrido, Emulação de Dispositivos e Compatibilidade Lightpanda](docs/adr/0007-navegador-interno-e-emulacao-visual.md)
- [ADR 0008 — RAG Multi-Formato Universal com AnyDoc, Motor Calamine e PDF Inspector](docs/adr/0008-rag-multi-formato-anydoc-e-pdf-inspector.md)
- [ADR 0009 — Sistema de 6 Suítes de Extensões e Auto-Update Open VSX](docs/adr/0009-sistema-de-extensoes-e-auto-update-open-vsx.md)
- [ADR 0010 — Segurança de Servidores MCP e Cisco AI Defense Scanner](docs/adr/0010-seguranca-mcp-e-cisco-scanner.md)
- [ADR 0011 — Sanitização Dinâmica de Prompts e Mascaramento de PII](docs/adr/0011-sanitizacao-dinamica-pii.md)

---

## 🤝 Contribuindo

Este projeto está em fase **beta** e aceita contribuições. Veja
[`CONTRIBUTING.md`](CONTRIBUTING.md) para o fluxo de PR, convenções de código e como rodar os
testes. Participantes concordam em seguir o [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).
Vulnerabilidades de segurança têm um processo próprio — veja [`SECURITY.md`](SECURITY.md), não
abra uma issue pública.

---

## 📄 Licença

Licenciado sob [Apache License 2.0](LICENSE).
