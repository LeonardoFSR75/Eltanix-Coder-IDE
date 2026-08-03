from __future__ import annotations

import os

import certifi

os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from sicoobito.config import REPO_ROOT, Settings, get_settings
from sicoobito.router.catalog import load_catalog
from sicoobito.router.pricing import PriceTable

# O catálogo real é a melhor fixture disponível: se um teste quebra porque o
# providers.yaml mudou, é exatamente isso que se quer saber.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

# A suíte não pode depender do `.env` do desenvolvedor. Sem isto, um teste que
# afirma "modelo indisponível por faltar AZURE_API_BASE" passa numa máquina sem
# `.env` e falha na de quem já configurou o projeto — a suíte mediria o
# ambiente, não o código.
#
# Duas fontes precisam ser neutralizadas, e a segunda não é óbvia: além do
# `env_file` do pydantic, o **litellm chama `load_dotenv()` no import** e
# despeja o `.env` inteiro em `os.environ`. Por isso ele é importado aqui de
# propósito, antes da limpeza — deixar para depois faria as variáveis
# reaparecerem no primeiro módulo que importasse o router.
Settings.model_config["env_file"] = None

import litellm  # noqa: E402, F401 — importado cedo: ver comentário acima

_CREDENCIAIS_DE_PROVEDOR = (
    "AZURE_API_BASE",
    "AZURE_API_KEY",
    "AZURE_AI_API_BASE",
    "AZURE_AI_API_KEY",
    "DATABRICKS_HOST",
    "DATABRICKS_TOKEN",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GITHUB_TOKEN",
    "WORKSPACE_ROOT",
)
for _nome in _CREDENCIAIS_DE_PROVEDOR:
    os.environ.pop(_nome, None)

get_settings.cache_clear()


CONFIG_DIR = REPO_ROOT / "config"


@pytest.fixture
def catalog():
    return load_catalog(CONFIG_DIR / "providers.yaml", CONFIG_DIR / "routes.yaml")


@pytest.fixture
def prices():
    return PriceTable.load(CONFIG_DIR / "pricing.yaml")


@pytest.fixture
async def pg_session():
    """Sessão real contra Postgres, isolada por transação com rollback no
    teardown — cada teste escreve de verdade no banco e some sozinho, sem
    precisar de schema/banco descartável nem de rodar migração por teste (as
    funções de `store.py` só pedem um `AsyncSession`, não `session_scope()` —
    encaixa aqui sem mudar nada nelas).

    Pulado por padrão: só ativa com `DATABASE_URL_TEST` definida (ver
    `apps/api/CLAUDE.md` para o comando de migração local, rodado uma vez, não
    a cada teste). Mantém o `pytest tests -q` do dia a dia rápido e sem
    depender de Postgres no ar — mudança de categoria explícita, não descuido
    (mesmo espírito documentado em `test_indexing_pipeline.py`).
    """
    url = os.environ.get("DATABASE_URL_TEST")
    if not url:
        pytest.skip("DATABASE_URL_TEST não definida — teste de integração com Postgres pulado")

    engine = create_async_engine(url)
    async with engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()
    await engine.dispose()
