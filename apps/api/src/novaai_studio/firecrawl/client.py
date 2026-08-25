"""Cliente HTTP assíncrono para a API do Firecrawl (v1).

Comunica com a API pública do Firecrawl (https://api.firecrawl.dev) ou instâncias
self-hosted (http://firecrawl:3002).

Suporta:
- scrape: extrai markdown limpo, html, metadados e links de uma única URL;
- search: busca na web e obtém conteúdo em markdown dos principais resultados;
- map: mapeamento rápido de sitemap/links de um domínio;
- crawl: rastreamento assíncrono de múltiplas páginas com controle de profundidade e caminhos;
- get_crawl_status / poll_crawl: consulta de status e espera ativa do resultado do crawl.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx

from sicoobito.logging_setup import get_logger

log = get_logger(__name__)

_DEFAULT_API_URL = "https://api.firecrawl.dev"
_DEFAULT_TIMEOUT_SECONDS = 45.0


class FirecrawlError(Exception):
    """Erro base para operações com Firecrawl."""


class FirecrawlAuthError(FirecrawlError):
    """Chave de API inválida, não autorizada ou ausente."""


class FirecrawlRateLimitError(FirecrawlError):
    """Limite de requisições ou créditos excedido no Firecrawl."""


class FirecrawlUnavailableError(FirecrawlError):
    """Serviço Firecrawl indisponível ou inacessível via rede."""


@dataclass(slots=True)
class FirecrawlConfig:
    api_key: str = ""
    api_url: str = _DEFAULT_API_URL
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS


class FirecrawlClient:
    """Cliente assíncrono para a API REST v1 do Firecrawl."""

    def __init__(
        self,
        config: FirecrawlConfig | None = None,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config or FirecrawlConfig()
        self._custom_client = http_client
        self._owned_client: httpx.AsyncClient | None = None

    @property
    def base_url(self) -> str:
        url = (self.config.api_url or _DEFAULT_API_URL).strip().rstrip("/")
        if url.endswith("/v1"):
            url = url[:-3]
        return url

    def _get_client(self) -> httpx.AsyncClient:
        if self._custom_client is not None:
            return self._custom_client
        if self._owned_client is None or self._owned_client.is_closed:
            self._owned_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.timeout_seconds),
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=15),
            )
        return self._owned_client

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _handle_response_error(self, response: httpx.Response) -> None:
        if response.status_code == 401 or response.status_code == 403:
            raise FirecrawlAuthError(
                f"Autenticação recusada pelo Firecrawl ({response.status_code}): "
                f"{response.text[:200]}"
            )
        if response.status_code == 429:
            raise FirecrawlRateLimitError(
                f"Limite de requisições/créditos excedido no Firecrawl (429): "
                f"{response.text[:200]}"
            )
        if response.status_code >= 500:
            raise FirecrawlUnavailableError(
                f"Serviço Firecrawl retornou erro do servidor ({response.status_code}): "
                f"{response.text[:200]}"
            )
        if response.status_code >= 400:
            raise FirecrawlError(
                f"Erro na requisição ao Firecrawl ({response.status_code}): "
                f"{response.text[:300]}"
            )

    async def scrape(
        self,
        url: str,
        *,
        formats: list[str] | None = None,
        only_main_content: bool = True,
        include_tags: list[str] | None = None,
        exclude_tags: list[str] | None = None,
        wait_for: int = 0,
        timeout_ms: int = 30_000,
    ) -> dict[str, Any]:
        """Raspa uma única página web e retorna Markdown limpo e metadados."""
        client = self._get_client()
        endpoint = f"{self.base_url}/v1/scrape"
        payload: dict[str, Any] = {
            "url": url,
            "formats": formats or ["markdown"],
            "onlyMainContent": only_main_content,
        }
        if include_tags:
            payload["includeTags"] = include_tags
        if exclude_tags:
            payload["excludeTags"] = exclude_tags
        if wait_for > 0:
            payload["waitFor"] = wait_for
        if timeout_ms:
            payload["timeout"] = timeout_ms

        try:
            res = await client.post(endpoint, json=payload, headers=self._build_headers())
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise FirecrawlUnavailableError(
                f"Não foi possível conectar ao Firecrawl em {self.base_url}: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise FirecrawlUnavailableError(
                f"Tempo limite excedido ao raspar {url} via Firecrawl: {exc}"
            ) from exc
        except httpx.HTTPError as exc:
            raise FirecrawlError(f"Falha de rede ao falar com Firecrawl: {exc}") from exc

        self._handle_response_error(res)
        data = res.json()
        if not data.get("success", True) and "error" in data:
            raise FirecrawlError(f"Firecrawl scrape falhou: {data.get('error')}")
        return data.get("data", data)

    async def search(
        self,
        query: str,
        *,
        limit: int = 5,
        scrape_options: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Pesquisa na web e extrai o conteúdo em Markdown dos principais resultados."""
        client = self._get_client()
        endpoint = f"{self.base_url}/v1/search"
        payload: dict[str, Any] = {
            "query": query,
            "limit": limit,
            "scrapeOptions": scrape_options or {"formats": ["markdown"]},
        }

        try:
            res = await client.post(endpoint, json=payload, headers=self._build_headers())
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise FirecrawlUnavailableError(
                f"Não foi possível conectar ao Firecrawl em {self.base_url}: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise FirecrawlUnavailableError(
                f"Tempo limite excedido na busca '{query}' via Firecrawl: {exc}"
            ) from exc
        except httpx.HTTPError as exc:
            raise FirecrawlError(f"Falha de rede ao falar com Firecrawl: {exc}") from exc

        self._handle_response_error(res)
        data = res.json()
        if not data.get("success", True) and "error" in data:
            raise FirecrawlError(f"Firecrawl search falhou: {data.get('error')}")
        results = data.get("data", [])
        if isinstance(results, list):
            return results
        return []

    async def map_urls(
        self,
        url: str,
        *,
        search: str | None = None,
        limit: int = 100,
    ) -> list[str]:
        """Mapeia rapidamente todas as URLs e links internos de um site."""
        client = self._get_client()
        endpoint = f"{self.base_url}/v1/map"
        payload: dict[str, Any] = {"url": url, "limit": limit}
        if search:
            payload["search"] = search

        try:
            res = await client.post(endpoint, json=payload, headers=self._build_headers())
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise FirecrawlUnavailableError(
                f"Não foi possível conectar ao Firecrawl em {self.base_url}: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise FirecrawlUnavailableError(
                f"Tempo limite excedido ao mapear {url} via Firecrawl: {exc}"
            ) from exc
        except httpx.HTTPError as exc:
            raise FirecrawlError(f"Falha de rede ao falar com Firecrawl: {exc}") from exc

        self._handle_response_error(res)
        data = res.json()
        if not data.get("success", True) and "error" in data:
            raise FirecrawlError(f"Firecrawl map falhou: {data.get('error')}")
        links = data.get("links", [])
        return links if isinstance(links, list) else []

    async def crawl(
        self,
        url: str,
        *,
        max_depth: int = 2,
        limit: int = 10,
        allow_backward_links: bool = False,
        allow_external_links: bool = False,
        include_paths: list[str] | None = None,
        exclude_paths: list[str] | None = None,
        scrape_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Inicia um job assíncrono de crawl em um site ou documentação."""
        client = self._get_client()
        endpoint = f"{self.base_url}/v1/crawl"
        payload: dict[str, Any] = {
            "url": url,
            "maxDepth": max_depth,
            "limit": limit,
            "allowBackwardLinks": allow_backward_links,
            "allowExternalLinks": allow_external_links,
            "scrapeOptions": scrape_options or {"formats": ["markdown"], "onlyMainContent": True},
        }
        if include_paths:
            payload["includePaths"] = include_paths
        if exclude_paths:
            payload["excludePaths"] = exclude_paths

        try:
            res = await client.post(endpoint, json=payload, headers=self._build_headers())
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise FirecrawlUnavailableError(
                f"Não foi possível conectar ao Firecrawl em {self.base_url}: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise FirecrawlUnavailableError(
                f"Tempo limite excedido ao iniciar crawl de {url} via Firecrawl: {exc}"
            ) from exc
        except httpx.HTTPError as exc:
            raise FirecrawlError(f"Falha de rede ao falar com Firecrawl: {exc}") from exc

        self._handle_response_error(res)
        data = res.json()
        if not data.get("success", True) and "error" in data:
            raise FirecrawlError(f"Firecrawl crawl falhou: {data.get('error')}")
        return data

    async def get_crawl_status(self, crawl_id: str) -> dict[str, Any]:
        """Consulta o status e os dados coletados de um job de crawl."""
        client = self._get_client()
        endpoint = f"{self.base_url}/v1/crawl/{crawl_id}"

        try:
            res = await client.get(endpoint, headers=self._build_headers())
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise FirecrawlUnavailableError(
                f"Não foi possível conectar ao Firecrawl em {self.base_url}: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise FirecrawlUnavailableError(
                f"Tempo limite excedido ao consultar crawl {crawl_id}: {exc}"
            ) from exc
        except httpx.HTTPError as exc:
            raise FirecrawlError(f"Falha de rede ao falar com Firecrawl: {exc}") from exc

        self._handle_response_error(res)
        data = res.json()
        if not data.get("success", True) and "error" in data:
            raise FirecrawlError(f"Firecrawl get_crawl_status falhou: {data.get('error')}")
        return data

    async def poll_crawl(
        self,
        crawl_id: str,
        *,
        poll_interval: float = 2.0,
        max_wait: float = 120.0,
    ) -> dict[str, Any]:
        """Aguarda ativamente até que o crawl atinja 'completed' ou estado terminal."""
        elapsed = 0.0
        while elapsed < max_wait:
            status_data = await self.get_crawl_status(crawl_id)
            current_status = status_data.get("status")
            if current_status in {"completed", "failed", "cancelled"}:
                return status_data
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        raise FirecrawlUnavailableError(
            f"Tempo máximo de espera ({max_wait}s) excedido para o crawl {crawl_id}."
        )

    async def aclose(self) -> None:
        """Fecha o cliente HTTP próprio se foi criado."""
        if self._owned_client is not None and not self._owned_client.is_closed:
            await self._owned_client.aclose()
