"""Wrapper package for the local Cisco SecureBERT 2.0 research repository."""

from __future__ import annotations

import sys
from pathlib import Path

for _candidate in (
    Path(__file__).resolve().parent.parent,
    Path(r"C:\Users\leona\Documents\Projetos\SicoobitoCode\vendor\securebert2"),
):
    if _candidate.exists() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

__all__ = ["__version__"]
__version__ = "0.1.0"
