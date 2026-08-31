"""Validação do catálogo: dimensão de embedding e capability trocada.

O bug que motivou estes testes: `EMBEDDING_DIM=768` (nomic) com
`databricks/bge-large-en` (1024) como primeiro candidato do perfil
`embedding`. Nada reclamava na carga; o INSERT do vetor é que falhava, no meio
de uma indexação, arquivo por arquivo.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from eltanix.router.catalog import RouteProfile, load_catalog, validate_catalog


def _escreve(tmp_path: Path, providers: str, routes: str) -> tuple[Path, Path]:
    p = tmp_path / "providers.yaml"
    r = tmp_path / "routes.yaml"
    p.write_text(textwrap.dedent(providers), encoding="utf-8")
    r.write_text(textwrap.dedent(routes), encoding="utf-8")
    return p, r


_ROUTES_PADRAO = """
    default_profile: auto
    profiles:
      embedding:
        strategy: priority
        models: [x/embed-grande, x/embed-certo]
"""


def test_dimensao_divergente_desabilita_o_modelo(tmp_path: Path) -> None:
    providers, routes = _escreve(
        tmp_path,
        """
        providers:
          - id: x/embed-grande
            provider: x
            model: grande
            embedding_dim: 1024
            capabilities: [embedding]
          - id: x/embed-certo
            provider: x
            model: certo
            embedding_dim: 768
            capabilities: [embedding]
        """,
        _ROUTES_PADRAO,
    )

    catalog = load_catalog(providers, routes, expected_embedding_dim=768)

    grande = catalog.get("x/embed-grande")
    certo = catalog.get("x/embed-certo")
    assert grande is not None and certo is not None
    assert grande.enabled is False
    assert "1024" in (grande.unavailable_reason or "")
    # O que cabe na coluna continua de pé: o perfil degrada, não morre.
    assert certo.enabled is True
    assert [i.model_id for i in catalog.issues if i.fatal] == ["x/embed-grande"]


def test_embedding_sem_dimensao_declarada_e_fatal(tmp_path: Path) -> None:
    providers, routes = _escreve(
        tmp_path,
        """
        providers:
          - id: x/embed-mudo
            provider: x
            model: mudo
            capabilities: [embedding]
        """,
        """
        default_profile: auto
        profiles:
          embedding:
            strategy: priority
            models: [x/embed-mudo]
        """,
    )

    catalog = load_catalog(providers, routes, expected_embedding_dim=768)

    modelo = catalog.get("x/embed-mudo")
    assert modelo is not None
    assert modelo.enabled is False
    assert "embedding_dim" in (modelo.unavailable_reason or "")


def test_sem_dimensao_esperada_a_conferencia_de_compatibilidade_nao_roda(tmp_path: Path) -> None:
    """Quem chama sem `expected_embedding_dim` não sabe qual é a coluna — não
    dá para acusar incompatibilidade com um número que ninguém informou."""
    providers, routes = _escreve(
        tmp_path,
        """
        providers:
          - id: x/embed-grande
            provider: x
            model: grande
            embedding_dim: 1024
            capabilities: [embedding]
        """,
        """
        default_profile: auto
        profiles:
          embedding:
            strategy: priority
            models: [x/embed-grande]
        """,
    )

    catalog = load_catalog(providers, routes)

    modelo = catalog.get("x/embed-grande")
    assert modelo is not None
    assert modelo.enabled is True
    assert catalog.issues == []


def test_id_de_embedding_cadastrado_como_chat(tmp_path: Path) -> None:
    """O caso do `databricks/qwen3-embedding-0-6b`: modelo de embedding que
    entrou no pool de chat pela sincronização automática do catálogo."""
    providers, routes = _escreve(
        tmp_path,
        """
        providers:
          - id: y/qwen3-embedding-0-6b
            provider: y
            model: qwen3
            capabilities: [chat]
        """,
        """
        default_profile: auto
        profiles:
          auto:
            strategy: priority
            models: [y/qwen3-embedding-0-6b]
        """,
    )

    catalog = load_catalog(providers, routes, expected_embedding_dim=768)

    modelo = catalog.get("y/qwen3-embedding-0-6b")
    assert modelo is not None
    assert modelo.enabled is False
    assert "capabilities" in (modelo.unavailable_reason or "")


def test_modelo_de_embedding_em_perfil_de_chat_e_so_aviso() -> None:
    """Não é fatal: o pedido falha no provedor, mas nada corrompe o índice."""
    from eltanix.router.catalog import ModelSpec

    modelos = {
        "x/embed": ModelSpec(
            id="x/embed", provider="x", capabilities=["embedding"], embedding_dim=768
        )
    }
    perfis = {"coding": RouteProfile(name="coding", strategy="priority", models=["x/embed"])}

    issues = validate_catalog(modelos, perfis, expected_embedding_dim=768)

    assert len(issues) == 1
    assert issues[0].fatal is False
    assert "perfil de chat" in issues[0].message


def test_modelo_desabilitado_no_yaml_nao_gera_issue() -> None:
    """Quem já está fora do pool não precisa ser acusado de nada."""
    from eltanix.router.catalog import ModelSpec

    modelos = {
        "x/embed": ModelSpec(id="x/embed", provider="x", capabilities=["embedding"], enabled=False)
    }

    assert validate_catalog(modelos, {}, expected_embedding_dim=768) == []


@pytest.mark.parametrize(
    "model_id",
    [
        "ollama/nomic-embed-text",
        "databricks/bge-large-en",
        "databricks/databricks-qwen3-embedding-0-6b",
    ],
)
def test_catalogo_real_declara_dimensao_em_todo_modelo_de_embedding(catalog, model_id: str) -> None:
    """Guarda contra regressão no `config/providers.yaml` de verdade: um
    modelo de embedding novo sem `embedding_dim` seria desabilitado no boot,
    e é melhor descobrir isso aqui."""
    spec = catalog.get(model_id)
    assert spec is not None, f"{model_id} sumiu de providers.yaml"
    assert spec.is_embedding, f"{model_id} deveria ter capability `embedding`"
    assert spec.embedding_dim is not None, f"{model_id} sem embedding_dim declarado"
