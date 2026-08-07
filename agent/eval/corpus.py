"""Load + validate the eval corpus (eval/corpus.yaml). The corpus is the versioned ground
truth: each entry pins a real public repo at a SHA and declares what the scanner should
detect. A malformed entry is a hard error — a broken corpus must be loud, never silently
scored as if smaller."""
from __future__ import annotations

import re

import yaml

# The closed failure-mode enum. `known_gaps` values must be members. Documented in eval/taxonomy.md.
TAXONOMY = frozenset({
    "url-split-version", "sdk-only-no-callsite", "uncatalogued-vendor",
    "wrong-host-attribution", "config-driven-url", "env-var-host",
    "private-source", "scan-error", "label-wrong",
})

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def load_corpus(path: str) -> list:
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or []
    if not isinstance(raw, list):
        raise ValueError("corpus must be a YAML list of entries")
    out = []
    for i, e in enumerate(raw):
        where = f"corpus entry #{i} ({e.get('repo') if isinstance(e, dict) else e!r})"
        if not isinstance(e, dict):
            raise ValueError(f"{where}: not a mapping")
        e = dict(e)
        for req in ("repo", "url", "sha", "category"):
            if not e.get(req):
                raise ValueError(f"{where}: missing required field '{req}'")
        e["sha"] = str(e["sha"])
        if not _SHA_RE.match(e["sha"]):
            raise ValueError(f"{where}: sha must be a 40-hex commit, got {e['sha']!r}")
        expect = e.get("expect") or {}
        if not isinstance(expect, dict):
            raise ValueError(f"{where}: expect must be a mapping, got {expect!r}")
        if not expect.get("vendor"):
            raise ValueError(f"{where}: missing required expect.vendor")
        gaps = e.get("known_gaps") or []
        if not isinstance(gaps, list):
            raise ValueError(f"{where}: known_gaps must be a list, got {gaps!r}")
        bad = [g for g in gaps if g not in TAXONOMY]
        if bad:
            raise ValueError(f"{where}: known_gaps not in taxonomy: {bad}")
        out.append(e)
    return out
