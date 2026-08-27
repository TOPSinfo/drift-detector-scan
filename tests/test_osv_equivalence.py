"""The batch path changes WHAT IS ASKED of the API, not what is concluded.

This asserts the two routes normalise to identical dicts — the same assertion the --jobs branch
made for scheduling, made here for a protocol change, which is the riskier of the two. There the
question was "does concurrency reorder anything"; here it is "does a different endpoint, returning
a different shape, reassembled in two phases, still mean the same thing".
"""
from agent.lib import osv


_ADVISORIES = {
    "GHSA-full": {
        "id": "GHSA-full", "aliases": ["CVE-2021-9"], "summary": "Prototype pollution",
        "database_specific": {"severity": "CRITICAL"},
        "affected": [{"package": {"ecosystem": "npm", "name": "lodash"},
                      "ranges": [{"events": [{"introduced": "0"}, {"fixed": "4.17.21"}]}]}],
        "references": [{"url": "https://example.test/lodash"}],
    },
    "GHSA-cvss": {                      # severity derived from a vector, not a label
        "id": "GHSA-cvss", "aliases": [],
        "details": "no summary field at all, only details, which gets truncated to 160 chars",
        "severity": [{"score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}],
        "affected": [], "references": [],
    },
    "GHSA-otherpkg": {                  # `fixed` must come from OUR package's affected entry
        "id": "GHSA-otherpkg", "aliases": ["CVE-2022-3"], "summary": "Cross-package advisory",
        "affected": [
            {"package": {"ecosystem": "npm", "name": "some-other-package"},
             "ranges": [{"events": [{"introduced": "0"}, {"fixed": "9.9.9"}]}]},
            {"package": {"ecosystem": "npm", "name": "lodash"},
             "ranges": [{"events": [{"introduced": "0"}, {"fixed": "4.17.21"}]}]},
        ],
        "references": [{"url": "https://example.test/cross"}],
    },
}

# The SAME package name in two ecosystems, with different fix versions. Without this the
# ecosystem argument to _normalise is dead weight — the name alone disambiguates — and a gate
# that cannot tell the difference passes a probe that drops it. Verified: it does.
_ADVISORIES["GHSA-samename"] = {
    "id": "GHSA-samename", "aliases": ["CVE-2023-7"], "summary": "Same name, two ecosystems",
    "affected": [
        {"package": {"ecosystem": "Packagist", "name": "lodash"},
         "ranges": [{"events": [{"introduced": "0"}, {"fixed": "1.0.0-php"}]}]},
        {"package": {"ecosystem": "npm", "name": "lodash"},
         "ranges": [{"events": [{"introduced": "0"}, {"fixed": "4.17.21"}]}]},
    ],
    "references": [{"url": "https://example.test/samename"}],
}

_FOR_LODASH = ["GHSA-full", "GHSA-cvss", "GHSA-otherpkg", "GHSA-samename"]


def _http(url, *, method="GET", body=None, timeout=20):
    if url.endswith("/query"):
        ids = _FOR_LODASH if body["package"]["name"] == "lodash" else []
        return {"vulns": [_ADVISORIES[i] for i in ids]}
    if url.endswith("/querybatch"):
        out = []
        for q in body["queries"]:
            ids = _FOR_LODASH if q["package"]["name"] == "lodash" else []
            out.append({"vulns": [{"id": i, "modified": "2026-01-01T00:00:00Z"} for i in ids]})
        return {"results": out}
    return _ADVISORIES[url.rsplit("/", 1)[-1]]


def _serial(keys):
    return {tuple(k): osv.query_package(k[0], k[1], k[2], http=_http) for k in keys}


def test_batch_and_per_package_normalise_identically():
    keys = [("npm", "lodash", "4.17.0"), ("npm", "axios", "0.21.1"),
            ("rubygems", "unsupported", "1.0"), ("npm", "noversion", None)]
    assert osv.query_batch(keys, http=_http) == _serial(keys)


def test_equivalence_holds_across_a_chunk_boundary():
    """Chunking is an implementation detail; it must not be visible in the result."""
    keys = [("npm", "lodash", "4.17.0")] + [("npm", f"p{i}", "1.0") for i in range(6)]
    saved, osv.BATCH_CHUNK = osv.BATCH_CHUNK, 2
    try:
        assert osv.query_batch(keys, http=_http) == _serial(keys)
    finally:
        osv.BATCH_CHUNK = saved


def test_the_fixed_version_comes_from_our_package_not_another_in_the_same_advisory():
    """`_normalise` takes the ecosystem and name so `_fixed_version` picks the right `affected`
    entry. Dropping either argument silently yields another package's fix version — a number a
    reader would act on. This is the exact confound the gate above is proved against."""
    out = osv.query_batch([("npm", "lodash", "4.17.0")], http=_http)
    fixed = {v["id"]: v["fixed"] for v in out[("npm", "lodash", "4.17.0")]}
    assert fixed["GHSA-otherpkg"] == "4.17.21", (
        f"expected lodash's fix, got {fixed['GHSA-otherpkg']!r} — the other package's entry won")
    # and the case the NAME cannot disambiguate: same name, different ecosystem, first in the list
    assert fixed["GHSA-samename"] == "4.17.21", (
        f"expected the npm fix, got {fixed['GHSA-samename']!r} — the ecosystem argument was "
        f"ignored and the Packagist entry matched first")
