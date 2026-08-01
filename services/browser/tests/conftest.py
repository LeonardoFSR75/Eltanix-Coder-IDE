"""Torna `app.py` (services/browser/app.py) importável como módulo
top-level `app` nos testes, sem transformar o serviço num pacote instalável
só para isso — o serviço roda sozinho num container próprio (ver
`services/browser/Dockerfile`), então não há um `pyproject.toml` aqui.
"""

from __future__ import annotations

import sys
from pathlib import Path

BROWSER_ROOT = Path(__file__).resolve().parent.parent
if str(BROWSER_ROOT) not in sys.path:
    sys.path.insert(0, str(BROWSER_ROOT))
