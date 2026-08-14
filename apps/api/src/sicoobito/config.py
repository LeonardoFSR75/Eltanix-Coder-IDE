"""Configuração da aplicação, carregada de variáveis de ambiente e do `.env` da raiz."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_repo_root() -> Path:
    """Raiz que contém `config/`, procurando para cima.

    Contar níveis fixos (`parents[4]`) só funciona no layout do checkout: numa
    imagem Docker o pacote fica em `/app/src/sicoobito`, que não tem cinco
    níveis acima, e a contagem estoura com IndexError no import.
    """
    aqui = Path(__file__).resolve()
    for candidato in aqui.parents:
        if (candidato / "config" / "providers.yaml").exists():
            return candidato
    # Sem `config/` em lugar nenhum, resta um palpite razoável; quem manda de
    # verdade nesse caso é SICOOBITO_CONFIG_DIR.
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
    api_key: str = Field(default="", alias="SICOOBITO_API_KEY")
    # Usuário único do login (etapa 1 — ver `auth/service.py`). Sem senha
    # definida, o lifespan gera uma aleatória e loga uma vez: login continua
    # obrigatório, só a senha do primeiro acesso fica no log em vez do `.env`.
    admin_username: str = Field(default="admin", alias="SICOOBITO_ADMIN_USERNAME")
    admin_password: str = Field(default="", alias="SICOOBITO_ADMIN_PASSWORD")
    log_level: str = Field(default="INFO", alias="SICOOBITO_LOG_LEVEL")
    log_json: bool = Field(default=False, alias="SICOOBITO_LOG_JSON")
    config_dir: Path = Field(default=REPO_ROOT / "config", alias="SICOOBITO_CONFIG_DIR")
    # Só para testes/deploys incomuns redirecionarem onde a tela de
    # credenciais escreve; no dia a dia o padrão (`.env` da raiz) já basta.
    env_file_override: Path | None = Field(default=None, alias="SICOOBITO_ENV_FILE")

    # ── Infra ───────────────────────────────────────────────────────────────
    database_url: str = Field(
        default="postgresql+asyncpg://sicoobito:sicoobito@localhost:5433/sicoobito",
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
    minio_documents_bucket: str = Field(
        default="sicoobito-documents", alias="MINIO_DOCUMENTS_BUCKET"
    )

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
