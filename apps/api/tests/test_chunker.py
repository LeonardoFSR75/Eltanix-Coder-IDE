"""O corte por símbolo é o que separa RAG de código de RAG de texto.

Estes testes verificam a propriedade que importa: cada chunk é uma unidade que
um humano reconheceria, e nenhuma função é cortada ao meio sem aviso.
"""

from __future__ import annotations

from eltanix.context.chunker import MAX_CHUNK_TOKENS, chunk_file
from eltanix.context.languages import detect_language, supports_symbols

PYTHON_SOURCE = '''
import os
from pathlib import Path

CONSTANTE = 42


def soma(a: int, b: int) -> int:
    """Soma dois números."""
    return a + b


class Calculadora:
    """Uma calculadora."""

    precisao = 2

    def multiplicar(self, a: int, b: int) -> int:
        return a * b

    def dividir(self, a: int, b: int) -> float:
        if b == 0:
            raise ValueError("divisão por zero")
        return a / b
'''

TYPESCRIPT_SOURCE = """
import { useState } from "react";

export interface Props {
  title: string;
}

export function Card({ title }: Props) {
  const [open, setOpen] = useState(false);
  return <div>{title}</div>;
}

export class Store {
  private items: string[] = [];

  add(item: string): void {
    this.items.push(item);
  }
}
"""


def test_detects_language_from_extension():
    assert detect_language("router/policy.py") == "python"
    assert detect_language("app/page.tsx") == "tsx"
    assert detect_language("main.go") == "go"
    assert detect_language("dados.parquet") is None


def test_python_is_chunked_by_symbol_not_by_size():
    result = chunk_file("calc.py", PYTHON_SOURCE, "python")

    assert result.fallback_used is False
    symbols = {c.symbol for c in result.chunks if c.symbol}
    assert "soma" in symbols
    assert "Calculadora" in symbols
    assert "multiplicar" in symbols
    assert "dividir" in symbols


def test_methods_carry_their_class_as_parent():
    result = chunk_file("calc.py", PYTHON_SOURCE, "python")

    metodo = next(c for c in result.chunks if c.symbol == "multiplicar")
    assert metodo.parent == "Calculadora"
    # O nome qualificado é o que aparece no repo map e na citação da busca.
    assert metodo.qualified_name == "Calculadora.multiplicar"


def test_class_shell_exists_even_when_the_header_is_one_line():
    # `class X:` seguido direto de um método daria uma casca curta demais para
    # passar no mínimo de caracteres. Esse é o único chunk cujo símbolo é a
    # própria classe: sem ele, buscar pelo nome da classe não acha nada.
    fonte = "class Minimal:\n    def metodo(self):\n        return 1\n"
    result = chunk_file("m.py", fonte, "python")

    casca = next(c for c in result.chunks if c.symbol == "Minimal" and c.kind == "class")
    assert "class Minimal" in casca.content
    # E traz o esboço de membros, que é o que dá substância à busca.
    assert "metodo" in casca.content


def test_decorated_symbols_keep_their_real_kind():
    # `decorated_definition` embrulha a definição real. Sem desembrulhar, todo
    # @dataclass, rota FastAPI e fixture viraria "block" e sumiria do repo map,
    # que filtra por tipo.
    fonte = (
        "from dataclasses import dataclass\n\n"
        "@dataclass\nclass Config:\n    nome: str\n\n"
        "@app.get('/x')\ndef handler():\n    return 1\n"
    )
    result = chunk_file("api.py", fonte, "python")
    kinds = {c.symbol: c.kind for c in result.chunks if c.symbol}

    assert kinds.get("Config") == "class"
    assert kinds.get("handler") == "function"


def test_decorated_class_is_not_nested_under_itself():
    # `decorated_definition` não tem campo `body`. Procurar o corpo nele
    # devolvia o próprio wrapper, e a recursão reencontrava a classe — que
    # aparecia como `Config.Config` no repo map.
    fonte = (
        "from dataclasses import dataclass\n\n"
        "@dataclass\nclass Config:\n    nome: str\n\n"
        "    def validar(self):\n        return True\n"
    )
    result = chunk_file("c.py", fonte, "python")

    qualificados = [c.qualified_name for c in result.chunks if c.symbol]
    assert "Config.Config" not in qualificados
    assert "Config" in qualificados
    assert "Config.validar" in qualificados


def test_module_level_code_is_not_lost():
    # Imports e constantes de topo são onde moram as dependências do arquivo;
    # perdê-los deixaria a busca cega para "quem importa o quê".
    result = chunk_file("calc.py", PYTHON_SOURCE, "python")

    module_chunks = [c for c in result.chunks if c.kind == "module"]
    joined = "\n".join(c.content for c in module_chunks)
    assert "import os" in joined
    assert "CONSTANTE" in joined


def test_chunks_are_ordered_by_position():
    result = chunk_file("calc.py", PYTHON_SOURCE, "python")
    lines = [c.start_line for c in result.chunks]
    assert lines == sorted(lines)


def test_every_chunk_reports_its_lines_and_tokens():
    result = chunk_file("calc.py", PYTHON_SOURCE, "python")
    for chunk in result.chunks:
        assert chunk.start_line >= 1
        assert chunk.end_line >= chunk.start_line
        assert chunk.token_count > 0
        assert chunk.path == "calc.py"


def test_typescript_symbols_are_extracted():
    result = chunk_file("Card.tsx", TYPESCRIPT_SOURCE, "tsx")

    symbols = {c.symbol for c in result.chunks if c.symbol}
    assert "Card" in symbols
    assert "Store" in symbols


def test_unknown_language_falls_back_to_line_chunks():
    text = "\n".join(f"linha {i}" for i in range(200))
    result = chunk_file("dados.txt", text, None)

    assert result.fallback_used is True
    assert len(result.chunks) > 1
    assert all(c.kind == "block" for c in result.chunks)


def test_markdown_uses_line_chunking():
    # Markdown não tem símbolo no sentido de código; forçar tree-sitter aqui
    # produziria chunks piores que uma janela de linhas.
    assert supports_symbols("markdown") is False
    result = chunk_file("README.md", "# Título\n\n" + ("texto " * 500), "markdown")
    assert result.fallback_used is True
    assert result.chunks


def test_oversized_symbol_is_split_but_keeps_its_identity():
    corpo = "\n".join(f"    x = {i}" for i in range(4000))
    fonte = f"def gigante():\n{corpo}\n"
    result = chunk_file("grande.py", fonte, "python")

    pedacos = [c for c in result.chunks if c.symbol == "gigante"]
    assert len(pedacos) > 1, "função enorme deveria ter sido dividida"
    assert all(c.token_count <= MAX_CHUNK_TOKENS * 1.2 for c in pedacos)
    # A partir do segundo pedaço, precisa dizer de onde veio.
    assert "continuação de gigante" in pedacos[1].content


def test_empty_file_produces_no_chunks():
    assert chunk_file("vazio.py", "   \n\n  ", "python").chunks == []


def test_malformed_source_degrades_instead_of_raising():
    result = chunk_file("quebrado.py", "def (((:\n  ???", "python")
    assert isinstance(result.chunks, list)


def test_embedding_text_includes_path_and_symbol():
    # Buscas de código citam nome de arquivo e de função o tempo todo; sem isso
    # no texto, o vetor representaria só o corpo.
    result = chunk_file("router/policy.py", PYTHON_SOURCE, "python")
    chunk = next(c for c in result.chunks if c.symbol == "soma")
    texto = chunk.as_embedding_text()
    assert "router/policy.py" in texto
    assert "soma" in texto
