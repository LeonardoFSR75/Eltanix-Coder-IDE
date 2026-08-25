"""Ponte entre o editor no browser e os language servers do container."""

from sicoobito.lsp.bridge import LanguageServerProcess, LspError
from sicoobito.lsp.extension_bridge import extension_for_server, is_server_gated
from sicoobito.lsp.servers import ServerSpec, server_for_language, supported_languages

__all__ = [
    "LanguageServerProcess",
    "LspError",
    "ServerSpec",
    "extension_for_server",
    "is_server_gated",
    "server_for_language",
    "supported_languages",
]
