"""Cargo.lock extractor: directly-declared crates + their resolved versions.

A Rust repo produced NO inventory records, so its Supply Chain plane was silently empty.
We parse the LOCK rather than Cargo.toml: the lock carries exact resolved versions, and
its structure marks which crates this repo actually declares.

The distinction that makes it work: a `[[package]]` with **no `source`** is a workspace
member — this repo's own crate, fetched from nowhere. Its `dependencies` list is therefore
the authoritative set of direct dependencies. Everything else in the file was resolved
in to satisfy them.

    [[package]] name = "shop"   (no source)   -> this repo; its deps are DIRECT
    [[package]] name = "serde"  source = ...  -> a crate; report it if declared above
    [[package]] name = "getrandom" source=... -> pulled in by rand; transitive, excluded

Transitive crates are excluded for the same reason go `// indirect` and a Gemfile.lock
spec absent from DEPENDENCIES are: reporting them attributes another crate's choices to
this repo.
"""
from __future__ import annotations

import tomllib

from agent.lib.inventory_models import InventoryRecord, library_techkey
from agent.lib.extractors import register


def _dep_name(entry) -> str:
    """A dependencies entry is `serde`, or `serde 1.0.210`, or
    `serde 1.0.210 (registry+https://...)`. The crate name is the first token — taking
    the whole string as a name loses the crate."""
    return str(entry or "").strip().split(" ", 1)[0]


@register("Cargo.lock")
def extract(repo: str, path: str, content: str) -> list:
    try:
        data = tomllib.loads(content or "")
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid Cargo.lock: {exc}") from exc

    packages = data.get("package") or []
    # name -> resolved version, for packages that came FROM somewhere (crates.io etc.)
    resolved: dict = {}
    declared: list = []
    for pkg in packages:
        if not isinstance(pkg, dict):
            continue
        name = str(pkg.get("name") or "")
        if not name:
            continue
        if pkg.get("source"):
            resolved.setdefault(name, str(pkg.get("version") or ""))
        else:
            # A workspace member: this repo's own crate. Never reported as a library —
            # it is the thing being scanned, not a dependency of it.
            for dep in pkg.get("dependencies") or []:
                dn = _dep_name(dep)
                if dn and dn not in declared:
                    declared.append(dn)

    out: list = []
    for name in declared:
        version = resolved.get(name, "")
        out.append(InventoryRecord(
            repo=repo, manifest_path=path, ecosystem="cargo",
            tech_key=library_techkey("cargo", name), name=name, kind="library",
            declared_range=version,
            # A declared crate with no sourced package is a path/git dependency — say we
            # could not resolve it rather than pin a version the file never states.
            parse_quality="exact" if version else "best_effort",
        ))
    return out
