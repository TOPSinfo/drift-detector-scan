"""API-client packages — surface an integration from a MANIFEST dependency.

When a repo reaches a vendor's API through an SDK (method chains, config-injected base URLs)
there is no scannable host literal — the `sdk-only-no-callsite` blind spot. But the dependency
itself is the evidence: a repo that requires `twilio/sdk` calls the Twilio API even though nothing
in its source spells `api.twilio.com`. We attribute the vendor from the dependency (composer.json /
package.json), evidenced at that manifest file, `attribution: sdk-client` — a READ FACT (the
dependency exists), never a fabricated call-site. The synthetic endpoint carries the vendor's real
host so the coverage/attestation/sunset join dates it exactly like a scanned endpoint.

This is the CONSUMER side; agent/lib/sdk_profiles.py is the WRAPPER side (a repo that IS the SDK).
"""
from __future__ import annotations

from pathlib import Path

import yaml

_DEFAULT = str(Path(__file__).resolve().parent.parent / "sdk_clients.yaml")


def load(path: str | None = None) -> dict:
    """{"<ecosystem>/<name>": {vendor, host}} — the package→vendor map. Absent file → empty."""
    p = path or _DEFAULT
    try:
        with open(p, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or []
    except FileNotFoundError:
        return {}
    out = {}
    for e in raw:
        if isinstance(e, dict) and e.get("package") and e.get("vendor") and e.get("host"):
            out[e["package"]] = {"vendor": e["vendor"], "host": e["host"]}
    return out


def _pkg_key(techkey: str) -> str | None:
    """`lib:composer/twilio/sdk` -> `composer/twilio/sdk`; a non-library techKey -> None."""
    if not techkey or not techkey.startswith("lib:"):
        return None
    return techkey[4:]


def endpoints_for(repo_record: dict, clients: dict) -> list:
    """Synthetic endpoints for a repo that DEPENDS ON a known API-client package. Shaped like a
    scanned endpoint (vendor + the vendor's real host) so the audit/coverage join dates it, but
    marked `attribution: sdk-client` and evidenced at the manifest file — a read fact, not a
    call-site. One endpoint per distinct vendor host, so two Twilio packages don't double-count."""
    out, seen = [], set()
    for s in repo_record.get("sdks") or []:
        key = _pkg_key(s.get("techKey") or "")
        c = clients.get(key) if key else None
        if not c or c["host"] in seen:
            continue
        seen.add(c["host"])
        name = key.split("/", 1)[1] if "/" in key else key
        out.append({
            "vendor": c["vendor"], "host": c["host"], "domain": c["host"],
            "version": None, "techKey": None, "operation": None, "apiPath": "",
            "attribution": "sdk-client",
            "example": f"{s.get('file', 'manifest')} requires {name} → {c['vendor']} API ({c['host']})",
            "file_count": 1, "files": [s.get("file", "manifest")], "classified": True,
        })
    return out
