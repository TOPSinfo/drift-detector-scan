"""npm package.json extractor: production dependencies + node runtime."""
from __future__ import annotations

import json
import re

from agent.lib.inventory_models import InventoryRecord, library_techkey
from agent.lib.extractors import register

_RANGE = re.compile(r"[\^~<>*x|\-\s]")


def _quality(spec: str) -> str:
    return "unlocked" if _RANGE.search(spec or "") else "exact"


@register("package.json")
def extract(repo: str, path: str, content: str) -> list:
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid package.json: {exc}") from exc
    out: list = []
    for name, spec in (data.get("dependencies") or {}).items():
        out.append(InventoryRecord(
            repo=repo, manifest_path=path, ecosystem="npm",
            tech_key=library_techkey("npm", name), name=name, kind="library",
            declared_range=str(spec), parse_quality=_quality(str(spec)),
        ))
    node = (data.get("engines") or {}).get("node")
    if node:
        out.append(InventoryRecord(
            repo=repo, manifest_path=path, ecosystem="npm",
            tech_key="runtime:node", name="node", kind="runtime",
            version_hint=str(node), parse_quality=_quality(str(node)),
        ))
    return out
