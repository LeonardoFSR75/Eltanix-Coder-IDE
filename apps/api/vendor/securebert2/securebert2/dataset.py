"""Compatibility wrapper for the repo-level dataset module."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parents[4]
_CANDIDATES = [
    Path(__file__).resolve().parent.parent / "dataset.py",
    _repo_root / "vendor" / "securebert2" / "dataset.py",
]

for _candidate in _CANDIDATES:
    if _candidate.exists():
        _SPEC = importlib.util.spec_from_file_location("dataset", _candidate)
        if _SPEC is not None and _SPEC.loader is not None:
            _DATASET_MODULE = importlib.util.module_from_spec(_SPEC)
            _SPEC.loader.exec_module(_DATASET_MODULE)
            for _name, _value in _DATASET_MODULE.__dict__.items():
                if _name.startswith("__") and _name.endswith("__"):
                    continue
                globals()[_name] = _value
            __all__ = getattr(_DATASET_MODULE, "__all__", [])
            break
else:
    raise ImportError(
        "Could not locate the original SecureBERT2 dataset module. "
        "Expected a dataset.py in the cloned repo or in the workspace vendor directory."
    )

if str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
