FROM node:22-slim

WORKDIR /app

# Dependências antes do código, pelo mesmo motivo da imagem da API.
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .

ENV NEXT_TELEMETRY_DISABLED=1 \
    PORT=5400

EXPOSE 5400

CMD ["npm", "run", "dev"]
