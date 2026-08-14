"""go.mod extractor: direct requires + the go runtime.

A repo whose only manifest is go.mod produced NO inventory records at all, so its Supply
Chain plane was silently empty — not "no vulnerabilities found", but "nothing was ever
looked at". `go` was also absent from purl.OSV_ECOSYSTEM, so even an extracted record
could not have been audited.

Direct requires only. A `// indirect` line is the transitive set the module graph pulled
in rather than what this repo declares — excluded for the same reason npm devDependencies
are, since auditing them attributes another module's choices to this repo.
"""
from __future__ import annotations

import re

from agent.lib.inventory_models import InventoryRecord, library_techkey
from agent.lib.extractors import register

# `go 1.22` / `go 1.22.3` — the toolchain directive, not a dependency.
_GO_DIRECTIVE = re.compile(r"^go\s+(\d+(?:\.\d+)*)\s*$")
# `require github.com/x/y v1.2.3` (single-line form)
_REQUIRE_ONE = re.compile(r"^require\s+(\S+)\s+(\S+)")
# a line inside a `require ( ... )` block: `github.com/x/y v1.2.3`
_REQUIRE_IN_BLOCK = re.compile(r"^(\S+)\s+(\S+)")
# go.mod pins an exact version or a pseudo-version; neither is a range.
_UNLOCKED = re.compile(r"[\^~<>*\s]")


def _quality(spec: str) -> str:
    return "unlocked" if _UNLOCKED.search(spec or "") else "exact"


def _strip_comment(line: str) -> tuple:
    """(code, had_indirect). `// indirect` is a marker, not prose — check before stripping."""
    indirect = "// indirect" in line
    return line.split("//", 1)[0].strip(), indirect


@register("go.mod")
def extract(repo: str, path: str, content: str) -> list:
    out: list = []
    in_require_block = False
    for raw in (content or "").splitlines():
        line, indirect = _strip_comment(raw)
        if not line:
            continue
        if in_require_block:
            if line.startswith(")"):
                in_require_block = False
                continue
            m = _REQUIRE_IN_BLOCK.match(line)
            if m and not indirect:
                out.append(_library(repo, path, m.group(1), m.group(2)))
            continue
        if line.startswith("require") and line.rstrip().endswith("("):
            in_require_block = True
            continue
        m = _REQUIRE_ONE.match(line)
        if m and not indirect:
            out.append(_library(repo, path, m.group(1), m.group(2)))
            continue
        m = _GO_DIRECTIVE.match(line)
        if m:
            out.append(InventoryRecord(
                repo=repo, manifest_path=path, ecosystem="go",
                tech_key="runtime:go", name="go", kind="runtime",
                version_hint=m.group(1), parse_quality=_quality(m.group(1)),
            ))
    return out


def _library(repo: str, path: str, name: str, version: str) -> InventoryRecord:
    return InventoryRecord(
        repo=repo, manifest_path=path, ecosystem="go",
        tech_key=library_techkey("go", name), name=name, kind="library",
        declared_range=version, parse_quality=_quality(version),
    )
