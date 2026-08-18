# Diretrizes do Modo Planejamento (Planning Mode Guidelines)

Ao atuar no **Modo Planejamento** ou elaborar um `implementation_plan.md` neste repositório:

1. **Investigação Baseada no Código Existente**:
   - Sempre inspecione os arquivos reais do repositório, dependências, ADRs (`docs/adr/`) e o arquivo [`CLAUDE.md`](file:///c:/Users/leona/Documents/Projetos/SicoobitoCode/CLAUDE.md) antes de propor qualquer plano.
   - NUNCA proponha planos baseados em suposições ou trechos genéricos de código sem antes ler a arquitetura e os componentes já construídos.

2. **Propostas Objetivas e Sem Snippets Genéricos**:
   - O plano deve focar estritamente no **o que alterar**, citando com precisão os arquivos afetados (`[MODIFY]`, `[NEW]`, `[DELETE]`) e as funções/classes que mudarão.
   - Proibido colar grandes blocos de exemplos teóricos ou código genérico no plano. Mantenha a especificação sucinta, cirúrgica e orientada à lógica das modificações.

3. **Plano Direto ao Ponto e Verificação**:
   - Especifique a estratégia de execução direta e os comandos de teste/validação reais alinhados à stack do projeto (ex.: `pytest`, `bun run typecheck`, `docker compose`).
