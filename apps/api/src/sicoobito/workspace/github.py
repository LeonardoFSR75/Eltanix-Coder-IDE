"""Cliente mínimo da API do GitHub.

Só o que o agente precisa: abrir PR, ler issue, ver checks de CI. Um SDK
completo traria centenas de endpoints que nunca serão chamados.

O token vem, nesta ordem: `GITHUB_TOKEN` no ambiente, ou `gh auth token` da CLI
já autenticada. A segunda opção evita pedir ao usuário que duplique num `.env`
um token que o `gh` já guarda no keyring do sistema.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import httpx

from sicoobito.logging_setup import get_logger

log = get_logger(__name__)

API_ROOT = "https://api.github.com"
_TIMEOUT = 30.0

# git@github.com:dono/repo.git · https://github.com/dono/repo(.git)
_REMOTE_RE = re.compile(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.]+)")


class GitHubError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RepoRef:
    owner: str
    repo: str

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}"


def parse_remote(url: str) -> RepoRef | None:
    match = _REMOTE_RE.search(url)
    if match is None:
        return None
    return RepoRef(owner=match.group("owner"), repo=match.group("repo"))


@lru_cache(maxsize=1)
def _token_from_cli() -> str | None:
    """Token do `gh`, se a CLI estiver instalada e autenticada."""
    executable = shutil.which("gh")
    if executable is None:
        return None
    try:
        result = subprocess.run(
            [executable, "auth", "token"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("github.gh_cli.failed", error=str(exc))
        return None
    token = result.stdout.strip()
    return token or None


def resolve_token(configured: str = "") -> str | None:
    return configured or _token_from_cli()


class GitHubClient:
    def __init__(self, token: str | None) -> None:
        if not token:
            raise GitHubError(
                "Sem token do GitHub. Defina GITHUB_TOKEN ou rode `gh auth login`."
            )
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.request(
                method, f"{API_ROOT}{path}", headers=self._headers, **kwargs
            )
        if response.status_code >= 400:
            # A mensagem do GitHub é específica ("branch not found", "already
            # exists") e vale mais que o código HTTP sozinho.
            detail = response.text[:500]
            raise GitHubError(f"GitHub {response.status_code} em {path}: {detail}")
        return response.json() if response.content else None

    async def whoami(self) -> dict[str, Any]:
        return await self._request("GET", "/user")

    async def open_pull_request(
        self,
        ref: RepoRef,
        *,
        title: str,
        head: str,
        base: str,
        body: str = "",
        draft: bool = True,
    ) -> dict[str, Any]:
        """Abre um PR. `draft=True` por padrão — quem publica é o humano."""
        payload = {
            "title": title,
            "head": head,
            "base": base,
            "body": body,
            "draft": draft,
        }
        result = await self._request(
            "POST", f"/repos/{ref.owner}/{ref.repo}/pulls", json=payload
        )
        log.info("github.pr.opened", repo=ref.slug, number=result.get("number"), head=head)
        return result

    async def get_issue(self, ref: RepoRef, number: int) -> dict[str, Any]:
        return await self._request("GET", f"/repos/{ref.owner}/{ref.repo}/issues/{number}")

    async def list_issues(self, ref: RepoRef, *, state: str = "open", limit: int = 20) -> Any:
        return await self._request(
            "GET",
            f"/repos/{ref.owner}/{ref.repo}/issues",
            params={"state": state, "per_page": min(limit, 100)},
        )

    async def comment(self, ref: RepoRef, number: int, body: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/repos/{ref.owner}/{ref.repo}/issues/{number}/comments",
            json={"body": body},
        )

    async def check_runs(self, ref: RepoRef, sha: str) -> dict[str, Any]:
        return await self._request(
            "GET", f"/repos/{ref.owner}/{ref.repo}/commits/{sha}/check-runs"
        )
