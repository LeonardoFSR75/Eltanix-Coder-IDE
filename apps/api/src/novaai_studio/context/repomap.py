"""Mapa do repositório: árvore de símbolos com orçamento de tokens.

A ideia vem do Aider. Em vez de mandar arquivos inteiros para o modelo "se
situar", manda-se um esqueleto — quais arquivos existem e quais símbolos cada um
declara. Cabe em 1–2k tokens, é estável entre turnos (logo aproveita prompt
caching) e responde a pergunta que o modelo realmente tem no começo de uma
tarefa: "onde eu procuro?".

A seleção é por densidade de símbolo, não por tamanho: um arquivo de 800 linhas
com uma função só informa menos que um de 200 com quinze.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select

from novaai_studio.db.models import CodeChunk
from novaai_studio.db.session import session_scope
from novaai_studio.optimizer.tokens import count_text

# Tipos que valem a pena listar. `block` e `module` são ruído num mapa.
INTERESTING_KINDS = frozenset({"function", "method", "class", "interface", "enum", "type"})

DEFAULT_TOKEN_BUDGET = 1800


@dataclass(slots=True)
class FileEntry:
    path: str
    language: str | None
    symbols: list[tuple[str, str]] = field(default_factory=list)  # (kind, nome qualificado)

    @property
    def density(self) -> int:
        return len(self.symbols)


def _render(entries: list[FileEntry]) -> str:
    lines: list[str] = []
    for entry in entries:
        lines.append(f"{entry.path}")
        for kind, name in entry.symbols:
            lines.append(f"  {kind} {name}")
    return "\n".join(lines)


async def build_repo_map(
    workspace: str, *, token_budget: int = DEFAULT_TOKEN_BUDGET
) -> dict[str, object]:
    async with session_scope() as session:
        rows = (
            await session.execute(
                select(
                    CodeChunk.path,
                    CodeChunk.language,
                    CodeChunk.kind,
                    CodeChunk.symbol,
                    CodeChunk.parent,
                    CodeChunk.start_line,
                )
                .where(
                    CodeChunk.workspace == workspace,
                    CodeChunk.symbol.is_not(None),
                    CodeChunk.kind.in_(INTERESTING_KINDS),
                )
                .order_by(CodeChunk.path, CodeChunk.start_line)
            )
        ).all()

    by_path: dict[str, FileEntry] = {}
    for path, language, kind, symbol, parent, _line in rows:
        entry = by_path.setdefault(path, FileEntry(path=path, language=language))
        qualified = f"{parent}.{symbol}" if parent else symbol
        entry.symbols.append((kind, qualified))

    # Mais símbolos primeiro: são os arquivos que mais orientam a navegação.
    ranked = sorted(by_path.values(), key=lambda e: (-e.density, e.path))

    included: list[FileEntry] = []
    used_tokens = 0
    for entry in ranked:
        rendered = _render([entry])
        cost = count_text(rendered)
        if used_tokens + cost > token_budget and included:
            break
        included.append(entry)
        used_tokens += cost

    # Reordena por caminho para a saída ficar navegável por um humano.
    included.sort(key=lambda e: e.path)

    return {
        "text": _render(included),
        "token_count": used_tokens,
        "token_budget": token_budget,
        "files_included": len(included),
        "files_total": len(by_path),
        "symbols_included": sum(e.density for e in included),
        "truncated": len(included) < len(by_path),
    }
