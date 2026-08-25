# Contribuindo com o Eltanix Coder IDE

Obrigado pelo interesse em ajudar a construir o Eltanix Coder IDE. Este documento é o ponto de
entrada rápido — os guias detalhados de convenções por área já existem no repositório e não são
duplicados aqui.

## Antes de abrir um PR

1. Leia o [`CLAUDE.md`](CLAUDE.md) na raiz — invariantes de arquitetura que não devem ser
   quebrados sem atualizar o ADR correspondente (ex.: única porta de saída para LLM, execução
   sempre isolada no executor, toda ferramenta do agente declara `RiskClass`).
2. Leia o guia da área que você vai tocar: [`apps/api/CLAUDE.md`](apps/api/CLAUDE.md),
   [`apps/web/CLAUDE.md`](apps/web/CLAUDE.md) ou [`apps/desktop/CLAUDE.md`](apps/desktop/CLAUDE.md)
   — cada um documenta comandos de teste/lint, estrutura de pastas e padrões esperados para
   código novo naquela área.
3. Para mudanças de arquitetura, refatorações amplas ou novos módulos, dê uma olhada nos
   [ADRs](docs/adr/) e no [mapa de arquitetura](docs/architecture.md) antes de propor a
   alteração — evita retrabalho quando a decisão já foi tomada (ou descartada) antes.

## Fluxo de contribuição

1. Abra uma *issue* descrevendo o que pretende mudar antes de investir tempo numa mudança
   grande — para correções pequenas e óbvias, pode ir direto para o PR.
2. Faça um fork, crie uma branch descritiva (`feat/`, `fix/`, `docs/`...) e trabalhe nela.
3. Rode a suíte de testes e lint da área que você tocou antes de abrir o PR:

   ```bash
   # Backend
   cd apps/api && uv run pytest tests -q && uv run ruff check src

   # Frontend web
   cd apps/web && bun run typecheck && bun run test && bun run build

   # Desktop
   cd apps/desktop && npm run typecheck && npm run test
   ```

4. Abra o PR com uma descrição do *quê* e do *porquê* — o *como* já está no diff. Referencie a
   issue relacionada, se houver.
5. Todo PR passa pelo CI (`.github/workflows/ci.yml`) antes de ser revisado.

## Padrões de código

- **Backend**: Python 3.12, `ruff` para lint (`select = E,F,I,UP,B,ASYNC,RUF`), tipos em toda
  função pública, testes ao lado do código em `apps/api/tests/`.
- **Frontend web/desktop**: TypeScript estrito, `tsc --noEmit` limpo, testes junto do arquivo
  testado (`arquivo.test.ts`, não numa pasta `__tests__` separada).
- **Commits**: mensagens objetivas focadas no *porquê* da mudança, não só no *quê*.
- **Comentários**: só quando o código sozinho não explica uma decisão não óbvia (uma
  invariante escondida, um workaround para um bug específico) — não parafraseie o código.

## Reportando bugs e vulnerabilidades

- **Bugs comuns**: abra uma issue com passos para reproduzir, comportamento esperado vs. real,
  e ambiente (SO, versão do Docker).
- **Vulnerabilidades de segurança**: **não** abra uma issue pública. Veja
  [`SECURITY.md`](SECURITY.md) para o processo de divulgação responsável.

## Código de conduta

Este projeto segue o [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md). Participar implica concordar
em respeitá-lo.

## Licença

Ao contribuir, você concorda que sua contribuição será licenciada sob a mesma
[Apache License 2.0](LICENSE) que cobre o restante do projeto.
