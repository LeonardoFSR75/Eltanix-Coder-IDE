# Imagem da API. O contexto de build é a raiz do repositório, para que
# `config/` entre junto.
FROM python:3.12-slim

# git é dependência de runtime, não de build: o agente cria worktrees e commita.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates gnupg \
    && rm -rf /var/lib/apt/lists/*

# Node existe aqui por um motivo só: os language servers. Quase todo LSP maduro
# (pyright inclusive) é distribuído como pacote npm.
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Instalados globais e fixados por versão: um servidor que muda de comportamento
# sozinho vira "o editor parou de completar" sem nenhuma mudança no repositório.
RUN npm install -g --no-audit --no-fund \
      pyright@1.1.413 \
      typescript@5.8.2 \
      typescript-language-server@6.0.0 \
      vscode-langservers-extracted@4.10.0 \
      yaml-language-server@1.24.0 \
      bash-language-server@5.6.0 \
      dockerfile-language-server-nodejs@0.15.0 \
    && npm cache clean --force


COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv

WORKDIR /app

# As dependências entram antes do código: mudar um arquivo-fonte não invalida
# a camada de instalação.
COPY apps/api/pyproject.toml apps/api/uv.lock apps/api/.python-version ./
RUN uv sync --frozen --no-install-project --extra azure --extra securebert

COPY apps/api/vendor ./vendor
RUN uv pip install --python /app/.venv/bin/python -e /app/vendor/securebert2

COPY apps/api/src ./src
COPY apps/api/alembic ./alembic
COPY apps/api/alembic.ini ./
COPY config ./config
RUN uv sync --frozen --extra azure --extra securebert
RUN uv pip install --python /app/.venv/bin/python -e /app/vendor/securebert2

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LITELLM_LOCAL_MODEL_COST_MAP=True \
    HF_HOME=/root/.cache/huggingface \
    ELTANIX_CONFIG_DIR=/app/config

# O git recusa operar num diretório de outro dono, e os projetos montados vêm
# do host com uid diferente.
RUN git config --system --add safe.directory '*'

EXPOSE 5401

# `--reload` aqui é deliberado: o compose monta o código do host, e o ciclo de
# desenvolvimento é o caso de uso desta imagem.
CMD ["uvicorn", "eltanix.main:app", "--host", "0.0.0.0", "--port", "5401", "--reload", "--reload-dir", "/app/src"]
