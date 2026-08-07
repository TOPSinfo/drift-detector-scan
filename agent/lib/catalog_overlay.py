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
