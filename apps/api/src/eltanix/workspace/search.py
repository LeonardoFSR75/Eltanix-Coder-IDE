"""Busca textual em todo o projeto, com substituição.

É o `Ctrl+Shift+F` do editor, e por isso é diferente da busca semântica da
[fase 2]: aqui o usuário sabe o que procura e quer *todas* as ocorrências, não
as mais parecidas. Não há embedding, ranking nem índice — a varredura é direta,
respeitando o `.gitignore`.

O limite de resultados não é detalhe: uma busca por `self` num repositório
Python casa dezenas de milhares de linhas, e devolver tudo travaria o browser
antes de o usuário ler a primeira.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from eltanix.context.languages import detect_language
from eltanix.context.scanner import iter_paths, read_text
from eltanix.logging_setup import get_logger

log = get_logger(__name__)

MAX_MATCHES = 500
MAX_MATCHES_PER_FILE = 50
CONTEXT_CHARS = 160

# `re` da stdlib não tem timeout embutido e o Windows não tem `signal.alarm`
# — a defesa possível sem dependência nova é bounding: uma regex do usuário
# com backtracking catastrófico (ex. `(a+)+$`) só vira DoS se tiver bastante
# texto para explodir contra. Uma linha longa demais é pulada (o arquivo
# ainda é considerado buscado); o teto de tempo total corta a soma de muitas
# linhas moderadamente lentas antes que a busca vire perceptível como travada.
_MAX_REGEX_LINE_CHARS = 5_000
_SEARCH_DEADLINE_SECONDS = 10.0


@dataclass(slots=True)
class Match:
    path: str
    line: int
    column: int
    text: str
    preview: str


@dataclass(slots=True)
class SearchResult:
    matches: list[Match] = field(default_factory=list)
    files_searched: int = 0
    files_with_matches: int = 0
    truncated: bool = False


def build_pattern(
    query: str, *, regex: bool = False, case_sensitive: bool = False, whole_word: bool = False
) -> re.Pattern[str]:
    corpo = query if regex else re.escape(query)
    if whole_word:
        corpo = rf"\b{corpo}\b"
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        return re.compile(corpo, flags)
    except re.error as exc:
        raise ValueError(f"Expressão regular inválida: {exc}") from exc


def _preview(linha: str, inicio: int, fim: int) -> str:
    """Trecho ao redor do casamento, para linhas longas (minificados, dados)."""
    if len(linha) <= CONTEXT_CHARS:
        return linha
    meio = (inicio + fim) // 2
    corte = max(0, meio - CONTEXT_CHARS // 2)
    trecho = linha[corte : corte + CONTEXT_CHARS]
    prefixo = "…" if corte > 0 else ""
    sufixo = "…" if corte + CONTEXT_CHARS < len(linha) else ""
    return f"{prefixo}{trecho}{sufixo}"


def search(
    root: Path,
    query: str,
    *,
    regex: bool = False,
    case_sensitive: bool = False,
    whole_word: bool = False,
    path_glob: str | None = None,
    max_matches: int = MAX_MATCHES,
) -> SearchResult:
    if not query:
        return SearchResult()

    padrao = build_pattern(query, regex=regex, case_sensitive=case_sensitive, whole_word=whole_word)
    resultado = SearchResult()
    prazo_final = time.monotonic() + _SEARCH_DEADLINE_SECONDS

    for caminho, absoluto, _tamanho in iter_paths(root):
        if time.monotonic() > prazo_final:
            log.warning("search.deadline_exceeded", root=str(root), query_len=len(query))
            resultado.truncated = True
            break

        if path_glob and not Path(caminho).match(path_glob):
            continue

        conteudo = read_text(absoluto)
        if conteudo is None:
            continue

        resultado.files_searched += 1
        achou_no_arquivo = 0

        for numero, linha in enumerate(conteudo.splitlines(), start=1):
            if regex and len(linha) > _MAX_REGEX_LINE_CHARS:
                continue
            for casamento in padrao.finditer(linha):
                resultado.matches.append(
                    Match(
                        path=caminho,
                        line=numero,
                        column=casamento.start() + 1,
                        text=casamento.group(0),
                        preview=_preview(linha, casamento.start(), casamento.end()),
                    )
                )
                achou_no_arquivo += 1
                if achou_no_arquivo >= MAX_MATCHES_PER_FILE:
                    break
                if len(resultado.matches) >= max_matches:
                    break
            if achou_no_arquivo >= MAX_MATCHES_PER_FILE or len(resultado.matches) >= max_matches:
                break

        if achou_no_arquivo:
            resultado.files_with_matches += 1
        if len(resultado.matches) >= max_matches:
            resultado.truncated = True
            break

    return resultado


@dataclass(slots=True)
class ReplaceResult:
    files_changed: int = 0
    replacements: int = 0
    changed_paths: list[str] = field(default_factory=list)


def replace_all(
    root: Path,
    query: str,
    replacement: str,
    *,
    regex: bool = False,
    case_sensitive: bool = False,
    whole_word: bool = False,
    path_glob: str | None = None,
    only_paths: list[str] | None = None,
) -> ReplaceResult:
    """Substitui em todo o projeto.

    `only_paths` existe para o fluxo seguro do editor: o usuário vê os
    resultados, desmarca o que não quer e confirma. Substituir tudo às cegas
    numa base grande é o tipo de operação que se descobre errada depois do
    commit.
    """
    padrao = build_pattern(query, regex=regex, case_sensitive=case_sensitive, whole_word=whole_word)
    permitidos = set(only_paths) if only_paths else None
    resultado = ReplaceResult()
    prazo_final = time.monotonic() + _SEARCH_DEADLINE_SECONDS

    for caminho, absoluto, _tamanho in iter_paths(root):
        if time.monotonic() > prazo_final:
            log.warning("search.replace.deadline_exceeded", root=str(root), query_len=len(query))
            break

        if permitidos is not None and caminho not in permitidos:
            continue
        if path_glob and not Path(caminho).match(path_glob):
            continue

        conteudo = read_text(absoluto)
        if conteudo is None:
            continue

        novo, quantidade = padrao.subn(replacement, conteudo)
        if quantidade == 0:
            continue

        try:
            # `newline=""` preserva a convenção de quebra de linha do arquivo,
            # senão uma substituição de uma palavra viraria um diff completo.
            with absoluto.open("w", encoding="utf-8", newline="") as handle:
                handle.write(novo)
        except OSError as exc:
            log.warning("search.replace.failed", path=caminho, error=str(exc))
            continue

        resultado.files_changed += 1
        resultado.replacements += quantidade
        resultado.changed_paths.append(caminho)

    log.info(
        "search.replace",
        files=resultado.files_changed,
        replacements=resultado.replacements,
    )
    return resultado


def list_all_files(root: Path, *, limit: int = 20_000) -> list[dict[str, object]]:
    """Lista plana para o quick open (Ctrl+P).

    O casamento fuzzy acontece no cliente: mandar a lista uma vez e filtrar
    localmente responde a cada tecla sem ida ao servidor.

    Usa `iter_paths`, não `scan`: aqui só interessam os caminhos, e ler o
    conteúdo de cada arquivo para descobri-los custaria um minuto num projeto
    de mil arquivos sobre bind mount.
    """
    arquivos: list[dict[str, object]] = []
    for caminho, _absoluto, tamanho in iter_paths(root):
        arquivos.append(
            {
                "path": caminho,
                "name": caminho.rsplit("/", 1)[-1],
                "language": detect_language(caminho.rsplit("/", 1)[-1]),
                "size_bytes": tamanho,
            }
        )
        if len(arquivos) >= limit:
            break
    return arquivos
