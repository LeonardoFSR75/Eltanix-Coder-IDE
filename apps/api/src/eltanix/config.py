"""Configuração da aplicação, carregada de variáveis de ambiente e do `.env` da raiz."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_repo_root() -> Path:
    """Raiz que contém `config/`, procurando para cima.

    Contar níveis fixos (`parents[4]`) só funciona no layout do checkout: numa
    imagem Docker o pacote fica em `/app/src/eltanix`, que não tem cinco
    níveis acima, e a contagem estoura com IndexError no import.
    """
    aqui = Path(__file__).resolve()
    for candidato in aqui.parents:
        if (candidato / "config" / "providers.yaml").exists():
            return candidato
    # Sem `config/` em lugar nenhum, resta um palpite razoável; quem manda de
    # verdade nesse caso é ELTANIX_CONFIG_DIR.
    return aqui.parents[min(2, len(aqui.parents) - 1)]


REPO_ROOT = _find_repo_root()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", Path(".env")),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Núcleo ──────────────────────────────────────────────────────────────
    api_key: str = Field(default="", alias="ELTANIX_API_KEY")
    # Usuário único do login (etapa 1 — ver `auth/service.py`). Sem senha
    # definida, o lifespan gera uma aleatória e loga uma vez: login continua
    # obrigatório, só a senha do primeiro acesso fica no log em vez do `.env`.
    admin_username: str = Field(default="admin", alias="ELTANIX_ADMIN_USERNAME")
    admin_password: str = Field(default="", alias="ELTANIX_ADMIN_PASSWORD")
    # Cifra em repouso do segredo TOTP (`user_mfa.secret`) — F-7 da revisão de
    # segurança 2026-08. Vazia = segredo em claro, como antes (degrada, não
    # quebra). Ver `auth/secret_box.py`.
    mfa_secret_key: str = Field(default="", alias="ELTANIX_MFA_SECRET_KEY")
    log_level: str = Field(default="INFO", alias="ELTANIX_LOG_LEVEL")
    log_json: bool = Field(default=False, alias="ELTANIX_LOG_JSON")
    config_dir: Path = Field(default=REPO_ROOT / "config", alias="ELTANIX_CONFIG_DIR")
    # Só para testes/deploys incomuns redirecionarem onde a tela de
    # credenciais escreve; no dia a dia o padrão (`.env` da raiz) já basta.
    env_file_override: Path | None = Field(default=None, alias="ELTANIX_ENV_FILE")

    # ── Infra ───────────────────────────────────────────────────────────────
    database_url: str = Field(
        default="postgresql+asyncpg://eltanix:eltanix@localhost:5433/eltanix",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6380/0", alias="REDIS_URL")

    # ── Roteamento ──────────────────────────────────────────────────────────
    default_route_profile: str = Field(default="auto", alias="DEFAULT_ROUTE_PROFILE")

    # ── Orçamento (USD; 0 desliga o limite) ─────────────────────────────────
    budget_daily_usd: float = Field(default=0.0, alias="BUDGET_DAILY_USD")
    budget_monthly_usd: float = Field(default=0.0, alias="BUDGET_MONTHLY_USD")
    budget_hard_stop: bool = Field(default=False, alias="BUDGET_HARD_STOP")

    # ── Cache ───────────────────────────────────────────────────────────────
    cache_enabled: bool = Field(default=True, alias="CACHE_ENABLED")
    cache_ttl_seconds: int = Field(default=3600, alias="CACHE_TTL_SECONDS")
    # Respostas com temperatura > 0 são propositalmente variáveis; cacheá-las
    # transforma criatividade pedida em repetição silenciosa.
    cache_only_deterministic: bool = Field(default=True, alias="CACHE_ONLY_DETERMINISTIC")

    # ── Cache semântico (complementa o cache exato acima) ───────────────────
    # Desligado por padrão: um falso positivo aqui devolve um tool_call ou uma
    # resposta ERRADA (não uma "falta de cache"), então a ativação é opt-in.
    semantic_cache_enabled: bool = Field(default=False, alias="SEMANTIC_CACHE_ENABLED")
    semantic_cache_ttl_seconds: int = Field(default=3600, alias="SEMANTIC_CACHE_TTL_SECONDS")
    # Bem mais estrito que os ~0.7-0.8 típicos de recuperação em RAG: aqui um
    # falso positivo é uma resposta executada/exibida, não um trecho que um
    # humano ainda vai revisar antes de agir.
    semantic_cache_max_cosine_distance: float = Field(
        default=0.05, alias="SEMANTIC_CACHE_MAX_COSINE_DISTANCE"
    )
    # Fontes cujo veredito funciona como sinal de autorização (ex.: a revisão
    # de código do modo orchestra) — um veredito velho pra um diff diferente
    # é o mesmo risco de um tool_call trocado, então ficam de fora por padrão.
    semantic_cache_excluded_sources: list[str] = Field(
        default_factory=lambda: ["agent:code_review", "agent:pre_approval_review"],
        alias="SEMANTIC_CACHE_EXCLUDED_SOURCES",
    )

    # ── Compressão de contexto ──────────────────────────────────────────────
    compression_enabled: bool = Field(default=True, alias="COMPRESSION_ENABLED")
    # Desligue para medir: comparar o custo com e sem roteamento por
    # complexidade é a única forma de saber se ele está ajudando neste uso.
    complexity_routing_enabled: bool = Field(default=True, alias="COMPLEXITY_ROUTING_ENABLED")

    # ── Contexto / indexação ────────────────────────────────────────────────
    # Dimensão do vetor de embedding. Mudar exige migração: o índice HNSW do
    # pgvector é criado sobre uma coluna de dimensão fixa. 768 = nomic-embed-text.
    embedding_dim: int = Field(default=768, alias="EMBEDDING_DIM")
    embedding_profile: str = Field(default="embedding", alias="EMBEDDING_PROFILE")
    embedding_batch_size: int = Field(default=32, alias="EMBEDDING_BATCH_SIZE")
    # Prefixos assimétricos (`search_query:` / `search_document:`) declarados por
    # modelo em providers.yaml. Desligado por padrão de propósito: ligar muda o
    # espaço vetorial, e o índice existente vira legado. A troca é segura —
    # a etiqueta de proveniência ganha `#prefixed` e o filtro do ADR 0017 tira os
    # vetores antigos do ramo vetorial sozinho — mas até reindexar a busca cai
    # para as pernas lexicais. É rollout em dois passos, decidido por quem opera.
    embedding_prefixes_enabled: bool = Field(default=False, alias="EMBEDDING_PREFIXES_ENABLED")
    # `validate_catalog` já desabilita o modelo de embedding com dimensão
    # incompatível. Ligado, o boot também falha em vez de subir degradado —
    # o que se quer em produção, onde subir sem embedding é subir sem RAG.
    catalog_strict: bool = Field(default=False, alias="ELTANIX_CATALOG_STRICT")
    # `hnsw.ef_search` por query de busca. O default do pgvector (40) é baixo
    # para um pool de 50 candidatos: o índice devolve menos vizinhos do que a
    # fusão RRF pede, e a metade vetorial chega truncada. Custa latência, então
    # é ajuste por deployment, medido pelo `eltanix-eval-rag`.
    hnsw_ef_search: int = Field(default=100, alias="HNSW_EF_SEARCH")
    # Reaper que reindexa workspaces com embedding pendente (arquivos marcados
    # `pendente:<hash>` porque o modelo estava fora do ar). 0 desliga.
    embedding_backfill_interval_seconds: int = Field(
        default=1800, alias="EMBEDDING_BACKFILL_INTERVAL_SECONDS"
    )
    # Git-Aware RAG (Fase 4 do Git Intelligence): `search_code` expande os hits
    # por vizinhança no Code Knowledge Graph e re-rankeia por recência/co-mudança
    # do git. Degrada para o hybrid_search puro sem grafo/git. Off = só RRF.
    context_git_aware_search: bool = Field(default=True, alias="CONTEXT_GIT_AWARE_SEARCH")

    # ── Camada de recuperação (`retrieval/`, ADR 0019) ──────────────────────
    # Kill switch da camada inteira. Desligada, quem chama volta ao caminho
    # antigo (`IndexerService.search` direto) — que continua existindo e
    # funcionando, justamente para que desligar isto seja possível.
    retrieval_enabled: bool = Field(default=True, alias="RETRIEVAL_ENABLED")
    # Candidatos pedidos a cada fonte antes da fusão. Maior que o `limit` final
    # de propósito: rerank e MMR precisam de material para escolher, e um pool
    # do tamanho do resultado transforma as duas etapas em no-op.
    retrieval_candidate_pool: int = Field(default=50, alias="RETRIEVAL_CANDIDATE_POOL")
    # Quantos candidatos da lista fundida entram na chamada do reranker.
    retrieval_rerank_candidates: int = Field(default=40, alias="RETRIEVAL_RERANK_CANDIDATES")
    # Fator de sobreamostragem entre rerank e MMR: o reranker devolve
    # `limit × isto` para o MMR ter o que diversificar.
    retrieval_oversample: int = Field(default=3, alias="RETRIEVAL_OVERSAMPLE")
    retrieval_rerank_enabled: bool = Field(default=True, alias="RETRIEVAL_RERANK_ENABLED")
    # Expansão só dispara em pergunta curta e sem identificador citado (ver
    # `retrieval/query.py::should_expand`), então ligada por padrão ela não
    # cobra latência da busca típica do agente, que cita nome de símbolo.
    retrieval_expansion_enabled: bool = Field(default=True, alias="RETRIEVAL_EXPANSION_ENABLED")
    # HyDE desligado por padrão: paga uma chamada em *toda* busca (não tem
    # heurística de porta como a expansão) e o ganho depende do corpus.
    # Ligar é decisão medida pelo `eltanix-eval-rag`.
    retrieval_hyde_enabled: bool = Field(default=False, alias="RETRIEVAL_HYDE_ENABLED")
    retrieval_max_variants: int = Field(default=3, alias="RETRIEVAL_MAX_VARIANTS")
    retrieval_documents_enabled: bool = Field(default=True, alias="RETRIEVAL_DOCUMENTS_ENABLED")
    retrieval_notes_enabled: bool = Field(default=True, alias="RETRIEVAL_NOTES_ENABLED")
    # Perfil usado por expansão, HyDE e rerank. Perfil, não modelo: a escolha do
    # modelo é do `routes.yaml`, nunca de constante no código (ADR 0001).
    retrieval_utility_profile: str = Field(default="utility", alias="RETRIEVAL_UTILITY_PROFILE")
    # Orçamento de tokens do bloco de contexto montado pelo empacotador.
    retrieval_token_budget: int = Field(default=6000, alias="RETRIEVAL_TOKEN_BUDGET")
    # λ do MMR: 1.0 = só relevância (MMR vira no-op), 0.0 = só diversidade.
    retrieval_mmr_lambda: float = Field(default=0.7, alias="RETRIEVAL_MMR_LAMBDA")
    # Pesos das pernas dentro de cada fonte, repassados ao SQL dos stores, e o
    # `k` do RRF. São os parâmetros que as evals afinam (item 8 da revisão) —
    # por isso saíram de constante de módulo para configuração.
    retrieval_weight_vector: float = Field(default=1.0, alias="RETRIEVAL_WEIGHT_VECTOR")
    retrieval_weight_text: float = Field(default=1.0, alias="RETRIEVAL_WEIGHT_TEXT")
    retrieval_weight_trigram: float = Field(default=0.5, alias="RETRIEVAL_WEIGHT_TRIGRAM")
    retrieval_rrf_k: int = Field(default=60, alias="RETRIEVAL_RRF_K")
    # Peso de cada fonte na fusão entre fontes. Código pesa mais numa IDE.
    retrieval_source_weight_context: float = Field(
        default=1.0, alias="RETRIEVAL_SOURCE_WEIGHT_CONTEXT"
    )
    retrieval_source_weight_documents: float = Field(
        default=0.7, alias="RETRIEVAL_SOURCE_WEIGHT_DOCUMENTS"
    )
    retrieval_source_weight_notes: float = Field(default=0.7, alias="RETRIEVAL_SOURCE_WEIGHT_NOTES")

    # ── Autocompletar inline / ghost text (Onda 1.1, ADR 0014) ──────────────
    # Kill switch: desligado, `POST /api/context/completions` responde 204 e o
    # provider do Monaco não registra nada. Falha de modelo já degrada para
    # completion vazia — isto é para desligar o recurso inteiro sem deploy.
    ide_inline_completions_enabled: bool = Field(
        default=True, alias="IDE_INLINE_COMPLETIONS_ENABLED"
    )
    # Perfil de rota que responde o autocompletar. `completion` (routes.yaml) é
    # ordenado por latência com modelo local à frente; trocar para `fast` ou um
    # id concreto é ajuste de .env, não de código (ADR 0014 §2).
    ide_completion_profile: str = Field(default="completion", alias="IDE_COMPLETION_PROFILE")
    # Teto de chamadas de autocompletar por ator por minuto. Ghost text dispara
    # muito mais que o Cmd+K (20/min), daí o teto mais alto. Redis fora → não
    # limita (degrada, não derruba).
    ide_completion_max_per_minute: int = Field(default=120, alias="IDE_COMPLETION_MAX_PER_MINUTE")

    # ── Predição do próximo edit / "tab to jump" (Onda 1.2, ADR 0015) ───────
    # Kill switch: desligado, `POST /api/context/next-edit` responde 204 e o
    # editor não arma a regra de Tab. Candidato a `false` se a taxa de
    # aceitação (medida por `kind` em completion_event) não compensar o custo.
    ide_next_edit_enabled: bool = Field(default=True, alias="IDE_NEXT_EDIT_ENABLED")
    # Perfil de rota do next-edit. `next-edit` (routes.yaml) é mais capaz que o
    # `completion` e mais rápido que o `coding`. Ajuste de .env, não de código.
    ide_next_edit_profile: str = Field(default="next-edit", alias="IDE_NEXT_EDIT_PROFILE")
    # Teto por ator por minuto. Dispara por edição assentada, bem menos que o
    # autocompletar por tecla. Redis fora → não limita.
    ide_next_edit_max_per_minute: int = Field(default=40, alias="IDE_NEXT_EDIT_MAX_PER_MINUTE")

    # ── Roteamento automático de skills (Fase 1 do upgrade do agente) ────────
    # Similaridade de cosseno mínima (0..1) para uma skill entrar no system
    # prompt por roteamento automático, e quantas skills no máximo. O default
    # 0.72 foi calibrado à mão; expor por env permite ajustar por deployment
    # sem editar código, e o log `skills.routing.near_miss` mostra os
    # candidatos que ficaram logo abaixo do corte para orientar o ajuste.
    agent_skill_routing_min_score: float = Field(
        default=0.72, alias="AGENT_SKILL_ROUTING_MIN_SCORE"
    )
    agent_skill_routing_top_k: int = Field(default=2, alias="AGENT_SKILL_ROUTING_TOP_K")

    # ── Projetos ────────────────────────────────────────────────────────────
    # Pasta que contém os projetos editáveis, como este processo a enxerga.
    # É a fronteira: nada fora dela é alcançável pelo IDE ou pelo agente.
    projects_root: Path | None = Field(default=None, alias="PROJECTS_ROOT")
    # O mesmo caminho visto pelo host. Só é necessário quando a API roda em
    # container: o daemon do Docker resolve bind mounts contra o host.
    projects_root_host: str = Field(default="", alias="PROJECTS_ROOT_HOST")
    # Compatibilidade com a configuração de projeto único anterior.
    workspace_root: Path | None = Field(default=None, alias="WORKSPACE_ROOT")

    @property
    def effective_projects_root(self) -> Path | None:
        """Raiz de projetos, caindo para o antigo WORKSPACE_ROOT se preciso."""
        if self.projects_root is not None:
            return self.projects_root
        # Um WORKSPACE_ROOT antigo aponta para um projeto, não para a pasta que
        # os contém; tratamos o pai como raiz para não quebrar quem já usava.
        return self.workspace_root.parent if self.workspace_root else None

    # ── Sandbox de execução ─────────────────────────────────────────────────
    sandbox_image: str = Field(default="python:3.12-slim", alias="SANDBOX_IMAGE")
    sandbox_memory: str = Field(default="2g", alias="SANDBOX_MEMORY")
    sandbox_timeout_seconds: int = Field(default=300, alias="SANDBOX_TIMEOUT_SECONDS")
    # Rede desligada por padrão: impede exfiltrar código e impede baixar e
    # executar algo de origem desconhecida. Ligue só quando precisar instalar
    # dependências, e prefira fazê-lo por uma imagem preparada.
    sandbox_network: bool = Field(default=False, alias="SANDBOX_NETWORK")
    # Teto de sandboxes ativos ao mesmo tempo neste host/executor (Horizonte 3
    # da auditoria arquitetural — fila local, sem infraestrutura nova; ver
    # sandbox/concurrency.py). Sessão além do teto espera na fila em vez de
    # competir por CPU/memória com as já ativas. Default generoso o bastante
    # para não travar o fluxo de dev atual, que hoje roda efetivamente sem teto.
    sandbox_max_concurrent: int = Field(default=6, alias="SANDBOX_MAX_CONCURRENT")
    # Quando definido, a execução vai pelo serviço executor em vez do daemon
    # local. É o modo usado quando a própria API roda em container: só o
    # executor tem acesso ao socket do Docker (ver ADR 0002).
    executor_url: str = Field(default="", alias="EXECUTOR_URL")
    executor_token: str = Field(default="", alias="EXECUTOR_TOKEN")

    # ── Orquestração multiagente (ver ADR 0004) ────────────────────────────
    # Tetos contra fork-bomb — cada `spawn_agent` cria worktree+sandbox+
    # checkpoint de verdade, então o limite fica aqui, não só na cota de USD
    # do BudgetGuard (que não sabe nada sobre quantidade de sessões paralelas).
    agent_max_children_per_agent: int = Field(default=4, alias="AGENT_MAX_CHILDREN_PER_AGENT")
    agent_max_spawn_depth: int = Field(default=3, alias="AGENT_MAX_SPAWN_DEPTH")
    # Teto pro `timeout_seconds` que o modelo pedir em `wait_for_agents` — sem
    # isto uma chamada de ferramenta poderia travar o turno (e a conexão SSE,
    # se for humano dirigindo) por tempo arbitrário.
    agent_wait_max_seconds: float = Field(default=300.0, alias="AGENT_WAIT_MAX_SECONDS")
    # TTL deslizante do estado de coordenação no Redis (status, inbox, árvore
    # pai/filho) — renovado a cada operação. Não é a fonte de verdade de "esse
    # agente existiu" (isso é o Postgres/checkpoint), só da coordenação ativa.
    agent_coordination_ttl_seconds: int = Field(
        default=21_600, alias="AGENT_COORDINATION_TTL_SECONDS"
    )
    # Uma aba fechada sem `close_session` explícito deixa `AgentSessionRecord.
    # status` em "open" para sempre — sem essa varredura periódica a listagem
    # de "sessões ativas" acumula ruído indefinidamente (achado na auditoria
    # arquitetural, ver docs/proposals/plano-implementacao-auditoria-arquitetural.md).
    agent_session_abandon_after_hours: int = Field(
        default=24, alias="AGENT_SESSION_ABANDON_AFTER_HOURS"
    )
    # Retenção dos snapshots de arquivo do rewind (Fase 8). A tabela
    # `session_file_snapshot` cresce a cada escrita de toda sessão e só serve
    # à janela de rewind da própria sessão — um reaper poda o que passou disso.
    agent_snapshot_retention_days: int = Field(default=14, alias="AGENT_SNAPSHOT_RETENTION_DAYS")

    # ── Navegador para verificação visual (Fase 7) ──────────────────────────
    # Serviço à parte, numa rede restrita própria (ver docker-compose.yml,
    # `browser_net`) — o sandbox de execução acima continua sem rede nenhuma.
    # Vazio faz a ferramenta responder "indisponível" (mesmo padrão de
    # `run_command` sem sandbox), não desregistra nada.
    browser_url: str = Field(default="", alias="BROWSER_URL")
    browser_token: str = Field(default="", alias="BROWSER_TOKEN")

    # ── Scanner de Segurança MCP (Cisco AI Defense) ─────────────────────────
    mcp_scanner_url: str = Field(default="", alias="MCP_SCANNER_URL")
    mcp_scanner_api_key: str = Field(default="", alias="MCP_SCANNER_API_KEY")

    # ── Segurança / Classificador SecureBERT ────────────────────────────────
    # Quando True, o SecureBertService ativa o modelo neural real HuggingFace
    # (ehsanaghaei/SecureBERT) se transformers/torch estiverem instalados.
    # Quando False, utiliza o analisador heurístico veloz sem carregar pesos.
    securebert_model_enabled: bool = Field(default=False, alias="SECUREBERT_MODEL_ENABLED")

    # ── Armazenamento de blobs (documentos do RAG) ──────────────────────────
    # Visto pelo processo da API — dentro do compose é `minio:9000`.
    minio_endpoint: str = Field(default="localhost:5407", alias="MINIO_ENDPOINT")
    # Visto pelo browser, para URLs pré-assinadas de upload/download. Vazio cai
    # para `minio_endpoint` — só diverge quando a API roda em container.
    minio_public_endpoint: str = Field(default="", alias="MINIO_PUBLIC_ENDPOINT")
    minio_access_key: str = Field(default="minioadmin", alias="MINIO_ACCESS_KEY")
    minio_secret_key: str = Field(default="minioadmin", alias="MINIO_SECRET_KEY")
    minio_secure: bool = Field(default=False, alias="MINIO_SECURE")
    minio_documents_bucket: str = Field(default="eltanix-documents", alias="MINIO_DOCUMENTS_BUCKET")

    @property
    def effective_minio_public_endpoint(self) -> str:
        return self.minio_public_endpoint or self.minio_endpoint

    # ── Documentos (RAG) ─────────────────────────────────────────────────────
    documents_max_upload_mb: int = Field(default=25, alias="DOCUMENTS_MAX_UPLOAD_MB")
    documents_chunk_tokens: int = Field(default=512, alias="DOCUMENTS_CHUNK_TOKENS")
    documents_chunk_overlap_tokens: int = Field(default=64, alias="DOCUMENTS_CHUNK_OVERLAP_TOKENS")

    # ── Credenciais de provedores ───────────────────────────────────────────
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")

    azure_api_base: str = Field(default="", alias="AZURE_API_BASE")
    azure_api_key: str = Field(default="", alias="AZURE_API_KEY")
    azure_api_version: str = Field(default="2024-10-21", alias="AZURE_API_VERSION")
    azure_ai_api_base: str = Field(default="", alias="AZURE_AI_API_BASE")
    azure_ai_api_key: str = Field(default="", alias="AZURE_AI_API_KEY")
    azure_use_entra_id: bool = Field(default=False, alias="AZURE_USE_ENTRA_ID")

    databricks_host: str = Field(default="", alias="DATABRICKS_HOST")
    databricks_token: str = Field(default="", alias="DATABRICKS_TOKEN")

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")

    github_token: str = Field(default="", alias="GITHUB_TOKEN")

    # ── Firecrawl (Web Scraping / Crawling / Search para RAG e Agente) ───────
    firecrawl_api_key: str = Field(default="", alias="FIRECRAWL_API_KEY")
    firecrawl_api_url: str = Field(default="https://api.firecrawl.dev", alias="FIRECRAWL_API_URL")

    # ── Observabilidade (Langfuse) ─────────────────────────────────────────
    langfuse_public_key: str = Field(default="", alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str = Field(default="", alias="LANGFUSE_SECRET_KEY")
    langfuse_host: str = Field(default="https://cloud.langfuse.com", alias="LANGFUSE_HOST")
    langfuse_enabled: bool = Field(default=True, alias="LANGFUSE_ENABLED")

    cors_origins: list[str] = Field(
        default=[
            "http://localhost:5400",
            "http://127.0.0.1:5400",
            "http://localhost:5409",
            "http://127.0.0.1:5409",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        alias="CORS_ORIGINS",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> list[str]:
        if isinstance(value, str):
            val_str = value.strip()
            if val_str.startswith("[") and val_str.endswith("]"):
                import json

                try:
                    res = json.loads(val_str)
                    if isinstance(res, list):
                        return [str(x) for x in res]
                except Exception:
                    pass
            return [item.strip() for item in val_str.split(",") if item.strip()]
        if isinstance(value, list):
            return [str(x) for x in value]
        return [
            "http://localhost:5400",
            "http://127.0.0.1:5400",
            "http://localhost:5409",
            "http://127.0.0.1:5409",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]

    @field_validator("cors_origins", mode="after")
    @classmethod
    def _sanitize_origins(cls, origins: list[str]) -> list[str]:
        """`main.py` monta o CORS com `allow_credentials=True`. Combinado com
        `*` isso seria uma API autenticada aberta a qualquer site — o Starlette
        já se recusa a mandar `Allow-Credentials` junto com `*`, mas o pior
        caso real é uma origem pública na lista. Então: `*` é sempre descartado,
        e origem não-loopback só passa com um aviso alto (F-3 da revisão de
        segurança)."""
        import warnings

        limpos: list[str] = []
        for origem in origins:
            o = origem.strip()
            if not o or o == "*":
                if o == "*":
                    warnings.warn(
                        "CORS_ORIGINS continha '*' — descartado (incompatível com "
                        "allow_credentials). Liste origens explícitas.",
                        stacklevel=2,
                    )
                continue
            host = o.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0].lower()
            if host not in {"localhost", "127.0.0.1", "::1", "[::1]"}:
                warnings.warn(
                    f"CORS_ORIGINS inclui origem não-loopback {o!r} com "
                    "allow_credentials=True — confirme que é intencional.",
                    stacklevel=2,
                )
            limpos.append(o)
        return limpos

    @property
    def env_file_path(self) -> Path:
        """`.env` da raiz — mesmo arquivo que o `env_file` acima já carrega.

        Existe como propriedade porque quem *escreve* de volta (a tela de
        credenciais) precisa do caminho sem duplicar `REPO_ROOT` espalhado.
        """
        return self.env_file_override or (REPO_ROOT / ".env")

    @property
    def providers_file(self) -> Path:
        return self.config_dir / "providers.yaml"

    @property
    def routes_file(self) -> Path:
        return self.config_dir / "routes.yaml"

    @property
    def pricing_file(self) -> Path:
        return self.config_dir / "pricing.yaml"

    @property
    def mcp_config_file(self) -> Path:
        return self.config_dir / "mcp.yaml"

    @property
    def mcp_catalog_file(self) -> Path:
        return self.config_dir / "mcp_catalog.yaml"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
