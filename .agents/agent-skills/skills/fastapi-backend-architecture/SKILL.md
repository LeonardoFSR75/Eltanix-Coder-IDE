---
name: fastapi-backend-architecture
description: Padrões de arquitetura, rotas modulares, injeção de dependências e banco de dados assíncrono para projetos FastAPI.
---

# FastAPI Backend Architecture & Engineering Guide

Este guia estabelece os padrões e a estrutura de pastas recomendada para o desenvolvimento de APIs modernas, robustas e performáticas com FastAPI no ecossistema Eltanix Coder IDE.

---

## 1. Estrutura Canônica de Diretórios

```
meu-projeto/
├── app/
│   ├── __init__.py
│   ├── main.py                  # Ponto de entrada da aplicação FastAPI
│   ├── config.py                # Configurações com Pydantic Settings / .env
│   ├── dependencies.py          # Injeção de dependências (Auth, DB session)
│   ├── routers/                 # Endpoints organizados por domínio
│   │   ├── __init__.py
│   │   ├── health.py
│   │   ├── auth.py
│   │   └── items.py
│   ├── models/                  # Entidades de banco de dados (SQLAlchemy / SQLModel)
│   │   ├── __init__.py
│   │   └── item.py
│   ├── schemas/                 # Modelos Pydantic para validação de entrada/saída
│   │   ├── __init__.py
│   │   └── item.py
│   ├── services/                # Regras de negócio desacopladas
│   │   └── item_service.py
│   └── templates/               # (Opcional) Jinja2 templates se houver SSR
│   └── static/                  # (Opcional) CSS / JS estáticos
├── tests/                       # Testes automatizados com pytest e httpx AsyncClient
│   ├── conftest.py
│   └── test_items.py
├── requirements.txt             # Dependências pinadas (fastapi, uvicorn, pydantic, etc.)
└── README.md
```

---

## 2. Padrões de Implementação

### 2.1 Ponto de Entrada (`app/main.py`)
```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import items, health

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: inicializa conexões e pools
    yield
    # Shutdown: fecha pools e recursos

app = FastAPI(
    title="Minha API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(items.router, prefix="/api/v1/items", tags=["items"])
```

### 2.2 Schemas Pydantic v2 (`app/schemas/item.py`)
```python
from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime

class ItemBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    price: float = Field(..., gt=0)

class ItemCreate(ItemBase):
    pass

class ItemResponse(ItemBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
```

---

## 3. Boas Práticas
- Utilize sempre `async def` para rotas que realizam I/O (banco de dados, chamadas HTTP externas).
- Não faça queries diretas ou regras de negócio dentro dos routers; isole em `services/`.
- Use `HTTPException` com status codes semânticos (`400`, `404`, `422`, etc.).
- Valide inputs sempre via schemas Pydantic tipados.
