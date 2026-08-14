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
        id="pyrefly",
        command=["pyrefly", "lsp"],
        languages=("python",),
        initialization_options={
            "python": {"analysis": {"typeCheckingMode": "basic", "useLibraryCodeForTypes": True}}
        },
    ),
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
    ServerSpec(
        id="clangd",
        command=["clangd", "--background-index"],
        languages=("c", "cpp", "objc", "objcpp"),
    ),
    ServerSpec(
        id="gopls",
        command=["gopls"],
        languages=("go", "gomod"),
    ),
    ServerSpec(
        id="ruby-lsp",
        command=["ruby-lsp"],
        languages=("ruby",),
    ),
    ServerSpec(
        id="dockerfile",
        command=["docker-langserver", "--stdio"],
        languages=("dockerfile",),
    ),
    ServerSpec(
        id="volar",
        command=["vue-language-server", "--stdio"],
        languages=("vue",),
    ),
    ServerSpec(
        id="svelte",
        command=["svelteserver", "--stdio"],
        languages=("svelte",),
    ),
    ServerSpec(
        id="tailwindcss",
        command=["tailwindcss-language-server", "--stdio"],
        languages=("html", "css", "javascriptreact", "typescriptreact", "vue", "svelte"),
    ),
    ServerSpec(
        id="angular",
        command=["ngserver", "--stdio"],
        languages=("html", "typescript"),
    ),
)


def server_for_language(language: str, preferred_server: str | None = None) -> ServerSpec | None:
    candidatos = [spec for spec in _SPECS if language in spec.languages]
    if not candidatos:
        return None
    if preferred_server:
        for spec in candidatos:
            if spec.id == preferred_server:
                return spec
    # Retorna o primeiro candidato disponível; se nenhum estiver instalado no host,
    # retorna o primeiro candidato como fallback para que o teste/ponte possa
    # reportar o comando ausente.
    for spec in candidatos:
        if spec.available:
            return spec
    return candidatos[0]


def supported_languages(*, only_installed: bool = True) -> dict[str, str]:
    """Linguagem → id do servidor preferencial/ativo.

    Filtrar pelo que está instalado importa: a imagem pode ser construída sem um
    servidor, e o editor precisa degradar em silêncio em vez de abrir um
    WebSocket que morre.
    """
    resultado: dict[str, str] = {}
    for spec in _SPECS:
        if only_installed and not spec.available:
            continue
        for lang in spec.languages:
            if lang not in resultado:
                resultado[lang] = spec.id
    return resultado
