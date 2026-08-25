"""Ponte LSP.

O foco é a tradução de caminhos e o enquadramento, que é onde os erros são
silenciosos: uma URI mal traduzida não derruba nada — o servidor apenas
responde "não sei nada sobre esse arquivo", e o sintoma no editor é
"autocomplete não funciona", que não parece um bug de string.

Para exercitar isso sem depender de ter o `pyright` instalado, o processo é
substituído por um eco em Python que devolve a mensagem recebida.
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest
from fastapi.testclient import TestClient

os.environ["NOVAAI_STUDIO_API_KEY"] = "chave-de-teste"
os.environ["REDIS_URL"] = "redis://localhost:65533/0"

from novaai_studio.config import get_settings
from novaai_studio.lsp.bridge import LanguageServerProcess
from novaai_studio.lsp.servers import ServerSpec, server_for_language, supported_languages
from novaai_studio.main import create_app

AUTH = {"Authorization": "Bearer chave-de-teste"}

# Lê um frame com cabeçalho `Content-Length` e devolve exatamente o mesmo corpo,
# reenquadrado. É um language server degenerado, mas fala o protocolo certo.
_ECO = r"""
import sys
entrada = sys.stdin.buffer
saida = sys.stdout.buffer
while True:
    tamanho = None
    while True:
        linha = entrada.readline()
        if not linha:
            sys.exit(0)
        texto = linha.decode("ascii").strip()
        if not texto:
            break
        if texto.lower().startswith("content-length:"):
            tamanho = int(texto.split(":", 1)[1])
    if tamanho is None:
        sys.exit(0)
    corpo = entrada.read(tamanho)
    saida.write(b"Content-Length: %d\r\n\r\n" % len(corpo))
    saida.write(corpo)
    saida.flush()
"""


@pytest.fixture
def projeto(tmp_path):
    raiz = tmp_path / "meu-app"
    (raiz / "src").mkdir(parents=True)
    (raiz / "src" / "app.py").write_bytes(b"x = 1\n")
    return raiz


@pytest.fixture
def spec_eco():
    return ServerSpec(id="eco", command=[sys.executable, "-c", _ECO], languages=("python",))


async def _ida_e_volta(servidor: LanguageServerProcess, mensagem: dict) -> dict:
    await servidor.send(mensagem)
    resposta = await servidor.receive()
    assert resposta is not None
    return resposta


@pytest.mark.asyncio
async def test_caminho_relativo_vira_uri_absoluta_e_volta(projeto, spec_eco):
    servidor = LanguageServerProcess(spec_eco, projeto)
    await servidor.start()
    try:
        volta = await _ida_e_volta(
            servidor,
            {"jsonrpc": "2.0", "id": 1, "params": {"textDocument": {"uri": "src/app.py"}}},
        )
    finally:
        await servidor.stop()

    # O editor mandou relativo e recebeu relativo de volta: o caminho do
    # container nunca aparece do lado de fora.
    assert volta["params"]["textDocument"]["uri"] == "src/app.py"


@pytest.mark.asyncio
async def test_uri_fora_do_projeto_chega_intacta(projeto, spec_eco):
    """Definição em biblioteca instalada: mostrar sim, fingir que é do projeto não."""
    servidor = LanguageServerProcess(spec_eco, projeto)
    await servidor.start()
    try:
        volta = await _ida_e_volta(
            servidor,
            {"jsonrpc": "2.0", "id": 2, "params": {"uri": "file:///usr/lib/python3/typing.py"}},
        )
    finally:
        await servidor.stop()

    assert volta["params"]["uri"] == "file:///usr/lib/python3/typing.py"


@pytest.mark.asyncio
async def test_traduz_uri_em_qualquer_profundidade(projeto, spec_eco):
    """`targetUri` dentro de uma lista aninhada é o formato de `LocationLink`.

    Enumerar as chaves conhecidas envelheceria em silêncio: esquecer uma faz
    "ir para definição" não fazer nada, e nada nesse sintoma aponta para a
    tradução.
    """
    servidor = LanguageServerProcess(spec_eco, projeto)
    await servidor.start()
    try:
        volta = await _ida_e_volta(
            servidor,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "result": [{"targetUri": "src/app.py", "extra": {"scopeUri": "src"}}],
            },
        )
    finally:
        await servidor.stop()

    assert volta["result"][0]["targetUri"] == "src/app.py"
    assert volta["result"][0]["extra"]["scopeUri"] == "src"


@pytest.mark.asyncio
async def test_initialize_ganha_a_raiz_do_projeto(projeto, spec_eco):
    """O cliente não conhece o caminho no container; a ponte preenche."""
    servidor = LanguageServerProcess(spec_eco, projeto)
    await servidor.start()
    try:
        volta = await _ida_e_volta(
            servidor, {"jsonrpc": "2.0", "id": 4, "method": "initialize", "params": {}}
        )
    finally:
        await servidor.stop()

    params = volta["params"]
    # A raiz em si não ganha a barra final e por isso não casa com o prefixo de
    # tradução: volta como a URI absoluta que foi enviada. É o comportamento
    # correto — o cliente nunca pede nada sobre a raiz, só sobre arquivos.
    assert params["rootUri"].startswith("file://")
    assert params["rootUri"].endswith("meu-app")
    assert params["rootPath"] == str(projeto)
    assert params["workspaceFolders"][0]["name"] == "meu-app"


@pytest.mark.asyncio
async def test_mensagem_grande_atravessa_inteira(projeto, spec_eco):
    """Um `didOpen` de arquivo grande passa do buffer padrão do asyncio."""
    servidor = LanguageServerProcess(spec_eco, projeto)
    await servidor.start()
    try:
        gigante = "linha de código\n" * 40_000
        volta = await _ida_e_volta(
            servidor,
            {"jsonrpc": "2.0", "id": 5, "params": {"textDocument": {"text": gigante}}},
        )
    finally:
        await servidor.stop()

    assert volta["params"]["textDocument"]["text"] == gigante


@pytest.mark.asyncio
async def test_comando_inexistente_falha_com_mensagem_util(projeto):
    spec = ServerSpec(id="fantasma", command=["nao-existe-mesmo"], languages=("python",))
    servidor = LanguageServerProcess(spec, projeto)
    with pytest.raises(Exception) as erro:
        await servidor.start()
    assert "nao-existe-mesmo" in str(erro.value)


def test_catalogo_mapeia_linguagens_para_servidores():
    assert server_for_language("python") is not None
    assert server_for_language("typescriptreact") is not None
    assert server_for_language("cobol") is None


def test_linguagens_suportadas_refletem_o_que_esta_instalado():
    # Numa máquina de desenvolvimento sem os servidores npm, a lista filtrada
    # fica vazia — e é isso que o front consulta para nem tentar conectar.
    todas = supported_languages(only_installed=False)
    instaladas = supported_languages()
    assert "python" in todas
    assert set(instaladas) <= set(todas)


# ── rotas ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    raiz = tmp_path_factory.mktemp("projetos")
    (raiz / "demo").mkdir()
    os.environ["PROJECTS_ROOT"] = str(raiz)
    get_settings.cache_clear()
    with TestClient(create_app()) as test_client:
        yield test_client
    os.environ.pop("PROJECTS_ROOT", None)
    get_settings.cache_clear()


def test_rota_de_linguagens_exige_a_chave(client):
    assert client.get("/api/lsp/languages").status_code == 401


def test_rota_de_linguagens_responde(client):
    resposta = client.get("/api/lsp/languages", headers=AUTH)
    assert resposta.status_code == 200
    assert isinstance(resposta.json()["languages"], dict)


def test_ticket_recusa_linguagem_sem_servidor(client):
    resposta = client.post(
        "/api/lsp/ticket", params={"project": "demo", "language": "cobol"}, headers=AUTH
    )
    assert resposta.status_code == 400


def test_websocket_sem_ticket_nao_conecta(client):
    # O Starlette recusa antes do accept; o formato exato varia com a versão, e
    # o que importa é que a conexão não se estabelece.
    with pytest.raises(Exception) as erro:
        with client.websocket_connect("/api/lsp/demo/python?ticket=inventado"):
            pass
    assert "WebSocket" in type(erro.value).__name__ or "4401" in str(erro.value)


def test_websocket_com_ticket_valido_completa_o_handshake(client):
    """O ticket precisa valer de fato, e não apenas existir.

    Este é o mesmo defeito que já apareceu no terminal: a dependência de
    autenticação por header no router mataria toda conexão antes de o ticket
    ser avaliado, e um teste que só afirma "falhou" passaria mesmo assim.
    """
    ticket = client.post(
        "/api/lsp/ticket", params={"project": "demo", "language": "python"}, headers=AUTH
    ).json()["ticket"]

    with client.websocket_connect(f"/api/lsp/demo/python?ticket={ticket}") as ws:
        ws.send_json({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})

        # A resposta não é a primeira mensagem: o pyright anuncia a própria
        # versão por `window/logMessage` antes. Um cliente que lesse só o
        # primeiro frame concluiria que o handshake falhou — e é exatamente o
        # erro que este teste pegou.
        for _ in range(20):
            mensagem = ws.receive_json()
            assert mensagem["jsonrpc"] == "2.0"
            if mensagem.get("method") == "novaai_studio/error":
                # Imagem sem o language server: informar pelo canal já exige que
                # a conexão tenha sido aceita, que é o que este teste garante.
                return
            if mensagem.get("id") == 1:
                assert "result" in mensagem, mensagem
                assert "capabilities" in mensagem["result"]
                return

        raise AssertionError("o servidor nunca respondeu ao initialize")


@pytest.mark.skipif(
    server_for_language("python") is None or not server_for_language("python").available,
    reason="pyright não está instalado nesta máquina (ele vive na imagem da API)",
)
def test_pyright_responde_uma_completion_de_verdade(client, tmp_path_factory):
    """O caminho inteiro, com o language server real.

    Os outros testes usam um eco: eles provam a tradução e o enquadramento, mas
    passariam mesmo que o protocolo estivesse errado — o eco concorda com
    qualquer coisa. Este exige que um servidor de verdade entenda o que
    mandamos.
    """
    raiz = get_settings().effective_projects_root
    from pathlib import Path

    (Path(raiz) / "demo" / "exemplo.py").write_text("import json\njson.\n", encoding="utf-8")

    ticket = client.post(
        "/api/lsp/ticket", params={"project": "demo", "language": "python"}, headers=AUTH
    ).json()["ticket"]

    with client.websocket_connect(f"/api/lsp/demo/python?ticket={ticket}") as ws:
        ws.send_json({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        _esperar_resposta(ws, 1)
        ws.send_json({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        ws.send_json(
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        # Caminho relativo: é o que o editor manda, e a ponte
                        # traduz. Se a tradução estiver errada, o pyright
                        # responde sobre um arquivo que não existe — e devolve
                        # lista vazia, sem erro nenhum.
                        "uri": "exemplo.py",
                        "languageId": "python",
                        "version": 1,
                        "text": "import json\njson.\n",
                    }
                },
            }
        )
        ws.send_json(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/completion",
                "params": {
                    "textDocument": {"uri": "exemplo.py"},
                    "position": {"line": 1, "character": 5},
                    "context": {"triggerKind": 1},
                },
            }
        )
        resposta = _esperar_resposta(ws, 2)

    itens = resposta["result"]
    itens = itens if isinstance(itens, list) else itens["items"]
    rotulos = {i["label"] for i in itens}
    assert "dumps" in rotulos and "loads" in rotulos, sorted(rotulos)[:20]


def _esperar_resposta(ws, ident: int, limite: int = 60) -> dict:
    """Descarta notificações até chegar a resposta do id pedido."""
    for _ in range(limite):
        mensagem = ws.receive_json()
        if mensagem.get("id") == ident:
            assert "result" in mensagem, mensagem
            return mensagem
    raise AssertionError(f"sem resposta para o id {ident}")


def test_projeto_invalido_e_recusado(client):
    ticket = client.post(
        "/api/lsp/ticket", params={"project": "../fora", "language": "python"}, headers=AUTH
    ).json()["ticket"]

    with pytest.raises(Exception) as erro:
        with client.websocket_connect(f"/api/lsp/..%2Ffora/python?ticket={ticket}"):
            pass
    assert "WebSocket" in type(erro.value).__name__ or "44" in str(erro.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("bruto", "esperado"),
    [
        (b"Content-Length: 42\r\n\r\n", 42),
        # Servidores reais mandam `Content-Type` junto; ignorar o que não
        # interessa é diferente de tropeçar nele.
        (b"Content-Type: application/vscode-jsonrpc\r\nContent-Length: 7\r\n\r\n", 7),
        # Sem `Content-Length` não há como saber onde a mensagem acaba.
        # Continuar lendo dessincronizaria o stream: a partir dali, toda
        # mensagem sairia misturada com o resto da anterior.
        (b"Content-Type: texto\r\n\r\n", None),
        (b"", None),
    ],
)
async def test_enquadramento_le_o_cabecalho(bruto, esperado, projeto, spec_eco):
    stream = asyncio.StreamReader()
    stream.feed_data(bruto)
    stream.feed_eof()

    servidor = LanguageServerProcess(spec_eco, projeto)
    assert await servidor._ler_cabecalho(stream) == esperado
