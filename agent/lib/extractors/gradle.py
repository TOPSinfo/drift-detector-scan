"""Gradle version catalog (`libs.versions.toml`): declared libraries as Maven coordinates.

A repo whose only manifest is a version catalog produced NO inventory records, so its
Supply Chain plane was silently empty.

We parse the CATALOG, never `build.gradle` / `build.gradle.kts`: those are Groovy and
Kotlin DSLs that can only be read by running them — the same reason this project parses
`Gemfile.lock` and not `Gemfile`. Everything a build script adds outside the catalog is a
miss, and an honest one.

**The records are `ecosystem="maven"`, not `"gradle"`.** A catalog entry IS a Maven
coordinate, and that is what OSV audits. `gradle` deliberately stays absent from
`purl.OSV_ECOSYSTEM`, where it is the stand-in for an ecosystem we cannot audit at all —
mapping it here would quietly retire that guard.

Scope is this file only. A `version.ref` resolves against this catalog's own `[versions]`
and nowhere else, exactly as a pom's `${property}` resolves against its own `<properties>`.
"""
from __future__ import annotations

import re
import tomllib

from agent.lib.inventory_models import InventoryRecord, library_techkey
from agent.lib.extractors import register

# Gradle version ranges and dynamic versions: [1.0,2.0), 1.+, latest.release
_RANGE = re.compile(r"[\[\]()+,]|latest")


def _quality(version: str, resolved: bool) -> str:
    if not version or not resolved:
        return "best_effort"
    return "unlocked" if _RANGE.search(version) else "exact"


def _coordinate(alias: str, spec) -> tuple:
    """(name, raw_version, version_ref) for one [libraries] entry, or (None, ..) to skip."""
    if isinstance(spec, str):
        # "group:name:version" — the terse string form.
        parts = spec.split(":")
        if len(parts) >= 3:
            return f"{parts[0]}:{parts[1]}", parts[2], None
        if len(parts) == 2:
            return f"{parts[0]}:{parts[1]}", "", None
        return None, "", None
    if not isinstance(spec, dict):
        return None, "", None

    module = spec.get("module")
    if module and ":" in str(module):
        group, _, artifact = str(module).partition(":")
    else:
        group, artifact = spec.get("group"), spec.get("name")
    if not group or not artifact:
        return None, "", None

    version = spec.get("version")
    if isinstance(version, dict):
        # `version.ref = "okhttp"` parses as a nested table.
        return f"{group}:{artifact}", "", version.get("ref")
    return f"{group}:{artifact}", str(version or ""), None


@register("libs.versions.toml")
def extract(repo: str, path: str, content: str) -> list:
    try:
        data = tomllib.loads(content or "")
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid libs.versions.toml: {exc}") from exc

    versions = {k: str(v) for k, v in (data.get("versions") or {}).items()
                if isinstance(v, (str, int, float))}

    out: list = []
    # [plugins] is build tooling and [bundles] is an alias list whose members are already
    # here — including either would report something the application does not ship, or
    # double-count something it does.
    for alias, spec in (data.get("libraries") or {}).items():
        name, version, ref = _coordinate(alias, spec)
        if not name:
            continue
        resolved = True
        if ref is not None:
            version = versions.get(ref, "")
            resolved = ref in versions          # a ref we cannot resolve is NOT a version
        out.append(InventoryRecord(
            repo=repo, manifest_path=path, ecosystem="maven",
            tech_key=library_techkey("maven", name), name=name, kind="library",
            declared_range=version, parse_quality=_quality(version, resolved),
        ))
    return out
