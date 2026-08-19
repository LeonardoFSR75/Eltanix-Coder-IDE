#!/usr/bin/env bash
set -e

echo "================================================="
echo "🚀 SicoobitoCode - Script de Instalação e Deploy"
echo "================================================="

if ! command -v docker &> /dev/null; then
    echo "❌ Erro: Docker não foi encontrado. Por favor instale o Docker primeiro."
    exit 1
fi

if ! docker compose version &> /dev/null; then
    echo "❌ Erro: Docker Compose plugin (docker compose) não foi encontrado."
    exit 1
fi

if [ ! -f .env ]; then
    echo "📄 Arquivo .env não encontrado. Criando a partir de .env.example..."
    cp .env.example .env
    echo "⚠️ Por favor revise as chaves e credenciais no arquivo .env!"
fi

echo "🐳 Construindo e iniciando os contêineres Docker..."
docker compose up -d --build

echo "🗄️ Executando migrações do banco de dados (Alembic)..."
docker compose exec -T api alembic upgrade head

echo "================================================="
echo "✅ Instalação concluída com sucesso!"
echo "🌐 Acesse a Web UI em: http://localhost:5400"
echo "================================================="
