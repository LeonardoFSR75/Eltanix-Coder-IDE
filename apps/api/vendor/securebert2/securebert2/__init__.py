"""Wrapper package for the local Cisco SecureBERT 2.0 research repository."""

from __future__ import annotations

import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parents[4]
for _candidate in (
    Path(__file__).resolve().parent.parent,
    _repo_root / "vendor" / "securebert2",
):
    if _candidate.exists() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

__all__ = ["__version__"]
__version__ = "0.1.0"
