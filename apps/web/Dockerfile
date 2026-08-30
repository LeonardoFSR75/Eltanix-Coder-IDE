FROM node:22-slim

WORKDIR /app

# Dependências antes do código, pelo mesmo motivo da imagem da API. `scripts/`
# entra aqui também: o `postinstall` do install chama `scripts/copy-monaco.mjs`,
# então o arquivo precisa existir antes do install rodar, não só depois do
# `COPY . .` de baixo.
# `npm install` (não `npm ci`): o package-lock.json do repo está fora de sync
# com o package.json e `npm ci` aborta nesse caso — mesmo motivo pelo qual os
# jobs de CI já usam `npm install` (commit 0a05762).
COPY package.json package-lock.json ./
COPY scripts ./scripts
RUN npm install --no-audit --no-fund --fetch-retries=5 --fetch-retry-mintimeout=20000 --fetch-retry-maxtimeout=120000

COPY . .

ENV NEXT_TELEMETRY_DISABLED=1 \
    PORT=5400

EXPOSE 5400

CMD ["npm", "run", "dev"]
