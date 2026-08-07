"""Manifest/runtime extractor registry. Extractors are pure functions:
extract(repo, path, content) -> list[InventoryRecord], registered by filename basename."""
from __future__ import annotations

_BY_NAME: dict = {}


def register(*basenames: str):
    def deco(fn):
        for n in basenames:
            _BY_NAME[n] = fn
        return fn
    return deco


def extractor_for(path: str):
    return _BY_NAME.get(path.split("/")[-1])


def registered_basenames() -> set:
    return set(_BY_NAME)
