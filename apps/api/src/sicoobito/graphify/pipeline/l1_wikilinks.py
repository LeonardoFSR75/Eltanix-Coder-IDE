"""Extrator de Relacionamentos Camada 1: Sintáticos (Wikilinks, Tags, AST, TS/JS Imports)."""

from __future__ import annotations

import re


def extract_wikilinks(content: str) -> list[str]:
    """Extrai todos os alvos de wikilinks em formato [[Nome da Nota]]."""
    pattern = r"\[\[(.*?)\]\]"
    matches = re.findall(pattern, content)
    links = []
    for m in matches:
        # Suporta aliases tipo [[Nota|Alias]]
        clean_target = m.split("|")[0].strip()
        if clean_target and clean_target not in links:
            links.append(clean_target)
    return links


def extract_tags(content: str) -> list[str]:
    """Extrai todas as hashtags #tag do texto."""
    pattern = r"(?:^|\s)#([a-zA-Z0-9_\-/]+)"
    matches = re.findall(pattern, content)
    tags = []
    for m in matches:
        clean = m.strip()
        if clean and clean not in tags:
            tags.append(clean)
    return tags


def extract_python_imports(code_content: str) -> list[str]:
    """Extrai módulos importados em código Python."""
    pattern = r"^(?:from|import)\s+([a-zA-Z0-9_\.]+)"
    matches = re.findall(pattern, code_content, re.MULTILINE)
    modules = []
    for m in matches:
        base_mod = m.split(".")[0]
        if base_mod and base_mod not in modules:
            modules.append(base_mod)
    return modules


def extract_ts_imports(code_content: str) -> list[str]:
    """Extrai módulos/arquivos importados em TypeScript/JavaScript/JSX/TSX."""
    pattern = r"(?:import|export)\s+.*?from\s+['\"]([^'\"]+)['\"]|require\(['\"]([^'\"]+)['\"]\)"
    matches = re.findall(pattern, code_content)
    modules = []
    for m in matches:
        target = (m[0] or m[1]).strip()
        if target and target not in modules:
            # Pega o último componente significativo se for relativo/alias
            base_mod = (
                target.split("/")[-1]
                .replace(".ts", "")
                .replace(".tsx", "")
                .replace(".js", "")
                .replace(".jsx", "")
            )
            if base_mod and base_mod not in modules:
                modules.append(base_mod)
    return modules
