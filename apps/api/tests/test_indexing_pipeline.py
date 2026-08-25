"""Pipeline de indexação rodando contra o código real do projeto.

Fixture sintética esconde o que quebra na prática: arquivo com encoding
estranho, símbolo aninhado fundo, classe sem métodos. Aqui o alvo é o próprio
`apps/api/src`, então qualquer regressão do chunker em código de verdade
aparece.

Só a parte que não precisa de banco: varredura, corte e mapa. Persistência e
busca híbrida exigem Postgres com pgvector e estão cobertas pelo runbook.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import eltanix
from eltanix.context.chunker import chunk_file
from eltanix.context.scanner import read_text, scan

# Localizado pelo próprio pacote, e não contado a partir da raiz do repositório:
# no checkout ele fica em `apps/api/src/eltanix`, na imagem em `/app/src/
# eltanix`. Contar níveis fixos faria estes testes sumirem em silêncio dentro
# do container — sem falhar, sem pular, apenas varrendo um diretório vazio.
API_SRC = Path(eltanix.__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def indexed():
    """Varre e corta o código do projeto uma vez para todos os testes."""
    files = list(scan(API_SRC))
    results = []
    for scanned in files:
        content = read_text(scanned.absolute)
        if content is None:
            continue
        results.append((scanned, chunk_file(scanned.path, content, scanned.language)))
    return results


def test_scan_finds_the_project_source(indexed):
    paths = {scanned.path for scanned, _ in indexed}
    assert any(p.endswith("router/engine.py") for p in paths)
    assert any(p.endswith("context/chunker.py") for p in paths)


def test_python_files_use_symbol_chunking_not_fallback(indexed):
    python_files = [
        (scanned, result)
        for scanned, result in indexed
        if scanned.language == "python"
        and scanned.size_bytes > 2000
        and not scanned.path.endswith("__init__.py")
    ]
    assert python_files, "esperava encontrar arquivos Python substanciais"

    fallbacks = [s.path for s, r in python_files if r.fallback_used]
    assert not fallbacks, f"corte por símbolo falhou em: {fallbacks}"


def test_known_symbols_are_extracted(indexed):
    by_path = {scanned.path: result for scanned, result in indexed}

    engine = next(r for p, r in by_path.items() if p.endswith("router/engine.py"))
    symbols = {c.qualified_name for c in engine.chunks if c.symbol}

    assert "RouterEngine" in symbols
    assert "RouterEngine.complete" in symbols
    assert "RouterEngine.stream" in symbols


def test_no_chunk_is_empty_or_unbounded(indexed):
    for _scanned, result in indexed:
        for chunk in result.chunks:
            assert chunk.content.strip(), f"chunk vazio em {chunk.path}"
            assert chunk.token_count > 0
            assert chunk.end_line >= chunk.start_line


def test_chunks_cover_a_reasonable_share_of_each_file(indexed):
    """Um corte que perde metade do arquivo transformaria a busca em loteria."""
    for scanned, result in indexed:
        if scanned.language != "python" or scanned.size_bytes < 3000:
            continue
        content = read_text(scanned.absolute) or ""
        total_lines = len(content.splitlines())
        covered = set()
        for chunk in result.chunks:
            covered.update(range(chunk.start_line, chunk.end_line + 1))
        cobertura = len(covered) / max(1, total_lines)
        assert cobertura > 0.7, f"{scanned.path}: só {cobertura:.0%} das linhas viraram chunk"


def test_average_chunk_is_small_enough_to_be_useful(indexed):
    tokens = [c.token_count for _s, r in indexed for c in r.chunks]
    assert tokens
    media = sum(tokens) / len(tokens)
    # Chunk gigante devolve contexto irrelevante junto com o relevante e gasta
    # token à toa; a média precisa ficar bem abaixo do teto de corte.
    assert media < 400, f"média de {media:.0f} tokens por chunk está alta demais"
