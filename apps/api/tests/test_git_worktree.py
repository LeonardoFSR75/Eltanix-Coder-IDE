"""Git de verdade em repositórios temporários.

O worktree por sessão é a peça que impede o agente de mexer na árvore em que
você está trabalhando. É testável sem nenhum mock, então é testado assim.
"""

from __future__ import annotations

import pytest
from git import Repo

from sicoobito.workspace import git as git_ops
from sicoobito.workspace.git import GitError


@pytest.fixture
def repo(tmp_path):
    caminho = tmp_path / "projeto"
    caminho.mkdir()
    repositorio = Repo.init(caminho, initial_branch="main")
    with repositorio.config_writer() as config:
        config.set_value("user", "name", "Teste")
        config.set_value("user", "email", "teste@exemplo.com")

    (caminho / "app.py").write_text("print('v1')\n", encoding="utf-8")
    repositorio.index.add(["app.py"])
    repositorio.index.commit("commit inicial")
    return caminho


def test_status_reports_a_clean_tree(repo):
    estado = git_ops.status(repo)
    assert estado.branch == "main"
    assert estado.dirty is False
    assert estado.files == []


def test_status_reports_modified_and_untracked(repo):
    (repo / "app.py").write_text("print('v2')\n", encoding="utf-8")
    (repo / "novo.py").write_text("x = 1\n", encoding="utf-8")

    estado = git_ops.status(repo)
    por_arquivo = {f.path: f.status for f in estado.files}

    assert estado.dirty is True
    assert por_arquivo["app.py"] == "modified"
    assert por_arquivo["novo.py"] == "untracked"


def test_diff_shows_the_change(repo):
    (repo / "app.py").write_text("print('v2')\n", encoding="utf-8")
    saida = git_ops.diff(repo)
    assert "-print('v1')" in saida
    assert "+print('v2')" in saida


def test_worktree_isolates_the_agent_from_your_tree(repo):
    # O ponto inteiro do worktree: você mexe na sua árvore, o agente na dele.
    (repo / "meu-trabalho.py").write_text("em andamento\n", encoding="utf-8")

    worktree = git_ops.create_worktree(repo, "abc123")

    assert worktree.path.exists()
    assert worktree.branch == "sicoobito/abc123"
    assert worktree.base_branch == "main"
    # A árvore principal continua no branch dela, com o trabalho intacto.
    assert git_ops.status(repo).branch == "main"
    assert (repo / "meu-trabalho.py").read_text(encoding="utf-8") == "em andamento\n"


def test_agent_changes_do_not_leak_into_the_main_tree(repo):
    worktree = git_ops.create_worktree(repo, "sessao1")

    (worktree.path / "do-agente.py").write_text("gerado\n", encoding="utf-8")
    git_ops.commit(worktree.path, "adiciona arquivo do agente")

    assert not (repo / "do-agente.py").exists()
    assert git_ops.status(repo).dirty is False


def test_commit_in_worktree_lands_on_the_session_branch(repo):
    worktree = git_ops.create_worktree(repo, "sessao2")
    (worktree.path / "x.py").write_text("y = 1\n", encoding="utf-8")

    sha = git_ops.commit(worktree.path, "mudança do agente")

    historico = git_ops.log_recent(worktree.path, limit=1)
    assert historico[0]["sha"] == sha[:8]
    assert historico[0]["message"] == "mudança do agente"
    # E não aparece no histórico do main.
    assert git_ops.log_recent(repo, limit=1)[0]["message"] == "commit inicial"


def test_commit_with_nothing_staged_fails_clearly(repo):
    with pytest.raises(GitError, match="Nada para commitar"):
        git_ops.commit(repo, "vazio")


def test_reopening_a_session_reuses_its_worktree(repo):
    primeiro = git_ops.create_worktree(repo, "retomada")
    (primeiro.path / "parcial.py").write_text("trabalho em andamento\n", encoding="utf-8")

    segundo = git_ops.create_worktree(repo, "retomada")

    assert segundo.path == primeiro.path
    assert (segundo.path / "parcial.py").exists()


def test_remove_worktree_cleans_up(repo):
    worktree = git_ops.create_worktree(repo, "descartavel")
    assert worktree.path.exists()

    git_ops.remove_worktree(repo, "descartavel", delete_branch=True)

    assert not worktree.path.exists()
    assert "sicoobito/descartavel" not in {b.name for b in Repo(repo).branches}


def test_worktree_auto_initializes_commit_if_empty(tmp_path):
    vazio = tmp_path / "vazio"
    vazio.mkdir()
    Repo.init(vazio, initial_branch="main")

    worktree = git_ops.create_worktree(vazio, "x")
    assert worktree.path.exists()
    assert Repo(vazio).head.is_valid()


def test_worktree_auto_initializes_git_when_project_is_not_a_repo(tmp_path):
    sem_repo = tmp_path / "sem_repo"
    sem_repo.mkdir()

    worktree = git_ops.create_worktree(sem_repo, "semrepo")

    assert worktree.path.exists()
    assert (sem_repo / ".git").exists()
    assert Repo(sem_repo).head.is_valid()


def test_open_repo_on_a_plain_directory_fails(tmp_path):
    with pytest.raises(GitError, match="não é um repositório Git"):
        git_ops.status(tmp_path)


def test_push_without_remote_fails_clearly(repo):
    with pytest.raises(GitError, match="Remote 'origin' não existe"):
        git_ops.push(repo, "main")
