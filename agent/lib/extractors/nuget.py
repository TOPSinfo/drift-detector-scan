""".NET manifests: SDK-style `*.csproj` and legacy `packages.config`.

A repo whose only manifest is a project file produced NO inventory records — its Supply
Chain plane was silently empty. Two things were missing: this extractor, and a registry
that could match it at all. A .NET project file is named after its project (`Shop.csproj`),
so the exact-basename registry could never resolve one; see the suffix form in
`agent/lib/extractors/__init__.py`.

SDK-style `<PackageReference>` only. `<ProjectReference>` is another project in the same
solution — source we already scan directly, not a NuGet package to audit.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from agent.lib.inventory_models import InventoryRecord, library_techkey
from agent.lib.extractors import register

# csproj usually has NO xmlns; the legacy format does. Strip either way.
_NS = re.compile(r"^\{[^}]*\}")
# NuGet floating versions: 13.0.*, [13.0,14.0) — a range, not a pin.
_RANGE = re.compile(r"[\[\]()*,]")


def _tag(el) -> str:
    return _NS.sub("", el.tag)


def _child_or_attr(el, name: str) -> str:
    """MSBuild accepts item metadata as either an attribute or a child element, and the
    templates emit both forms — reading one place only silently misses the other."""
    value = (el.get(name) or "").strip()
    if value:
        return value
    for c in el:
        if _tag(c) == name:
            return (c.text or "").strip()
    return ""


def _quality(spec: str) -> str:
    if not spec:
        return "best_effort"
    return "unlocked" if _RANGE.search(spec) else "exact"


@register("*.csproj")
def extract(repo: str, path: str, content: str) -> list:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValueError(f"invalid csproj: {exc}") from exc

    out: list = []
    for el in root.iter():
        if _tag(el) != "PackageReference":
            continue
        name = (el.get("Include") or el.get("Update") or "").strip()
        if not name:
            continue
        # PrivateAssets="all" severs the package from the project output — analyzers and
        # build-only tooling. The same exclusion as Maven scope=test, npm devDependencies
        # and packages.config developmentDependency="true". ONLY `all` qualifies: `runtime`,
        # `compile`, `analyzers` and their combinations still ship or compile against the
        # app. Nothing is skipped by NAME — Moq stays, because the file never says it is
        # test-only, and guessing from names would drop real dependencies.
        if _child_or_attr(el, "PrivateAssets").lower() == "all":
            continue
        # Version can be an attribute or a child element in either style.
        version = _child_or_attr(el, "Version")
        out.append(InventoryRecord(
            repo=repo, manifest_path=path, ecosystem="nuget",
            tech_key=library_techkey("nuget", name), name=name, kind="library",
            declared_range=version, parse_quality=_quality(version),
        ))

    # TargetFramework(s). Kept verbatim (`net8.0`) — that is the moniker .NET itself uses,
    # and rewriting it to `8.0` would invent a version string the file never stated.
    for el in root.iter():
        if _tag(el) in ("TargetFramework", "TargetFrameworks"):
            tfm = (el.text or "").strip()
            if tfm:
                out.append(InventoryRecord(
                    repo=repo, manifest_path=path, ecosystem="nuget",
                    tech_key="runtime:dotnet", name="dotnet", kind="runtime",
                    version_hint=tfm.split(";")[0].strip(),
                    parse_quality="exact" if ";" not in tfm else "best_effort",
                ))
            break
    return out


@register("packages.config")
def extract_packages_config(repo: str, path: str, content: str) -> list:
    """The legacy .NET manifest, pre-SDK-style projects.

    Its own file, not a csproj: `packages.config` is a flat `<packages><package id=.. />`
    list with no ItemGroups and no ProjectReferences, so parsing it as a csproj would find
    nothing. Repos still on it had a silently empty Supply Chain plane.

    NO runtime record is emitted. Each `<package>` carries a `targetFramework` saying what
    THAT PACKAGE was built against — not the project's own TFM. Taking the first one (or
    any of them) would state a runtime the file never asserts, which is a known miss here
    rather than a guess.
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValueError(f"invalid packages.config: {exc}") from exc

    out: list = []
    for el in root.iter():
        if _tag(el) != "package":
            continue
        # The legacy marker for build-only packages — same exclusion as Maven scope=test
        # and npm devDependencies: it is tooling, not something the application ships.
        if (el.get("developmentDependency") or "").strip().lower() == "true":
            continue
        name = (el.get("id") or "").strip()
        if not name:
            continue
        version = (el.get("version") or "").strip()
        out.append(InventoryRecord(
            repo=repo, manifest_path=path, ecosystem="nuget",
            tech_key=library_techkey("nuget", name), name=name, kind="library",
            declared_range=version, parse_quality=_quality(version),
        ))
    return out
