"""Lote 2 / item 88 — o invariante do ADR 0002 ("execução de comando nunca
fala direto com o daemon Docker; em produção/container vai pelo serviço
`executor` isolado, autenticado por `EXECUTOR_TOKEN`, e as restrições de
sandbox são fixadas NO executor, nunca recebidas por parâmetro do chamador")
virando teste executável.

Cobre o cliente `RemoteSandbox`/`ExecutorSandboxManager`:
  1. o módulo não tem nenhum acesso ao daemon Docker;
  2. toda requisição ao executor leva `Authorization: Bearer <token>`;
  3. `start()` nunca manda `image`/`network` — o chamador não influencia as
     travas de segurança do sandbox.
"""

from __future__ import annotations

import inspect
import sys

import pytest

from eltanix.sandbox import executor as executor_mod
from eltanix.sandbox.executor import ExecutorConfig, ExecutorSandboxManager, RemoteSandbox


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    """Registra toda chamada HTTP em vez de sair na rede."""

    def __init__(self) -> None:
        self.is_closed = False
        self.calls: list[dict] = []

    async def post(self, url, json=None, headers=None, timeout=None):  # noqa: ASYNC109 - assinatura espelha httpx.AsyncClient
        self.calls.append({"method": "POST", "url": url, "json": json, "headers": headers or {}})
        if url.endswith("/sandboxes"):
            return _FakeResponse({"id": "sbx-1", "reused": False})
        return _FakeResponse({"exit_code": 0, "stdout": "ok", "stderr": "", "duration_ms": 3})

    async def delete(self, url, headers=None, timeout=None):  # noqa: ASYNC109 - idem
        self.calls.append({"method": "DELETE", "url": url, "headers": headers or {}})
        return _FakeResponse({}, status_code=200)

    async def aclose(self) -> None:
        self.is_closed = True


_CFG = ExecutorConfig(base_url="http://executor:8080", token="tok-secreto-123")


def test_executor_client_module_nao_toca_no_daemon_docker():
    fonte = inspect.getsource(executor_mod)
    for proibido in ("import docker", "from docker", "docker.from_env", "_docker_client", "docker.sock"):
        assert proibido not in fonte, f"cliente do executor referencia {proibido!r} (viola ADR 0002)"
    # E importar o módulo não puxa o SDK do Docker para o processo.
    assert "docker" not in sys.modules or getattr(sys.modules["docker"], "__file__", "") == ""


@pytest.mark.asyncio
async def test_start_manda_token_e_nao_manda_image_nem_network(tmp_path):
    fake = _FakeAsyncClient()
    sbx = RemoteSandbox("sess-1", tmp_path, _CFG, client=fake)

    await sbx.start()

    (chamada,) = [c for c in fake.calls if c["url"].endswith("/sandboxes")]
    assert chamada["headers"].get("Authorization") == "Bearer tok-secreto-123"
    assert chamada["url"] == "http://executor:8080/sandboxes"
    # O chamador não escolhe imagem nem rede — isso é fixado pelo executor.
    assert "image" not in chamada["json"]
    assert "network" not in chamada["json"]


@pytest.mark.asyncio
async def test_exec_e_stop_sempre_autenticam_no_executor(tmp_path):
    fake = _FakeAsyncClient()
    sbx = RemoteSandbox("sess-1", tmp_path, _CFG, client=fake)

    resultado = await sbx.exec("pytest -q", timeout=10)
    assert resultado.exit_code == 0

    await sbx.stop()

    assert fake.calls, "nenhuma chamada HTTP registrada"
    for c in fake.calls:
        assert c["url"].startswith("http://executor:8080/"), c["url"]
        assert c["headers"].get("Authorization") == "Bearer tok-secreto-123", c


@pytest.mark.asyncio
async def test_sem_token_nenhum_header_de_auth_e_enviado(tmp_path):
    fake = _FakeAsyncClient()
    sbx = RemoteSandbox("s", tmp_path, ExecutorConfig(base_url="http://executor:8080"), client=fake)
    await sbx.start()
    assert "Authorization" not in fake.calls[0]["headers"]


def test_manager_do_executor_expoe_a_mesma_interface_do_local():
    """As ferramentas do agente não podem saber quem executa — `acquire`
    precisa existir nos dois managers com a mesma assinatura."""
    from eltanix.sandbox.container import SandboxManager

    assert hasattr(ExecutorSandboxManager, "acquire")
    assert inspect.signature(ExecutorSandboxManager.acquire).parameters.keys() == (
        inspect.signature(SandboxManager.acquire).parameters.keys()
    )
