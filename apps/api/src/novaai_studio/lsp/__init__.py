"""Ponte entre o editor no browser e os language servers do container."""

from novaai_studio.lsp.bridge import LanguageServerProcess, LspError
from novaai_studio.lsp.extension_bridge import extension_for_server, is_server_gated
from novaai_studio.lsp.servers import ServerSpec, server_for_language, supported_languages

__all__ = [
    "LanguageServerProcess",
    "LspError",
    "ServerSpec",
    "extension_for_server",
    "is_server_gated",
    "server_for_language",
    "supported_languages",
]
