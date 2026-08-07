"""Framework catalog: which packages are frameworks (vs generic SDKs) in the inventory."""
from __future__ import annotations

from pathlib import Path

import yaml

_CACHE: dict | None = None

# Package-relative so the catalog resolves regardless of the caller's cwd.
_DEFAULT_FRAMEWORKS = str(Path(__file__).resolve().parent.parent / "frameworks.yaml")


def load_frameworks(path: str | None = None) -> dict:
    path = path or _DEFAULT_FRAMEWORKS
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return {eco: {str(n).lower() for n in (names or [])} for eco, names in raw.items()}


def is_framework(ecosystem: str, name: str, catalog: dict | None = None) -> bool:
    global _CACHE
    if catalog is None:
        if _CACHE is None:
            _CACHE = load_frameworks()
        catalog = _CACHE
    return name.lower() in catalog.get(ecosystem, set())
