"""pom.xml extractor: direct Maven dependencies + an optional Java runtime.

A repo whose only manifest is pom.xml produced NO inventory records, so its Supply Chain
plane was silently empty — not "no vulnerabilities", but "nothing was looked at".

Scope is deliberately THIS pom only: no parent POMs, no BOM resolution, no network. A
Maven build's true dependency set often lives in a parent we cannot see, so this reports
what the file actually declares and marks anything it could not resolve rather than
guessing. `${...}` versions resolve from this file's own <properties> and nowhere else.

Excluded, each for the same reason npm devDependencies and go `// indirect` are:
  scope=test          the build's own tooling, not what the application ships
  type=pom+import     a BOM — a version manifest, not a package that ships
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from agent.lib.inventory_models import InventoryRecord, library_techkey
from agent.lib.extractors import register

# Real POMs namespace every tag (http://maven.apache.org/POM/4.0.0). A parser matching
# bare `dependency` finds nothing in a real file, so tags are matched local-name-wise.
_NS = re.compile(r"^\{[^}]*\}")
_PROP_REF = re.compile(r"\$\{([^}]+)\}")
_RANGE = re.compile(r"[\[\](),]")          # Maven version RANGES: [1.0,2.0)


def _tag(el) -> str:
    return _NS.sub("", el.tag)


def _child(el, name: str) -> str:
    for c in el:
        if _tag(c) == name:
            return (c.text or "").strip()
    return ""


def _find_all(root, name: str) -> list:
    return [el for el in root.iter() if _tag(el) == name]


def _properties(root) -> dict:
    for el in root:
        if _tag(el) == "properties":
            return {_tag(c): (c.text or "").strip() for c in el}
    return {}


def _resolve(value: str, props: dict) -> tuple:
    """(resolved, fully_resolved). An unresolved ${...} keeps its raw text — the property
    almost always lives in a parent POM we do not fetch, and inventing a version would
    state a fact about the repo that nobody established."""
    if not value or "${" not in value:
        return value, True
    out = _PROP_REF.sub(lambda m: props.get(m.group(1), m.group(0)), value)
    return out, "${" not in out


def _quality(spec: str, resolved: bool) -> str:
    if not resolved:
        return "best_effort"
    return "unlocked" if _RANGE.search(spec or "") else "exact"


@register("pom.xml")
def extract(repo: str, path: str, content: str) -> list:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValueError(f"invalid pom.xml: {exc}") from exc

    props = _properties(root)
    out: list = []
    for dep in _find_all(root, "dependency"):
        scope = _child(dep, "scope")
        dtype = _child(dep, "type")
        if scope == "test":
            continue
        if dtype == "pom" and scope == "import":
            continue
        group, artifact = _child(dep, "groupId"), _child(dep, "artifactId")
        if not group or not artifact:
            continue
        raw = _child(dep, "version")
        version, resolved = _resolve(raw, props)
        name = f"{group}:{artifact}"
        out.append(InventoryRecord(
            repo=repo, manifest_path=path, ecosystem="maven",
            tech_key=library_techkey("maven", name), name=name, kind="library",
            declared_range=version, parse_quality=_quality(version, resolved),
        ))

    # Only from an EXPLICIT property in this pom — never inferred from a plugin default.
    for key in ("maven.compiler.source", "java.version"):
        if props.get(key):
            java, resolved = _resolve(props[key], props)
            out.append(InventoryRecord(
                repo=repo, manifest_path=path, ecosystem="maven",
                tech_key="runtime:java", name="java", kind="runtime",
                version_hint=java, parse_quality=_quality(java, resolved),
            ))
            break
    return out
