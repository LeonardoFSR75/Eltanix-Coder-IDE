"""Ponte entre um WebSocket e um language server falando JSON-RPC por stdio.

Três traduções acontecem aqui, e cada uma existe por um motivo distinto:

1. **Enquadramento.** O LSP sobre stdio delimita mensagens com um cabeçalho
   `Content-Length`. Sobre WebSocket isso é redundante — o próprio protocolo já
   entrega mensagens inteiras —, então cada frame vira uma mensagem e vice-versa.

2. **Caminhos.** O servidor fala em URIs absolutas do container
   (`file:///projects/meu-app/src/app.py`); o editor conhece apenas caminhos
   relativos ao projeto. Traduzir aqui mantém o layout interno do container
   fora do browser — que é onde ele não deveria mesmo aparecer.

3. **Handshake.** O `initialize` precisa da raiz do workspace, que o cliente não
   sabe. A ponte preenche.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from eltanix.logging_setup import get_logger
from eltanix.lsp.servers import ServerSpec

log = get_logger(__name__)

_ENCERRAMENTO_SEGUNDOS = 5.0
# Um `initialize` de projeto grande demora; o resto é instantâneo.
_LEITURA_MAX_BYTES = 64 * 1024 * 1024


class LspError(RuntimeError):
    """Falha ao iniciar ou falar com um language server."""


def _ambiente_limpo() -> dict[str, str]:
    """Ambiente para o language server, sem o virtualenv da própria API.

    A API roda com `/app/.venv/bin` no `PATH` e o pacote `eltanix` instalado
    em modo editável apontando para `/app/src`. Um analisador que herde isso
    resolve os imports do projeto pela **cópia dentro do container** em vez dos
    arquivos que estão abertos no editor — e "ir para definição" leva a
    `/app/src/...`, um caminho que o editor não consegue abrir.
    """
    ambiente = {
        chave: valor
        for chave, valor in os.environ.items()
        # `PYTHONPATH` e `PYTHONHOME` arrastam o mesmo problema por outra via.
        if chave not in {"VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME"}
    }

    venv = os.environ.get("VIRTUAL_ENV") or "/app/.venv"
    caminhos = [
        parte
        for parte in ambiente.get("PATH", "").split(os.pathsep)
        if parte and not parte.startswith(venv)
    ]
    ambiente["PATH"] = os.pathsep.join(caminhos)
    # Sem isto o servidor herda o locale do container e emite mensagens com
    # codificação inconsistente.
    ambiente["LANG"] = "C.UTF-8"
    ambiente["LC_ALL"] = "C.UTF-8"
    return ambiente


def _para_uri(raiz: Path, caminho_relativo: str) -> str:
    absoluto = (raiz / caminho_relativo.lstrip("/")).as_posix()
    # `quote` com `/` e `:` preservados: o servidor compara URIs como texto, e
    # escapar a barra transformaria caminhos válidos em arquivos inexistentes.
    return "file://" + quote(absoluto, safe="/:")


class LanguageServerProcess:
    """Um processo de language server, dedicado a uma conexão do editor.

    Um processo por conexão, e o front abre uma conexão por (projeto,
    linguagem). Sem multiplexação: compartilhar um processo entre conexões
    exigiria remapear ids de requisição para não entregar a resposta de um
    cliente a outro, e o ganho não paga essa complexidade num IDE de um usuário.
    """

    def __init__(self, spec: ServerSpec, root: Path) -> None:
        self.spec = spec
        self.root = root
        self._prefixo = _para_uri(root, "").rstrip("/") + "/"
        self._processo: asyncio.subprocess.Process | None = None
        self._escrita = asyncio.Lock()
        self._stderr_task: asyncio.Task[None] | None = None

    # ── ciclo de vida ────────────────────────────────────────────────────

    async def start(self) -> None:
        if not self.spec.available:
            raise LspError(f"{self.spec.command[0]} não está instalado nesta imagem")

        ambiente = _ambiente_limpo()
        try:
            self._processo = await asyncio.create_subprocess_exec(
                *self.spec.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.root),
                env=ambiente,
                limit=_LEITURA_MAX_BYTES,
            )
        except (OSError, ValueError) as exc:
            raise LspError(f"não foi possível iniciar {self.spec.id}: {exc}") from exc

        self._stderr_task = asyncio.create_task(self._drenar_stderr())
        log.info("lsp.started", server=self.spec.id, root=str(self.root))

    async def stop(self) -> None:
        processo = self._processo
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            self._stderr_task = None
        if processo is None or processo.returncode is not None:
            self._processo = None
            return

        # Pedir para sair antes de matar: o pyright grava cache em disco no
        # `shutdown`, e um SIGKILL faz a próxima sessão reindexar do zero.
        # `_escrever` lê `self._processo` — precisa continuar setado até aqui,
        # senão toda chamada levanta LspError (engolida pelo except abaixo) e
        # shutdown/exit nunca chegam a ser enviados de verdade.
        try:
            await self._escrever({"jsonrpc": "2.0", "id": -1, "method": "shutdown"})
            await self._escrever({"jsonrpc": "2.0", "method": "exit"})
        except Exception:
            pass
        finally:
            self._processo = None

        try:
            await asyncio.wait_for(processo.wait(), timeout=_ENCERRAMENTO_SEGUNDOS)
        except TimeoutError:
            try:
                processo.kill()
            except Exception:
                pass
            await processo.wait()
        log.info("lsp.stopped", server=self.spec.id)

    async def _drenar_stderr(self) -> None:
        """Sem alguém lendo, o pipe enche e o servidor trava ao escrever nele."""
        processo = self._processo
        if processo is None or processo.stderr is None:
            return
        try:
            while linha := await processo.stderr.readline():
                log.debug("lsp.stderr", server=self.spec.id, line=linha.decode(errors="replace"))
        except asyncio.CancelledError:
            raise
        except Exception:
            return

    # ── tradução de caminhos ─────────────────────────────────────────────

    def _uri_para_servidor(self, valor: str) -> str:
        if "://" in valor:
            return valor
        return _para_uri(self.root, valor)

    def _uri_para_cliente(self, valor: str) -> str:
        if not valor.startswith(self._prefixo):
            # Definição em dependência instalada, stub de biblioteca, arquivo
            # fora do projeto: entregue como veio. O editor mostra a origem mas
            # não tenta abrir o que não pode ler.
            return valor
        return unquote(valor[len(self._prefixo) :])

    def _traduzir(self, nó: Any, para_servidor: bool) -> Any:
        """Reescreve toda chave que termina em `uri`, em qualquer profundidade.

        Genérico de propósito: o protocolo tem `uri`, `targetUri`, `newUri`,
        `rootUri`, `scopeUri`, e extensões inventam mais. Enumerá-las seria uma
        lista que envelhece em silêncio — e o sintoma de esquecer uma é
        "ir para definição não faz nada", que não parece um bug de tradução.
        """
        if isinstance(nó, dict):
            resultado: dict[str, Any] = {}
            for chave, valor in nó.items():
                if isinstance(valor, str) and chave.lower().endswith("uri"):
                    resultado[chave] = (
                        self._uri_para_servidor(valor)
                        if para_servidor
                        else self._uri_para_cliente(valor)
                    )
                else:
                    resultado[chave] = self._traduzir(valor, para_servidor)
            return resultado
        if isinstance(nó, list):
            return [self._traduzir(item, para_servidor) for item in nó]
        return nó

    def _preparar_initialize(self, mensagem: dict[str, Any]) -> dict[str, Any]:
        raiz_uri = _para_uri(self.root, "")
        params = dict(mensagem.get("params") or {})
        params["processId"] = os.getpid()
        # O pyright lê `capabilities.workspace` sem checar o pai: um cliente que
        # omite o campo derruba o `initialize` com um erro que fala de
        # JavaScript, não de LSP. Garantir o objeto é mais barato do que
        # depurar isso depois.
        params.setdefault("capabilities", {})
        params["rootUri"] = raiz_uri
        params["rootPath"] = str(self.root)
        # `rootUri` e `rootPath` são o que o pyright usa quando o cliente não
        # anuncia suporte a múltiplas raízes — e é assim que queremos, porque
        # anunciá-lo o faz parar de analisar (ver o comentário em `lsp.ts`).
        # `workspaceFolders` fica aqui para os servidores que só entendem essa
        # forma; quem não a pediu simplesmente a ignora.
        params["workspaceFolders"] = [{"uri": raiz_uri, "name": self.root.name}]
        if self.spec.initialization_options:
            params["initializationOptions"] = {
                **self.spec.initialization_options,
                **(params.get("initializationOptions") or {}),
            }
        return {**mensagem, "params": params}

    # ── transporte ───────────────────────────────────────────────────────

    async def send(self, mensagem: dict[str, Any]) -> None:
        """Recebe uma mensagem do editor e a repassa ao servidor."""
        if mensagem.get("method") == "initialize":
            mensagem = self._preparar_initialize(mensagem)
        await self._escrever(self._traduzir(mensagem, para_servidor=True))

    async def _escrever(self, mensagem: dict[str, Any]) -> None:
        processo = self._processo
        if processo is None or processo.stdin is None:
            raise LspError("language server não está rodando")

        corpo = json.dumps(mensagem, ensure_ascii=False).encode("utf-8")
        cabecalho = f"Content-Length: {len(corpo)}\r\n\r\n".encode("ascii")
        async with self._escrita:
            processo.stdin.write(cabecalho + corpo)
            await processo.stdin.drain()

    async def receive(self) -> dict[str, Any] | None:
        """Próxima mensagem do servidor, já com os caminhos traduzidos.

        `None` quando o processo terminou.
        """
        processo = self._processo
        if processo is None or processo.stdout is None:
            return None

        tamanho = await self._ler_cabecalho(processo.stdout)
        if tamanho is None:
            return None

        try:
            corpo = await processo.stdout.readexactly(tamanho)
        except asyncio.IncompleteReadError:
            return None

        try:
            mensagem = json.loads(corpo)
        except json.JSONDecodeError as exc:
            log.warning("lsp.decode.failed", server=self.spec.id, error=str(exc))
            return None

        return self._traduzir(mensagem, para_servidor=False)

    async def _ler_cabecalho(self, stream: asyncio.StreamReader) -> int | None:
        tamanho: int | None = None
        while True:
            try:
                linha = await stream.readline()
            except (asyncio.IncompleteReadError, ValueError):
                return None
            if not linha:
                return None
            texto = linha.decode("ascii", errors="replace").strip()
            if not texto:
                # Linha em branco encerra o cabeçalho. Sem `Content-Length` não
                # há como saber onde a mensagem acaba: desistir é a única saída
                # honesta, porque prosseguir dessincroniza o stream inteiro.
                return tamanho
            if texto.lower().startswith("content-length:"):
                try:
                    tamanho = int(texto.split(":", 1)[1].strip())
                except ValueError:
                    return None
