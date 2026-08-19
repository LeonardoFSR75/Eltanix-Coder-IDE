"""Item 18c do plano de robustez do navegador interno: bateria parametrizada
que roda a mesma lista de hostnames contra os pontos de chamada de validação
SSRF, garantindo que concordam entre si.

Há 3 pontos de chamada no total, mas só 2 deles compartilham código de
verdade — `sicoobito.security.url_safety` (item 1), consumido por
`firecrawl/service.py::validate_target_url` e por
`agent/tools/browser.py::is_agent_local_test_target`. O terceiro,
`services/browser/app.py::validate_url`, mantém uma cópia sincronizada
DELIBERADAMENTE não importada (aquele serviço roda isolado, sem o pacote
`sicoobito` instalado — ver a docstring de `security/url_safety.py` e o
addendum do ADR 0007). Para comparar os dois mesmo assim, este arquivo carrega
`services/browser/app.py` via `importlib.util.spec_from_file_location`
(mesmo truque já usado por `test_security_pentest.py`), sem precisar
instalar o serviço como pacote.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from sicoobito.security.url_safety import (
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
# próprio gatilho da substituição por `sicoobito-<sid>`/`host.docker.internal`
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
    """`sicoobito-<session_id>` é Docker-interno (bloqueado como alvo de
    scraping externo) mas é exatamente o que a sessão de AGENTE precisa
    alcançar para testar o próprio sandbox — as duas coisas ao mesmo tempo,
    não uma contradição."""
    hostname = "sicoobito-algum-id-de-sessao"
    assert is_internal_hostname(hostname) is True
    assert is_agent_local_test_target(hostname) is True
    with pytest.raises(ValueError):
        validate_target_url(f"http://{hostname}/x")

    with pytest.raises(browser_app.HTTPException):
        browser_app.validate_url(f"http://{hostname}/x", session_id="panel-x")
    browser_app.validate_url(f"http://{hostname}/x", session_id="agent-x")
