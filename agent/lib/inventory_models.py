"""Inventory data models + techKey helper. Pure data, no I/O."""
from __future__ import annotations

from dataclasses import dataclass, asdict


def library_techkey(ecosystem: str, name: str) -> str:
    return f"lib:{ecosystem}/{name.strip().lower()}"


@dataclass(frozen=True)
class InventoryRecord:
    repo: str
    manifest_path: str
    ecosystem: str            # npm | composer | python | docker
    tech_key: str             # lib:<eco>/<name>  or  runtime:<product>
    name: str
    kind: str                 # library | runtime
    declared_range: str = ""
    version_hint: str = ""    # for runtimes (e.g. Dockerfile FROM node:18 -> "18")
    parse_quality: str = "exact"   # exact | unlocked | best_effort
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class UsedTech:
    repo: str
    tech_key: str             # api:* / fw:* from the pattern table
    evidence: str

    def to_dict(self) -> dict:
        return asdict(self)
