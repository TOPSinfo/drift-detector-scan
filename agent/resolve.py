"""The resolution gate: the only thing standing between a model's opinion and the reviewed
data the deterministic scanner trusts.

A scan leaves some hosts unresolved (`coverage == "queued"` in drift.json — a detected API
service the catalog can't yet name, or an own-infra guess too weak to trust on its own). An AI
resolution pass reads `work_list()`, investigates each host, and proposes a verdict. Nothing it
says is trusted because it said it: every verdict passes through `check_verdicts` first, and
only a CLEAN pass is allowed to land anything (`apply`). This is the no-queue design's data
path (docs/superpowers/specs/2026-08-13-no-queue-design.md) — the AI never writes the answer,
it writes evidence; a gate validates the evidence; the evidence becomes reviewed catalog data;
the deterministic scanner re-derives the answer itself on its next run.

Four verdict shapes, four refusals, each guarding a specific way this goes wrong:

  own-domain       claims a host is this project's own infrastructure. Needs a non-empty
                   `reason` (an unreasoned claim is a guess dressed as a verdict) AND the host
                   must not match a catalogued vendor (agent/vendors.yaml) — a wrong own-domain
                   claim silently deletes a real third party from the audit backlog, this
                   project's cardinal sin, so the vendor always wins regardless of what the
                   model believes. Lands in the own-domains overlay (agent/lib/own_domains.py).
  vendor-identity  claims a host belongs to a named vendor. Needs a `source_url` — without one
                   the model is guessing at attribution. Lands in the vendors overlay.
  retiring         claims a vendor's API is sunsetting. Needs `source_url` + `date` + `excerpt`,
                   with the date appearing VERBATIM in the excerpt (agent.absorb.date_in_text,
                   reused, never reimplemented) — this project shipped plausible-but-wrong dates
                   before this check existed. Lands in the sunsets overlay.
  unknown          "I could not tell." Always legitimate — refusing it would pressure the model
                   into inventing an answer to clear the gate. Never lands in a catalog; it only
                   shows up in the needs-human summary `apply` returns.

All-or-nothing: `apply` gate-validates every verdict in the batch before writing anything. If
any one is rejected, `ResolveRejected` is raised and NOTHING is written — a half-applied verdict
set would leave the catalog in a state nobody reviewed.

Client hostnames can never enter the public tree, so every catalog write in this module goes to
the LOCAL overlay ($DRIFT_CATALOG_DIR, agent/lib/catalog_overlay.py), never agent/*.yaml — the
same rule own_domains.py already follows. If a batch needs to write a catalog entry and no
overlay directory is configured, that too is refused (there is nowhere safe to put it).

Deterministic: stdlib + PyYAML only, no wall-clock (`now` is passed in, exactly like `research`
and `absorb`).
"""
from __future__ import annotations

from pathlib import Path

import yaml

from agent import absorb
from agent.lib import catalog_overlay, classify_url
from agent.lib import vendors as vendors_mod

_STATUSES = ("own-domain", "vendor-identity", "retiring", "unknown")


class ResolveRejected(Exception):
    """A verdict (or the batch) failed the gate. `args[0]` is the list of problem strings."""


def work_list(drift: dict) -> list:
    """The unresolved work-list from a drift.json payload — every endpoint still
    `coverage == "queued"`: its host, its repo (the scope an own-domain verdict must echo back
    so the overlay entry lands correctly-scoped), its call-sites, and why it's unresolved. This
    is exactly what an AI resolution pass consumes."""
    out = []
    for e in drift.get("endpoints", []):
        if e.get("coverage") != "queued":
            continue
        out.append({
            "host": e.get("domain"),
            "repo": e.get("repo"),
            "call_sites": list(e.get("files", [])),
            "hostClass": e.get("hostClass"),
            "reason": e.get("ownInfraReason") or "detected API service, not yet catalogued",
        })
    return out


def _catalogued_vendor_for(host: str, vendors_path=None):
    """The catalogued Vendor whose domain matches `host`, or None. Reuses classify_url's own
    matching (the same logic that classifies scanned endpoints) rather than reimplementing a
    second notion of "matches a vendor"."""
    vs = vendors_mod.load_vendors(vendors_path)
    return classify_url.classify_host((host or "").lower(), vs)


def check_verdicts(verdicts: list, *, vendors_path=None) -> list:
    """Gate every verdict. Returns the list of problems — empty means every verdict passes.
    Refuses, never sanitises: a bad verdict is never dropped-and-continued, it is a reason the
    whole batch fails (see `apply`)."""
    problems = []
    for i, v in enumerate(verdicts or []):
        host = v.get("host") if isinstance(v, dict) else None
        where = f"verdict #{i} ({host or (v.get('domain') if isinstance(v, dict) else v)!r})"
        if not isinstance(v, dict):
            problems.append(f"{where}: not a mapping")
            continue
        host = host or v.get("domain")
        status = v.get("status")
        if status not in _STATUSES:
            problems.append(f"{where}: status must be one of {list(_STATUSES)}, got {status!r}")
            continue
        if not host:
            problems.append(f"{where}: missing `host`")
            continue
        if status == "own-domain":
            if not v.get("reason"):
                problems.append(f"{where}: 'own-domain' needs a non-empty reason")
            if not v.get("repo"):
                problems.append(f"{where}: 'own-domain' needs a `repo` to scope the claim to")
            match = _catalogued_vendor_for(host, vendors_path)
            if match is not None:
                problems.append(
                    f"{where}: 'own-domain' claims {host!r}, but it matches the catalogued "
                    f"vendor {match.vendor!r} (agent/vendors.yaml) — a domain that matches a "
                    f"catalogued vendor can never become own-infra")
        elif status == "vendor-identity":
            if not v.get("vendor"):
                problems.append(f"{where}: 'vendor-identity' needs a `vendor` name")
            if not v.get("source_url"):
                problems.append(
                    f"{where}: 'vendor-identity' needs a source_url confirming the host "
                    f"belongs to that vendor — without one the model is guessing at attribution")
        elif status == "retiring":
            if not v.get("vendor"):
                problems.append(f"{where}: 'retiring' needs a `vendor` name")
            if not v.get("source_url"):
                problems.append(f"{where}: 'retiring' with no source_url")
            elif not v.get("date"):
                problems.append(f"{where}: 'retiring' with no date")
            elif not v.get("excerpt"):
                problems.append(
                    f"{where}: 'retiring' with no excerpt — need the page text that states the date")
            elif not absorb.date_in_text(v.get("date"), v.get("excerpt")):
                problems.append(
                    f"{where}: date {v.get('date')} does NOT appear verbatim in the fetched "
                    f"excerpt (verbatim-date check) — the model may have inferred it")
        # 'unknown' needs nothing further: "I could not tell" is always admissible.
    return problems


def _append_overlay(overlay_dir: str, filename: str, entries: list) -> None:
    if not entries:
        return
    path = Path(overlay_dir) / filename
    existing = []
    if path.is_file():
        existing = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(list(existing) + entries, sort_keys=False, allow_unicode=True),
                    encoding="utf-8")


def apply(verdicts: list, *, now: str, vendors_path=None, overlay_dir: str | None = None) -> dict:
    """Gate-validate every verdict; ONLY if every one passes, land it as reviewed overlay data
    and return a summary. Raises `ResolveRejected` (writing NOTHING) if any verdict — or the
    batch as a whole, e.g. a catalog write with no overlay directory configured — fails.

    Returns {"written": {"own_domain", "vendor_identity", "retiring", "needs_human": <counts>},
             "needs_human": [{"host", "repo", "note"}, ...]}.
    """
    problems = check_verdicts(verdicts, vendors_path=vendors_path)
    if problems:
        raise ResolveRejected(problems)

    own_domain_entries, vendor_entries, sunset_entries, needs_human = [], [], [], []
    for v in verdicts:
        host = v.get("host") or v.get("domain")
        status = v["status"]
        if status == "own-domain":
            own_domain_entries.append({"repo": v["repo"], "domain": host, "by": "ai-resolution",
                                       "checked": now, "reason": v["reason"]})
        elif status == "vendor-identity":
            vendor_entries.append({
                "vendor": v["vendor"],
                "techKey": v.get("techKey") or f"api:{vendors_mod.vendor_slug(v['vendor'])}",
                "domains": [host], "source": v["source_url"],
                "by": "ai-resolution", "checked": now,
            })
        elif status == "retiring":
            sunset_entries.append({
                "vendor": v["vendor"], "domain": host, "source": v["source_url"],
                "retires": v["date"], "excerpt": str(v["excerpt"])[:400],
                "by": "ai-resolution", "checked": now,
            })
        else:   # unknown
            needs_human.append({"host": host, "repo": v.get("repo"), "note": v.get("note", "")})

    written = {"own_domain": len(own_domain_entries), "vendor_identity": len(vendor_entries),
               "retiring": len(sunset_entries), "needs_human": len(needs_human)}

    if own_domain_entries or vendor_entries or sunset_entries:
        d = overlay_dir or catalog_overlay.overlay_dir()
        if not d:
            raise ResolveRejected([
                "$DRIFT_CATALOG_DIR is not set — nowhere safe to write reviewed evidence "
                "(own-domain/vendor-identity/retiring verdicts can never land in agent/*.yaml)"])
        _append_overlay(d, catalog_overlay.OWN_DOMAINS, own_domain_entries)
        _append_overlay(d, catalog_overlay.VENDORS, vendor_entries)
        _append_overlay(d, catalog_overlay.SUNSETS, sunset_entries)

    return {"written": written, "needs_human": needs_human}
