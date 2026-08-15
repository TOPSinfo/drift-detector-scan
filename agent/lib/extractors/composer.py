"""composer.json extractor: production require + php runtime; skips platform reqs."""
from __future__ import annotations

import json
import re

from agent.lib.inventory_models import InventoryRecord, library_techkey
from agent.lib.extractors import register

_RANGE = re.compile(r"[\^~<>*|\-\s]")
_PLATFORM = re.compile(r"^(ext-|lib-|composer-)")


def _quality(spec: str) -> str:
    return "unlocked" if _RANGE.search(spec or "") else "exact"


@register("composer.json")
def extract(repo: str, path: str, content: str) -> list:
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid composer.json: {exc}") from exc
    out: list = []
    # The package's own `name` is the integration when scanning an SDK tree (require{}
    # lists only its deps). Consumers still get the same tech_key via require — emit
    # once; skip if it also appears in require (rare self-require).
    self_name = (data.get("name") or "").strip()
    required = data.get("require") or {}
    if self_name and self_name not in required and not _PLATFORM.match(self_name.lower()):
        out.append(InventoryRecord(
            repo=repo, manifest_path=path, ecosystem="composer",
            tech_key=library_techkey("composer", self_name), name=self_name,
            kind="library", parse_quality="exact",
            notes="package-self",
        ))
    for name, spec in required.items():
        low = name.lower()
        if low == "php":
            out.append(InventoryRecord(
                repo=repo, manifest_path=path, ecosystem="composer",
                tech_key="runtime:php", name="php", kind="runtime",
                version_hint=str(spec), parse_quality=_quality(str(spec)),
            ))
            continue
        if _PLATFORM.match(low):
            continue
        out.append(InventoryRecord(
            repo=repo, manifest_path=path, ecosystem="composer",
            tech_key=library_techkey("composer", name), name=name, kind="library",
            declared_range=str(spec), parse_quality=_quality(str(spec)),
        ))
    return out
