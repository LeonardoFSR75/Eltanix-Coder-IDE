"""A fronteira do workspace é a defesa mais importante do agente.

Um modelo não precisa ser malicioso para pedir `../../.ssh/id_rsa` — basta
alucinar. E conteúdo de README ou issue entra no contexto como dado; se algo ali
sugerir um caminho, ele chega até aqui.
"""

from __future__ import annotations

import pytest

from novaai_studio.workspace.fs import FileTooLargeError, PathEscapeError, WorkspaceFS


@pytest.fixture
def fs(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x = 1\ny = 2\nz = 3\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Projeto\n", encoding="utf-8")
    # Um arquivo sensível FORA da raiz, para provar que continua inalcançável.
    (tmp_path.parent / "segredo.txt").write_text("chave-secreta", encoding="utf-8")
    return WorkspaceFS(tmp_path)


def test_reads_a_file_inside_the_workspace(fs):
    assert fs.read("src/app.py").startswith("x = 1")


@pytest.mark.parametrize(
    "caminho",
    [
        "../segredo.txt",
        "../../segredo.txt",
        "src/../../segredo.txt",
        "./src/./../../segredo.txt",
    ],
)
def test_parent_traversal_is_refused(fs, caminho):
    with pytest.raises(PathEscapeError):
        fs.read(caminho)


def test_absolute_paths_are_refused(fs, tmp_path):
    with pytest.raises(PathEscapeError):
        fs.read(str(tmp_path / "src" / "app.py"))
    with pytest.raises(PathEscapeError):
        fs.read("/etc/passwd")


def test_windows_style_absolute_path_never_escapes(fs):
    """`C:/...` só é absoluto no Windows.

    Em Linux — onde a API roda — é um caminho *relativo* cujo primeiro segmento
    tem dois-pontos no nome. A propriedade que importa não é qual exceção sai,
    e sim que a leitura não alcance nada fora da raiz: no Windows a fronteira
    recusa; em Linux o caminho fica dentro do workspace, onde não existe.
    """
    with pytest.raises((PathEscapeError, FileNotFoundError)):
        fs.read("C:/Windows/System32/drivers/etc/hosts")


def test_backslash_traversal_is_refused(fs):
    # No Windows a barra invertida é separador válido; normalizamos antes de
    # resolver justamente para que isto não escape.
    with pytest.raises(PathEscapeError):
        fs.read("..\\segredo.txt")


def test_empty_path_is_refused(fs):
    with pytest.raises(PathEscapeError):
        fs.read("   ")


def test_symlink_pointing_outside_is_refused(fs, tmp_path):
    # Checar a string antes de resolver seria contornável exatamente assim.
    link = tmp_path / "atalho.txt"
    try:
        link.symlink_to(tmp_path.parent / "segredo.txt")
    except (OSError, NotImplementedError):
        pytest.skip("criação de symlink não permitida neste ambiente")

    with pytest.raises(PathEscapeError):
        fs.read("atalho.txt")


def test_write_creates_parent_directories(fs):
    fs.write("novo/dir/arquivo.py", "conteudo\n")
    assert fs.read("novo/dir/arquivo.py") == "conteudo\n"


def test_write_outside_the_workspace_is_refused(fs):
    with pytest.raises(PathEscapeError):
        fs.write("../invasao.txt", "x")


def test_write_preserves_line_endings_exactly(fs):
    # Sem newline="", o Python traduziria \n para \r\n no Windows e sujaria o
    # diff inteiro de um arquivo que deveria ter mudado numa linha só.
    fs.write("lf.txt", "a\nb\nc\n")
    assert (fs.root / "lf.txt").read_bytes() == b"a\nb\nc\n"


def test_read_lines_returns_a_numbered_range(fs):
    saida = fs.read_lines("src/app.py", 2, 3)
    assert "2  y = 2" in saida
    assert "3  z = 3" in saida
    assert "x = 1" not in saida


def test_oversized_file_is_refused_with_a_useful_message(fs):
    fs.write("grande.txt", "a" * 5000)
    with pytest.raises(FileTooLargeError) as erro:
        fs.read("grande.txt", max_bytes=1000)
    assert "read_lines" in str(erro.value)


def test_list_dir_hides_dependency_directories(fs):
    (fs.root / "node_modules").mkdir()
    (fs.root / ".git").mkdir()
    nomes = {e.path for e in fs.list_dir(".")}
    assert "src" in nomes
    assert "node_modules" not in nomes
    assert ".git" not in nomes


def test_exists_returns_false_instead_of_raising_for_escapes(fs):
    assert fs.exists("../segredo.txt") is False
    assert fs.exists("README.md") is True


def test_delete_refuses_directories(fs):
    with pytest.raises(IsADirectoryError):
        fs.delete("src")
