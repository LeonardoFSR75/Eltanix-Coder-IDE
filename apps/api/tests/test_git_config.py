"""Testes das configurações de conta Git e GitHub."""

from __future__ import annotations

import os
import pytest
from fastapi.testclient import TestClient
from git import Repo

os.environ["NOVAAI_STUDIO_API_KEY"] = "chave-de-teste"

from novaai_studio.config import get_settings
from novaai_studio.main import create_app
from novaai_studio.workspace import git as git_ops


@pytest.fixture
def repo(tmp_path):
    caminho = tmp_path / "projeto"
    caminho.mkdir()
    repositorio = Repo.init(caminho, initial_branch="main")
    with repositorio.config_writer() as config:
        config.set_value("user", "name", "Desenvolvedor NovaAI Studio")
        config.set_value("user", "email", "dev@novaai-studio.com")
        config.set_value("init", "defaultBranch", "main")
    return caminho


@pytest.fixture(scope="module")
def api_client():
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        yield client


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer chave-de-teste"}


def test_get_git_user_config_reads_local_repo(repo):
    cfg = git_ops.get_git_user_config(root=repo)
    assert cfg["local_user_name"] == "Desenvolvedor NovaAI Studio"
    assert cfg["local_user_email"] == "dev@novaai-studio.com"
    assert isinstance(cfg["ssh_keys"], list)


def test_update_git_user_config_local_scope(repo):
    novo_cfg = git_ops.update_git_user_config(
        user_name="Novo Nome",
        user_email="novo@novaai-studio.com",
        scope="local",
        root=repo,
    )
    assert novo_cfg["local_user_name"] == "Novo Nome"
    assert novo_cfg["local_user_email"] == "novo@novaai-studio.com"


def test_git_config_api_routes(api_client, auth_headers):
    # GET /api/git/config
    res = api_client.get("/api/git/config", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert "user_name" in data
    assert "user_email" in data
    assert "ssh_keys" in data

    # GET /api/git/github/config
    res_gh = api_client.get("/api/git/github/config", headers=auth_headers)
    assert res_gh.status_code == 200
    gh_data = res_gh.json()
    assert "status" in gh_data
    assert "token_source" in gh_data

    # POST /api/git/github/config/test (token inválido)
    res_test = api_client.post(
        "/api/git/github/config/test",
        json={"token": "invalid_test_token_123"},
        headers=auth_headers,
    )
    assert res_test.status_code == 200
    test_data = res_test.json()
    assert test_data["valid"] is False
    assert test_data["user"] is None
