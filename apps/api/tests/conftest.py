from __future__ import annotations

import os

import pytest

from sicoobito.config import REPO_ROOT
from sicoobito.router.catalog import load_catalog
from sicoobito.router.pricing import PriceTable

# O catálogo real é a melhor fixture disponível: se um teste quebra porque o
# providers.yaml mudou, é exatamente isso que se quer saber.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")


CONFIG_DIR = REPO_ROOT / "config"


@pytest.fixture
def catalog():
    return load_catalog(CONFIG_DIR / "providers.yaml", CONFIG_DIR / "routes.yaml")


@pytest.fixture
def prices():
    return PriceTable.load(CONFIG_DIR / "pricing.yaml")
