"""Ad-hoc / just-in-time shapes — the MIDDLE tier.

A finding here was attributed by an idiom **authored this session** and validated against **this one
repo** by the absorb gate (`absorb --check`: claims met, no invented vendor, no unclaimed
attribution, residue not grown), then dated by the **same human-curated sunset catalog** the
certified tier uses. So it is:

  · not CERTIFIED — nobody reviewed the shape;
  · not a raw LEAD — a deterministic scanner attributed these exact lines under a gate that proved
    the shape claims nothing beyond what was named.

Label everywhere: **"AI-shaped · gate-validated (this run)"**. The AI supplies the *where* (the
call-sites); the reviewed catalog supplies the *when* (the date) — an unreviewed shape can surface a
call-site but can never invent a date (no `sunsets.yaml` is ever authored in the ad-hoc lane).

Pure functions only — the diff + the sibling-document shaping, no I/O — mirroring
`probabilistic.compare`, so the whole tier is unit-testable below the artifact.
"""
from __future__ import annotations

import hashlib
import json


def _loc_set(claims) -> set:
    return {str(c).strip() for c in (claims or []) if str(c).strip()}


def _action_locs(files) -> set:
    """The `file:line`s an action touches. A drift.json action's `files` is a list of either
    `{href, loc}` dicts (vendor/sunset actions) or plain `"file:line"` strings — handle both."""
    out = set()
    for f in (files or []):
        loc = f.get("loc") if isinstance(f, dict) else f
        if loc:
            out.add(str(loc).strip())
    return out


def compare(adhoc_drift: dict, claims: list, gate_delta: dict, idioms: list, repo: str) -> dict:
    """The middle-tier projection for ONE repo, restricted to the claimed blind spots.

    `shaped` = the ad-hoc scan's actions whose `file:line` is a claimed loc — i.e. findings the
    certified scan was blind to and the ad-hoc idiom surfaced. `problems` is non-empty iff the gate
    reported anything over-broad (invented vendor / unclaimed attribution); a caller MUST refuse to
    render a repo with problems as validated.
    """
    want = _loc_set(claims)
    problems = list(gate_delta.get("problems") or [])
    if gate_delta.get("invented"):
        problems.append(f"gate reported invented vendor(s): {gate_delta['invented']}")
    if gate_delta.get("unclaimed"):
        problems.append(f"gate reported unclaimed attribution: {gate_delta['unclaimed']}")

    shaped = [a for a in (adhoc_drift.get("actions") or [])
              if _action_locs(a.get("files")) & want]
    dated = [a for a in shaped if a.get("date")]
    attributed_delta = int(gate_delta.get("attributedAfter", 0)) - int(gate_delta.get("attributedBefore", 0))
    return {
        "repo": repo,
        "idioms": idioms,                         # the shape IS the provenance — attached verbatim
        "claims": sorted(want),
        "attributedNew": attributed_delta,        # call-sites the shape newly attributed (from the gate)
        "shaped": shaped,                         # of those, the ones that became actionable findings
        "datedCount": len(dated),                 # of those, the ones the CATALOG could date
        "gate": {k: gate_delta.get(k) for k in
                 ("attributedBefore", "attributedAfter", "residueBefore", "residueAfter", "claims")},
        "problems": problems,                     # non-empty ⇒ NOT validated, do not render as tier 2
    }


def bundle(certified_drift: dict, per_repo: list, now: str) -> dict:
    """The `adhoc.json` sibling document. Hash-bound to ONE certified scan: leads/shapes rendered
    against a different scan than they were derived from are a stale-data trust bug, and hashing is
    the cheapest guard. `drift.json` itself is NEVER modified — this is a separate document, exactly
    as `leads.json`/`probabilistic` are."""
    blob = json.dumps(certified_drift, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return {
        "schemaVersion": "drift-adhoc/v1",
        "meta": {
            "producer": "claude-code",
            "driftJsonSha256": hashlib.sha256(blob).hexdigest(),
            "generated": now,
        },
        "byRepo": list(per_repo),
    }
