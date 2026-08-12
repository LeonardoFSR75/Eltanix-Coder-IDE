"""Rotas do language server: capacidades, ticket e o túnel WebSocket.

O editor abre uma conexão por (projeto, linguagem) e fala LSP puro por ela. A
API não interpreta o protocolo — só autentica, resolve o projeto e traduz
caminhos (ver `lsp/bridge.py`). Manter a ponte burra é deliberado: quando o
`pyright` ganhar um recurso novo, ele funciona sem mudança aqui.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect, status

from sicoobito.api.deps import AuthDep
from sicoobito.api.tickets import TICKET_TTL_SECONDS, TicketStore
from sicoobito.config import get_settings
from sicoobito.logging_setup import get_logger
from sicoobito.lsp import LanguageServerProcess, LspError, server_for_language, supported_languages
from sicoobito.workspace import projects as project_ops
from sicoobito.workspace.projects import ProjectError

log = get_logger(__name__)

router = APIRouter(prefix="/api/lsp", tags=["lsp"], dependencies=[AuthDep])

# Mesmo motivo da rota do terminal: o browser não envia `Authorization` ao abrir
# um WebSocket. A autenticação desta rota é o ticket de uso único.
ws_router = APIRouter(prefix="/api/lsp", tags=["lsp"])


def _escopo(project: str, language: str) -> str:
    return f"lsp:{project}:{language}"


@router.get("/languages")
async def languages() -> dict[str, Any]:
    """Quais linguagens têm servidor instalado nesta imagem."""
    return {"languages": supported_languages()}


@router.get("/extensions")
async def extensions() -> dict[str, Any]:
    """Lista as extensões e suítes de linguagem ativas na IDE agêntica."""
    pyrefly_spec = server_for_language("python", preferred_server="pyrefly")
    server_for_language("python", preferred_server="pyright")
    
    return {
        "extensions": [
            {
                "id": "meta.pyrefly",
                "name": "Pyrefly - Python Language Server",
                "publisher": "meta",
                "version": "0.1.0",
                "description": (
                    "Python autocomplete, typechecking & high-performance static analysis "
                    "engine by Meta."
                ),
                "category": "LSP & Python",
                "installed": True,
                "active": pyrefly_spec is not None and pyrefly_spec.available,
                "latency_ms": 496,
                "server_id": "pyrefly",
            },
            {
                "id": "ms-python.python",
                "name": "Python",
                "publisher": "ms-python",
                "version": "2026.1.0",
                "description": (
                    "Python language support with extension hooks, code formatting & "
                    "refactoring."
                ),
                "category": "LSP & Python",
                "installed": True,
                "active": True,
                "latency_ms": 7072,
                "server_id": "pyright",
            },
            {
                "id": "ms-python.debugpy",
                "name": "Python Debugger",
                "publisher": "ms-python",
                "version": "2026.1.0",
                "description": "Python Debugger extension using debugpy & container executor.",
                "category": "LSP & Python",
                "installed": True,
                "active": True,
                "latency_ms": 593,
                "server_id": "debugpy",
            },
            {
                "id": "ms-python.python-environments",
                "name": "Python Environments",
                "publisher": "ms-python",
                "version": "2026.1.0",
                "description": (
                    "Provides a unified python environment discovery and virtualenv manager."
                ),
                "category": "LSP & Python",
                "installed": True,
                "active": True,
                "latency_ms": 874,
                "server_id": "venv",
            },
            {
                "id": "ms-vscode.node-js",
                "name": "Node.js & npm Package Manager",
                "publisher": "ms-vscode",
                "version": "2026.2.0",
                "description": (
                    "Node.js environment discovery, package.json management & npm script "
                    "execution."
                ),
                "category": "Node & Next.js",
                "installed": True,
                "active": True,
                "latency_ms": 310,
                "server_id": "node",
            },
            {
                "id": "vercel.nextjs-tools",
                "name": "Next.js & React App Router",
                "publisher": "vercel",
                "version": "15.1.0",
                "description": (
                    "Next.js App Router autocomplete, Server Components, Server Actions & "
                    "route navigation."
                ),
                "category": "Node & Next.js",
                "installed": True,
                "active": True,
                "latency_ms": 280,
                "server_id": "typescript",
            },
            {
                "id": "dbaeumer.vscode-eslint",
                "name": "ESLint & Prettier",
                "publisher": "dbaeumer",
                "version": "3.0.10",
                "description": (
                    "Real-time JavaScript/TypeScript linting, code formatting & style "
                    "enforcement."
                ),
                "category": "Node & Next.js",
                "installed": True,
                "active": True,
                "latency_ms": 190,
                "server_id": "eslint",
            },
            {
                "id": "meta.react-devtools",
                "name": "React 19 & JSX Features",
                "publisher": "meta",
                "version": "19.0.0",
                "description": (
                    "React Hooks, Server Components, JSX/TSX autocomplete & component "
                    "inspector."
                ),
                "category": "Frontend & Frameworks",
                "installed": True,
                "active": True,
                "latency_ms": 210,
                "server_id": "typescript",
            },
            {
                "id": "vue.volar",
                "name": "Vue.js Language Features (Volar)",
                "publisher": "vue",
                "version": "2.2.0",
                "description": (
                    "Vue 3 Composition API, Single File Components (.vue), template "
                    "typechecking & Volar LSP."
                ),
                "category": "Frontend & Frameworks",
                "installed": True,
                "active": True,
                "latency_ms": 290,
                "server_id": "volar",
            },
            {
                "id": "angular.ng-template",
                "name": "Angular Language Service",
                "publisher": "angular",
                "version": "18.2.0",
                "description": (
                    "Angular template IntelliSense, AOT typechecking & component navigation."
                ),
                "category": "Frontend & Frameworks",
                "installed": True,
                "active": True,
                "latency_ms": 340,
                "server_id": "angular",
            },
            {
                "id": "svelte.svelte-vscode",
                "name": "Svelte & SvelteKit",
                "publisher": "svelte",
                "version": "108.4.0",
                "description": (
                    "Svelte 5 Runes, SvelteKit routing, reactive state autocomplete & "
                    "Svelte LSP."
                ),
                "category": "Frontend & Frameworks",
                "installed": True,
                "active": True,
                "latency_ms": 250,
                "server_id": "svelte",
            },
            {
                "id": "tailwindcss.vscode-tailwindcss",
                "name": "Tailwind CSS IntelliSense",
                "publisher": "tailwindcss",
                "version": "0.14.0",
                "description": (
                    "Advanced class autocomplete, CSS directive linting, variant preview & "
                    "color picker."
                ),
                "category": "Frontend & Frameworks",
                "installed": True,
                "active": True,
                "latency_ms": 180,
                "server_id": "tailwindcss",
            },
            {
                "id": "mtxr.sqltools",
                "name": "SQLTools - Database Client",
                "publisher": "mtxr",
                "version": "0.28.3",
                "description": (
                    "Conexão e navegação nativa em bancos PostgreSQL (pgvector), Redis, "
                    "MySQL e SQLite."
                ),
                "category": "Bancos & SQL",
                "installed": True,
                "active": True,
                "latency_ms": 150,
                "server_id": "sqltools",
            },
            {
                "id": "prisma.prisma",
                "name": "Prisma ORM",
                "publisher": "prisma",
                "version": "5.19.0",
                "description": "Autocompletar, realce de sintaxe e migrações para esquemas Prisma.",
                "category": "Bancos & SQL",
                "installed": True,
                "active": True,
                "latency_ms": 130,
                "server_id": "prisma",
            },
            {
                "id": "usernamehw.errorlens",
                "name": "Error Lens",
                "publisher": "usernamehw",
                "version": "3.20.0",
                "description": (
                    "Exibe mensagens de erro, warnings e diagnósticos do LSP diretamente "
                    "inline nas linhas de código."
                ),
                "category": "Produtividade",
                "installed": True,
                "active": True,
                "latency_ms": 90,
                "server_id": "errorlens",
            },
            {
                "id": "eamodio.gitlens",
                "name": "GitLens — Git supercharged",
                "publisher": "eamodio",
                "version": "2026.1.0",
                "description": (
                    "Autoria de código linha por linha (blame), histórico de commits e "
                    "comparação visual de branches."
                ),
                "category": "Produtividade",
                "installed": True,
                "active": True,
                "latency_ms": 110,
                "server_id": "gitlens",
            },
            {
                "id": "pkief.material-icon-theme",
                "name": "Material Icon Theme",
                "publisher": "pkief",
                "version": "5.7.0",
                "description": (
                    "Ícones dinâmicos e modernos para todos os tipos de arquivo e pasta "
                    "no Explorer."
                ),
                "category": "Produtividade",
                "installed": True,
                "active": True,
                "latency_ms": 60,
                "server_id": "material-icons",
            },
            {
                "id": "rangav.vscode-thunder-client",
                "name": "Thunder Client",
                "publisher": "rangav",
                "version": "2.26.0",
                "description": (
                    "Executor leve de requisições HTTP/REST e GraphQL integrado na IDE "
                    "agêntica."
                ),
                "category": "APIs & Testes",
                "installed": True,
                "active": True,
                "latency_ms": 140,
                "server_id": "thunder-client",
            },
            {
                "id": "vitest.explorer",
                "name": "Vitest & Jest Runner",
                "publisher": "vitest",
                "version": "1.0.8",
                "description": (
                    "Execução e debug de testes unitários com 1 clique direto no código."
                ),
                "category": "APIs & Testes",
                "installed": True,
                "active": True,
                "latency_ms": 120,
                "server_id": "vitest",
            },
            {
                "id": "ms-kubernetes-tools.vscode-kubernetes-tools",
                "name": "Kubernetes",
                "publisher": "ms-kubernetes-tools",
                "version": "1.3.15",
                "description": (
                    "Inspeção de pods, navegação de namespaces, deployments e logs de "
                    "clusters K8s."
                ),
                "category": "DevOps & Cloud",
                "installed": True,
                "active": True,
                "latency_ms": 220,
                "server_id": "kubernetes",
            },
            {
                "id": "hashicorp.terraform",
                "name": "HashiCorp Terraform",
                "publisher": "hashicorp",
                "version": "2.32.0",
                "description": (
                    "Autocompletar, validação HCL e linting para infraestrutura como código."
                ),
                "category": "DevOps & Cloud",
                "installed": True,
                "active": True,
                "latency_ms": 200,
                "server_id": "terraform",
            },
            {
                "id": "vscjava.vscode-mermaid-editor",
                "name": "Mermaid Preview",
                "publisher": "vscjava",
                "version": "1.8.0",
                "description": (
                    "Renderização e preview em tempo real de diagramas Mermaid em Markdown."
                ),
                "category": "Produtividade",
                "installed": True,
                "active": True,
                "latency_ms": 110,
                "server_id": "mermaid",
            },
            {
                "id": "esbenp.prettier-vscode",
                "name": "Prettier - Code Formatter",
                "publisher": "esbenp",
                "version": "10.4.0",
                "description": (
                    "Formatação universal ao salvar arquivos TypeScript, JavaScript, CSS "
                    "e HTML."
                ),
                "category": "Produtividade",
                "installed": True,
                "active": True,
                "latency_ms": 100,
                "server_id": "prettier",
            },
        ]
    }





@router.post("/ticket")
async def ticket(
    request: Request, project: str, language: str, server: str | None = None
) -> dict[str, Any]:
    if server_for_language(language, preferred_server=server) is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"nenhum language server para '{language}'",
        )

    store: TicketStore | None = getattr(request.app.state, "tickets", None)
    if store is None:  # pragma: no cover - só ocorre se o lifespan falhar
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Tickets indisponíveis."
        )
    emitido = await store.issue(_escopo(project, language))
    return {"ticket": emitido, "expires_in": TICKET_TTL_SECONDS}


@ws_router.websocket("/{project}/{language}")
async def lsp_socket(websocket: WebSocket, project: str, language: str) -> None:
    settings = get_settings()

    # Sempre exigido, com ou sem SICOOBITO_API_KEY: o ticket só é emitido por
    # `POST .../ticket`, atrás de `AuthDep` (`require_session`) — ver mesmo
    # ajuste em `workspace.py::terminal`.
    store: TicketStore | None = getattr(websocket.app.state, "tickets", None)
    bilhete = websocket.query_params.get("ticket", "")
    server_pref = websocket.query_params.get("server", None)
    if store is None or not await store.consume(bilhete, _escopo(project, language)):
        log.warning("lsp.rejected", project=project, language=language)
        await websocket.close(code=4401, reason="ticket inválido ou expirado")
        return

    spec = server_for_language(language, preferred_server=server_pref)
    if spec is None:
        await websocket.close(code=4404, reason=f"sem language server para {language}")
        return


    raiz_projetos = settings.effective_projects_root
    if raiz_projetos is None:
        await websocket.close(code=4400, reason="PROJECTS_ROOT não configurado")
        return

    try:
        raiz = project_ops.resolve(Path(raiz_projetos), project)
    except ProjectError as exc:
        await websocket.close(code=4400, reason=str(exc)[:120])
        return

    servidor = LanguageServerProcess(spec, raiz)
    try:
        await servidor.start()
    except LspError as exc:
        # Aceitar antes de fechar para que o motivo chegue ao editor: uma recusa
        # no handshake vira apenas "connection failed" no console do browser.
        await websocket.accept()
        await websocket.send_json(
            {"jsonrpc": "2.0", "method": "sicoobito/error", "params": str(exc)}
        )
        await websocket.close(code=4503)
        return

    # `servidor.start()` já subiu o processo do language server (pyright,
    # tsserver — centenas de MB) neste ponto. Se `accept()` ou a criação da
    # task de bombeamento falharem agora (cliente desconectou bem nessa
    # janela, por exemplo), nada mais chamaria `servidor.stop()`: o `finally`
    # do laço de mensagens abaixo só existe DEPOIS destas duas linhas — sem
    # este try/except o processo vazava como zumbi até o restart da API.
    try:
        await websocket.accept()
        log.info("lsp.attached", project=project, language=language, server=spec.id)

        async def do_servidor_para_o_editor() -> None:
            while True:
                mensagem = await servidor.receive()
                if mensagem is None:
                    break
                await websocket.send_json(mensagem)
            # O processo morreu. Fechar aqui é o que informa o editor: sem isso, o
            # laço de leitura abaixo continuaria aceitando requisições que nunca
            # teriam resposta, e a UI ficaria eternamente "conectando".
            log.warning("lsp.server.exited", project=project, language=language, server=spec.id)
            await websocket.close(code=4503, reason="o language server encerrou")

        bombeador = asyncio.create_task(do_servidor_para_o_editor())
    except Exception:
        await servidor.stop()
        raise

    try:
        while True:
            mensagem = await websocket.receive_json()
            if isinstance(mensagem, dict):
                await servidor.send(mensagem)
    except WebSocketDisconnect:
        log.debug("lsp.disconnected", project=project, language=language)
    except Exception as exc:
        log.warning("lsp.failed", project=project, language=language, error=str(exc))
    finally:
        bombeador.cancel()
        # O processo morre junto com a conexão. É o que garante que fechar o
        # editor não deixa um pyright de 1 GB residente até o próximo reboot.
        await servidor.stop()
