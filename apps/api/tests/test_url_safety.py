"""Item 18c do plano de robustez do navegador interno: bateria parametrizada
que roda a mesma lista de hostnames contra os pontos de chamada de validação
SSRF, garantindo que concordam entre si.

Há 3 pontos de chamada no total, mas só 2 deles compartilham código de
verdade — `eltanix.security.url_safety` (item 1), consumido por
`firecrawl/service.py::validate_target_url` e por
`agent/tools/browser.py::is_agent_local_test_target`. O terceiro,
`services/browser/app.py::validate_url`, mantém uma cópia sincronizada
DELIBERADAMENTE não importada (aquele serviço roda isolado, sem o pacote
`eltanix` instalado — ver a docstring de `security/url_safety.py` e o
addendum do ADR 0007). Para comparar os dois mesmo assim, este arquivo carrega
`services/browser/app.py` via `importlib.util.spec_from_file_location`
(mesmo truque já usado por `test_security_pentest.py`), sem precisar
instalar o serviço como pacote.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from eltanix.security.url_safety import (
    is_agent_local_test_target,
    is_internal_hostname,
    validate_target_url,
)

_SERVICES_PATH = Path(__file__).resolve().parents[3] / "services"

_browser_spec = importlib.util.spec_from_file_location(
    "browser_app_url_safety_test", _SERVICES_PATH / "browser" / "app.py"
)
browser_app = importlib.util.module_from_spec(_browser_spec)
_browser_spec.loader.exec_module(browser_app)  # type: ignore[union-attr]


# Infra que nenhuma sessão alcança, seja pelo firecrawl (scraping externo),
# pelo agente (browser_action) ou pelo painel manual.
HOSTS_SEMPRE_BLOQUEADOS = [
    "169.254.169.254",
    "metadata.google.internal",
    "postgres",
    "redis",
    "minio",
    "executor",
    "mcp-scanner",
]

# Só bloqueado pra sessão de painel (o resultado vai pra um <iframe> do
# navegador real do usuário, que não resolve nomes Docker-internos) — a
# sessão de agente pode alcançar de propósito, pra testar a própria app.
HOSTS_BLOQUEADOS_SO_PARA_PAINEL = ["web", "api", "host.docker.internal"]

HOSTS_SEMPRE_PERMITIDOS = ["exemplo.com", "docs.python.org"]

# `localhost`/`127.0.0.1`/`0.0.0.0` são o único ponto de divergência
# INTENCIONAL entre os dois módulos: `url_safety` os bloqueia (scraping
# externo via firecrawl nunca deveria mirar loopback), mas
# `services/browser/app.py::validate_url` os permite de propósito — são o
# próprio gatilho da substituição por `eltanix-<sid>`/`host.docker.internal`
# (ver `_LOOPBACK_TRIGGERS` naquele arquivo). Verificado explicitamente aqui
# em vez de ficar de fora da bateria, para o divergir continuar sendo uma
# escolha visível, não um esquecimento.
HOSTS_GATILHO_DE_FALLBACK_DIVERGEM_DE_PROPOSITO = ["localhost", "127.0.0.1", "0.0.0.0"]


@pytest.mark.parametrize("hostname", HOSTS_SEMPRE_BLOQUEADOS)
def test_infra_hosts_blocked_by_shared_module_and_by_browser_service(hostname):
    assert is_internal_hostname(hostname) is True
    with pytest.raises(ValueError):
        validate_target_url(f"http://{hostname}/x")

    for session_id in ("panel-x", "agent-x"):
        with pytest.raises(browser_app.HTTPException) as exc_info:
            browser_app.validate_url(f"http://{hostname}/x", session_id=session_id)
        assert exc_info.value.status_code == 400


@pytest.mark.parametrize("hostname", HOSTS_BLOQUEADOS_SO_PARA_PAINEL)
def test_docker_internal_hosts_blocked_for_panel_allowed_for_agent(hostname):
    # Módulo compartilhado: bloqueado para scraping externo (nunca há sessão
    # "de painel" ali) e reconhecido como alvo local legítimo do agente.
    assert is_internal_hostname(hostname) is True
    with pytest.raises(ValueError):
        validate_target_url(f"http://{hostname}/x")
    assert is_agent_local_test_target(hostname) is True

    # Serviço de navegador: mesma distinção painel vs. agente.
    with pytest.raises(browser_app.HTTPException):
        browser_app.validate_url(f"http://{hostname}/x", session_id="panel-x")
    browser_app.validate_url(f"http://{hostname}/x", session_id="agent-x")  # não levanta


@pytest.mark.parametrize("hostname", HOSTS_SEMPRE_PERMITIDOS)
def test_ordinary_hosts_allowed_everywhere(hostname):
    validate_target_url(f"http://{hostname}/x")
    for session_id in ("panel-x", "agent-x"):
        browser_app.validate_url(f"http://{hostname}/x", session_id=session_id)


@pytest.mark.parametrize("hostname", HOSTS_GATILHO_DE_FALLBACK_DIVERGEM_DE_PROPOSITO)
def test_loopback_trigger_hosts_diverge_on_purpose_between_the_two_modules(hostname):
    # Módulo compartilhado (firecrawl/scraping externo): bloqueado, é loopback.
    assert is_internal_hostname(hostname) is True
    with pytest.raises(ValueError):
        validate_target_url(f"http://{hostname}/x")

    # Serviço de navegador: permitido para QUALQUER sessão — é o gatilho do
    # fallback Docker-interno, não um alvo final de verdade.
    for session_id in ("panel-x", "agent-x"):
        browser_app.validate_url(f"http://{hostname}/x", session_id=session_id)


def test_sandbox_container_hostnames_are_internal_but_agent_local() -> None:
    """`eltanix-<session_id>` é Docker-interno (bloqueado como alvo de
    scraping externo) mas é exatamente o que a sessão de AGENTE precisa
    alcançar para testar o próprio sandbox — as duas coisas ao mesmo tempo,
    não uma contradição."""
    hostname = "eltanix-algum-id-de-sessao"
    assert is_internal_hostname(hostname) is True
    assert is_agent_local_test_target(hostname) is True
    with pytest.raises(ValueError):
        validate_target_url(f"http://{hostname}/x")

    with pytest.raises(browser_app.HTTPException):
        browser_app.validate_url(f"http://{hostname}/x", session_id="panel-x")
    browser_app.validate_url(f"http://{hostname}/x", session_id="agent-x")


# --- Lote 2 / item 87: bypass por codificação alternativa de IPv4 -------------
#
# `socket.inet_aton` (e todo resolver real: httpx, curl, libc) aceita IPv4 em
# decimal (`2130706433`), octal (`0177.0.0.1`), hex (`0x7f.0.0.1`) e curto
# (`127.1`). Um bloqueio que só compara o texto `"169.254.169.254"` era
# contornável com `http://2852039166/`. Ambos os módulos normalizam agora
# antes de classificar (`canonical_ipv4` / `_canonical_ipv4`).

# Metadados cloud e faixas privadas, codificados — bloqueados em TODOS os
# pontos de chamada e para qualquer sessão.
IPV4_CODIFICADO_METADADOS_E_PRIVADO = [
    "2852039166",  # 169.254.169.254 (metadados AWS/GCP) em decimal
    "0xa9fea9fe",  # 169.254.169.254 em hex
    "0xA000001",  # 10.0.0.1 (privado) em hex
    "3232235521",  # 192.168.0.1 (privado) em decimal
]

# Loopback codificado: o `validate_target_url` (firecrawl/scraping externo)
# bloqueia — nunca deveria mirar 127.0.0.0/8. O `browser_app.validate_url`
# canoniza para `127.0.0.1`, que é gatilho legítimo de fallback Docker-interno
# (mesma divergência intencional de `HOSTS_GATILHO_DE_FALLBACK_DIVERGEM_DE_PROPOSITO`).
IPV4_CODIFICADO_LOOPBACK = ["2130706433", "0x7f.0.0.1", "127.1", "0177.0.0.1"]

# Ponto final de FQDN — `localhost.` resolve igual a `localhost`.
HOSTS_COM_PONTO_FINAL = ["localhost.", "redis.", "metadata.google.internal."]


@pytest.mark.parametrize("hostname", IPV4_CODIFICADO_METADADOS_E_PRIVADO)
def test_encoded_ipv4_metadata_and_private_blocked_everywhere(hostname):
    assert is_internal_hostname(hostname) is True
    with pytest.raises(ValueError):
        validate_target_url(f"http://{hostname}/x")
    for session_id in ("panel-x", "agent-x"):
        with pytest.raises(browser_app.HTTPException):
            browser_app.validate_url(f"http://{hostname}/x", session_id=session_id)


@pytest.mark.parametrize("hostname", IPV4_CODIFICADO_LOOPBACK)
def test_encoded_ipv4_loopback_blocked_for_external_scraping(hostname):
    assert is_internal_hostname(hostname) is True
    with pytest.raises(ValueError):
        validate_target_url(f"http://{hostname}/x")
    # Serviço de navegador: canoniza para 127.0.0.1, que é gatilho de fallback
    # — permitido de propósito para qualquer sessão.
    for session_id in ("panel-x", "agent-x"):
        browser_app.validate_url(f"http://{hostname}/x", session_id=session_id)


@pytest.mark.parametrize("hostname", HOSTS_COM_PONTO_FINAL)
def test_trailing_dot_hostname_is_normalized_and_blocked(hostname):
    assert is_internal_hostname(hostname) is True
    with pytest.raises(ValueError):
        validate_target_url(f"http://{hostname}/x")


@pytest.mark.parametrize(
    "url",
    [
        "http://[::ffff:169.254.169.254]/",  # IPv4-mapeado em IPv6
        "http://[::1]/",  # loopback IPv6
        "http://[fd00::1]/",  # ULA IPv6 (privado)
        "http://legit.example.com@169.254.169.254/",  # userinfo enganoso
    ],
)
def test_ipv6_and_userinfo_ssrf_vectors_blocked(url):
    with pytest.raises(ValueError):
        validate_target_url(url)
