# ADR 0007: Navegador Interno Híbrido, Emulação de Dispositivos e Compatibilidade Lightpanda

## Contexto

A verificação visual e o teste interativo de aplicações web desenvolvidas pelo usuário ou pelo Agente de IA exigiam alternar frequentemente entre o editor de código e navegadores externos do sistema operacional. Além disso:
1. O modo headless isolado com Playwright é ideal para inspeção automatizada do Agente (`browser_action`), mas possui latência para digitação e testes manuais de Hot Module Replacement (HMR).
2. Motores Chromium headless tradicionais possuem alto consumo de memória RAM (~300MB+ por instância).
3. Testes visuais de responsividade em layouts modernos exigem simulação rápida de viewports (Desktop, Tablet e Mobile).

## Decisão

Adotar uma arquitetura de **Navegador Interno Híbrido** no SicoobitoCode composto por:

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

