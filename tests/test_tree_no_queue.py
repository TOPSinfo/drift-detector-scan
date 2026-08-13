"""No-queue design (docs/superpowers/specs/2026-08-13-no-queue-design.md): the tree stops
rendering a `queued` node — `queued` meant "we have not looked yet", and a scan now resolves
every host in one run (scan -> AI resolution pass -> gate -> re-scan), so that state has
nowhere left to live.

Removing the node is mechanical. The trap is what it implies: an EMPTY lifecycle (tracked=N,
needs-human=0, blocked=0, nothing else) now reads as "everything is settled" — and that
reading is only TRUE if a resolution pass actually ran. A bare `drift-scan run` with no
`--resolve` (a plain scan, a first-ever run, this project's own test suite) must not produce a
tree that LOOKS resolved when nobody ever attempted to resolve anything.

This file is written FIRST, before `queued` is touched in `agent/lib/tree.py` — the honesty
guard has to be proven to fail before the rename exists, or it proves nothing.

Fictional identifiers only (real client hostnames were scrubbed from this public repo):
acmegrocer.com, zenithapp-crm, geo-mapper.
"""
from agent.lib import tree


def _unresolved_eps(n):
    """`n` endpoints exactly the shape a real scan leaves behind when it cannot classify a
    host: an API-shaped one, unclassified, coverage still `queued` in the DATA MODEL (that
    field name does not change — only how the TREE renders it does)."""
    return [{"domain": f"h{i}.geo-mapper.test", "hostClass": "unclassified",
            "coverage": "queued"} for i in range(n)]


def _payload(n_unresolved=3, resolution_ran=None):
    """`resolution_ran=None` omits the key entirely — the shape every payload built before this
    task, and every payload a bare `drift-scan run` (no `--resolve`) produces, actually has."""
    p = {"counts": {
            "detected": n_unresolved, "integrations": n_unresolved, "excluded": 0,
            "coverage": {"tracked": 0, "queued": n_unresolved, "needs-human": 0,
                        "blocked": 0, "na": 0}},
        "endpoints": _unresolved_eps(n_unresolved)}
    if resolution_ran is not None:
        p["resolutionRan"] = resolution_ran
    return p


def _flat(nodes, out=None):
    out = {} if out is None else out
    for n in nodes:
        out[n["key"]] = n
        _flat(n["children"], out)
    return out


def _lifecycle_kids(payload):
    f = _flat(tree.build(payload))
    return {c["key"]: c for c in f["integrations"]["children"]}


# ---------------------------------------------------------------------------------------
# Requirement 1: no `queued` node, ever — resolved or not.
# ---------------------------------------------------------------------------------------

def test_no_queued_node_anywhere_resolved_or_not():
    for resolution_ran in (True, False, None):
        f = _flat(tree.build(_payload(3, resolution_ran)))
        assert "queued" not in f
        assert all(n["label"] != "queued" for n in f.values())


def test_needs_human_and_blocked_still_render_at_zero():
    """Real states a scan can be in — must render even when nothing is in them."""
    kids = _lifecycle_kids(_payload(0, True))
    assert "needs-human" in kids and kids["needs-human"]["n"] == 0
    assert "blocked" in kids and kids["blocked"]["n"] == 0


def test_removing_queued_does_not_drop_the_hosts_it_used_to_count():
    """The rename must not silently lose rows — integrations still sums to its children."""
    f = _flat(tree.build(_payload(3, True)))
    assert sum(c["n"] for c in f["integrations"]["children"]) == f["integrations"]["n"]


# ---------------------------------------------------------------------------------------
# THE HONESTY GUARD. Written first; must fail against pre-Task-4 tree.py (KeyError on
# "unresolved" / the note assertions), because today `build()` has no notion of whether
# resolution ran and no node carries that fact.
# ---------------------------------------------------------------------------------------

def test_a_never_resolved_scan_does_not_render_as_a_clean_zero():
    """The exact failure this task exists to prevent: delete `queued` with nothing to replace
    it, and a scan that never ran `--resolve` becomes indistinguishable from one that settled
    everything — tracked=0, needs-human=0, blocked=0, nothing on screen says why. `resolutionRan`
    is absent here (the ordinary shape of a plain `drift-scan run`), so the tree must carry a
    node — not `needs-human` (that would claim the AI tried and failed) and not `blocked` (that
    would claim a fetch failed; neither happened) — that both counts the 3 genuinely unresolved
    hosts and says the resolution pass did not run."""
    kids = _lifecycle_kids(_payload(3, resolution_ran=None))
    assert kids["needs-human"]["n"] == 0
    assert kids["blocked"]["n"] == 0
    assert "unresolved" in kids, f"expected an 'unresolved' bucket, got {sorted(kids)}"
    node = kids["unresolved"]
    assert node["n"] == 3
    assert "did not run" in (node["note"] or "").lower()


def test_even_a_zero_count_still_declares_the_pass_did_not_run():
    """The stricter form: zero queued-coverage hosts is not, by itself, proof anything was
    resolved — it might just mean nothing needed it. Absent the note, a reader cannot tell
    'we checked, nothing was stuck' from 'nobody looked' — an unnoted zero IS the silent-clean-
    zero this task exists to refuse, even though the raw number is technically correct."""
    kids = _lifecycle_kids(_payload(0, resolution_ran=None))
    node = kids["unresolved"]
    assert node["n"] == 0
    assert node["note"], "a resolution-not-run payload must carry a note even at n=0"


def test_resolution_pass_not_run_is_distinct_from_gate_rejected_or_errored():
    """`resolutionRan=False` (an explicit False, not just an absent key) covers the run.py
    outcomes that are NOT 'applied' — rejected, errored, degraded — where drift.json still
    reflects the pre-resolution scan. Those must read exactly like 'did not run', because from
    the report's point of view nothing was settled."""
    kids = _lifecycle_kids(_payload(2, resolution_ran=False))
    node = kids["unresolved"]
    assert node["n"] == 2
    assert "did not run" in (node["note"] or "").lower()


def test_resolution_having_applied_clears_the_did_not_run_note():
    """The positive control: once the payload carries evidence the pass ran and applied this
    session, the bucket (now legitimately empty — a resolved host reclassifies to tracked/na on
    the re-scan) carries no 'did not run' warning."""
    kids = _lifecycle_kids(_payload(0, resolution_ran=True))
    node = kids["unresolved"]
    assert node["n"] == 0
    assert "did not run" not in (node["note"] or "").lower()


def test_a_leftover_unresolved_host_after_a_real_resolution_pass_is_still_honest():
    """Not every host resolves on the first attempt (an 'unknown' verdict is legitimate and
    leaves the host `queued`, per agent/resolve.py). When resolution DID run this session but a
    host is still stuck, the count must still show — just without the 'never even tried' note,
    since that would understate what actually happened."""
    kids = _lifecycle_kids(_payload(1, resolution_ran=True))
    node = kids["unresolved"]
    assert node["n"] == 1
    assert "did not run" not in (node["note"] or "").lower()


# ---------------------------------------------------------------------------------------
# The payload must actually be ABLE to carry this — proves the plumbing end, not just the
# hand-built fixture shape above. `run.py` records whether `--resolve` applied; `build_payload`
# must be able to receive that and put it on the payload `tree.build` reads.
# ---------------------------------------------------------------------------------------

def test_build_payload_carries_whether_resolution_ran():
    from agent.lib.dashboard_render import build_payload

    inventory = {"repos": [], "scope": {}}
    audit = {"generated": "2026-08-13", "actions": [], "counts": {}, "coverage": {"catalog": []}}
    assert build_payload(inventory, audit)["resolutionRan"] is False
    assert build_payload(inventory, audit, resolved=True)["resolutionRan"] is True
