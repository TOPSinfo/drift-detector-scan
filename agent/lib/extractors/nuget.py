"""*.csproj extractor: SDK-style PackageReference + the .NET target framework.

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
        # Version can be an attribute or a child element in either style.
        version = (el.get("Version") or "").strip()
        if not version:
            for c in el:
                if _tag(c) == "Version":
                    version = (c.text or "").strip()
                    break
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
