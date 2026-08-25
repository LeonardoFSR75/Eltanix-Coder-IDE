# ADR 0009: Sistema de 6 Suítes de Extensões & Atualização Automática via Open VSX / VS Code Registry

## Contexto

A plataforma NovaAI Studio oferecia inicialmente uma lista estática de extensões de linguagens (LSP) no frontend, sem integração em tempo real com repositórios públicos, sem gestão centralizada de ciclo de vida e sem cobrir todas as etapas do fluxo de engenharia de software contemporâneo (Design System, Scraping com Firecrawl, pgvector/RAG, SAST/Segurança, Testes visuais E2E e Segundo Cérebro com Graphify).

Adicionalmente, os desenvolvedores e os próprios agentes de IA necessitavam de ferramentas sempre atualizadas com as versões mais recentes distribuídas nos repositórios oficiais do ecossistema VS Code / Open VSX.

## Decisão

Implementar uma arquitetura de extensões dinâmica e modular composta por:

1. **6 Suítes Completas de Extensões Especializadas**:
   - **🎨 Frontend & Design System**: *Shadcn UI / Radix Registry*, *DaisyUI Theme Explorer (28 temas)*, *Lucide & Tabler Icons*, *Live Server Hot-Reload* e *Chart.js Data Viz Studio*.
   - **🚀 IA & Web Scraping**: *Visual Workflow Builder (`firecrawl/open-agent-builder`)*, *LLM Data Connectors (`firecrawl/data-connectors`)* e *MCP Marketplace com Security Scanner (`cisco-mcp-scanner`)*.
   - **🗄️ Bancos de Dados & RAG**: *pgvector Semantic Studio*, *Redis Commander* e *MinIO Object Storage Explorer*.
   - **🛡️ Segurança & Governança**: *Semgrep SAST Scanner*, *Dependency CVE Auditor (Pip-Audit)* e *Token Cost & Latency Profiler*.
   - **🧪 Testes & APIs**: *Playwright Visual E2E Studio*, *Bruno / Thunder Client API Runner* e *Coverage Heatmap*.
   - **🧠 Arquitetura & Segundo Cérebro**: *Graphify 3D Live Canvas*, *ADR Assistant* e *Git Smart Blame*.

2. **Cliente de Repositório Open VSX / VS Code (`OpenVSXClient`)**:
   - Cliente assíncrono com tolerância a falhas para consultar a API pública do **Open VSX Registry** (`https://open-vsx.org/api`) e galeria do VS Code.
   - Suporte a busca online por palavras-chave, verificação de novas versões semânticas e extração de metadados (downloads, ratings, ícones, changelogs e links de repositório).

3. **Gerenciador Central de Ciclo de Vida (`ExtensionsManager`)**:
   - Rastreamento persistente de extensões instaladas, status de ativação (`active`/`disabled`) e atualizações pendentes.
   - Motor de auto-update com capacidade de atualização unitária (`/api/extensions/{id}/update`) ou em lote (`/api/extensions/update-all`).
   - Sincronização periódica em segundo plano e sob demanda via API REST.

4. **Interface IDE Reativa (`ExtensionsPanel`)**:
   - Painel com abas por categoria, contador em badge de atualizações pendentes e aba de busca em tempo real no Open VSX Registry.
   - Botão de 1 clique "Atualizar Todas", toggle de modo Auto-Update e gaveta de detalhes técnicos com lista de recursos e link do repositório oficial.

## Consequências

- **Positivas**:
  - Ecossistema de extensões profissional cobrindo todo o ciclo de vida do desenvolvimento de software.
  - Atualizações contínuas e seguras vindas diretamente dos repositórios oficiais sem intervenção manual obrigatória.
  - Integração nativa com o agente autônomo, que agora conta com extensões de design system e ferramentas visuais pré-configuradas.
- **Negativas / Limitações**:
  - A busca e checagem no Open VSX dependem de conectividade de rede externa (mitigado por cache persistente em disco e fallback estático local).
