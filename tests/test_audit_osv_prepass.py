"""The 642 sequential requests live in audit_inventory, not in osv.query_all (which has no
production caller at all). Batching therefore needs a pre-pass here: collect every key across
every repo BEFORE the findings loop, so there is something to batch.

The risk this file exists to pin: the pre-pass and the findings loop must derive the SAME keys.
If they drift, the batch fetches keys nobody asks about, or — worse — misses keys the loop then
requests one at a time, quietly restoring the behaviour this change removes.
"""
from agent import audit as audit_mod


_DOC = {"repos": [
    {"path": "a", "sdks": [{"eco": "npm", "pkg": "axios", "ver": "^0.21.1", "resolved": "0.21.1"}]},
    {"path": "b", "sdks": [{"eco": "npm", "pkg": "axios", "ver": "^0.21.1", "resolved": "0.21.1"},
                           {"eco": "npm", "pkg": "lodash", "ver": "^4.17.0", "resolved": "4.17.0"},
                           # unaskable: no version, and an ecosystem OSV does not cover
                           {"eco": "npm", "pkg": "noversion", "ver": None, "resolved": None},
                           {"eco": "rubygems", "pkg": "rack", "ver": "2.0.0", "resolved": "2.0.0"}]},
]}

_VULN = {"id": "GHSA-x", "cve": "CVE-2020-1", "severity": "HIGH", "summary": "s",
         "fixed": "0.21.2", "url": "https://example.test/a"}


def _noop_eol(*a, **k):
    return None


def test_the_prepass_asks_once_for_every_deduped_key_and_the_loop_asks_for_none():
    """One batch call for the whole fleet; zero per-package calls left behind."""
    batched, per_package = [], []

    def fake_batch(keys, *, http=None, jobs=1):
        batched.append(sorted(keys))
        return {tuple(k): [] for k in keys}

    def fake_query(*a, **k):
        per_package.append(a)
        return []

    audit_mod.audit_inventory(_DOC, "2026-08-27", osv_batch=fake_batch, osv_query=fake_query,
                              eol_check=_noop_eol, sunsets=[])
    assert len(batched) == 1, "the fleet must be asked for in ONE batch, not one per repo"
    assert batched[0] == [("npm", "axios", "0.21.1"), ("npm", "lodash", "4.17.0")], (
        f"keys must be deduped across repos and filtered before the request, got {batched[0]}")
    assert per_package == [], "no package may still take the one-at-a-time path"


def test_a_failed_batch_degrades_the_source_loudly_and_finds_nothing_silently():
    """Principle 1: a lookup that could not run must not render as a clean package."""
    def boom(keys, *, http=None, jobs=1):
        raise OSError("connection reset")

    out = audit_mod.audit_inventory(_DOC, "2026-08-27", osv_batch=boom,
                                    eol_check=_noop_eol, sunsets=[])
    assert out["coverage"]["osvErrors"] == 1
    assert any("OSV unreachable" in n for n in out["coverage"]["notes"])
    assert [f for f in out["findings"] if f["kind"] == "cve"] == []


def test_findings_are_identical_to_the_per_package_path():
    """The gate for this task: same vulns in, same findings out."""
    def fake_batch(keys, *, http=None, jobs=1):
        return {tuple(k): ([_VULN] if k[1] == "axios" else []) for k in keys}

    def fake_query(eco, pkg, ver, *, http=None):
        return [_VULN] if pkg == "axios" else []

    batched = audit_mod.audit_inventory(_DOC, "2026-08-27", osv_batch=fake_batch,
                                        eol_check=_noop_eol, sunsets=[])
    serial = audit_mod.audit_inventory(_DOC, "2026-08-27", osv_batch=None, osv_query=fake_query,
                                       eol_check=_noop_eol, sunsets=[])
    assert batched["findings"] == serial["findings"]


def test_osv_batch_none_selects_the_one_at_a_time_path_explicitly():
    """`None` must MEAN "no batching" — distinct from "not specified", which batches. Without
    that distinction the equivalence oracle above cannot be expressed at all."""
    per_package = []

    def fake_query(eco, pkg, ver, *, http=None):
        per_package.append((eco, pkg, ver))
        return []

    audit_mod.audit_inventory(_DOC, "2026-08-27", osv_batch=None, osv_query=fake_query,
                              eol_check=_noop_eol, sunsets=[])
    assert per_package, "osv_batch=None must fall back to query_package, not batch anyway"


def test_the_prepass_and_the_findings_loop_derive_the_same_keys():
    """THE DRIFT GUARD. If the pre-pass computes keys differently from the loop, the loop asks
    for something the batch never fetched — and falls back to a per-package call, quietly
    restoring the 642 requests. Asserted by giving the batch a mapping that covers EXACTLY the
    keys it was handed and failing loudly if the loop then wants anything else."""
    handed = []

    def fake_batch(keys, *, http=None, jobs=1):
        handed.extend(tuple(k) for k in keys)
        return {tuple(k): [] for k in keys}

    def strict_query(eco, pkg, ver, *, http=None):
        raise AssertionError(
            f"the findings loop asked for {(eco, pkg, ver)}, which the pre-pass never fetched — "
            f"the two key derivations have drifted apart")

    audit_mod.audit_inventory(_DOC, "2026-08-27", osv_batch=fake_batch, osv_query=strict_query,
                              eol_check=_noop_eol, sunsets=[])
    assert handed, "the pre-pass fetched nothing at all"


def test_injecting_only_a_per_package_query_selects_that_path():
    """The seam rule, pinned. A caller injecting `osv_query` to stay offline must not find the
    batch path reaching the network behind their back — every existing caller in this suite is a
    test doing exactly that, and they were silently degraded before this rule existed."""
    per_package = []

    def fake_query(eco, pkg, ver, *, http=None):
        per_package.append((eco, pkg, ver))
        return []

    audit_mod.audit_inventory(_DOC, "2026-08-27", osv_query=fake_query,
                              eol_check=_noop_eol, sunsets=[])
    assert per_package, "an injected osv_query was ignored in favour of batching"


def test_an_explicit_batch_wins_even_alongside_an_injected_query():
    """The rule is a default, not a lock: passing osv_batch explicitly decides, in either
    direction. The drift guard above depends on this."""
    batched = []

    def fake_batch(keys, *, http=None, jobs=1):
        batched.append(sorted(keys))
        return {tuple(k): [] for k in keys}

    def fake_query(*a, **k):
        raise AssertionError("explicit osv_batch must win over an injected osv_query")

    audit_mod.audit_inventory(_DOC, "2026-08-27", osv_batch=fake_batch, osv_query=fake_query,
                              eol_check=_noop_eol, sunsets=[])
    assert batched
