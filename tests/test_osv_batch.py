"""POST /v1/querybatch returns ids only, index-aligned to the queries sent, and paginates when a
queryset is large. Each of those three is a way to silently under-report CVEs, which is the one
outcome principle 1 forbids: a missing vulnerability renders identically to a clean package.

Verified against OSV's own endpoint documentation before these were written:
  - the response is `{"results": [{"vulns": [{"id", "modified"}], "next_page_token"?}]}`;
  - `results` is POSITIONAL — nothing in it names the package it answers;
  - there is NO documented maximum queries per batch;
  - pagination triggers when one query returns >1,000 vulns OR the whole queryset returns >3,000.
"""
import pytest

from agent.lib import osv


def _resp(*id_lists, tokens=None):
    """A querybatch response for N queries, in query order."""
    results = []
    for i, ids in enumerate(id_lists):
        r = {"vulns": [{"id": x, "modified": "2026-01-01T00:00:00Z"} for x in ids]}
        if tokens and tokens.get(i):
            r["next_page_token"] = tokens[i]
        results.append(r)
    return {"results": results}


def test_batch_maps_ids_back_to_the_key_that_asked_for_them():
    """`results` is positional, not keyed. Joining it by anything other than index attributes one
    package's vulnerabilities to another — a wrong CVE against a real repo."""
    keys = [("npm", "axios", "0.21.1"), ("npm", "lodash", "4.17.0"), ("python", "django", "3.0")]
    seen = {}

    def http(url, *, method="GET", body=None, timeout=20):
        seen["queries"] = body["queries"]
        return _resp(["GHSA-axios"], [], ["GHSA-dj1", "GHSA-dj2"])

    out = osv._batch_ids(keys, http=http)
    assert out[("npm", "axios", "0.21.1")] == ["GHSA-axios"]
    assert out[("npm", "lodash", "4.17.0")] == []
    assert out[("python", "django", "3.0")] == ["GHSA-dj1", "GHSA-dj2"]
    assert seen["queries"][1] == {"package": {"ecosystem": "npm", "name": "lodash"},
                                  "version": "4.17.0"}


def test_batch_splits_into_chunks_and_keeps_every_key():
    """A fleet sends far more keys than one request should carry. Chunking must not drop or
    reorder keys across the boundary."""
    keys = [("npm", f"p{i}", "1.0") for i in range(5)]
    calls = []

    def http(url, *, method="GET", body=None, timeout=20):
        calls.append([q["package"]["name"] for q in body["queries"]])
        return _resp(*[[f"GHSA-{q['package']['name']}"] for q in body["queries"]])

    out = osv._batch_ids(keys, http=http, chunk=2)
    assert calls == [["p0", "p1"], ["p2", "p3"], ["p4"]]
    assert len(out) == 5
    assert out[("npm", "p4", "1.0")] == ["GHSA-p4"]


def test_batch_follows_next_page_token_until_exhausted():
    """OSV pages once the whole queryset exceeds 3,000 vulns — reachable at fleet scale. Stopping
    at page one loses real findings and reports the package as clean."""
    keys = [("npm", "big", "1.0")]
    pages = []

    def http(url, *, method="GET", body=None, timeout=20):
        tok = body["queries"][0].get("page_token")
        pages.append(tok)
        if tok is None:
            return _resp(["GHSA-1"], tokens={0: "tok-2"})
        if tok == "tok-2":
            return _resp(["GHSA-2"], tokens={0: "tok-3"})
        return _resp(["GHSA-3"])

    out = osv._batch_ids(keys, http=http)
    assert pages == [None, "tok-2", "tok-3"]
    assert out[("npm", "big", "1.0")] == ["GHSA-1", "GHSA-2", "GHSA-3"]


def test_only_the_unfinished_queries_are_resent_on_the_next_page():
    """page_token is per-QUERY. Resending finished queries would duplicate their ids."""
    keys = [("npm", "a", "1.0"), ("npm", "b", "1.0")]
    sent = []

    def http(url, *, method="GET", body=None, timeout=20):
        sent.append([q["package"]["name"] for q in body["queries"]])
        if len(sent) == 1:
            return _resp(["GHSA-a"], ["GHSA-b1"], tokens={1: "more"})
        return _resp(["GHSA-b2"])

    out = osv._batch_ids(keys, http=http)
    assert sent == [["a", "b"], ["b"]], f"second page must carry only the unfinished query: {sent}"
    assert out[("npm", "a", "1.0")] == ["GHSA-a"]
    assert out[("npm", "b", "1.0")] == ["GHSA-b1", "GHSA-b2"]


def test_batch_refuses_a_response_whose_results_do_not_line_up():
    """Fewer results than queries means the mapping is undefined. Guessing which key lost its
    result would attribute vulnerabilities to the wrong package; failing loudly degrades the whole
    OSV source instead, which the audit already knows how to report."""
    keys = [("npm", "a", "1.0"), ("npm", "b", "1.0")]

    def http(url, *, method="GET", body=None, timeout=20):
        return _resp(["GHSA-a"])            # one result for two queries

    with pytest.raises(ValueError, match="results"):
        osv._batch_ids(keys, http=http)


def test_batch_skips_unsupported_ecosystems_and_missing_versions_without_asking():
    """`rubygems` and a version-less package are both unaskable — verified against
    purl.osv_ecosystem rather than assumed (`go` IS supported, `pypi` is spelled `python`).
    The same filter query_package applies, applied BEFORE the request so an unsupported key
    never occupies a slot in the batch — and still appears in the result with no vulns."""
    keys = [("rubygems", "x", "1.0"), ("npm", "axios", None), ("npm", "axios", "0.21.1")]
    sent = []

    def http(url, *, method="GET", body=None, timeout=20):
        sent.extend(q["package"]["name"] for q in body["queries"])
        return _resp(["GHSA-axios"])

    out = osv._batch_ids(keys, http=http)
    assert sent == ["axios"]
    assert out[("rubygems", "x", "1.0")] == []
    assert out[("npm", "axios", None)] == []
    assert out[("npm", "axios", "0.21.1")] == ["GHSA-axios"]


def test_no_askable_keys_makes_no_request_at_all():
    """A fleet of only unsupported ecosystems must not POST an empty queryset."""
    calls = []

    def http(url, *, method="GET", body=None, timeout=20):
        calls.append(url)
        return _resp()

    out = osv._batch_ids([("rubygems", "x", "1.0")], http=http)
    assert calls == []
    assert out == {("rubygems", "x", "1.0"): []}


# --- phase 2: the detail fetch ----------------------------------------------------------------

def test_detail_is_fetched_once_per_unique_vuln_across_the_whole_fleet():
    """The same CVE recurs across repos and packages. Fetching it once per OCCURRENCE would
    replace 642 query calls with more detail calls than we started with — the collapse, not the
    concurrency, is where the saving comes from."""
    keys = [("npm", "a", "1.0"), ("npm", "b", "1.0"), ("npm", "c", "1.0")]
    detail_calls = []

    def http(url, *, method="GET", body=None, timeout=20):
        if url.endswith("/querybatch"):
            return _resp(["GHSA-shared"], ["GHSA-shared"], ["GHSA-shared", "GHSA-only-c"])
        detail_calls.append(url)
        vid = url.rsplit("/", 1)[-1]
        return {"id": vid, "summary": f"summary for {vid}", "references": []}

    out = osv.query_batch(keys, http=http)
    assert len(detail_calls) == 2, f"expected 2 unique details, got {detail_calls}"
    assert [v["id"] for v in out[("npm", "a", "1.0")]] == ["GHSA-shared"]
    assert [v["id"] for v in out[("npm", "c", "1.0")]] == ["GHSA-shared", "GHSA-only-c"]


def test_a_detail_fetch_that_fails_raises_rather_than_dropping_the_vulnerability():
    """A vuln whose detail cannot be read is NOT a vuln that does not exist. Dropping it renders a
    vulnerable package as clean — the collapse principle 1 refuses. audit_inventory already knows
    how to degrade the whole OSV source and say so."""
    keys = [("npm", "a", "1.0")]

    def http(url, *, method="GET", body=None, timeout=20):
        if url.endswith("/querybatch"):
            return _resp(["GHSA-x"])
        raise OSError("connection reset")

    with pytest.raises(OSError):
        osv.query_batch(keys, http=http)


def test_batch_result_preserves_osv_order_within_a_key():
    """Findings are built by walking this list; a reordering would change drift.json for the same
    inputs, which the determinism principle forbids."""
    keys = [("npm", "a", "1.0")]

    def http(url, *, method="GET", body=None, timeout=20):
        if url.endswith("/querybatch"):
            return _resp(["GHSA-3", "GHSA-1", "GHSA-2"])
        vid = url.rsplit("/", 1)[-1]
        return {"id": vid, "summary": vid, "references": []}

    assert [v["id"] for v in osv.query_batch(keys, http=http)[("npm", "a", "1.0")]] == \
           ["GHSA-3", "GHSA-1", "GHSA-2"]


def test_a_key_with_no_vulns_is_present_and_empty():
    """audit_inventory primes its cache from this mapping; a missing key would read as 'never
    looked' and send that package back down the one-at-a-time path."""
    keys = [("npm", "clean", "9.9.9")]

    def http(url, *, method="GET", body=None, timeout=20):
        return _resp([])

    out = osv.query_batch(keys, http=http)
    assert out == {("npm", "clean", "9.9.9"): []}


# --- transient network faults ------------------------------------------------------------------
#
# Measured on the real fleet: the batched audit failed 3 runs in 5, every time with
# `Errno 104 Connection reset by peer`, losing all 568 CVE findings. The detail phase makes ~177
# requests and any ONE of them failing discarded the entire result. The same egress fault is
# already documented in the fleet's .gitlab-ci.yml, where plain `--retry` proved insufficient
# because it does not cover connection-level resets.
#
# Retrying does not weaken principle 1: "could not read it THIS attempt" and "could not read it"
# are different claims, and only the second should degrade the source.

def test_a_transient_reset_is_retried_rather_than_losing_every_finding():
    calls = {"n": 0}

    def http(url, *, method="GET", body=None, timeout=20):
        if url.endswith("/querybatch"):
            return _resp(["GHSA-x"])
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError(104, "Connection reset by peer")
        return {"id": "GHSA-x", "summary": "s", "references": []}

    out = osv.query_batch([("npm", "a", "1.0")], http=http)
    assert [v["id"] for v in out[("npm", "a", "1.0")]] == ["GHSA-x"]
    assert calls["n"] == 2, "the reset should have been retried exactly once"


def test_a_persistent_failure_still_raises_after_the_retries_are_spent():
    """An OSV that is genuinely unreachable must still degrade the source loudly. Retrying for
    ever would turn 'cannot see' into 'still trying', which is worse than either."""
    calls = {"n": 0}

    def http(url, *, method="GET", body=None, timeout=20):
        if url.endswith("/querybatch"):
            return _resp(["GHSA-x"])
        calls["n"] += 1
        raise OSError(104, "Connection reset by peer")

    with pytest.raises(OSError):
        osv.query_batch([("npm", "a", "1.0")], http=http)
    assert calls["n"] == osv.HTTP_ATTEMPTS, (
        f"expected exactly {osv.HTTP_ATTEMPTS} attempts, got {calls['n']}")


def test_a_malformed_response_is_not_retried():
    """A short `results` array is a protocol violation, not a transient fault. Retrying it would
    hammer OSV for a fault no repetition can fix, and hide a real bug behind a delay."""
    calls = {"n": 0}

    def http(url, *, method="GET", body=None, timeout=20):
        calls["n"] += 1
        return _resp()                      # zero results for one query

    with pytest.raises(ValueError):
        osv._batch_ids([("npm", "a", "1.0")], http=http)
    assert calls["n"] == 1, "a protocol violation must not be retried"


def test_the_batch_request_itself_is_retried_too():
    """The querybatch POST rides the same flaky egress as the detail fetches."""
    calls = {"n": 0}

    def http(url, *, method="GET", body=None, timeout=20):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError(104, "Connection reset by peer")
        return _resp([])

    out = osv._batch_ids([("npm", "a", "1.0")], http=http)
    assert out == {("npm", "a", "1.0"): []}
    assert calls["n"] == 2
