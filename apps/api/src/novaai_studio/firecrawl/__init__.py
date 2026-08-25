"""Módulo Firecrawl: cliente HTTP assíncrono e serviço de raspagem, busca e ingestão RAG."""

from sicoobito.firecrawl.client import (
    FirecrawlAuthError,
    FirecrawlClient,
    FirecrawlConfig,
    FirecrawlError,
    FirecrawlRateLimitError,
    FirecrawlUnavailableError,
)
from sicoobito.firecrawl.service import FirecrawlService, validate_target_url

__all__ = [
    "FirecrawlAuthError",
    "FirecrawlClient",
    "FirecrawlConfig",
    "FirecrawlError",
    "FirecrawlRateLimitError",
    "FirecrawlService",
    "FirecrawlUnavailableError",
    "validate_target_url",
]
