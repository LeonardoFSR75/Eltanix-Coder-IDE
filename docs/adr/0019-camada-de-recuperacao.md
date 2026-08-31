# ADR 0019 — Camada de Recuperação (`retrieval/`)

- **Status**: Aceito
- **Data**: 2026-08-31
- **Contexto**: Onda 1 da [revisão de ML](../proposals/revisao-estrutura-ml-50-melhorias.md) (itens 7–15, 47)
- **Relacionado**: [ADR 0001](0001-camada-unica-de-llm.md), [ADR 0003](0003-grafo-de-conhecimento-graphify.md), [ADR 0017](0017-contrato-do-espaco-vetorial.md), [ADR 0018](0018-gate-de-qualidade-de-recuperacao.md)

## Contexto

Antes desta onda, "recuperação" na IDE era literalmente uma chamada:
`hybrid_search(..., limit=8)` numa fonte, e os oito trechos colados no prompt.
Cinco coisas faltavam, e nenhuma delas cabia dentro de um store:

1. **Ordenação final era o próprio RRF.** RRF é bom em recall e cego a
   intenção: ele sabe que o texto parece, não que responde. Precisão no topo
   ficava por conta da sorte.
2. **Corte por número de itens, não por espaço.** `limit=8` não tem relação com
   quantos tokens cabem. Oito classes grandes estouravam a janela e o provedor
   cortava pelo meio — silenciosamente, perdendo o fim do último trecho.
3. **Redundância consumia o orçamento.** Os oito hits eram, com frequência,
   oito trechos do mesmo arquivo. O arquivo que dava a outra metade da resposta
   ficava de fora.
4. **Uma fonte por chamada.** Quem perguntava "por que decidimos X" recebia
   código; o ADR que respondia estava em `document_chunk` e ninguém foi olhar.
5. **A pergunta ia crua para o buscador.** "Onde é que a gente aprova
   ferramenta?" carrega tratamento e palavras de ligação que diluem o vetor e
   sujam o full-text.

O `CLAUDE.md` proíbe abstrair os quatro stores num helper compartilhado — e a
proibição está certa: o SQL de cada fonte é pequeno, legível, e o acoplamento
entre eles custaria mais do que a duplicação. Mas a proibição foi lida, na
prática, como "não existe camada acima dos stores", e é por isso que os cinco
problemas acima ficaram sem dono.

## Decisão

Existe um pacote `apps/api/src/eltanix/retrieval/` que **orquestra** as fontes
sem fundi-las. A distinção é o coração deste ADR.

### 1. A direção da dependência é a invariante

`retrieval/` importa dos stores. **Nenhum store importa de `retrieval/`.**

Isso mantém a independência que o `CLAUDE.md` protege: cada `hybrid_search`
continua dono do seu SQL, das suas tabelas e da sua decisão de ter ou não perna
de trigrama. `retrieval/` só vê o que eles devolveram, normalizado em
`RetrievedItem`. Um store pode ser reescrito inteiro sem tocar nesta camada;
esta camada pode ser desligada (`RETRIEVAL_ENABLED=false`) sem tocar nos stores.

O que **não** pode acontecer, e é o que este ADR proíbe explicitamente: mover a
construção de SQL para `retrieval/`, ou criar aqui um `hybrid_search` genérico
parametrizado por tabela. Isso seria o helper compartilhado com outro nome.

### 2. Duas fusões, em níveis diferentes

- **Dentro de uma fonte**, no SQL do store: vetor + full-text + trigrama, por
  RRF ponderado. Fica no SQL porque só ali as três pernas se calculam numa ida
  ao banco.
- **Entre fontes**, em `retrieval/fusion.py`: por **rank**, nunca por score. Um
  score 0,03 de RRF de código não significa nada ao lado de 0,05 de nota — as
  escalas são incomparáveis, e fundir por posição é o que dispensa calibrá-las.

Os pesos das duas fusões saíram de constante de módulo para configuração
(`RETRIEVAL_WEIGHT_*`, `RETRIEVAL_SOURCE_WEIGHT_*`, `RETRIEVAL_RRF_K`), porque
é o `eltanix-eval-rag` (ADR 0018) que decide os valores, não intuição.

### 3. A ordem do pipeline é uma decisão, não uma conveniência

`preparo → fontes → fusão → rerank → diversidade → packing`

- **Fusão antes do rerank**: rerankear cada fonte separada e depois juntar
  reintroduz a comparação de escalas incomparáveis.
- **Rerank antes da diversidade**: o MMR trabalha sobre o `score` da posição; se
  rodar antes, diversifica uma ordem que o reranker vai desmanchar.
- **Packing por último**: é o único ponto que sabe quanto cabe e o **único que
  descarta**. Todas as etapas anteriores reordenam e rebaixam.

### 4. Nada entra pela metade

O empacotador (`retrieval/pack.py`) nunca trunca um trecho: ou ele cabe
inteiro, ou não entra. Meio trecho de código é pior que nenhum — parece
completo e mente sobre onde a função termina. Quando um item não cabe, o
empacotador **pula** e segue: um trecho grande na terceira posição não pode
barrar os três seguintes.

### 5. Toda saída de LLM passa pelo router

Expansão de query, HyDE e rerank listwise usam `RouterEngine.complete()` no
perfil `utility` (`RETRIEVAL_UTILITY_PROFILE`), com `source="retrieval:expand"`,
`"retrieval:hyde"` e `"retrieval:rerank"`. **Perfil, não modelo**: a escolha do
modelo continua sendo do `routes.yaml`, nunca de constante no código — mesma
regra dos ADRs 0001, 0014 e 0015.

### 6. Prefixo assimétrico é decisão do router, não do chamador

Modelos como nomic e BGE foram treinados com objetivo assimétrico e esperam
instruções diferentes ao indexar e ao consultar. Os prefixos são declarados por
modelo em `providers.yaml` (`embedding_prefixes.query` / `.document`) e
aplicados dentro de `RouterEngine.embed()`, escolhidos pelo argumento
`purpose="query"|"document"`. Nenhum chamador monta prefixo.

Ligar (`EMBEDDING_PREFIXES_ENABLED=true`) **muda o espaço vetorial**. Por isso
a etiqueta de proveniência do ADR 0017 ganha o sufixo `#prefixed`: o filtro
`embedding_model` que já existe tira os vetores antigos do ramo vetorial
sozinho, em vez de compará-los com os novos em silêncio. Fica **desligado por
padrão**, e a reindexação é um segundo passo deliberado — forçá-la
automaticamente destruiria um índice funcionando se o modelo estivesse fora do
ar.

### 7. Toda etapa degrada isolada

Sem embedding, a busca cai para as pernas lexicais. Sem reranker, fica a ordem
da fusão. Com o modelo respondendo fora do formato, a ordem de entrada é
preservada. Uma busca degradada continua sendo uma busca; o que esta camada não
pode fazer é derrubar o que funcionava antes dela. O span de RAG
(`kind="rag"`, `name="retrieval"`) registra qual caminho foi tomado —
`degraded_to_lexical`, `reranked_by_llm`, `rerank_error` — porque uma busca pior
por reranker fora do ar é indistinguível de uma busca pior por regressão de
qualidade se ninguém anotar a diferença.

### 8. O git-aware continua sendo a perna de código

Com `CONTEXT_GIT_AWARE_SEARCH` ligado, a fonte `context` passa por
`context/git_aware.py` (Fase 4 do Git Intelligence), não direto pelo
`hybrid_search`. Esta camada roda **por cima** dele. Os pesos de RRF são
repassados aos dois caminhos, ou ligar o git-aware mudaria a ordenação por um
motivo que não é o git.

### 9. O juiz de geração passa a ter intervalo

`evals/judge.py` mede a concordância do juiz (`evals/ragas.py`) com um conjunto
rotulado por humano (`config/judge_labels.yaml`): erro absoluto médio,
correlação de Pearson, kappa de Cohen sobre a decisão binarizada, e o desvio do
próprio juiz entre execuções repetidas — o **piso de ruído** da métrica.
Ajusta uma calibração afim e reporta intervalo de confiança por bootstrap.

Uma calibração com menos de 8 pontos é gravada mas **não corrige nada**
(`Calibration.usable`): uma reta ajustada em pouca coisa acompanha o ruído do
próprio conjunto. Sem arquivo de calibração, a métrica crua continua valendo —
ausência de rótulo não quebra a eval.

## Consequências

**Positivas**

- Precisão no topo passa a ter um responsável (o reranker) e diversidade passa
  a ter outro (o MMR), em vez de serem efeito colateral do RRF.
- O orçamento de contexto vira um número explícito (`RETRIEVAL_TOKEN_BUDGET`),
  medido e reportado no span, em vez de uma consequência de `limit=8`.
- Pergunta conceitual passa a alcançar ADR e nota, não só código.
- Os parâmetros que antes eram constantes de módulo agora são configuração, o
  que os torna afináveis pelo gate do ADR 0018 sem editar código.
- `POST /api/context/retrieve` expõe o pipeline com a consulta normalizada, as
  variantes e o plano de fontes na resposta — "por que este resultado?" deixa de
  se responder só lendo log de servidor.

**Negativas / custos**

- Latência: expansão e rerank são chamadas de LLM. A expansão só dispara em
  pergunta curta e sem identificador citado (`should_expand`), e o rerank pode
  ser desligado por configuração — mas o caminho ligado é mais lento que o
  anterior, e isso é uma troca, não um almoço grátis.
- Mais um lugar onde a busca pode piorar sem erro visível. É por isso que o
  span carrega o caminho tomado e que a mudança de qualquer parâmetro daqui
  exige rodar `eltanix-eval-rag` antes do PR.
- `config.py` ganhou 18 chaves. Nenhuma delas é obrigatória, e todas existem
  porque o ADR 0018 precisa variá-las sem redeploy.

## Alternativas consideradas

- **Cross-encoder local (`bge-reranker` via ONNX)** em vez de rerank listwise
  por LLM: melhor custo por item e latência previsível, mas adiciona um runtime
  de modelo ao container da API e um segundo caminho de download/versionamento
  de peso. Fica como evolução natural — a interface de `retrieval/rerank.py`
  não muda, só a implementação da segunda passagem.
- **Rerank pointwise** (pontuar cada candidato isolado): custa N chamadas e
  produz notas incomparáveis entre si. O que se quer aqui é uma ordem, e ordem
  sai de uma lista comparada de uma vez.
- **Calibração isotônica** do juiz em vez de afim: mais flexível, mas ~30 pontos
  rotulados não sustentam a estrutura extra — inventaria degraus onde há ruído.
- **Fundir os quatro stores num buscador único**: rejeitado. É exatamente o
  helper compartilhado que o `CLAUDE.md` proíbe, e a razão da proibição
  continua válida.
