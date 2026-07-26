# ADR 0002 — Executor isolado em vez de docker.sock na API

**Status:** aceito · **Data:** 2026-07-25

## Contexto

Com toda a plataforma rodando em containers, o agente ainda precisa criar
sandboxes de execução. O caminho óbvio é montar `/var/run/docker.sock` no
container da API e deixá-la falar com o daemon do host — o padrão conhecido como
*sibling containers*.

O problema é o que esse socket concede: quem o alcança pode criar um container
privilegiado montando `/` do host. É acesso root ao host, sem intermediários.

E a API é justamente o pior lugar para essa capacidade morar. Ela atende
requisições HTTP, monta prompts com conteúdo vindo de README, issues e saída de
comando, e executa código escrito por um modelo. Qualquer falha de validação,
qualquer injeção que escape do tratamento de "conteúdo externo como dado", passa
a valer root no host em vez de valer uma resposta errada.

## Decisão

Um serviço `executor` separado, e só ele com o socket montado.

- A API fala com ele por HTTP na rede interna do compose, autenticada por
  `EXECUTOR_TOKEN`.
- O contrato é mínimo e fechado: criar sandbox, executar comando, destruir,
  listar, limpar órfãos. Não há endpoint que aceite caminho arbitrário nem
  opções de container vindas do chamador.
- **As restrições de segurança do sandbox são fixadas no executor**, não
  recebidas por parâmetro: usuário não-root, `cap_drop: ALL`,
  `no-new-privileges`, limites de memória e PIDs, rede desabilitada. Um chamador
  comprometido não consegue afrouxá-las.
- A imagem do executor instala quatro pacotes. Cada dependência ali é uma
  dependência com o socket ao alcance.

## Tradução de caminho

Consequência que só aparece na prática: o daemon do Docker resolve bind mounts
contra o **host**, não contra o container que pediu. A API enxerga o projeto em
`/projects/meu-app`; o daemon precisa de `C:/Users/leona/Documents/Projetos/meu-app`.

Por isso o executor recebe os dois lados (`PROJECTS_ROOT_CONTAINER` e
`PROJECTS_ROOT_HOST`) e traduz. Um caminho que não comece pela raiz de projetos
é recusado — só chega ali por engano ou por tentativa de abuso.

## Alternativas rejeitadas

- **`docker.sock` direto na API.** Menos serviços e menos código, mas coloca
  root-no-host no processo mais exposto da plataforma. É a razão de este ADR
  existir.
- **Sem execução quando containerizado.** Elimina o risco, mas tira
  `run_command` do agente — e um agente que não roda os próprios testes entrega
  mudanças não verificadas.
- **Docker-in-Docker.** Isola de verdade, mas exige container privilegiado
  (trocando um risco por outro), duplica o cache de imagens e complica volumes.

## Consequências

- O executor fora do ar degrada a plataforma sem derrubá-la: as ferramentas de
  execução recusam com uma mensagem clara, e o resto do agente segue.
- Rodando fora de container (`EXECUTOR_URL` vazio), a API volta a usar o daemon
  local — que é o certo na máquina de desenvolvimento, onde não há barreira a
  proteger.
- Se um dia houver mais de um usuário, o executor é onde entram cota por sessão
  e limite de containers simultâneos.
