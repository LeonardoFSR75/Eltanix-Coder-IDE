"""Validação compartilhada de URL/hostname contra SSRF (Server-Side Request Forgery).

Ponto único de verdade para "isto é um host de infraestrutura interna, nunca
deveria ser alcançado a partir de uma URL fornecida por fora" — hoje
consumido por `eltanix.firecrawl.service` (scraping/crawling externo) e
`eltanix.agent.tools.browser` (navegação do agente).

`services/browser/app.py` **não** importa este módulo: aquele serviço roda
num container Docker isolado e deliberadamente mínimo (ver seu Dockerfile —
só instala FastAPI/Playwright/pydantic, nunca o pacote `eltanix` inteiro,
para manter a menor superfície possível numa rede que já é a mais permissiva
do sistema). Ele mantém sua própria cópia sincronizada da mesma lista/lógica
em vez de importar — ver a docstring de `validate_url` lá e o addendum do
ADR 0007 para o porquê dessa duplicação ser intencional, não um descuido.
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.parse


def canonical_ipv4(host: str) -> str | None:
    """Se `host` for um IPv4 em qualquer codificação que os resolvers de fato
    aceitam — decimal (`2130706433`), octal (`0177.0.0.1`), hexadecimal
    (`0x7f.0.0.1`) ou curta (`127.1`) —, devolve a forma pontilhada canônica
    (`127.0.0.1`); senão `None`.

    Sem isto, um bloqueio que só compara o texto `"127.0.0.1"`/`"169.254.169.254"`
    é trivialmente contornável (`http://2130706433/` alcança o loopback em
    `httpx`/`curl`/libc). `socket.inet_aton` aceita exatamente o mesmo
    conjunto de formas que a resolução real de nome faria.
    """
    try:
        packed = socket.inet_aton(host)
    except OSError:
        return None
    return socket.inet_ntoa(packed)


# Hosts e endereços internos que nunca devem ser alvos de scraping/crawling/
# navegação vinda de uma URL externa/fornecida pelo modelo.
BLOCKED_HOSTNAMES: frozenset[str] = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "host.docker.internal",
        "metadata.google.internal",
        "169.254.169.254",
        "postgres",
        "redis",
        "minio",
        "executor",
        "browser",
        "api",
        "web",
        "mcp-scanner",
    }
)

# Prefixo dos hostnames de containers de sandbox por sessão — ver
# `eltanix.sandbox.container.Sandbox.container_name`.
SANDBOX_HOSTNAME_PREFIX = "eltanix-"

# Allowlist (não blocklist!) dos alvos locais que a ferramenta de navegação
# do agente (`browser_action`) pode alcançar para testar a própria aplicação
# — o agente nunca deve sair para a internet pública, então "permitido" é a
# exceção, não a regra. Semântica inversa de `BLOCKED_HOSTNAMES` acima
# (aquela é para scraping/crawling externo, onde "bloqueado" é a exceção).
#
# `host.docker.internal` entra pelo mesmo motivo de `web`/`api`: é o
# fallback de `services/browser/app.py` quando a rede Docker não resolve o
# nome do serviço diretamente (Docker Desktop em Mac/Windows) — o comentário
# de `_DOCKER_INTERNAL_HOSTS_BLOCKED_FOR_PANEL` naquele arquivo já trata esta
# lista como a fonte de verdade para o que uma sessão de agente pode
# alcançar; faltar aqui deixava as duas cópias em desacordo (achado pela
# bateria parametrizada do item 18c, `tests/test_url_safety.py`).
AGENT_LOCAL_TEST_HOSTNAMES: frozenset[str] = frozenset(
    {"localhost", "127.0.0.1", "0.0.0.0", "web", "api", "host.docker.internal"}
)


def is_agent_local_test_target(hostname: str) -> bool:
    """True se `hostname` é um alvo local legítimo para o agente testar a
    própria aplicação: `AGENT_LOCAL_TEST_HOSTNAMES` ou um container de
    sandbox (`eltanix-<session_id>`)."""
    h = (hostname or "").lower()
    return h in AGENT_LOCAL_TEST_HOSTNAMES or h.startswith(SANDBOX_HOSTNAME_PREFIX)


def is_internal_hostname(hostname: str) -> bool:
    """True se `hostname` é infraestrutura Docker interna (nunca alcançável
    de fora da malha de containers, seja pela internet pública ou pelo
    navegador real do usuário)."""
    # Ponto/fim de FQDN: "localhost." e "localhost" resolvem igual.
    h = (hostname or "").lower().rstrip(".")
    if not h:
        return False
    if h in BLOCKED_HOSTNAMES or h.startswith(SANDBOX_HOSTNAME_PREFIX):
        return True
    if h.startswith("169.254."):
        return True
    # Normaliza IPv4 em codificação alternativa (decimal/octal/hex/curta) antes
    # de classificar — senão "http://2130706433/" fura o bloqueio de loopback.
    canonical = canonical_ipv4(h)
    if canonical is not None:
        h = canonical
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved)


def validate_target_url(url: str) -> None:
    """Valida se a URL é segura para scraping/crawling/navegação externa.

    Levanta `ValueError` com uma mensagem explicativa quando a URL é
    vazia/malformada, não usa esquema http(s), ou aponta para um host
    bloqueado por `is_internal_hostname`.
    """
    if not url or not isinstance(url, str):
        raise ValueError("URL não pode ser vazia.")

    url_clean = url.strip()
    if not url_clean.startswith(("http://", "https://")):
        raise ValueError("URL deve começar com http:// ou https://.")

    try:
        parsed = urllib.parse.urlparse(url_clean)
    except Exception as exc:
        raise ValueError(f"URL inválida: {exc}") from exc

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValueError("URL não contém um hostname válido.")

    if is_internal_hostname(hostname):
        raise ValueError(f"Acesso ao host '{hostname}' bloqueado por política de segurança (SSRF).")
