"""Quais language servers existem e como iniciá-los.

Um servidor por *linguagem*, não por arquivo: é assim que o protocolo foi
desenhado. O servidor indexa o projeto inteiro uma vez e responde sobre
qualquer arquivo dele — abrir um processo por arquivo jogaria fora exatamente
o índice que torna "ir para definição" possível entre arquivos.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ServerSpec:
    """Um language server e as linguagens que ele atende."""

    id: str
    command: list[str]
    languages: tuple[str, ...]
    # Enviado em `initializationOptions`. Cada servidor tem o seu dialeto.
    initialization_options: dict[str, object] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return shutil.which(self.command[0]) is not None


# `--stdio` em todos: a ponte fala com o processo por stdin/stdout e traduz para
# o WebSocket. Nenhum servidor abre porta própria — não há o que expor por engano.
_SPECS: tuple[ServerSpec, ...] = (
    ServerSpec(
        id="pyright",
        command=["pyright-langserver", "--stdio"],
        languages=("python",),
        initialization_options={
            # `basic` em vez de `strict`: num projeto sem anotações completas o
            # modo estrito enche a tela de erro em código que funciona, e o
            # ruído treina quem edita a ignorar os marcadores.
            "python": {"analysis": {"typeCheckingMode": "basic", "useLibraryCodeForTypes": True}}
        },
    ),
    ServerSpec(
        id="typescript",
        command=["typescript-language-server", "--stdio"],
        languages=("typescript", "typescriptreact", "javascript", "javascriptreact"),
    ),
    ServerSpec(
        id="json",
        command=["vscode-json-language-server", "--stdio"],
        languages=("json", "jsonc"),
    ),
    ServerSpec(
        id="css",
        command=["vscode-css-language-server", "--stdio"],
        languages=("css", "scss", "less"),
    ),
    ServerSpec(
        id="html",
        command=["vscode-html-language-server", "--stdio"],
        languages=("html",),
    ),
    ServerSpec(
        id="yaml",
        command=["yaml-language-server", "--stdio"],
        languages=("yaml",),
    ),
    ServerSpec(
        id="bash",
        command=["bash-language-server", "start"],
        languages=("shellscript", "bash"),
    ),
)

_POR_LINGUAGEM: dict[str, ServerSpec] = {
    linguagem: spec for spec in _SPECS for linguagem in spec.languages
}


def server_for_language(language: str) -> ServerSpec | None:
    return _POR_LINGUAGEM.get(language)


def supported_languages(*, only_installed: bool = True) -> dict[str, str]:
    """Linguagem → id do servidor, para o front saber quando nem tentar abrir.

    Filtrar pelo que está instalado importa: a imagem pode ser construída sem um
    servidor, e o editor precisa degradar em silêncio em vez de abrir um
    WebSocket que morre.
    """
    return {
        linguagem: spec.id
        for linguagem, spec in _POR_LINGUAGEM.items()
        if not only_installed or spec.available
    }
