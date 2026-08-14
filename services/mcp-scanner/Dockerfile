FROM python:3.13-slim-bookworm

# Instala dependências de sistema essenciais e Node.js LTS (necessário para rodar MCPs stdio via npx)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Instala uv e cisco-ai-mcp-scanner
RUN pip install --no-cache-dir uv && \
    uv pip install --system --no-cache cisco-ai-mcp-scanner

# Copia script de entrada
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENV PYTHONUNBUFFERED=1
ENV PATH="/root/.local/bin:${PATH}"

# Porta padrão para o modo servidor REST API
EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["--help"]
