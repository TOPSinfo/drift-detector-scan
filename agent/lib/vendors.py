"""Vendor catalog: the single source of truth for third-party endpoint detection."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from agent.lib import catalog_overlay

# Captures /v3, /v24.0, /2010-10-01, /2021-06-30 — the version forms in the PM's inventory.
DEFAULT_VERSION_REGEX = r'/(v[0-9][0-9.]*|[0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]{4}-[0-9]{2})'

# Package-relative so the catalog resolves no matter the caller's cwd
# (e.g. when the plugin runs from a teammate's project dir). agent/lib/ -> agent/.
_DEFAULT_VENDORS = str(Path(__file__).resolve().parent.parent / "vendors.yaml")


@dataclass(frozen=True)
class Vendor:
    vendor: str
    techKey: str
    domains: tuple
    version_regex: str
    # An optional DISTINCTIVE path signature (regex, group 1 = version) that identifies this
    # vendor from the URL PATH alone, regardless of host — for calls whose host is a runtime
    # variable ("https://{$shop}/admin/api/2024-01/…"), where host classification is blind but
    # the path is unmistakably this vendor's. Shopify's Admin API is the motivating case.
    path_signature: str | None = None


def vendor_slug(vendor: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", vendor.lower()).strip("-")


def load_vendors(path: str | None = None) -> list:
    # a default (no explicit path) load layers the writable overlay on top of the package
    # baseline; an explicit path means "load exactly this file" (tests, catalog tools).
    overlay = catalog_overlay.load_list(catalog_overlay.VENDORS) if path is None else []
    with open(path or _DEFAULT_VENDORS, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or []
    out = []
    for d in list(raw) + list(overlay):
        out.append(Vendor(
            vendor=d["vendor"], techKey=d["techKey"],
            domains=tuple(d.get("domains") or []),
            version_regex=d.get("versionRegex") or DEFAULT_VERSION_REGEX,
            path_signature=d.get("pathSignature") or None,
        ))
    return out
