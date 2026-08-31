# ADR 0018 — Gate de Qualidade de Recuperação

- **Status**: Aceito
- **Data**: 2026-08-30
- **Contexto**: Onda 0 da [revisão de ML](../proposals/revisao-estrutura-ml-50-melhorias.md) (itens 45, 46, 49)
- **Relacionado**: [ADR 0017](0017-contrato-do-espaco-vetorial.md), [ADR 0003](0003-grafo-de-conhecimento-graphify.md)

## Contexto

O harness de avaliação (`eltanix-eval-rag`) existia desde cedo e media hit@k e
MRR contra os buscadores reais. Só que o dataset versionado tinha **dois
casos**, ambos com `root` apontando para um caminho de exemplo — ou seja, não
rodava sem edição manual, e mesmo rodando não media nada: com dois casos, um
acerto a mais move a métrica em 50 pontos percentuais.

O efeito prático: mexer no chunker, no RRF, no `ef_search` ou no modelo de
embedding mudava a qualidade da busca, e ninguém percebia até a IDE começar a
responder pior. Lint e teste barram regressão de código; nada barrava
regressão de recuperação — que é a parte do produto mais fácil de piorar sem
notar, porque ela sempre devolve *alguma coisa*.

## Decisão

### 1. Dataset com massa crítica, e escrito para medir o que interessa

`config/eval_dataset.yaml` passa a ter 96 casos cobrindo router, otimização,
RAG, agente, editor, segurança, grafo, plataforma e analytics.

Três regras de escrita, todas verificadas por `tests/test_eval_dataset.py`:

- **A query não pode conter o identificador esperado.** Se contiver, o caso
  passa pelo ramo full-text mesmo com o embedding fora do ar — vira decoração.
- **Todo caso tem `tags`.** O gate compara tag a tag, porque uma média única
  esconde regressão localizada: a recuperação pode cair 30% só nas consultas
  sobre o router e a média geral mal se mexer.
- **`root` sai de `${ELTANIX_EVAL_ROOT}`**, via o bloco `defaults` do YAML.
  Caminho absoluto por caso significa que ninguém roda de outra máquina.

### 2. Métricas separadas da execução

`evals/metrics.py` é puro — sem I/O, sem banco, sem rede — justamente para o
gate poder rodar em CI e ser testável sem infraestrutura. Três números:

- `hit_rate` — fração de casos com relevante dentro do `limit`. Como cada caso
  tem um alvo, é o `recall@k` **do dataset**; não é recall sobre o conjunto
  completo de trechos relevantes do repositório, que ninguém rotulou. O nome
  evita que o número seja lido como outra coisa.
- `mrr` — penaliza achar na quinta posição o que deveria estar na primeira.
- `ndcg` — desconto logarítmico sobre todas as posições relevantes. É o que
  separa "achou um" de "achou os três".

### 3. Baseline versionado, comparação pura

```bash
uv run eltanix-eval-rag --json /tmp/eval.json
uv run eltanix-eval-gate --report /tmp/eval.json          # compara e falha
uv run eltanix-eval-gate --report /tmp/eval.json --write  # promove a baseline
```

`config/eval_baseline.json` é versionado de propósito: a régua muda por
decisão registrada em commit, não porque alguém rodou de novo até passar.

`gate.comparar()` reprova quando:

- alguma métrica cai mais que a tolerância (padrão 0,02 absoluto) no agregado
  geral, em uma fonte ou em uma tag;
- o número de casos **diminui** — sem isso, apagar os casos difíceis é o jeito
  mais fácil de passar no gate;
- um escopo que existia no baseline some do relatório.

Escopo novo no relatório não reprova nada: não havia régua para ele, e cobrar
seria inventar um número.

A tolerância existe porque recuperação tem ruído real (desempate do RRF,
ordem entre scores iguais). Um gate que dispara com 0,3 pp de variação vira
ruído que todo mundo aprende a ignorar — e um gate ignorado é pior que
nenhum, porque dá a impressão de que alguém está olhando.

### 4. Roda agendado, não por PR

`.github/workflows/rag-quality.yml`, com serviços `pgvector` e `ollama`,
noturno e sob demanda (`workflow_dispatch`).

Não roda em todo PR porque medir de verdade exige indexar o repositório e
baixar o modelo de embedding — minutos por execução. E rodar **sem** embedding
seria pior que não rodar: a busca degrada para full-text puro e o número
medido não é o número que a IDE entrega. `eltanix.evals.index_workspace`
falha explicitamente quando nenhum vetor foi gerado, para o gate nunca
comparar duas coisas diferentes e chamar isso de regressão (ou de melhora).

Quem mexer no chunker, no RRF ou no modelo de embedding dispara à mão antes de
fechar o PR.

### 5. O span de RAG diz o que aconteceu na recuperação

`TraceEntry` ganha `attributes`, e as três buscas (`context`, `documents`,
`notes`) anexam `hits`, `vector_hits`, `text_hits`, `top_score`,
`embedding_model` e `degraded_to_fulltext`.

Sem isso um span de RAG só informa "demorou X e não deu erro", o que não
distingue uma busca boa de uma que degradou para full-text e devolveu qualquer
coisa — e é exatamente essa diferença que se procura quando a resposta veio
ruim. Os atributos saem no log estruturado e no JSON OTLP.

## Consequências

**Ganhos**

- Existe uma régua. As melhorias das ondas seguintes passam a ser
  verificáveis em vez de plausíveis.
- Regressão localizada por área é detectada, não diluída na média.
- Uma resposta ruim do agente pode ser atribuída (ou não) à recuperação, com
  evidência no span.

**Custos aceitos**

- O gate não protege PR a PR. Uma regressão pode entrar e ser pega na noite
  seguinte — melhor que o estado anterior, em que não era pega nunca.
- 96 casos precisam de manutenção: renomear um símbolo público quebra o caso
  que o esperava. É o preço de casos ancorados em identificador estável, e a
  quebra é informativa.
- Promover baseline é passo manual e deliberado.

## Alternativas descartadas

- **Rodar o gate em todo PR sem embedding.** Mediria a busca full-text, não a
  busca do produto. Um número errado com aparência de rigor.
- **Dataset gerado por LLM.** Barato de produzir e caro de confiar: os casos
  refletiriam o que o modelo acha que o repositório contém.
- **Gate sem tolerância.** Falharia por ruído de desempate e seria desligado
  na primeira semana.
