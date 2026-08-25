# ADR 0001 — Camada única de saída para LLM

**Status:** aceito · **Data:** 2026-07-24

## Contexto

A plataforma precisa consumir modelos de origens muito diferentes: Ollama rodando na
máquina do desenvolvedor, Azure AI Foundry (deployments gerenciados e endpoints
serverless) e Databricks Model Serving. Cada um tem autenticação, formato de erro e
semântica de streaming próprios. Além disso, é requisito explícito poder trocar de modelo
sem alterar a plataforma, e contabilizar token e custo de forma confiável.

A tentação natural é importar o SDK de cada provedor onde ele for necessário — no chat, no
agente, na geração de mensagem de commit, na indexação. Isso espalha autenticação,
tratamento de erro e contagem de token por toda a base de código e torna a troca de
fornecedor uma refatoração.

## Decisão

Existe **exatamente uma** porta de saída para LLM: `eltanix.router`. Nenhum outro módulo
importa `litellm`, `openai`, `anthropic`, SDK do Databricks ou do Azure.

Consequências práticas:

1. Todo consumo interno chama `RouterEngine.complete()` ou `.embed()`.
2. Provedores entram como adaptadores em `router/adapters/`, atrás de uma interface comum
   (`validate()`, `healthcheck()`, `to_litellm_params()`, `normalize_usage()`).
3. O LiteLLM é usado **como biblioteca** (`litellm.Router`) dentro do processo FastAPI, e
   não como proxy separado — isso mantém hooks de custo, cache e compressão no mesmo lugar
   e evita um salto de rede.
4. A contabilidade de token e custo vive no router, então é impossível uma chamada escapar
   do `request_log`.
5. A fachada `/v1` OpenAI-compatible é uma casca fina sobre o mesmo router, o que faz o
   gateway servir ferramentas externas (Cline, Continue, Aider) com o mesmo código.

## Alternativas consideradas

- **SDK por provedor onde for preciso** — mais direto no começo, inviabiliza a contabilidade
  central e a troca de fornecedor. Rejeitado.
- **LiteLLM Proxy como serviço separado** — ganha o dashboard pronto do LiteLLM, mas empurra
  a lógica de custo e compressão para fora do nosso processo e adiciona um hop. Rejeitado
  para a fase 1; pode voltar se houver necessidade multiusuário.

## Consequências

- Um adaptador mal escrito degrada só o próprio provedor: o circuit breaker o isola e o
  fallback assume.
- Qualquer feature nova de provedor (prompt caching, structured output) precisa ser
  modelada na interface comum antes de ser usada — atrito deliberado, para não vazar
  detalhe de fornecedor para dentro da plataforma.
