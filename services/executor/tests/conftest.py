"""Torna `app.py` (services/executor/app.py) importável como módulo
top-level `app` nos testes, sem transformar o serviço num pacote instalável
só para isso — o serviço roda sozinho num container próprio (ver
`services/executor/Dockerfile`), então não há um `pyproject.toml` aqui.
"""

from __future__ import annotations

import sys
from pathlib import Path

EXECUTOR_ROOT = Path(__file__).resolve().parent.parent
if str(EXECUTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EXECUTOR_ROOT))
