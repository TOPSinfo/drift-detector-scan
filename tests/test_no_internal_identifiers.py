"""Guard: the public tool tree must never carry the internal GitLab host or client repo names.

The tool is published for adoption; its source is a shop window. A client's private repo map —
namespaces, repo names, `file:line` — must never ship in it. This scans the WHOLE tracked tree so a
future PR can't reintroduce a leak.

The deny-list itself is sensitive (it *names* the client namespaces), so it is NOT hardcoded in the
public tree — earlier it was, which is how the identifiers reached a public mirror. Provide it via
the `DRIFT_INTERNAL_IDS` env var (a single `|`-joined regex) in your PRIVATE dev/CI environment;
when it is absent — any public checkout — the guard skips rather than shipping the names.

Principle 5 (prove a guard against its bug): set DRIFT_INTERNAL_IDS to your real deny-list and this
FAILS on a tree carrying those identifiers; sanitize until it passes. Client-scoped catalog data
lives in the private drift-ops overlay; public examples cite public repos.
"""
import os
import re
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_PATTERNS = os.environ.get("DRIFT_INTERNAL_IDS", "").strip()

_ALLOW = {"tests/test_no_internal_identifiers.py"}
_BINARY = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf"}


def _tracked_text_files():
    out = subprocess.run(["git", "ls-files"], cwd=_ROOT, capture_output=True, text=True).stdout
    for rel in out.splitlines():
        if rel in _ALLOW or Path(rel).suffix.lower() in _BINARY:
            continue
        yield rel, _ROOT / rel


@pytest.mark.skipif(not _PATTERNS,
                    reason="DRIFT_INTERNAL_IDS not set — the internal deny-list lives outside the "
                           "public tree; set it in private dev/CI to run this guard")
def test_no_internal_or_client_identifiers_in_the_public_tree():
    deny = re.compile(_PATTERNS)
    hits = []
    for rel, p in _tracked_text_files():
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except (OSError, ValueError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if deny.search(line):
                hits.append(f"{rel}:{i}: {line.strip()[:100]}")
    assert not hits, (f"{len(hits)} internal/client identifier(s) in the public tree "
                      f"(move client-scoped data to the drift-ops overlay; cite public repos in "
                      f"examples):\n" + "\n".join(hits))
