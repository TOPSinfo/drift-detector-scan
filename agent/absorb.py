"""The absorb gate: how the tool learns a new integration shape.

This is the reviewed adaptation mechanism. A shape the scanner is *shown* becomes a durable,
trusted detection capability only by passing this gate — and thereafter it is detected
deterministically, forever. Adaptation is never autonomous: that is the whole point of the
checks below.

An agent can read a repo the scanner cannot and propose what would close the gap —
a new idiom instance, a new vendor, a sunset entry. None of that is trusted because
an agent said it. Everything passes through here first, and this is deterministic
and costs zero tokens.

The three checks exist because of three specific ways this can go wrong:

  1. A DATE NOBODY SOURCED. An unverified retirement date in an audit is worse than
     no entry — people act on these. Every sunset must cite a source URL and parse
     as a real date. (Observed for real: a research pass reported GetCategorySpecifics
     as 2022-04-20 and AddDispute as 2023-01-31; both were wrong by days.)
  2. AN IDIOM THAT CLAIMS MORE THAN IT DELIVERS. A proposal names the call-sites it
     will attribute; we re-scan and require they actually get attributed.
  3. AN IDIOM THAT INVENTS ENDPOINTS. The cardinal rule is no false endpoints, so a
     staged idiom must not attribute anything to a vendor it did not before, and
     residue must strictly shrink — a rule that "fixes" a gap by inventing calls
     elsewhere is worse than the gap.

Only on a clean pass are the specs promoted and an attestation written.
"""
from __future__ import annotations

import os
import re
import shutil

import yaml

from agent.lib import idioms, shapes

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class AbsorbRejected(Exception):
    """A staged proposal failed the gate. The message names which check and why."""


def _load(path: str) -> list:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or []


def check_sunsets(entries: list) -> list:
    """Reject any sunset without a citable source and a parseable date."""
    problems = []
    for i, e in enumerate(entries):
        where = (f"sunset #{i} ({e.get('vendor')} "
                 f"{e.get('operation') or e.get('path') or e.get('domain') or e.get('version')})")
        if not isinstance(e, dict) or not e.get("vendor"):
            problems.append(f"{where}: not a mapping with a vendor")
            continue
        src = str(e.get("source") or "")
        if not src.startswith("http"):
            problems.append(f"{where}: no source URL — a date nobody sourced is not admissible")
        # A dateless entry is legitimate — the catalog format says so ("Omit if the API is
        # already deprecated with no fixed date"), audit.py renders it as "deprecated"
        # without a date, and the seed Amazon MWS entry has none. But silence is
        # ambiguous: "the vendor announced no date" and "I could not find the date" look
        # identical, and only the first is admissible. Requiring the marker makes the
        # author state which one it is.
        retires = str(e.get("retires") or "")
        if retires:
            if not _DATE.match(retires):
                problems.append(f"{where}: `retires` must be YYYY-MM-DD, got {e.get('retires')!r}")
        elif e.get("status") != "deprecated-no-date":
            problems.append(
                f"{where}: no `retires` date. If the vendor announced a deprecation with "
                f"no cut-off, say so explicitly with `status: deprecated-no-date`. If you "
                f"simply could not find the date, do not stage the entry — an undated "
                f"guess is what this gate exists to stop.")
        if not (e.get("operation") or e.get("path") or e.get("domain")
                or e.get("version") is not None):
            problems.append(f"{where}: needs a scope (operation, path, domain, or version)")
        if e.get("path") and not str(e["path"]).startswith("/"):
            problems.append(f"{where}: `path` is an API-family prefix and must start with "
                            f"'/' (e.g. /fba/inbound/v0), got {e['path']!r}")
    return problems


def check_idioms(instances: list) -> list:
    problems = []
    for i, inst in enumerate(instances):
        try:
            idioms._validate(inst, f"idiom #{i} ({inst.get('id') if isinstance(inst, dict) else inst!r})")
        except idioms.IdiomError as exc:
            problems.append(str(exc))
    return problems


def check_claims_in_scope(claims: list, residue_locs) -> list:
    """A claim must name a call-site the certified scan independently flagged as its OWN blind spot
    — the residue (`file:line`s) the `brief` enumerated, derived deterministically BEFORE any agent
    saw the code. A claim outside that set is expansion beyond the stated job.

    Why this matters (the ad-hoc lane's sharpest risk): the gate's `unclaimed` check proves "every
    attributed site was named", which in a human loop a reviewer reads. In an AUTONOMOUS loop nobody
    does — an agent can scan first, read what an over-broad pattern attributed, then write
    claims.yaml to match, and the gate passes on a rule nobody would approve. Bounding claims to the
    scanner's own declared blind spots caps what a gamed claims file can cover. Weakening this check
    is a P0 regression."""
    scope = {str(loc).strip() for loc in (residue_locs or [])}
    return [f"claim out of scope (not a blind spot the brief flagged): {c}"
            for c in (claims or []) if str(c).strip() not in scope]


def measure_against_repo(repo_abs: str, staged_idioms: list, claims: list, *, scan) -> dict:
    """Re-scan `repo_abs` with the staged idioms and MEASURE the proposal against its claims —
    the delta an iterating agent climbs (`absorb --check`), plus the gate problems.

    `scan(idiom_instances) -> {"endpoints": [...], "residue": {...}}` is injected so this is
    testable without an engine. Returns:
        {attributedBefore, attributedAfter, residueBefore, residueAfter,
         claims: {met, missing}, invented, unclaimed, problems}
    `problems` empty == would pass the gate. Pure: writes nothing.
    """
    before = scan(None)
    after = scan(staged_idioms)

    def _attributed(res):
        return {loc for e in res["endpoints"]
                if e.get("vendor") and e["vendor"] != "Unknown" for loc in e.get("files", [])}

    attributed_before = _attributed(before)
    attributed_after = _attributed(after)
    problems = []

    missing = [c for c in claims if c not in attributed_after]
    if missing:
        problems.append("claimed call-sites still unattributed after the change: "
                        + ", ".join(missing[:6]))

    # no false endpoints: no vendor may appear that was not there before — EXCEPT the vendor a
    # path-constant instance is explicitly BOUND to. That family exists precisely because a
    # config-injected host classifies nothing, so its bound vendor is new-by-design and already
    # reviewed (it is named in the instance). Any OTHER new vendor is still a false endpoint.
    bound_vendors = {i.get("vendor") for i in staged_idioms
                     if i.get("family") == "path-constant" and i.get("vendor")}
    vendors_before = {e.get("vendor") for e in before["endpoints"] if e.get("vendor")}
    vendors_after = {e.get("vendor") for e in after["endpoints"] if e.get("vendor")}
    invented = sorted(vendors_after - vendors_before - bound_vendors)
    if invented:
        problems.append(f"attributes endpoints to vendor(s) not previously present: {invented}"
                        " — a rule that invents calls is worse than the gap it closes")

    # An idiom must attribute EXACTLY what it claimed. A proposal that also sweeps up
    # call-sites it never named has not been reviewed for those, and the reviewer had no
    # chance to judge them. This is the check that catches an over-broad pattern: e.g.
    # `$A->getHost()` where $A is a metavariable matching ANY object, which will happily
    # attribute an unrelated library's paths to the repo's one classified vendor.
    unclaimed = sorted((attributed_after - attributed_before) - set(claims))
    if unclaimed:
        problems.append("attributes call-sites it did not claim: " + ", ".join(unclaimed[:6])
                        + " — every attributed site must be named and reviewed")

    # residue must not grow: an idiom that "fixes" a gap by surfacing signals it cannot
    # attribute has traded one blind spot for another. Count BOTH versioned path literals and
    # path constants — a path-constant instance surfaces the latter, so they must be included
    # or the guard is blind to its own family's under-attribution.
    def _residue_n(res):
        r = res["residue"]
        return len(r.get("pathLiterals", [])) + len(r.get("pathConstants", []))
    n_before = _residue_n(before)
    n_after = _residue_n(after)
    if n_after > n_before:
        problems.append(f"residue grew ({n_before} -> {n_after} unattributed path literals/constants)")

    return {"attributedBefore": len(attributed_before), "attributedAfter": len(attributed_after),
            "residueBefore": n_before, "residueAfter": n_after,
            "claims": {"met": [c for c in claims if c in attributed_after], "missing": missing},
            "invented": invented, "unclaimed": unclaimed, "problems": problems}


def verify_against_repo(repo_abs: str, staged_idioms: list, claims: list, *, scan) -> list:
    """The gate's verdict: the list of problems (empty == passes). Thin wrapper over
    measure_against_repo — same before/after logic, just the problems."""
    return measure_against_repo(repo_abs, staged_idioms, claims, scan=scan)["problems"]


def promote(staged_dir: str, *, idioms_path: str, sunsets_path: str) -> dict:
    """Append staged specs to the live catalogs. Only called after a clean gate."""
    added = {"idioms": 0, "sunsets": 0}
    for name, dest, key in (("idioms.yaml", idioms_path, "idioms"),
                            ("sunsets.yaml", sunsets_path, "sunsets")):
        staged = _load(os.path.join(staged_dir, name))
        if not staged:
            continue
        with open(dest, "a", encoding="utf-8") as fh:
            fh.write("\n" + yaml.safe_dump(staged, sort_keys=False))
        added[key] = len(staged)
    return added
