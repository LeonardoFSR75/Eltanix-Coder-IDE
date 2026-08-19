# 🚀 Guia de Instalação e Deploy no Servidor — SicoobitoCode

Este pacote contém o código-fonte completo e as configurações de infraestrutura necessárias para instalar e executar o **SicoobitoCode** no servidor via Docker Compose.

---

## 📋 Pré-requisitos do Servidor

1. **Sistema Operacional**: Linux (Ubuntu 22.04 LTS / Debian 12 recomendado) ou Windows Server / macOS com Docker Desktop.
2. **Requisitos de Sistema**:
   - Mínimo: 4 vCPUs / 8 GB de RAM
   - Recomendado: 8 vCPUs / 16 GB de RAM ou superior
   - Disco: 20 GB livres (para imagens Docker e volumes Postgres/MinIO)
3. **Softwares Necessários**:
   - **Docker** (`>= 24.0.0`)
   - **Docker Compose** (`>= 2.20.0` - plugin `docker compose`)
   - **Git** e **Python 3** (opcional, para utilitários de suporte)

---

## ⚡ Passo a Passo de Instalação no Servidor

### 1. Descompactar o Pacote no Servidor

No seu servidor, crie um diretório para o projeto e descompacte o arquivo `.zip`:

```bash
mkdir -p /opt/sicoobitocode
cd /opt/sicoobitocode
unzip sicoobito_deploy.zip
```

---

### 2. Configurar Variáveis de Ambiente (`.env`)

Crie o arquivo `.env` a partir do modelo `.env.example`:

```bash
cp .env.example .env
```

Gere chaves seguras e defina os acessos no `.env`:

```bash
# Exemplo de geração de chaves randômicas no terminal
python3 -c "import secrets; print('SICOOBITO_API_KEY=' + secrets.token_urlsafe(32))"
python3 -c "import secrets; print('EXECUTOR_TOKEN=' + secrets.token_urlsafe(32))"
python3 -c "import secrets; print('AUTH_JWT_SECRET=' + secrets.token_urlsafe(32))"
```

Configure os principais valores no seu `.env`:
- `SICOOBITO_API_KEY`: Chave única de serviço para integrações externas (Cline, Cursor, Aider).
- `EXECUTOR_TOKEN`: Chave de autenticação do sandbox de execução.
- `AUTH_JWT_SECRET`: Segredo de assinatura de tokens de sessão.
- `SICOOBITO_ADMIN_USERNAME`: Usuário admin inicial da Web UI.
- `SICOOBITO_ADMIN_PASSWORD`: Senha admin inicial da Web UI.
- `OLLAMA_BASE_URL` ou Provedores Cloud (`OPENAI_API_KEY`, `AZURE_OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.): Conexão com os provedores de LLM desejados.

---

### 3. Subir os Contêineres Docker

Execute o build e suba todos os 11 microsserviços em segundo plano:

```bash
docker compose up -d --build
```

---

### 4. Executar Migrações do Banco de Dados

Suba a estrutura de tabelas do PostgreSQL executando o Alembic no contêiner da API:

```bash
docker compose exec api alembic upgrade head
```

---

### 5. Verificar a Saúde dos Serviços

Confira se todos os contêineres estão `Up` e `healthy`:

```bash
docker compose ps
```

Serão inicializados os seguintes serviços:
- `sicoobito-web` (Interface Web Next.js - Porta 5400)
- `sicoobito-api` (Backend FastAPI - Porta 5401)
- `sicoobito-postgres` (PostgreSQL com pgvector - Porta 5403)
- `sicoobito-redis` (Redis 7 - Porta 5404)
- `sicoobito-executor` (Sandbox de Execução Segura - Porta 5402)
- `sicoobito-browser` (Navegador CDP Headless - Porta 5406)
- `sicoobito-minio` (Armazenamento S3 Compatible - Porta 5407/5408)
- `sicoobito-desktop` (Motor Desktop VNC - Porta 5409)
- `sicoobito-mcp-scanner` (Scanner de Segurança MCP Cisco - Porta 5410)
- `sicoobito-lightpanda` (Browser Headless Ultrarrápido - Porta 9222)

---

## 🌐 Acesso à Aplicação

- **Interface Web**: `http://<IP-DO-SERVIDOR>:5400`
- **Documentação Swagger API**: `http://<IP-DO-SERVIDOR>:5401/docs`

---

## 🔄 Scripts Utilitários Inclusos

- `./scripts/install.sh`: Script automatizado bash para checagem de requisitos, cópia de `.env` e inicialização.
- `docker compose restart api web`: Reinicia serviços com alterações de configuração sem rebuild completo.
