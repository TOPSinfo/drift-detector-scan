"""The catalog OVERLAY — a writable, git-versioned layer over the read-only package catalogs.

The package YAMLs (vendors / idioms / vendor_sunsets / catalog_attestations) ship inside the
plugin and the container image, where they are READ-ONLY. The Learn loop grows the two
indexes by ABSORBING entries, and those must land somewhere the deterministic scan can read
on its next run — a rebuild of the image is not an option per scan. That somewhere is
`$DRIFT_CATALOG_DIR`: in production, a directory in the `drift-ops` persistence repo.

Every loader reads `package baseline + overlay`, baseline FIRST so the order is deterministic
(CLAUDE.md principle 3). An absorbed idiom or sunset therefore tunes the very next scan with
no code change and no image rebuild. Unset env var → no overlay → exactly today's behaviour.
The overlay is additive and git-reviewed (principle 4: the catalog is data, reviewed).
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import yaml

# Overlay filenames, one per catalog. NB: the sunsets PACKAGE file is `vendor_sunsets.yaml`,
# but the overlay is `sunsets.local.yaml` — short, and it sits beside the other three.
VENDORS = "vendors.local.yaml"
IDIOMS = "idioms.local.yaml"
SUNSETS = "sunsets.local.yaml"
ATTESTATIONS = "attestations.local.yaml"
SDK_PROFILES = "sdk_profiles.local.yaml"   # client-scoped SDK profiles live in the overlay, not the package
OWN_DOMAINS = "own_domains.local.yaml"     # confirmed own-infra domains — CLIENT DATA, overlay only
NEEDS_HUMAN = "needs_human.local.yaml"     # hosts a resolution pass could not settle — CLIENT DATA, overlay only


def overlay_dir() -> str | None:
    """The overlay directory from $DRIFT_CATALOG_DIR, or None when unset/empty."""
    return os.environ.get("DRIFT_CATALOG_DIR") or None


def overlay_file(name: str) -> str | None:
    """Absolute path to an overlay file iff the overlay dir is set AND the file exists."""
    d = overlay_dir()
    if not d:
        return None
    p = Path(d) / name
    return str(p) if p.is_file() else None


def load_list(name: str) -> list:
    """The overlay YAML list for `name`, or [] (dir unset / file missing / empty file).

    Raises if the overlay file exists but is not a YAML list — a malformed overlay is an
    error, never silently ignored (an overlay that quietly forgets what it holds is worse
    than none: it looks the same as clean)."""
    p = overlay_file(name)
    if not p:
        return []
    with open(p, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"catalog overlay {name} must be a YAML list, "
                         f"got {type(raw).__name__}")
    return raw


def overlay_signature() -> str:
    """A content hash over EVERY file in the overlay directory — not the named overlays one by
    one, the whole directory. This is what a scan-cache key should fold in alongside the compiled
    ruleset signature: `own_domains.local.yaml` (own-infra confirmations) changes a repo's
    classification without changing a single ast-grep rule, so a cache keyed on the ruleset alone
    stays blind to it — the exact bug that made an `own-domain` verdict through `run --resolve` a
    silent no-op (a gated, correctly-written overlay entry the re-scan's cache never saw). Hashing
    the directory rather than enumerating filenames means a FUTURE overlay kind invalidates the
    cache by construction the day it starts being read during a scan, with no call site needing to
    remember to add it.

    Deterministic and content-only (never mtime, never file order): '' when the overlay dir is
    unset, missing, or holds no files, so an unconfigured overlay changes nothing."""
    d = overlay_dir()
    if not d or not os.path.isdir(d):
        return ""
    h = hashlib.sha256()
    for p in sorted(Path(d).iterdir()):
        if not p.is_file():
            continue
        h.update(p.name.encode("utf-8"))
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()[:12]
