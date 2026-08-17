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

5. **Compatibilidade com Lightpanda**:
   - Suporte à integração com navegadores headless ultraleves via CDP (`lightpanda-io/browser`), reduzindo o consumo de memória em até 16x para rotinas de extração de dados e automação de agentes.

## Consequências

- **Positivas**:
  - Testes visuais e navegação sem sair do ambiente da IDE ou via página dedicada `/browser`.
  - Experiência fluida para desenvolvedores com atalhos rápidos de portas comuns (`:3000`, `:5173`, `:8000/docs`, `:5000`).
  - Redução de consumo de recursos computacionais através da opção de motores headless enxutos.
- **Negativas / Limitações**:
  - Aplicações externas que configuram cabeçalhos rígidos de `X-Frame-Options: DENY` ou `Content-Security-Policy: frame-ancestors 'none'` requerem uso do modo Headless ou abertura em janela externa via botão `↗`.
