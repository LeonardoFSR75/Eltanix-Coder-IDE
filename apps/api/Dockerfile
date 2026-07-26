# Imagem da API. O contexto de build é a raiz do repositório, para que
# `config/` entre junto.
FROM python:3.12-slim

# git é dependência de runtime, não de build: o agente cria worktrees e commita.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv

WORKDIR /app

# As dependências entram antes do código: mudar um arquivo-fonte não invalida
# a camada de instalação.
COPY apps/api/pyproject.toml apps/api/uv.lock apps/api/.python-version ./
RUN uv sync --frozen --no-install-project --extra azure

COPY apps/api/src ./src
COPY apps/api/alembic ./alembic
COPY apps/api/alembic.ini ./
COPY config ./config
RUN uv sync --frozen --extra azure

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LITELLM_LOCAL_MODEL_COST_MAP=True \
    SICOOBITO_CONFIG_DIR=/app/config

# O git recusa operar num diretório de outro dono, e os projetos montados vêm
# do host com uid diferente.
RUN git config --system --add safe.directory '*'

EXPOSE 5401

# `--reload` aqui é deliberado: o compose monta o código do host, e o ciclo de
# desenvolvimento é o caso de uso desta imagem.
CMD ["uvicorn", "sicoobito.main:app", "--host", "0.0.0.0", "--port", "5401", "--reload", "--reload-dir", "/app/src"]
