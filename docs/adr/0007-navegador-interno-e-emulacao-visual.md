# ADR 0007: Navegador Interno Híbrido, Emulação de Dispositivos e Compatibilidade Lightpanda

## Contexto

A verificação visual e o teste interativo de aplicações web desenvolvidas pelo usuário ou pelo Agente de IA exigiam alternar frequentemente entre o editor de código e navegadores externos do sistema operacional. Além disso:
1. O modo headless isolado com Playwright é ideal para inspeção automatizada do Agente (`browser_action`), mas possui latência para digitação e testes manuais de Hot Module Replacement (HMR).
2. Motores Chromium headless tradicionais possuem alto consumo de memória RAM (~300MB+ por instância).
3. Testes visuais de responsividade em layouts modernos exigem simulação rápida de viewports (Desktop, Tablet e Mobile).

## Decisão

Adotar uma arquitetura de **Navegador Interno Híbrido** no Eltanix Coder IDE composto por:

1. **Modo Híbrido de Renderização**:
   - **⚡ Modo Live (Iframe Interativo)**: Iframe em sandbox seguro (`allow-scripts allow-same-origin allow-forms allow-popups allow-modals`) para renderização direta da aplicação local em tempo real, com suporte nativo a cliques, digitação, WebSockets e HMR.
   - **🤖 Modo Headless / Agente (Playwright & Lightpanda CDP)**: Comunicação via Chrome DevTools Protocol (CDP) e API REST para captura de screenshots, inspeção do DOM, injeção de texto por seletor e streaming de telemetria e rede.

2. **Modo Tela Cheia (Fullscreen)**:
   - Suporte nativo à Fullscreen API via atalho `F11` ou botão dedicado `⛶`, permitindo ocupar 100% da tela do monitor para testes imersivos.

3. **Múltiplas Abas & Histórico**:
   - Gerenciamento de múltiplas abas com URLs, títulos e históricos independentes (`Back`, `Forward`, `Reload`, `Home`).

4. **Simulador de Dispositivos**:
   - Presets integrados para Desktop (1280px), Laptop (1024px), Tablet (768x1024), Mobile SE (375x667) e Mobile Max (390x844) com rotação (*Portrait / Landscape*) e zoom configurável.

5. **Arquitetura Dual-Engine (Lightpanda & Chromium Playwright)**:
   - **🐼 Lightpanda Engine (`lightpanda-io/browser`)**: Motor headless em C/C++ (QuickJS/V8) com inicialização em sub-50ms e consumo de apenas ~25MB de RAM (15x a 20x menor que Chromium). Conectado via CDP puro (`ws://lightpanda:9222`), ideal para web scraping massivo, RAG crawling (Firecrawl), auditorias rápidas de DOM e enxames multiagente concorrentes.
   - **🌐 Chromium Engine (Playwright)**: Motor de renderização completo para screenshots pixel-perfect, captura de traces, gravação de vídeo e testes visuais E2E.
   - **⚡ Modo Inteligente (`engine="auto"`)**: Roteamento automático baseado no tipo de tarefa (Lightpanda para extração e DOM, Chromium para screenshots) com fallback resiliente para Chromium em caso de indisponibilidade transitória.

## Consequências

- **Positivas**:
  - Testes visuais e navegação sem sair do ambiente da IDE ou via página dedicada `/browser`.
  - Redução drástica de consumo de RAM (~25MB por sessão) para rotinas de scraping e inspeção de código do agente.
  - Alternância de motores via seletor visual na barra de ferramentas da IDE (`⚡ Auto`, `🐼 Lightpanda`, `🌐 Chromium`).
  - Experiência fluida para desenvolvedores com atalhos rápidos de portas comuns (`:3000`, `:5173`, `:8000/docs`, `:5000`).
- **Negativas / Limitações**:
  - Aplicações externas que configuram cabeçalhos rígidos de `X-Frame-Options: DENY` ou `Content-Security-Policy: frame-ancestors 'none'` requerem uso do modo Headless ou abertura em janela externa via botão `↗`.

## Addendum (2026) — Painel Manual, Streaming ao Vivo, Persistência de Replay e Robustez

Esta ADR descrevia a experiência do navegador interno como só um recurso do Agente. Na prática, o
navegador interno tem hoje **dois domínios de risco distintos, compartilhando a mesma infraestrutura**:

1. **`browser_action`** (tool do Agente, `agent/tools/browser.py`) — `RiskClass.EXEC`, sempre para no
   grafo (`agent/graph.py`) esperando aprovação humana via `interrupt()` do LangGraph, exatamente como
   qualquer outra ferramenta de risco.
2. **Painel manual** (`api/routes/browser.py`, rota `/api/browser/*`, consumido por
   `EditorBrowserView.tsx` e pelo painel lateral `BrowserPanel`) — sem `RiskClass`, sem aprovação: o
   usuário já está no controle direto, o mesmo raciocínio por trás do Terminal do IDE não pedir
   aprovação a cada comando digitado.

Os dois falam com o mesmo serviço isolado `services/browser` (rede `browser_net`, `internal: true`) via
`BrowserClient` (`browser/client.py`), mas cada um mantém sua própria instância de cliente por sessão —
uma cacheada em `app.state.browser_panel_clients` (painel), outra gerenciada pelo `AgentRunner` (agente).
O serviço Lightpanda (`lightpanda-io/browser`, item 5 da Decisão acima) está em produção no
`docker-compose.yml`, não mais planejado — ambos os domínios de risco o alcançam via `engine="auto"`.

**Sinal `url_is_internal_fallback`.** Quando `services/browser` substitui a URL pedida por um hostname
Docker-interno (`eltanix-<session_id>`, `host.docker.internal`) porque o hostname original não resolve
de dentro do container, o retorno de `navigate` inclui `url_is_internal_fallback: true` + `original_url`.
Sem esse sinal explícito, a URL substituída podia vazar como `src` de um `<iframe>` renderizado no
navegador REAL do usuário (modo Live) — que não resolve nomes Docker-internos, resultando numa tela em
branco silenciosa. `EditorBrowserView.tsx` nunca usa uma URL Docker-interna como `src` do iframe; em vez
disso mostra um banner (`role="alert"`/`role="status"`) e sugere o modo 🤖 Agente. Complementarmente, uma
heurística client-side (regex sobre o hostname digitado) cobre o caso de o usuário digitar um hostname
Docker-interno direto na barra de endereço, sem esperar uma resposta do backend. `validate_url` no
próprio `services/browser/app.py` também é sensível ao contexto: sessões `panel-*` bloqueiam hosts
Docker-internos que só fazem sentido para uma sessão de agente (`web`, `api`, `host.docker.internal`).

**Streaming ao vivo (screencast CDP).** O modo 🤖 Agente pode manter um canal WebSocket de frames JPEG
ao vivo (em vez de screenshot sob pedido), auto-iniciado ao entrar nesse modo, com reconexão automática
por backoff exponencial (teto de 5 tentativas). Como o navegador do usuário não pode mandar um header
`Authorization` customizado ao abrir um WebSocket, a rota (`ws_router`, sem `AuthDep`) se autentica por um
**ticket de uso único** (`api/tickets.py::TicketStore`, escopado por `session_id`, TTL de 60s, Redis
quando disponível e memória do processo como alternativa) — o mesmo padrão já usado pelo WS do LSP. A
ponte API→serviço de navegador do outro lado do salto usa `Authorization` de verdade (`BROWSER_TOKEN`),
já que ali quem abre a conexão é o próprio servidor.

**Persistência de replay.** Ao fechar uma sessão (painel ou agente), `services/browser` devolve
trace.zip/vídeo (Playwright) como bytes no corpo da resposta — o serviço não alcança o MinIO, nunca fala
com ele diretamente (mesma garantia de isolamento de rede). É do lado da API (`browser/replay.py`) que os
bytes viram objetos no bucket via `BlobStore`, com um índice de sessões recentes no Redis (TTL de 7 dias,
opcional — sem Redis o replay ainda sobe, só não aparece na lista de "recentes"). Um limite de tamanho
(`BROWSER_MAX_REPLAY_BLOB_BYTES`, default 20MB) evita que trace/vídeo grandes demais estourem o corpo da
resposta JSON; quando o reaper de TTL do serviço de navegador descarta uma sessão com gravação em
andamento (30min de inatividade), um marcador `browser:replay-expired:<id>` no Redis torna esse "replay
perdido" consultável via `GET /replays/{id}` → `410 Gone`, em vez de um `404` indistinguível de "nunca
existiu". Um reaper periódico (`run_replay_purge_reaper`) remove do MinIO blobs órfãos cujo índice Redis
já expirou, respeitando uma margem de 1h para não competir com um upload em andamento.

**Validação SSRF compartilhada.** `eltanix.security.url_safety` é o módulo único consumido por
`firecrawl/service.py` (scraping/crawling externo) e `agent/tools/browser.py` (allowlist de alvos locais
do agente). `services/browser/app.py` mantém deliberadamente uma cópia sincronizada, não importada — o
serviço roda isolado, sem o pacote `eltanix` instalado, para manter a menor superfície possível numa
rede que já é a mais permissiva do sistema (ver docstring de `security/url_safety.py`).

