"""Route InventoryRecords into the superset buckets: runtimes / frameworks / sdks."""
from __future__ import annotations

from agent.lib.frameworks import is_framework


def partition_records(records: list, catalog: dict | None = None) -> dict:
    out = {"runtimes": [], "frameworks": [], "sdks": []}
    for r in records:
        if r.kind == "runtime":
            out["runtimes"].append(r)
        elif r.kind == "library":
            bucket = "frameworks" if is_framework(r.ecosystem, r.name, catalog) else "sdks"
            out[bucket].append(r)
        # any other kind is ignored
    return out
