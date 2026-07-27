"""Ponte entre o editor no browser e os language servers do container."""

from sicoobito.lsp.bridge import LanguageServerProcess, LspError
from sicoobito.lsp.servers import ServerSpec, server_for_language, supported_languages

__all__ = [
    "LanguageServerProcess",
    "LspError",
    "ServerSpec",
    "server_for_language",
    "supported_languages",
]
