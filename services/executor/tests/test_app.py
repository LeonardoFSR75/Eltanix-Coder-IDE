"""Testes do executor: o único serviço com acesso ao docker.sock (ADR 0002).

Nunca depende de um Docker de verdade — `docker.from_env()` nem chega a ser
chamado porque `app._client` é substituído por um `MagicMock` antes de cada
requisição que alcança `client()`. `TOKEN` e `PROJECTS_ROOT_HOST` são lidos
no import do módulo, então cada teste que precisa de uma combinação diferente
dessas env vars recarrega o módulo via `importlib.reload` (helper
`_reload_app` abaixo) em vez de confiar em um valor fixado uma única vez.
"""

from __future__ import annotations

import asyncio
import importlib
import time
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

TOKEN = "segredo-de-teste"
AUTH_HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def _reload_app(monkeypatch, *, token: str | None = TOKEN, projects_root_host: str | None = None):
    """Recarrega `app.py` com as env vars lidas no import ajustadas.

    `token=None` simula EXECUTOR_TOKEN ausente (sem autenticação exigida).
    `projects_root_host=None` simula PROJECTS_ROOT_HOST ausente (sem tradução
    de caminho, `to_host_path` vira um no-op).
    """
    if token is None:
        monkeypatch.delenv("EXECUTOR_TOKEN", raising=False)
    else:
        monkeypatch.setenv("EXECUTOR_TOKEN", token)

    if projects_root_host is None:
        monkeypatch.delenv("PROJECTS_ROOT_HOST", raising=False)
    else:
        monkeypatch.setenv("PROJECTS_ROOT_HOST", projects_root_host)

    import app as app_module  # type: ignore[import-not-found]

    importlib.reload(app_module)
    return app_module


def _with_mock_docker(app_module) -> MagicMock:
    """Instala um client docker mockado no módulo e devolve o mock."""
    mock_client = MagicMock()
    app_module._client = mock_client
    return mock_client


# --------------------------------------------------------------------------
# require_token
# --------------------------------------------------------------------------


def test_require_token_rejects_request_without_authorization_header(monkeypatch):
    app_module = _reload_app(monkeypatch, token=TOKEN)
    client = TestClient(app_module.app)

    response = client.get("/sandboxes")

    assert response.status_code == 401


def test_require_token_rejects_wrong_token(monkeypatch):
    app_module = _reload_app(monkeypatch, token=TOKEN)
    client = TestClient(app_module.app)

    response = client.get("/sandboxes", headers={"Authorization": "Bearer token-errado"})

    assert response.status_code == 401


def test_require_token_accepts_correct_token(monkeypatch):
    app_module = _reload_app(monkeypatch, token=TOKEN)
    mock_client = _with_mock_docker(app_module)
    mock_client.containers.list.return_value = []
    client = TestClient(app_module.app)

    response = client.get("/sandboxes", headers=AUTH_HEADERS)

    assert response.status_code == 200


def test_require_token_allows_everything_when_no_token_configured(monkeypatch):
    # EXECUTOR_TOKEN vazio é o caso "sem auth exigida" — usado em dev local,
    # nunca em produção. Precisa passar mesmo sem nenhum header.
    app_module = _reload_app(monkeypatch, token=None)
    mock_client = _with_mock_docker(app_module)
    mock_client.containers.list.return_value = []
    client = TestClient(app_module.app)

    response = client.get("/sandboxes")

    assert response.status_code == 200


# --------------------------------------------------------------------------
# to_host_path
# --------------------------------------------------------------------------


def test_to_host_path_translates_container_path_to_host(monkeypatch):
    app_module = _reload_app(monkeypatch, projects_root_host="/host/projetos")

    resultado = app_module.to_host_path("/projects/minha-sessao/workspace")

    assert resultado == "/host/projetos/minha-sessao/workspace"


def test_to_host_path_rejects_path_outside_projects_root(monkeypatch):
    app_module = _reload_app(monkeypatch, projects_root_host="/host/projetos")

    with pytest.raises(HTTPException) as exc_info:
        app_module.to_host_path("/etc/passwd")

    assert exc_info.value.status_code == 400


def test_to_host_path_is_noop_without_host_root_configured(monkeypatch):
    # Sem PROJECTS_ROOT_HOST, não há tradução possível — devolve o caminho
    # normalizado como veio, sem recusar nada.
    app_module = _reload_app(monkeypatch, projects_root_host=None)

    resultado = app_module.to_host_path("/projects/qualquer-coisa/")

    assert resultado == "/projects/qualquer-coisa"


# --------------------------------------------------------------------------
# exec_command
# --------------------------------------------------------------------------


def test_exec_command_returns_decoded_output_on_success(monkeypatch):
    app_module = _reload_app(monkeypatch)
    mock_client = _with_mock_docker(app_module)
    mock_client.containers.get.return_value = MagicMock(id="container-123")
    mock_client.api.exec_create.return_value = {"Id": "exec-abc"}
    mock_client.api.exec_start.return_value = (b"ola mundo\n", b"")
    mock_client.api.exec_inspect.return_value = {"ExitCode": 0}
    client = TestClient(app_module.app)

    response = client.post(
        "/sandboxes/minha-sessao/exec",
        headers=AUTH_HEADERS,
        json={"command": "echo 'ola mundo'", "timeout": 5},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["exit_code"] == 0
    assert body["stdout"] == "ola mundo\n"
    assert body["stderr"] == ""
    assert body["timed_out"] is False


def test_exec_command_returns_404_when_sandbox_does_not_exist(monkeypatch):
    import docker.errors

    app_module = _reload_app(monkeypatch)
    mock_client = _with_mock_docker(app_module)
    mock_client.containers.get.side_effect = docker.errors.NotFound("não existe")
    client = TestClient(app_module.app)

    response = client.post(
        "/sandboxes/sessao-fantasma/exec",
        headers=AUTH_HEADERS,
        json={"command": "echo oi", "timeout": 5},
    )

    assert response.status_code == 404


def test_exec_command_times_out_without_hanging_the_test(monkeypatch):
    """A correção que este teste protege: antes, `exec_create`/`exec_start`/
    `exec_inspect` bloqueavam a coroutine direto, e não existia `wait_for`
    nenhum cortando a chamada — um comando lento no container prendia o
    único event loop do processo (derrubando /health e as outras sessões
    junto), e nunca devolvia 124. O mock de `exec_start` aqui dorme 3s; o
    request pede timeout de 1s. Se o `asyncio.wait_for` não estivesse
    cortando de verdade, esta chamada de teste levaria os 3s do sleep (ou
    mais) em vez de ~1s.
    """
    app_module = _reload_app(monkeypatch)
    mock_client = _with_mock_docker(app_module)
    mock_client.containers.get.return_value = MagicMock(id="container-123")
    mock_client.api.exec_create.return_value = {"Id": "exec-lento"}

    def _exec_start_lento(*args, **kwargs):
        time.sleep(3)
        return (b"nunca deveria aparecer", b"")

    mock_client.api.exec_start.side_effect = _exec_start_lento
    mock_client.api.exec_inspect.return_value = {"ExitCode": 0}

    # Precisa ser `with TestClient(...) as client:`, não `TestClient(...)`
    # solto: fora do context manager, o portal do TestClient é aberto e
    # fechado a cada chamada, e fechá-lo espera o `ThreadPoolExecutor` padrão
    # do asyncio terminar — o que inclui a thread da sandbox ainda dormindo
    # os 3s completos. Dentro do `with`, o portal (e o loop) ficam vivos
    # entre chamadas, então só o tempo real do `wait_for` conta.
    with TestClient(app_module.app) as client:
        inicio = time.perf_counter()
        response = client.post(
            "/sandboxes/sessao-lenta/exec",
            headers=AUTH_HEADERS,
            json={"command": "sleep 999", "timeout": 1},
        )
        duracao = time.perf_counter() - inicio

    assert response.status_code == 200
    body = response.json()
    assert body["exit_code"] == 124
    assert body["timed_out"] is True
    assert "excedeu" in body["stderr"]
    # Prova de que o corte é real, não só documentado: bem menor que os 3s
    # do sleep mockado.
    assert duracao < 2.5


# --------------------------------------------------------------------------
# create_sandbox / destroy_sandbox / list_sandboxes
# --------------------------------------------------------------------------


def test_create_sandbox_runs_new_container_when_none_exists(monkeypatch):
    app_module = _reload_app(monkeypatch, projects_root_host="/host/projetos")
    mock_client = _with_mock_docker(app_module)
    mock_client.containers.list.return_value = []
    mock_client.containers.run.return_value = MagicMock(id="novo-container-id")
    client = TestClient(app_module.app)

    response = client.post(
        "/sandboxes",
        headers=AUTH_HEADERS,
        json={"session_id": "minha-sessao", "workspace": "/projects/minha-sessao"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "novo-container-id"
    assert body["name"] == "novaai-studio-minha-sessao"
    assert body["reused"] is False
    assert body["host_path"] == "/host/projetos/minha-sessao"
    mock_client.containers.run.assert_called_once()
    kwargs = mock_client.containers.run.call_args.kwargs
    assert kwargs["environment"]["PIP_RETRIES"] == "0"
    assert kwargs["environment"]["PIP_DISABLE_PIP_VERSION_CHECK"] == "1"


def test_create_sandbox_reuses_existing_container(monkeypatch):
    app_module = _reload_app(monkeypatch, projects_root_host="/host/projetos")
    mock_client = _with_mock_docker(app_module)
    container_existente = MagicMock(id="ja-existe-id", status="exited")
    mock_client.containers.list.return_value = [container_existente]
    client = TestClient(app_module.app)

    response = client.post(
        "/sandboxes",
        headers=AUTH_HEADERS,
        json={"session_id": "minha-sessao", "workspace": "/projects/minha-sessao"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reused"] is True
    assert body["id"] == "ja-existe-id"
    container_existente.start.assert_called_once()
    mock_client.containers.run.assert_not_called()


def test_destroy_sandbox_removes_existing_container(monkeypatch):
    app_module = _reload_app(monkeypatch)
    mock_client = _with_mock_docker(app_module)
    container = MagicMock()
    mock_client.containers.get.return_value = container
    client = TestClient(app_module.app)

    response = client.delete("/sandboxes/minha-sessao", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json() == {"removed": True}
    container.remove.assert_called_once_with(force=True)


def test_destroy_sandbox_reports_when_container_did_not_exist(monkeypatch):
    import docker.errors

    app_module = _reload_app(monkeypatch)
    mock_client = _with_mock_docker(app_module)
    mock_client.containers.get.side_effect = docker.errors.NotFound("não existe")
    client = TestClient(app_module.app)

    response = client.delete("/sandboxes/sessao-fantasma", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json() == {"removed": False, "reason": "não existia"}


def test_list_sandboxes_returns_expected_shape(monkeypatch):
    app_module = _reload_app(monkeypatch)
    mock_client = _with_mock_docker(app_module)
    # `name` é um kwarg especial do construtor do Mock (define o repr, não o
    # atributo) — precisa ser atribuído depois de criado.
    container = MagicMock(status="running", labels={app_module.LABEL: "minha-sessao"})
    container.name = "novaai-studio-minha-sessao"
    container.attrs = {"Created": "2026-07-30T00:00:00Z"}
    mock_client.containers.list.return_value = [container]
    client = TestClient(app_module.app)

    response = client.get("/sandboxes", headers=AUTH_HEADERS)

    assert response.status_code == 200
    sandboxes = response.json()["sandboxes"]
    assert len(sandboxes) == 1
    assert sandboxes[0]["session_id"] == "minha-sessao"
    assert sandboxes[0]["status"] == "running"
    assert sandboxes[0]["created"] == "2026-07-30T00:00:00Z"


# --------------------------------------------------------------------------
# get_sandbox_stats / cache do port-scan / get_server_logs
# (item 10 do plano de robustez do navegador interno: chamadas docker-py
# bloqueantes movidas para `asyncio.to_thread`, sem cobertura de teste antes)
# --------------------------------------------------------------------------


def _container_com_portas(portas: list[int]) -> MagicMock:
    container = MagicMock(id="stats-container-id", status="running")
    saida = "\n".join(str(p) for p in portas).encode("utf-8")
    container.exec_run.return_value = MagicMock(exit_code=0, output=saida)
    container.stats.return_value = {
        "memory_stats": {"usage": 100 * 1024 * 1024, "limit": 2048 * 1024 * 1024},
        "pids_stats": {"current": 3},
    }
    return container


def test_get_sandbox_stats_returns_ports_and_metrics(monkeypatch):
    app_module = _reload_app(monkeypatch)
    mock_client = _with_mock_docker(app_module)
    container = _container_com_portas([5000, 8000])
    mock_client.containers.get.return_value = container
    client = TestClient(app_module.app)

    response = client.get("/sandboxes/minha-sessao/stats", headers=AUTH_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["ports"] == [5000, 8000]
    assert body["metrics"]["memory_mb"] == 100.0
    assert body["metrics"]["pids_count"] == 3
    container.exec_run.assert_called_once()


def test_get_sandbox_stats_caches_port_scan_within_ttl(monkeypatch):
    """Dois polls seguidos (StatusBar + EditorBrowserView pollam a mesma
    sessão de forma independente hoje) não podem disparar dois `exec_run`
    caros contra `/proc/net/tcp` — o segundo, dentro do TTL do cache,
    reaproveita o resultado do primeiro."""
    app_module = _reload_app(monkeypatch)
    mock_client = _with_mock_docker(app_module)
    container = _container_com_portas([5000])
    mock_client.containers.get.return_value = container
    client = TestClient(app_module.app)

    client.get("/sandboxes/minha-sessao/stats", headers=AUTH_HEADERS)
    client.get("/sandboxes/minha-sessao/stats", headers=AUTH_HEADERS)

    assert container.exec_run.call_count == 1


def test_get_sandbox_stats_rescans_ports_after_cache_ttl_expires(monkeypatch):
    app_module = _reload_app(monkeypatch)
    monkeypatch.setattr(app_module, "PORT_SCAN_CACHE_TTL_SECONDS", 0.0)
    mock_client = _with_mock_docker(app_module)
    container = _container_com_portas([5000])
    mock_client.containers.get.return_value = container
    client = TestClient(app_module.app)

    client.get("/sandboxes/minha-sessao/stats", headers=AUTH_HEADERS)
    client.get("/sandboxes/minha-sessao/stats", headers=AUTH_HEADERS)

    assert container.exec_run.call_count == 2


def test_get_sandbox_stats_returns_404_when_sandbox_does_not_exist(monkeypatch):
    import docker.errors

    app_module = _reload_app(monkeypatch)
    mock_client = _with_mock_docker(app_module)
    mock_client.containers.get.side_effect = docker.errors.NotFound("não existe")
    client = TestClient(app_module.app)

    response = client.get("/sandboxes/sessao-fantasma/stats", headers=AUTH_HEADERS)

    assert response.status_code == 404


def test_get_server_logs_returns_decoded_tail(monkeypatch):
    app_module = _reload_app(monkeypatch)
    mock_client = _with_mock_docker(app_module)
    container = MagicMock(id="logs-container-id")
    container.exec_run.return_value = MagicMock(exit_code=0, output=b"linha 1\nlinha 2\n")
    mock_client.containers.get.return_value = container
    client = TestClient(app_module.app)

    response = client.get("/sandboxes/minha-sessao/logs/server", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json()["logs"] == "linha 1\nlinha 2\n"


def test_destroy_sandbox_clears_port_scan_cache(monkeypatch):
    """Sem isto, um novo container recriado para a mesma sessão poderia
    herdar por engano portas escaneadas do container anterior (destruído)
    até o TTL do cache expirar sozinho."""
    app_module = _reload_app(monkeypatch)
    mock_client = _with_mock_docker(app_module)
    app_module._port_scan_cache["minha-sessao"] = (time.time(), [1234])
    mock_client.containers.get.return_value = MagicMock()
    client = TestClient(app_module.app)

    client.delete("/sandboxes/minha-sessao", headers=AUTH_HEADERS)

    assert "minha-sessao" not in app_module._port_scan_cache


# --------------------------------------------------------------------------
# reap + tetos de tamanho dos caches (item 11 do plano de robustez do
# navegador interno)
# --------------------------------------------------------------------------


def test_reap_removes_unrecognized_containers_and_clears_their_caches(monkeypatch):
    """Uma sessão removida via `/sandboxes/reap` (a API não a reconhece mais)
    passava batido por `_container_cache`/`_port_scan_cache` — a próxima
    chamada de stats para essa sessão reaproveitaria um id de container que
    não existe mais até o lookup por nome se autocorrigir."""
    app_module = _reload_app(monkeypatch)
    mock_client = _with_mock_docker(app_module)
    orfao = MagicMock(labels={app_module.LABEL: "sessao-orfa"})
    mantida = MagicMock(labels={app_module.LABEL: "sessao-mantida"})
    mock_client.containers.list.return_value = [orfao, mantida]
    app_module._container_cache["sessao-orfa"] = "id-orfao"
    app_module._container_cache["sessao-mantida"] = "id-mantido"
    app_module._port_scan_cache["sessao-orfa"] = (time.time(), [1234])
    client = TestClient(app_module.app)

    # `keep` chega como corpo JSON de lista pura (ver
    # `apps/api/src/novaai_studio/sandbox/executor.py::reap_orphans`,
    # `json=list(self._sandboxes)`), não como query param.
    response = client.post(
        "/sandboxes/reap", headers=AUTH_HEADERS, json=["sessao-mantida"]
    )

    assert response.status_code == 200
    assert response.json() == {"removed": 1}
    orfao.remove.assert_called_once_with(force=True)
    mantida.remove.assert_not_called()
    assert "sessao-orfa" not in app_module._container_cache
    assert "sessao-orfa" not in app_module._port_scan_cache
    assert app_module._container_cache["sessao-mantida"] == "id-mantido"


def test_cache_container_id_evicts_oldest_entry_past_the_cap(monkeypatch):
    app_module = _reload_app(monkeypatch)
    monkeypatch.setattr(app_module, "_MAX_CACHED_CONTAINERS", 2)

    app_module._cache_container_id("s1", "id-1")
    app_module._cache_container_id("s2", "id-2")
    app_module._cache_container_id("s3", "id-3")

    assert len(app_module._container_cache) == 2
    assert "s1" not in app_module._container_cache
    assert app_module._container_cache["s3"] == "id-3"


# --------------------------------------------------------------------------
# item 20: handlers do item 10 não bloqueiam o event loop
# --------------------------------------------------------------------------


def test_get_sandbox_stats_does_not_block_the_event_loop(monkeypatch):
    """Prova positiva de concorrência (não só timeout-cutting, que já é
    coberto por `test_exec_command_times_out_without_hanging_the_test`
    acima): enquanto `get_sandbox_stats` está presa dentro do
    `asyncio.to_thread` esperando um `container.stats()` lento, uma
    corrotina concorrente no MESMO event loop precisa continuar avançando
    livremente. Antes do item 10 (chamada docker-py síncrona direto dentro
    de `async def`), essa sonda ficaria inteiramente presa atrás da chamada
    lenta — o teste falharia por `progresso` nunca chegar a 5.
    """
    app_module = _reload_app(monkeypatch)
    mock_client = _with_mock_docker(app_module)
    container = _container_com_portas([5000])

    def _stats_lenta(*args, **kwargs):
        time.sleep(0.5)
        return {
            "memory_stats": {"usage": 100 * 1024 * 1024, "limit": 2048 * 1024 * 1024},
            "pids_stats": {"current": 3},
        }

    container.stats.side_effect = _stats_lenta
    mock_client.containers.get.return_value = container

    async def cenario():
        progresso: list[int] = []

        async def sonda_concorrente():
            for i in range(10):
                await asyncio.sleep(0.05)
                progresso.append(i)

        resultado, _ = await asyncio.gather(
            app_module.get_sandbox_stats("minha-sessao"), sonda_concorrente()
        )
        return resultado, progresso

    resultado, progresso = asyncio.run(cenario())

    assert resultado["metrics"]["memory_mb"] == 100.0
    # As 10 iterações da sonda (0.5s no total) precisam ter progredido
    # inteiras enquanto os 0.5s de `container.stats()` corriam em paralelo
    # numa thread separada — não em série, presas atrás dela.
    assert progresso == list(range(10))


def test_get_server_logs_does_not_block_the_event_loop(monkeypatch):
    app_module = _reload_app(monkeypatch)
    mock_client = _with_mock_docker(app_module)
    container = MagicMock(id="logs-lento")

    def _exec_run_lento(*args, **kwargs):
        time.sleep(0.5)
        return MagicMock(exit_code=0, output=b"linha 1\n")

    container.exec_run.side_effect = _exec_run_lento
    mock_client.containers.get.return_value = container

    async def cenario():
        progresso: list[int] = []

        async def sonda_concorrente():
            for i in range(10):
                await asyncio.sleep(0.05)
                progresso.append(i)

        resultado, _ = await asyncio.gather(
            app_module.get_server_logs("minha-sessao"), sonda_concorrente()
        )
        return resultado, progresso

    resultado, progresso = asyncio.run(cenario())

    assert resultado["logs"] == "linha 1\n"
    assert progresso == list(range(10))
