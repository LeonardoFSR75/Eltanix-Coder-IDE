"""Ferramentas do agente: classificação de risco e comportamento.

A classificação vive na definição da ferramenta, não no chamador. Se dependesse
de quem chama, bastaria um caminho de código esquecer a checagem para o agente
escrever sem aprovação — por isso o primeiro bloco de testes trava exatamente
isso.
"""

from __future__ import annotations

import pytest

from sicoobito.agent.tools import RiskClass, ToolContext, registry
from sicoobito.agent.tools.shell import summarize_output
from sicoobito.workspace.fs import WorkspaceFS


@pytest.fixture
def ctx(tmp_path):
    (tmp_path / "app.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (tmp_path / "dup.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
    return ToolContext(
        session_id="teste",
        workspace_root=tmp_path,
        fs=WorkspaceFS(tmp_path),
    )


# ── Classificação de risco ──────────────────────────────────────────────────


def test_read_tools_do_not_require_approval():
    for nome in ("read_file", "list_files", "search_code", "git_status", "git_diff", "read_issue"):
        ferramenta = registry.get(nome)
        assert ferramenta is not None, nome
        assert ferramenta.risk is RiskClass.READ
        assert ferramenta.risk.requires_approval is False


def test_mutating_tools_require_approval():
    for nome in ("write_file", "edit_file", "git_commit", "open_pull_request"):
        ferramenta = registry.get(nome)
        assert ferramenta is not None, nome
        assert ferramenta.risk is RiskClass.WRITE
        assert ferramenta.risk.requires_approval is True


def test_command_execution_is_its_own_risk_class():
    ferramenta = registry.get("run_command")
    assert ferramenta.risk is RiskClass.EXEC
    assert ferramenta.risk.requires_approval is True


def test_ask_mode_receives_no_write_or_exec_tools():
    # Restringir por schema é mais confiável que instruir o modelo a não chamar.
    nomes = {t["function"]["name"] for t in registry.schemas(allow_exec=False, allow_write=False)}
    assert "read_file" in nomes
    assert "write_file" not in nomes
    assert "run_command" not in nomes


def test_edit_mode_allows_writing_but_not_executing():
    nomes = {t["function"]["name"] for t in registry.schemas(allow_exec=False, allow_write=True)}
    assert "edit_file" in nomes
    assert "run_command" not in nomes


def test_every_tool_exposes_a_valid_openai_schema():
    for ferramenta in registry.all():
        schema = ferramenta.to_openai_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == ferramenta.name
        assert schema["function"]["description"].strip()
        assert schema["function"]["parameters"]["type"] == "object"


def test_approval_summaries_are_human_readable():
    # É este texto que a pessoa lê antes de aprovar; JSON cru não serve.
    resumo = registry.get("write_file").describe_call({"path": "a.py", "content": "x"})
    assert "a.py" in resumo and "{" not in resumo

    resumo = registry.get("run_command").describe_call({"command": "pytest -q"})
    assert "pytest -q" in resumo


# ── Comportamento ───────────────────────────────────────────────────────────


async def test_read_file_returns_content(ctx):
    resultado = await registry.get("read_file").handler(ctx, {"path": "app.py"})
    assert resultado.ok
    assert "def f()" in resultado.content


async def test_read_file_outside_workspace_returns_error_not_exception(ctx):
    # O modelo precisa ler o erro para corrigir; exceção mataria o turno.
    resultado = await registry.get("read_file").handler(ctx, {"path": "../fora.txt"})
    assert resultado.ok is False
    assert "ERRO" in resultado.content


async def test_edit_file_replaces_and_returns_a_diff(ctx):
    resultado = await registry.get("edit_file").handler(
        ctx, {"path": "app.py", "old_text": "return 1", "new_text": "return 2"}
    )
    assert resultado.ok
    assert "-    return 1" in resultado.data["diff"]
    assert "+    return 2" in resultado.data["diff"]
    assert "return 2" in ctx.fs.read("app.py")


async def test_edit_file_matches_across_line_ending_conventions(ctx, tmp_path):
    # O modelo escreve `old_text` com \n; um arquivo criado no Windows tem \r\n.
    # Comparar cru faria toda edição falhar com "trecho não encontrado", de
    # forma silenciosa e sistemática.
    (tmp_path / "crlf.py").write_bytes(b"def f():\r\n    return 1\r\n")

    resultado = await registry.get("edit_file").handler(
        ctx,
        {
            "path": "crlf.py",
            "old_text": "def f():\n    return 1",
            "new_text": "def f():\n    return 2",
        },
    )

    assert resultado.ok, resultado.content
    # E a convenção original do arquivo é preservada: converter tudo para LF
    # transformaria uma edição de uma linha num diff do arquivo inteiro.
    assert (tmp_path / "crlf.py").read_bytes() == b"def f():\r\n    return 2\r\n"


async def test_edit_file_preserves_lf_files_as_lf(ctx, tmp_path):
    (tmp_path / "lf.py").write_bytes(b"a = 1\nb = 2\n")

    resultado = await registry.get("edit_file").handler(
        ctx, {"path": "lf.py", "old_text": "b = 2", "new_text": "b = 3"}
    )

    assert resultado.ok
    assert (tmp_path / "lf.py").read_bytes() == b"a = 1\nb = 3\n"


async def test_edit_file_refuses_ambiguous_matches(ctx):
    # Substituir a primeira ocorrência silenciosamente editaria o lugar errado.
    antes = ctx.fs.read("dup.py")

    resultado = await registry.get("edit_file").handler(
        ctx, {"path": "dup.py", "old_text": "x = 1", "new_text": "x = 2"}
    )

    assert resultado.ok is False
    assert "2 vezes" in resultado.content
    assert ctx.fs.read("dup.py") == antes, "o arquivo não pode ter sido tocado"


async def test_edit_file_reports_a_missing_match_usefully(ctx):
    resultado = await registry.get("edit_file").handler(
        ctx, {"path": "app.py", "old_text": "não existe", "new_text": "y"}
    )
    assert resultado.ok is False
    assert "Leia o arquivo novamente" in resultado.content


async def test_run_command_without_sandbox_explains_why(ctx):
    resultado = await registry.get("run_command").handler(ctx, {"command": "ls"})
    assert resultado.ok is False
    assert "Docker" in resultado.content


async def test_open_pr_without_github_explains_what_is_missing(ctx):
    resultado = await registry.get("open_pull_request").handler(
        ctx, {"title": "t", "body": "b"}
    )
    assert resultado.ok is False
    assert "GITHUB_TOKEN" in resultado.content


# ── Truncamento de saída de comando ─────────────────────────────────────────


def test_short_output_is_not_truncated():
    texto = "\n".join(f"linha {i}" for i in range(20))
    assert summarize_output(texto) == texto


def test_long_output_keeps_head_and_tail():
    texto = "\n".join(f"linha {i}" for i in range(500))
    resumo = summarize_output(texto)

    assert "linha 0" in resumo
    assert "linha 499" in resumo
    assert len(resumo) < len(texto)
    assert "omitidas" in resumo


def test_error_lines_survive_truncation():
    # A saída de teste é o maior desperdício de token de uma sessão agêntica,
    # mas justamente as linhas de falha são as que importam.
    linhas = [f"ok {i}" for i in range(300)]
    linhas[150] = "FAILED tests/test_x.py::test_critico - AssertionError"
    linhas[151] = "E   assert 1 == 2"
    resumo = summarize_output("\n".join(linhas))

    assert "test_critico" in resumo
    assert "assert 1 == 2" in resumo
