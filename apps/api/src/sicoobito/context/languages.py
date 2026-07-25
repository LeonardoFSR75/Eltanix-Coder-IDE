"""Mapeamento de extensão para linguagem e os nós que valem como símbolo.

O que separa RAG de código de RAG de texto é o corte: partir por N caracteres
racha uma função no meio e produz trechos que não compilam nem fazem sentido
isolados. Aqui o corte é por símbolo — função, classe, método —, então cada
chunk é uma unidade que um humano reconheceria.
"""

from __future__ import annotations

from dataclasses import dataclass

# Extensão → nome da linguagem no tree-sitter-language-pack.
EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".scala": "scala",
    ".swift": "swift",
    ".sql": "sql",
    ".sh": "bash",
    ".bash": "bash",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".md": "markdown",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
}

# Arquivos sem extensão que ainda são código.
FILENAME_TO_LANGUAGE: dict[str, str] = {
    "Dockerfile": "dockerfile",
    "Makefile": "make",
}


@dataclass(frozen=True, slots=True)
class LanguageRules:
    """Nós que viram chunk e onde encontrar o nome do símbolo."""

    # Tipos de nó tratados como símbolo de topo.
    symbol_nodes: frozenset[str]
    # Nós que contêm outros símbolos e devem ser percorridos em vez de virar
    # um chunk gigante (ex.: o corpo de uma classe, o bloco `impl` do Rust).
    container_nodes: frozenset[str] = frozenset()


_RULES: dict[str, LanguageRules] = {
    "python": LanguageRules(
        symbol_nodes=frozenset({"function_definition", "class_definition", "decorated_definition"}),
    ),
    "javascript": LanguageRules(
        symbol_nodes=frozenset(
            {
                "function_declaration",
                "generator_function_declaration",
                "class_declaration",
                "method_definition",
                "lexical_declaration",
            }
        ),
        container_nodes=frozenset({"export_statement"}),
    ),
    "typescript": LanguageRules(
        symbol_nodes=frozenset(
            {
                "function_declaration",
                "class_declaration",
                "method_definition",
                "interface_declaration",
                "type_alias_declaration",
                "enum_declaration",
                "lexical_declaration",
            }
        ),
        container_nodes=frozenset({"export_statement", "ambient_declaration"}),
    ),
    "go": LanguageRules(
        symbol_nodes=frozenset(
            {"function_declaration", "method_declaration", "type_declaration"}
        ),
    ),
    "rust": LanguageRules(
        symbol_nodes=frozenset(
            {"function_item", "struct_item", "enum_item", "trait_item", "impl_item"}
        ),
    ),
    "java": LanguageRules(
        symbol_nodes=frozenset(
            {"class_declaration", "interface_declaration", "method_declaration", "enum_declaration"}
        ),
        container_nodes=frozenset({"class_body", "program"}),
    ),
    "ruby": LanguageRules(symbol_nodes=frozenset({"method", "class", "module"})),
    "c": LanguageRules(
        symbol_nodes=frozenset({"function_definition", "struct_specifier", "enum_specifier"})
    ),
    "cpp": LanguageRules(
        symbol_nodes=frozenset(
            {"function_definition", "class_specifier", "struct_specifier", "namespace_definition"}
        )
    ),
    "csharp": LanguageRules(
        symbol_nodes=frozenset(
            {
                "class_declaration",
                "method_declaration",
                "interface_declaration",
                "struct_declaration",
            }
        ),
        container_nodes=frozenset({"declaration_list", "namespace_declaration"}),
    ),
}

# TSX compartilha a gramática do TypeScript.
_RULES["tsx"] = _RULES["typescript"]

# Linguagens de marcação e configuração: corte por linha é adequado, porque não
# há símbolo no sentido de código.
LINE_CHUNKED_LANGUAGES = frozenset(
    {"markdown", "yaml", "json", "toml", "html", "css", "scss", "sql", "bash", "make", "dockerfile"}
)


def detect_language(filename: str) -> str | None:
    if language := FILENAME_TO_LANGUAGE.get(filename):
        return language
    lowered = filename.lower()
    for extension, language in EXTENSION_TO_LANGUAGE.items():
        if lowered.endswith(extension):
            return language
    return None


def rules_for(language: str) -> LanguageRules | None:
    return _RULES.get(language)


def supports_symbols(language: str) -> bool:
    return language in _RULES
