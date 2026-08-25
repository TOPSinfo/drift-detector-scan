"""Run-over-run movement in catalog coverage — what changed since the last scan.

`catalog_coverage` grades every detected vendor on ONE scan: where we stand. This answers the
other question a backlog is actually managed against — *is it shrinking?* — by diffing this
scan's verdicts against the previous scan's, which is the only form of progress a reader can
check rather than take on faith.

WHAT A FIRST RUN REPORTS: nothing. Diffing against an absent state file would present every
existing attestation as freshly earned, which is the same class of lie as rendering an unread
repo as clean — absence of a prior state is not evidence that everything changed. The delta
carries `comparedAgainst: null` so an empty result reads as "no baseline yet" rather than
"a calm week".

Deterministic: `now` is a pipeline input and every list is sorted, so the same two scans always
produce the same delta. Mirrors `findings_state.py`, which does this for findings.
"""
from __future__ import annotations

import json
import os

from agent.lib.catalog_coverage import SETTLED, STALE

STATE_NAME = "coverage-state.json"


def _load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, ValueError):
        return None


def _save(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2, sort_keys=True)


def apply(records: list, state_dir: str, *, now: str) -> dict:
    """Diff this scan's per-vendor verdicts against the previous scan's, advance the state, and
    return the delta. Writes state even on a first run, so the NEXT run has a baseline."""
    path = os.path.join(state_dir, STATE_NAME)
    prior = _load(path)
    prior_verdicts = (prior or {}).get("verdicts") or {}
    compared_against = (prior or {}).get("now")

    current = {r["vendor"]: r["verdict"] for r in records}
    _save(path, {"now": now, "verdicts": current})

    if prior is None:
        # No baseline at all. Report nothing rather than inventing movement.
        # Tested ON `prior is None`, never on an empty verdict map: a prior scan that detected
        # ZERO vendors is a real baseline saying "nothing was being called then", and treating
        # it as absent would silently skip the delta on every run after it. Absence and
        # emptiness are different states here for the same reason they are everywhere else in
        # this tool.
        return {"comparedAgainst": None, "newlyAttested": [], "newlyStale": [],
                "newlyDetected": [], "noLongerDetected": []}

    newly_attested, newly_stale, newly_detected = [], [], []
    for vendor, verdict in current.items():
        was = prior_verdicts.get(vendor)
        if was is None:
            # First sighting. Report it as detected and nothing else: a vendor that arrives
            # already catalogued was not absorbed this period — nobody did that work now, and
            # crediting it would make the headline movement unreliable.
            newly_detected.append(vendor)
            continue
        if verdict in SETTLED and was not in SETTLED:
            newly_attested.append(vendor)
        elif verdict == STALE and was != STALE:
            newly_stale.append(vendor)

    no_longer = [v for v in prior_verdicts if v not in current]

    return {"comparedAgainst": compared_against,
            "newlyAttested": sorted(newly_attested),
            "newlyStale": sorted(newly_stale),
            "newlyDetected": sorted(newly_detected),
            "noLongerDetected": sorted(no_longer)}
