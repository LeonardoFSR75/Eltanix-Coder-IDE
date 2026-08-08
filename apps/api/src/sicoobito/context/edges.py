"""Deriva o Code Knowledge Graph (arestas `contains`/`imports`) sobre os
chunks que o chunker já extraiu — ver `docs/proposals/git-code-intelligence.md`.

`contains` é praticamente de graça: já está nos campos `symbol`/`parent` que
cada `Chunk` carrega, não precisa reparsear nada. `imports` exige uma segunda
passada pela AST (o chunker não guarda a árvore) procurando os nós de
import/export e resolvendo o especificador contra os arquivos que este
workspace já tem indexados — import de pacote externo (numpy, react) nunca
resolve, porque não há arquivo de destino no índice, e isso é uma limitação
documentada, não um bug a perseguir.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import PurePosixPath
from typing import Any

from sicoobito.context.chunker import Chunk, get_parser
from sicoobito.logging_setup import get_logger

log = get_logger(__name__)

# Só linguagens onde vale a pena tentar resolver import → arquivo: as duas que
# o próprio SicoobitoCode usa (Python no backend, TS/TSX no frontend). Outras
# linguagens ainda ganham arestas `contains`; só ficam sem `imports`.
_IMPORT_LANGUAGES = frozenset({"python", "javascript", "typescript", "tsx"})
_JS_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx")


def contains_edges[T](chunk_ids: list[tuple[Chunk, T]]) -> list[tuple[T, T]]:
    """`[(id do container, id do filho)]` — ex. classe → método.

    Casa `chunk.parent` (nome da classe/contêiner) com o `chunk.symbol` de
    outro chunk do mesmo arquivo. Nomes de símbolo duplicados no mesmo
    arquivo (dois contêineres com o mesmo nome) são um caso não tratado — é
    código malformado, não vale a complexidade de desambiguar.
    """
    by_symbol = {chunk.symbol: chunk_id for chunk, chunk_id in chunk_ids if chunk.symbol}
    edges: list[tuple[T, T]] = []
    for chunk, chunk_id in chunk_ids:
        if chunk.parent and chunk.parent in by_symbol:
            edges.append((by_symbol[chunk.parent], chunk_id))
    return edges


def import_targets(path: str, source: str, language: str, known_paths: set[str]) -> list[str]:
    """Caminhos (relativos ao workspace) que este arquivo importa e que já
    estão indexados. Especificador que não resolve para dentro do workspace
    é descartado em silêncio — é o caso normal para pacote de terceiros."""
    if language not in _IMPORT_LANGUAGES:
        return []

    parser = get_parser(language)
    if parser is None:
        return []

    source_bytes = source.encode("utf-8")
    try:
        tree = parser.parse(source_bytes)
    except Exception as exc:
        log.debug("edges.import.parse_failed", path=path, error=str(exc))
        return []

    if language == "python":
        specifiers = _python_specifiers(tree.root_node, source_bytes)
        resolver = _resolve_python
    else:
        specifiers = _js_specifiers(tree.root_node, source_bytes)
        resolver = _resolve_js

    resolved: set[str] = set()
    for spec in specifiers:
        target = resolver(spec, path, known_paths)
        if target:
            resolved.add(target)
    return sorted(resolved)


def _find(node: Any, types: frozenset[str]) -> Iterator[Any]:
    if node.type in types:
        yield node
        return  # não desce dentro do próprio nó de import/export encontrado
    for child in node.children:
        yield from _find(child, types)


_PY_IMPORT_TYPES = frozenset({"import_statement", "import_from_statement"})


def _python_specifiers(root: Any, source: bytes) -> list[str]:
    """O **módulo** importado — e, no caso `from . import nome`, também um
    candidato a submódulo por nome importado.

    `import_from_statement` expõe o módulo como o campo `module_name`
    (`relative_import` ou `dotted_name`). `import_statement` não distingue
    "módulo" de "nome importado" por campo — mas lá todo filho *é* um alvo,
    então basta pegar os `dotted_name`/`aliased_import` diretos.

    `from pkg import nome` (relativo ou absoluto) é ambíguo na própria
    gramática do Python: nada diz se `nome` é um submódulo (arquivo) ou um
    atributo definido em `pkg/__init__.py`. Geramos os dois candidatos —
    `pkg` sozinho e `pkg.nome` — e deixamos `_resolve_python` decidir; um
    candidato só vira aresta se existir de fato um arquivo com esse nome no
    índice, então o caso comum (`nome` é um atributo, não um arquivo)
    simplesmente não resolve e não polui o grafo.
    """
    specifiers: list[str] = []
    for node in _find(root, _PY_IMPORT_TYPES):
        if node.type == "import_from_statement":
            module = node.child_by_field_name("module_name")
            module_text = _text(module, source) if module is not None else ""
            if module_text:
                specifiers.append(module_text)

            # Pontos (`.`, `..`) já terminam onde o nome começa; módulo com
            # letras (`pkg`, `pkg.sub`) precisa do separador entre os dois.
            separator = "" if module_text and set(module_text) <= {"."} else "."
            if module_text:
                for child in node.named_children:
                    if child is module:
                        continue
                    if child.type == "dotted_name":
                        specifiers.append(f"{module_text}{separator}{_text(child, source)}")
                    elif child.type == "aliased_import" and child.named_children:
                        specifiers.append(
                            f"{module_text}{separator}{_text(child.named_children[0], source)}"
                        )
            continue

        for child in node.named_children:
            if child.type == "dotted_name":
                specifiers.append(_text(child, source))
            elif child.type == "aliased_import" and child.named_children:
                specifiers.append(_text(child.named_children[0], source))
    return specifiers


_JS_IMPORT_TYPES = frozenset({"import_statement", "export_statement"})
_STRING_FRAGMENT = frozenset({"string_fragment"})


def _js_specifiers(root: Any, source: bytes) -> list[str]:
    """O especificador é sempre a única string do nó — nomes importados são
    identificadores, nunca strings, então basta pegar todo `string_fragment`
    dentro do `import`/`export ... from`."""
    specifiers: list[str] = []
    for stmt in _find(root, _JS_IMPORT_TYPES):
        for frag in _find(stmt, _STRING_FRAGMENT):
            specifiers.append(_text(frag, source))
    return specifiers


def _text(node: Any, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", "replace")


def _normalize(path: PurePosixPath) -> PurePosixPath:
    """Resolve `.`/`..` sem tocar o filesystem — `PurePosixPath` não faz isso."""
    parts: list[str] = []
    for part in path.parts:
        if part in (".", ""):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return PurePosixPath(*parts) if parts else PurePosixPath(".")


def _resolve_python(spec: str, current_path: str, known_paths: set[str]) -> str | None:
    current_dir = PurePosixPath(current_path).parent

    if spec.startswith("."):
        level = len(spec) - len(spec.lstrip("."))
        rest = spec[level:]
        base = current_dir
        for _ in range(level - 1):
            base = base.parent
        if rest:
            base = base / rest.replace(".", "/")
        base = _normalize(base)
        for candidate in (f"{base}.py", f"{base}/__init__.py"):
            if candidate in known_paths:
                return candidate
        return None

    # Absoluto: só conta se apontar para dentro do workspace — pacote da
    # stdlib ou instalado via pip não tem arquivo no índice para achar.
    base = PurePosixPath(spec.replace(".", "/"))
    direct = {f"{base}.py", f"{base}/__init__.py"}
    for candidate in direct:
        if candidate in known_paths:
            return candidate
    # O pacote pode estar aninhado sob `src/`, `apps/*/src/` etc. — casa pelo
    # sufixo do caminho em vez de exigir a raiz exata do workspace.
    for candidate in known_paths:
        if any(candidate.endswith(f"/{d}") for d in direct):
            return candidate
    return None


def _resolve_js(spec: str, current_path: str, known_paths: set[str]) -> str | None:
    if spec.startswith("."):
        base = _normalize(PurePosixPath(current_path).parent / spec)
    elif spec.startswith("@/"):
        # Alias comum do Next.js (`tsconfig.json`: `"@/*": ["./*"]`). Se o
        # projeto mapear diferente, o import simplesmente não resolve.
        base = PurePosixPath(spec[2:])
    else:
        return None  # pacote de node_modules — fora do índice, sem aresta

    candidates = [str(base)]
    candidates += [f"{base}{ext}" for ext in _JS_EXTENSIONS]
    candidates += [f"{base}/index{ext}" for ext in _JS_EXTENSIONS]
    for candidate in candidates:
        if candidate in known_paths:
            return candidate
    return None
