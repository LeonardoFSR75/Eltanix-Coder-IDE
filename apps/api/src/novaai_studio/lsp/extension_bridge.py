"""Ponte entre `ServerSpec.id` (lsp/servers.py) e o catálogo de extensões
(`extensions/catalog.py`).

Os dois sistemas nasceram sem chave em comum: o LSP registra servidores por
id de binário ("pyright", "svelte"), o catálogo de extensões por id de
publisher.nome ("ms-python.python", "svelte.svelte-vscode"). Só os servidores
com uma extensão de linguagem correspondente no catálogo entram no mapa
abaixo — desligar `sicoobito.dependency-cve-auditor` ou qualquer extensão sem
contraparte de LSP não tem efeito aqui, e um servidor sem entrada neste mapa
(json, css, html, yaml, bash, clangd, gopls, ruby-lsp, dockerfile, angular,
typescript) nunca é bloqueado — não faz sentido negar linguagem básica por um
toggle de extensão que não existe para ela.
"""

from __future__ import annotations

LSP_SERVER_TO_EXTENSION_ID: dict[str, str] = {
    "pyrefly": "meta.pyrefly",
    "pyright": "ms-python.python",
    "volar": "vue.volar",
    "svelte": "svelte.svelte-vscode",
    "tailwindcss": "tailwindcss.vscode-tailwindcss",
}


def is_server_gated(server_id: str) -> bool:
    """`True` se este servidor tem uma extensão associada que pode desligá-lo."""
    return server_id in LSP_SERVER_TO_EXTENSION_ID


def extension_for_server(server_id: str) -> str | None:
    return LSP_SERVER_TO_EXTENSION_ID.get(server_id)
