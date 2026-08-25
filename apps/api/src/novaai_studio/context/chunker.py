"""Corte de arquivos em chunks por símbolo, via tree-sitter.

Regras que valem para todo o módulo:

- Um símbolo grande demais é dividido por linhas, mas cada pedaço carrega o
  cabeçalho do símbolo. Sem isso, o segundo pedaço de uma função de 400 linhas
  chega ao modelo sem dizer de que função é.
- Código solto entre símbolos (imports, constantes de módulo) vira um chunk
  próprio: é lá que moram as dependências do arquivo.
- Linguagem sem gramática conhecida cai no corte por linha. Pior que por
  símbolo, melhor que ignorar o arquivo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from novaai_studio.context.languages import (
    LINE_CHUNKED_LANGUAGES,
    LanguageRules,
    rules_for,
    supports_symbols,
)
from novaai_studio.logging_setup import get_logger
from novaai_studio.optimizer.tokens import count_text

log = get_logger(__name__)

MAX_CHUNK_TOKENS = 900
MIN_CHUNK_CHARS = 30
LINE_CHUNK_SIZE = 60
LINE_CHUNK_OVERLAP = 8


@dataclass(slots=True)
class Chunk:
    path: str
    content: str
    start_line: int
    end_line: int
    kind: str
    symbol: str | None = None
    parent: str | None = None
    token_count: int = 0
    language: str | None = None

    @property
    def qualified_name(self) -> str:
        """Nome usado na exibição e no repo map."""
        if self.symbol and self.parent:
            return f"{self.parent}.{self.symbol}"
        return self.symbol or self.path

    def as_embedding_text(self) -> str:
        """Texto realmente enviado ao modelo de embedding.

        O caminho e o nome qualificado entram no texto de propósito: buscas de
        código costumam citar o nome do arquivo ou da função, e sem isso o
        vetor representaria só o corpo.
        """
        header = f"{self.path}"
        if self.symbol:
            header += f" · {self.qualified_name}"
        return f"{header}\n\n{self.content}"


@dataclass(slots=True)
class FileChunks:
    path: str
    language: str | None
    chunks: list[Chunk] = field(default_factory=list)
    fallback_used: bool = False


@lru_cache(maxsize=32)
def get_parser(language: str) -> Any | None:
    """Parsers são caros de construir e seguros para reutilizar.

    Público (não `_parser`) porque `context/edges.py` reaproveita o mesmo
    cache para extrair imports — cada linguagem paga a construção do parser
    uma vez só, não uma vez por módulo que o usa.
    """
    try:
        from tree_sitter_language_pack import get_parser as _get_parser

        return _get_parser(language)  # type: ignore[arg-type]
    except Exception as exc:
        log.debug("chunker.parser.unavailable", language=language, error=str(exc))
        return None


def _node_name(node: Any, source: bytes) -> str | None:
    """Nome do símbolo, quando a gramática expõe um campo `name`."""
    name_node = node.child_by_field_name("name")
    if name_node is not None:
        return source[name_node.start_byte : name_node.end_byte].decode("utf-8", "replace")

    # `decorated_definition` (Python) e `export_statement` (JS) embrulham o nó
    # real; o nome está um nível abaixo.
    for child in node.named_children:
        inner = child.child_by_field_name("name")
        if inner is not None:
            return source[inner.start_byte : inner.end_byte].decode("utf-8", "replace")
    return None


# Prefixo de comentário por linguagem, para o esboço de membros da classe não
# quebrar o realce de sintaxe de quem abrir o chunk.
_COMMENT_PREFIX = {
    "python": "#",
    "ruby": "#",
    "bash": "#",
    "yaml": "#",
}


def _comment(language: str, text: str) -> str:
    return f"{_COMMENT_PREFIX.get(language, '//')} {text}"


_WRAPPER_NODES = {"decorated_definition", "export_statement", "ambient_declaration"}


def _unwrap(node: Any) -> Any:
    """Nó real por trás de um que só embrulha outro.

    `decorated_definition` (`@dataclass`, `@router.get`, `@pytest.fixture`) e
    `export_statement` não declaram nada por conta própria — a definição está no
    filho.

    Desembrulhar importa duas vezes: sem isso todo símbolo decorado viraria
    `block` e sumiria do repo map (que filtra por tipo), e o corpo da classe
    seria procurado no wrapper — que não tem campo `body` —, fazendo a recursão
    reencontrar a própria classe e indexá-la aninhada sob si mesma.
    """
    if node.type not in _WRAPPER_NODES:
        return node
    for child in node.named_children:
        if child.type not in {"decorator", "comment"}:
            return child
    return node


def _effective_type(node: Any) -> str:
    return _unwrap(node).type


def _kind_of(node_type: str) -> str:
    lowered = node_type.lower()
    if "class" in lowered or "struct" in lowered or "impl" in lowered:
        return "class"
    if "interface" in lowered or "trait" in lowered:
        return "interface"
    if "method" in lowered:
        return "method"
    if "function" in lowered or lowered in {"method", "def"}:
        return "function"
    if "enum" in lowered:
        return "enum"
    if "type" in lowered:
        return "type"
    return "block"


def _split_oversized(chunk: Chunk) -> list[Chunk]:
    """Divide um símbolo grande mantendo a identidade em cada pedaço."""
    lines = chunk.content.splitlines()
    if len(lines) <= 1:
        return [chunk]

    pieces: list[Chunk] = []
    step = LINE_CHUNK_SIZE - LINE_CHUNK_OVERLAP
    for index, start in enumerate(range(0, len(lines), step)):
        window = lines[start : start + LINE_CHUNK_SIZE]
        if not window:
            break
        body = "\n".join(window)
        # A partir do segundo pedaço, prefixa uma marca dizendo de onde veio.
        if index > 0 and chunk.symbol:
            body = f"# ... continuação de {chunk.qualified_name}\n{body}"
        pieces.append(
            Chunk(
                path=chunk.path,
                content=body,
                start_line=chunk.start_line + start,
                end_line=min(chunk.start_line + start + len(window) - 1, chunk.end_line),
                kind=chunk.kind,
                symbol=chunk.symbol,
                parent=chunk.parent,
                token_count=count_text(body),
                language=chunk.language,
            )
        )
        if start + LINE_CHUNK_SIZE >= len(lines):
            break
    return pieces


def _collect_symbols(
    node: Any,
    source: bytes,
    rules: LanguageRules,
    path: str,
    language: str,
    parent: str | None = None,
    depth: int = 0,
) -> list[Chunk]:
    found: list[Chunk] = []

    for child in node.named_children:
        node_type = child.type

        if node_type in rules.container_nodes and depth < 6:
            found.extend(_collect_symbols(child, source, rules, path, language, parent, depth + 1))
            continue

        if node_type not in rules.symbol_nodes:
            continue

        name = _node_name(child, source)
        kind = _kind_of(_effective_type(child))
        text = source[child.start_byte : child.end_byte].decode("utf-8", "replace")

        # Classes e blocos `impl` viram contêiner: em vez de um chunk de 500
        # linhas, cada método vira um chunk com a classe como `parent`.
        if kind in {"class", "interface"} and depth < 6:
            # O corpo vem do nó desembrulhado; procurá-lo no wrapper devolveria
            # o próprio wrapper e a classe apareceria como filha de si mesma.
            interno = _unwrap(child)
            body = interno.child_by_field_name("body") or interno
            nested = _collect_symbols(
                body, source, rules, path, language, parent=name, depth=depth + 1
            )
            if nested:
                # A "casca" da classe: assinatura, docstring e atributos, do
                # início dela até a linha anterior ao primeiro método. O corpo
                # dos métodos já virou chunk à parte.
                class_start = child.start_point[0] + 1  # 1-based
                header_end = max(nested[0].start_line - 1, class_start)
                all_lines = text.splitlines()
                header_lines = all_lines[: max(1, header_end - class_start + 1)]

                # Anexa o esboço de membros. Uma classe cujo primeiro método
                # começa na linha seguinte teria uma casca de uma linha só —
                # curta demais para ser indexável, e é justamente o único chunk
                # cujo símbolo é a própria classe. Sem ela, procurar pelo nome
                # da classe não acharia nada.
                members = [n.symbol for n in nested if n.symbol and n.parent == name]
                body_text = "\n".join(header_lines)
                if members:
                    body_text += "\n" + _comment(language, f"membros: {', '.join(members)}")

                found.append(
                    Chunk(
                        path=path,
                        content=body_text,
                        start_line=class_start,
                        end_line=header_end,
                        kind=kind,
                        symbol=name,
                        parent=parent,
                        token_count=count_text(body_text),
                        language=language,
                    )
                )
                found.extend(nested)
                continue

        if len(text.strip()) < MIN_CHUNK_CHARS:
            continue

        found.append(
            Chunk(
                path=path,
                content=text,
                start_line=child.start_point[0] + 1,
                end_line=child.end_point[0] + 1,
                kind=kind,
                symbol=name,
                parent=parent,
                token_count=count_text(text),
                language=language,
            )
        )

    return found


def _line_chunks(path: str, text: str, language: str | None) -> list[Chunk]:
    lines = text.splitlines()
    if not lines:
        return []

    chunks: list[Chunk] = []
    step = max(1, LINE_CHUNK_SIZE - LINE_CHUNK_OVERLAP)
    for start in range(0, len(lines), step):
        window = lines[start : start + LINE_CHUNK_SIZE]
        body = "\n".join(window)
        if len(body.strip()) < MIN_CHUNK_CHARS:
            continue
        chunks.append(
            Chunk(
                path=path,
                content=body,
                start_line=start + 1,
                end_line=start + len(window),
                kind="block",
                token_count=count_text(body),
                language=language,
            )
        )
        if start + LINE_CHUNK_SIZE >= len(lines):
            break
    return chunks


def _gap_chunks(path: str, text: str, symbols: list[Chunk], language: str) -> list[Chunk]:
    """Captura o que sobra entre símbolos: imports, constantes, código de topo."""
    lines = text.splitlines()
    covered = set()
    for symbol in symbols:
        covered.update(range(symbol.start_line, symbol.end_line + 1))

    gaps: list[Chunk] = []
    current: list[tuple[int, str]] = []

    def flush() -> None:
        if not current:
            return
        body = "\n".join(line for _, line in current)
        if len(body.strip()) >= MIN_CHUNK_CHARS:
            gaps.append(
                Chunk(
                    path=path,
                    content=body,
                    start_line=current[0][0],
                    end_line=current[-1][0],
                    kind="module",
                    token_count=count_text(body),
                    language=language,
                )
            )
        current.clear()

    for number, line in enumerate(lines, start=1):
        if number in covered:
            flush()
            continue
        current.append((number, line))
        if len(current) >= LINE_CHUNK_SIZE:
            flush()
    flush()
    return gaps


def chunk_file(path: str, text: str, language: str | None) -> FileChunks:
    result = FileChunks(path=path, language=language)

    if not text.strip():
        return result

    if language is None or language in LINE_CHUNKED_LANGUAGES or not supports_symbols(language):
        result.chunks = _line_chunks(path, text, language)
        result.fallback_used = True
        return result

    parser = get_parser(language)
    rules = rules_for(language)
    if parser is None or rules is None:
        result.chunks = _line_chunks(path, text, language)
        result.fallback_used = True
        return result

    try:
        source = text.encode("utf-8")
        tree = parser.parse(source)
        symbols = _collect_symbols(tree.root_node, source, rules, path, language)
    except Exception as exc:
        log.warning("chunker.parse.failed", path=path, language=language, error=str(exc))
        result.chunks = _line_chunks(path, text, language)
        result.fallback_used = True
        return result

    if not symbols:
        result.chunks = _line_chunks(path, text, language)
        result.fallback_used = True
        return result

    combined = symbols + _gap_chunks(path, text, symbols, language)

    final: list[Chunk] = []
    for chunk in combined:
        if chunk.token_count > MAX_CHUNK_TOKENS:
            final.extend(_split_oversized(chunk))
        else:
            final.append(chunk)

    final.sort(key=lambda c: c.start_line)
    result.chunks = final
    return result
