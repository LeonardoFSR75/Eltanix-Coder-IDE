"""Carga do `config/eval_dataset.yaml`: defaults, expansão de ambiente e o
dataset de verdade que o gate mede.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from eltanix.config import REPO_ROOT
from eltanix.evals.dataset import load_dataset


def _escreve(tmp_path: Path, conteudo: str) -> Path:
    caminho = tmp_path / "eval_dataset.yaml"
    caminho.write_text(textwrap.dedent(conteudo), encoding="utf-8")
    return caminho


def test_defaults_preenchem_o_caso(tmp_path: Path) -> None:
    caminho = _escreve(
        tmp_path,
        """
        defaults:
          source: context
          root: /workspace
          limit: 8
        cases:
          - query: "onde fica o registro de ferramentas"
            expected_keywords: ["ToolRegistry"]
        """,
    )

    (caso,) = load_dataset(caminho)

    assert caso.source == "context"
    assert caso.root == "/workspace"
    assert caso.limit == 8


def test_caso_sobrescreve_o_default(tmp_path: Path) -> None:
    caminho = _escreve(
        tmp_path,
        """
        defaults:
          source: context
          root: /workspace
          limit: 8
        cases:
          - source: notes
            query: "política de reembolso"
            expected_keywords: ["reembolso"]
            limit: 3
        """,
    )

    (caso,) = load_dataset(caminho)

    assert caso.source == "notes"
    assert caso.limit == 3


def test_root_expande_variavel_de_ambiente(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ELTANIX_EVAL_ROOT", "/repo/eltanix")
    caminho = _escreve(
        tmp_path,
        """
        defaults:
          source: context
          root: "${ELTANIX_EVAL_ROOT}"
        cases:
          - query: "q"
            expected_keywords: ["x"]
        """,
    )

    (caso,) = load_dataset(caminho)

    assert caso.root == "/repo/eltanix"


def test_root_vazio_falha_com_mensagem_acionavel(tmp_path: Path, monkeypatch) -> None:
    """Variável não definida vira string vazia — o erro tem de dizer isso, e
    não "campo obrigatório ausente"."""
    monkeypatch.delenv("ELTANIX_EVAL_ROOT", raising=False)
    caminho = _escreve(
        tmp_path,
        """
        defaults:
          source: context
          root: "${ELTANIX_EVAL_ROOT}"
        cases:
          - query: "q"
            expected_keywords: ["x"]
        """,
    )

    with pytest.raises(ValidationError, match="ELTANIX_EVAL_ROOT"):
        load_dataset(caminho)


def test_arquivo_inexistente_devolve_lista_vazia(tmp_path: Path) -> None:
    assert load_dataset(tmp_path / "nao_existe.yaml") == []


def test_dataset_real_tem_massa_critica_e_esta_bem_formado(monkeypatch) -> None:
    """O dataset versionado precisa ser grande e variado o bastante para uma
    média significar alguma coisa: com dois casos, um acerto a mais move a
    métrica em 50 pontos percentuais e o gate não mede nada."""
    monkeypatch.setenv("ELTANIX_EVAL_ROOT", str(REPO_ROOT))
    casos = load_dataset(REPO_ROOT / "config" / "eval_dataset.yaml")

    assert len(casos) >= 80, f"dataset com apenas {len(casos)} casos"
    assert all(c.expected_keywords or c.expected_ids for c in casos)
    assert all(c.tags for c in casos), "todo caso precisa de tag para o gate fatiar"

    queries = [c.query for c in casos]
    assert len(set(queries)) == len(queries), "há query duplicada no dataset"

    # Uma query que já contém o identificador procurado passa só pelo
    # full-text e não mede o ramo vetorial — o caso viraria decoração.
    for caso in casos:
        for palavra in caso.expected_keywords:
            assert palavra.lower() not in caso.query.lower(), (
                f"a query {caso.query!r} entrega a resposta {palavra!r}"
            )

    assert len({tag for c in casos for tag in c.tags}) >= 10
