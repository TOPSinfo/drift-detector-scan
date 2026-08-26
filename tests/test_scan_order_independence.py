"""The engine's match order is NOT stable run-to-run, so nothing downstream may depend on it.

`agent/lib/endpoints.py` says so twice in its own comments and canonicalises for it — but both
canonicalising sorts carry a key that is not TOTAL, and Python's sort is stable, so records that
tie on the key silently keep the engine's arrival order:

  * the residue lists sorted on `loc` alone — two path constants on ONE line tie;
  * the processing walk sorted on `(url-first, path, line)` — two matches on one line tie, and
    `seen_known` is first-wins, so the engine got to pick which same-key record survived.

Found on a real 53-repo fleet: the same repo, scanned three times at the default `--jobs 1` with
no concurrency anywhere, produced three different `inventory.json` files — identical in size and
in the multiset of records, differing only in which of two same-line entries came first. That is
CLAUDE.md principle 3 ("same inputs -> byte-identical output"), and it was true before `--jobs`
existed; parallel scanning is merely the first thing that ever diffed two full runs of one fleet.
"""
from agent.lib.vendors import Vendor
from agent.lib.endpoints import scan_endpoints


_STRIPE = Vendor("Stripe", "api:stripe", ("stripe.com",), r'/(v\d+)')
_VENDORS = [_STRIPE]


def _pc(path, line, text):
    """A path-constant match carrying its own matched text, as ast-grep emits one."""
    return {"kind": "path-constant", "path": path, "line": line, "text": text}


def _url(path, line, text):
    return {"kind": "url", "path": path, "line": line, "text": text}


def test_two_path_constants_on_one_line_sort_the_same_whatever_order_they_arrive(tmp_path):
    """Two path-constant rules matching one line give two residue records with the SAME loc.
    Sorting on loc alone leaves the tie to the engine."""
    a = _pc("Orders.php", 9, '$base = "/admin/api/"; $ep = "/orders/[[ORDER_ID]]/cancel.json";')
    b = _pc("Orders.php", 9, '$ep = "/orders/[[ORDER_ID]]/cancel.json"; $base = "/admin/api/";')

    forward = scan_endpoints([a, b], str(tmp_path), _VENDORS)["residue"]["pathConstants"]
    reverse = scan_endpoints([b, a], str(tmp_path), _VENDORS)["residue"]["pathConstants"]

    assert [r["sample"] for r in forward] == [r["sample"] for r in reverse], (
        "the same two records, delivered in the other order, sorted differently — the residue "
        "sort key is the loc alone and both records share a loc")
    assert sorted(r["sample"] for r in forward) == sorted(r["sample"] for r in reverse), (
        "sanity: this is an ORDERING difference, not a lost or invented record")


def test_two_urls_on_one_line_pick_the_same_surviving_record_whatever_order_they_arrive(tmp_path):
    """`seen_known` is first-wins and the walk's sort key ties on (url, path, line), so which of
    two same-line URL matches becomes the group's `example` was the engine's choice."""
    a = _url("Pay.php", 4, '"https://api.stripe.com/v1/charges?expand=customer";')
    b = _url("Pay.php", 4, '"https://api.stripe.com/v1/charges";')

    forward = scan_endpoints([a, b], str(tmp_path), _VENDORS)["endpoints"]
    reverse = scan_endpoints([b, a], str(tmp_path), _VENDORS)["endpoints"]

    assert [(e.get("apiPath"), e.get("example")) for e in forward] == \
           [(e.get("apiPath"), e.get("example")) for e in reverse], (
        "the surviving record's `example` depended on which match the engine emitted first")


def test_the_whole_document_is_identical_under_a_reversed_match_stream(tmp_path):
    """The guarantee stated end-to-end: reverse the engine's entire emission order and every
    field of the returned document must be untouched."""
    ms = [
        _pc("Orders.php", 9, '$base = "/admin/api/"; $ep = "/orders/x/cancel.json";'),
        _pc("Orders.php", 9, '$ep = "/orders/x/cancel.json"; $base = "/admin/api/";'),
        _pc("Orders.php", 10, '$r = "/orders/x/refunds.json"; $b = "/admin/api/";'),
        _pc("Orders.php", 10, '$b = "/admin/api/"; $r = "/orders/x/refunds.json";'),
        _url("Pay.php", 4, '"https://api.stripe.com/v1/charges?expand=customer";'),
        _url("Pay.php", 4, '"https://api.stripe.com/v1/charges";'),
    ]
    assert scan_endpoints(ms, str(tmp_path), _VENDORS) == \
           scan_endpoints(list(reversed(ms)), str(tmp_path), _VENDORS)


_ACME = Vendor("Acme", "api:acme", ("acme.com",), r'/(v\d+)')


def _pl(path, line, text):
    return {"kind": "path-literal", "path": path, "line": line, "text": text}


def test_an_inferred_group_keeps_the_same_example_whatever_order_matches_arrive(tmp_path):
    """The concat idiom (endpoints.py:309) attributes host-less path literals to the repo's one
    classified vendor with `operation` unset, so every literal sharing an apiPath and version
    collapses into ONE record — and `groups` keeps the FIRST `example` it is handed. That loop
    walked `matches` raw, so the engine chose which call-site the record showed.

    Found on a real repo: one eBay record with 42 call-sites alternated between
    `post-order/v2/cancellation/$cancelId/approve` and `/post-order/v2/` across runs. Both
    collapse to apiPath `/post-order/v2` at version `v2`, so they are the same record by key and
    differ only in which literal got there first.
    """
    ms = [
        _url("Api.php", 1, '"https://api.acme.com/post-order/v2/";'),   # the single classified vendor
        {"kind": "path-assembly", "path": "Api.php", "line": 2},        # what arms the concat idiom
        _pl("Api.php", 3, '$a = "/post-order/v2/cancellation/approve";'),
        _pl("Api.php", 4, '$b = "/post-order/v2/";'),
    ]
    forward = scan_endpoints(ms, str(tmp_path), [_ACME])
    reverse = scan_endpoints(list(reversed(ms)), str(tmp_path), [_ACME])

    inferred = [e for e in forward["endpoints"] if e.get("attribution") == "inferred"]
    assert inferred, "fixture must actually exercise the concat idiom, or it proves nothing"
    assert [(e.get("apiPath"), e.get("example")) for e in forward["endpoints"]] == \
           [(e.get("apiPath"), e.get("example")) for e in reverse["endpoints"]], (
        "an inferred record's `example` depended on which of its call-sites the engine emitted "
        "first")
    assert forward == reverse
