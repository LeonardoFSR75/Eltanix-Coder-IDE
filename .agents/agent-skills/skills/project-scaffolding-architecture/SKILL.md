---
name: project-scaffolding-architecture
description: Guia de arquitetura e estrutura de pastas canônicas para projetos Python (Flask, FastAPI), Node/Vue/React e Full-Stack no Eltanix Coder IDE.
category: architecture
---

# Estrutura e Scaffolding de Projetos - Eltanix Coder IDE

Ao criar novos projetos ou refatorar estruturas existentes, siga rigorosamente as convenções de diretórios por ecossistema:

## 1. Python + Flask (Web App / API)
```text
meu_projeto/
├── app.py                  # Ponto de entrada do Flask com rotas
├── requirements.txt        # Dependências do projeto (Flask, etc.)
├── templates/              # NUNCA coloque arquivos .html soltos na raiz
│   ├── base.html           # Layout base com header/footer/CDN
│   └── index.html          # Template renderizado via render_template()
├── static/
│   ├── css/
│   │   └── style.css       # Folhas de estilo customizadas
│   └── js/
│       └── main.js         # Scripts ou lógica do frontend
└── tests/
    └── test_app.py         # Testes automatizados (pytest)
```

## 2. Python + FastAPI
```text
meu_projeto/
├── main.py                 # Instância FastAPI e inclusão de routers
├── requirements.txt        # FastAPI, Uvicorn, Pydantic, etc.
├── app/
│   ├── routers/            # Endpoints segregados por domínio
│   ├── models/             # Schemas Pydantic e modelos
│   ├── templates/          # Jinja2Templates se houver UI
│   └── static/             # StaticFiles montados em /static
└── tests/
```

## 3. Node.js + Vue / Vite / React
```text
meu_projeto/
├── package.json
├── index.html              # Ponto de montagem da SPA (<div id="app">)
├── vite.config.js
└── src/
    ├── main.js             # Entrada do framework
    ├── App.vue             # Componente raiz
    ├── components/         # Componentes reutilizáveis
    └── assets/             # Imagens e estilos globais
```
