"""Configuração da aplicação, carregada de variáveis de ambiente e do `.env` da raiz."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# .../apps/api/src/sicoobito/config.py -> raiz do repositório
REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", Path(".env")),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Núcleo ──────────────────────────────────────────────────────────────
    api_key: str = Field(default="", alias="SICOOBITO_API_KEY")
    log_level: str = Field(default="INFO", alias="SICOOBITO_LOG_LEVEL")
    log_json: bool = Field(default=False, alias="SICOOBITO_LOG_JSON")
    config_dir: Path = Field(default=REPO_ROOT / "config", alias="SICOOBITO_CONFIG_DIR")

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

    # ── Contexto / indexação ────────────────────────────────────────────────
    # Dimensão do vetor de embedding. Mudar exige migração: o índice HNSW do
    # pgvector é criado sobre uma coluna de dimensão fixa. 768 = nomic-embed-text.
    embedding_dim: int = Field(default=768, alias="EMBEDDING_DIM")
    embedding_profile: str = Field(default="embedding", alias="EMBEDDING_PROFILE")
    embedding_batch_size: int = Field(default=32, alias="EMBEDDING_BATCH_SIZE")
    workspace_root: Path | None = Field(default=None, alias="WORKSPACE_ROOT")

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

    github_token: str = Field(default="", alias="GITHUB_TOKEN")

    # ── CORS ────────────────────────────────────────────────────────────────
    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"],
        alias="CORS_ORIGINS",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def providers_file(self) -> Path:
        return self.config_dir / "providers.yaml"

    @property
    def routes_file(self) -> Path:
        return self.config_dir / "routes.yaml"

    @property
    def pricing_file(self) -> Path:
        return self.config_dir / "pricing.yaml"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
