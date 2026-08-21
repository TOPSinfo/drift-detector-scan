"""Manifest/runtime extractor registry. Extractors are pure functions:
extract(repo, path, content) -> list[InventoryRecord].

Registration is by exact basename (`package.json`, `go.mod`, `pom.xml`) or, for manifests
whose name varies per project, by SUFFIX (`*.csproj`). The suffix form exists because a
.NET project file is named after its project — `Shop.csproj` — so an exact-basename
registry could never match one, and a .NET repo's Supply Chain plane stayed silently empty
while an extractor sat registered and unreachable.

Exact names win over suffixes: a future `foo.csproj` special case must not be shadowed.
"""
from __future__ import annotations

_BY_NAME: dict = {}
_BY_SUFFIX: dict = {}


def register(*patterns: str):
    """`register("go.mod")` matches that basename; `register("*.csproj")` matches any
    file ending in `.csproj`."""
    def deco(fn):
        for p in patterns:
            if p.startswith("*"):
                _BY_SUFFIX[p[1:]] = fn
            else:
                _BY_NAME[p] = fn
        return fn
    return deco


def extractor_for(path: str):
    base = path.split("/")[-1]
    fn = _BY_NAME.get(base)
    if fn is not None:
        return fn
    for suffix, sfn in _BY_SUFFIX.items():
        # `.csproj` must not match a file literally named `.csproj` with no project name
        if base.endswith(suffix) and len(base) > len(suffix):
            return sfn
    return None


def registered_basenames() -> set:
    return set(_BY_NAME)


