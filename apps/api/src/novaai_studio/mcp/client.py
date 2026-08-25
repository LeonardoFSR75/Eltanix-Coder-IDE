"""Conexão com um servidor MCP — stdio ou Streamable HTTP.

Cada conexão fica aberta pelo tempo de vida do processo da API, não por
sessão do agente: os handlers das ferramentas MCP (montados em
`mcp/manager.py`) fecham sobre a conexão já estabelecida, sem reconectar a
cada chamada.

O transporte (`stdio_client`/`streamable_http_client`) usa um task group do
anyio por baixo, cujo cancel scope só pode ser fechado na mesma task
asyncio em que foi aberto — mas `connect()` e `disconnect()` são chamados
de tasks de requisição diferentes (uma request cria o servidor, outra o
remove). Por isso a conexão roda numa task dona de longa duração
(`_run`) que abre e fecha o `AsyncExitStack` inteiramente dentro de si
mesma; `connect`/`disconnect` só sinalizam essa task via eventos.

stdio sobe o subprocesso direto neste processo — sem passar pelo sandbox do
executor. O comando é o que o usuário digitou na tela de MCP, não código
influenciado pelo agente/LLM, então a fronteira de confiança é outra (ver
comentário no topo de `config/mcp.yaml`).
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from typing import Any

import mcp.types as types
from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from sicoobito.logging_setup import get_logger
from sicoobito.mcp.config import MCPServerConfig

log = get_logger(__name__)

_DISCONNECT_TIMEOUT_S = 10


def _content_to_text(blocks: list[Any]) -> str:
    """Achata o conteúdo de um CallToolResult. Blocos não textuais (imagem,
    áudio) viram um marcador — o agente não consegue interpretá-los mesmo
    assim, e omitir silenciosamente esconderia que algo voltou."""
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, types.TextContent):
            parts.append(block.text)
        else:
            parts.append(f"[{type(block).__name__} não textual]")
    return "\n".join(parts) if parts else "(sem conteúdo)"


class MCPServerConnection:
    """Uma conexão com um servidor MCP configurado."""

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self.status: str = "disabled" if not config.enabled else "connecting"
        self.error: str | None = None
        self.tools: list[types.Tool] = []
        self._client: Client | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None

    async def connect(self) -> None:
        if not self.config.enabled:
            self.status = "disabled"
            return

        ready = asyncio.Event()
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run(ready))
        await ready.wait()

    async def _run(self, ready: asyncio.Event) -> None:
        """Dona da conexão do início ao fim: abre o transporte, avisa quem
        chamou `connect()` (via `ready`), e só sai (fechando tudo) quando
        `disconnect()` sinalizar `_stop_event` — sempre na mesma task."""
        assert self._stop_event is not None
        try:
            async with AsyncExitStack() as stack:
                if self.config.transport == "stdio":
                    # Garantido pelo validator de MCPServerConfig.
                    assert self.config.command is not None
                    params = StdioServerParameters(
                        command=self.config.command,
                        args=self.config.args,
                        env=self.config.env or None,
                    )
                    transport = stdio_client(params)
                else:
                    assert self.config.url is not None
                    transport = streamable_http_client(self.config.url)

                client = await stack.enter_async_context(Client(transport))
                result = await client.list_tools()

                self._client = client
                self.tools = list(result.tools)
                self.status = "connected"
                log.info("mcp.connect.ok", server=self.config.name, tools=len(self.tools))
                ready.set()

                await self._stop_event.wait()
        except Exception as exc:
            self.status = "error"
            self.error = str(exc)[:300]
            log.warning("mcp.connect.failed", server=self.config.name, error=self.error)
            ready.set()
        finally:
            self._client = None

    async def disconnect(self) -> None:
        if self._task is None:
            return
        if self._stop_event is not None:
            self._stop_event.set()
        clean = True
        try:
            await asyncio.wait_for(self._task, timeout=_DISCONNECT_TIMEOUT_S)
        except Exception as exc:
            clean = False
            log.warning("mcp.disconnect.failed", server=self.config.name, error=str(exc)[:200])
        self._task = None
        self._stop_event = None
        self.tools = []
        # Desconexão limpa é "disabled" (não conectado agora, sem ser um
        # erro) mesmo que `enabled` continue True — `MCPManager.reload()`
        # descarta este objeto e cria um novo em seguida de qualquer forma.
        self.status = "error" if not clean else "disabled"

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> tuple[bool, str]:
        """Retorna `(ok, texto)`. `ok=False` cobre erro de transporte e
        `is_error=True` reportado pelo próprio servidor. Chamado a partir da
        task da sessão do agente, não da task dona da conexão — seguro
        porque `Client.call_tool` só envia/recebe mensagens pelos streams já
        abertos, sem tocar no cancel scope do transporte."""
        if self._client is None:
            return False, f"Servidor MCP {self.config.name!r} não está conectado ({self.status})."
        try:
            result = await self._client.call_tool(name, arguments)
        except Exception as exc:
            return False, f"Falha ao chamar {name!r} em {self.config.name!r}: {exc}"
        return not result.is_error, _content_to_text(result.content)
