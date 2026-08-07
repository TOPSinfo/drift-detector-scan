"""The OpenAPI tier answers WHAT is deprecated, never WHEN — and must not pretend."""
import pytest

from agent.lib import oas_deprecations as oas

# shaped after the real Amazon models/orders-api-model/ordersV0.json
ORDERS_V0 = {
    "swagger": "2.0",
    "info": {"title": "Selling Partner API for Orders", "version": "v0"},
    "paths": {
        "/orders/v0/orders": {
            "get": {"operationId": "getOrders", "deprecated": True},
        },
        "/orders/v0/orders/{orderId}": {
            "get": {"operationId": "getOrder", "deprecated": True},
        },
        "/orders/v0/orders/{orderId}/orderItems": {
            "get": {"operationId": "getOrderItems", "deprecated": True},
        },
        "/orders/v0/orders/{orderId}/shipment": {
            "post": {"operationId": "confirmShipment"},          # NOT deprecated
        },
    },
}


def test_extracts_only_the_deprecated_operations():
    recs = oas.extract(ORDERS_V0, source="https://example/ordersV0.json")
    assert {r["operationId"] for r in recs} == {"getOrders", "getOrder", "getOrderItems"}
    assert "confirmShipment" not in {r["operationId"] for r in recs}


def test_maps_operations_onto_the_api_family_the_catalog_scopes_on():
    """The catalog scopes on `path: /orders/v0`; the spec must land on the same axis or
    the two can never be compared."""
    recs = oas.extract(ORDERS_V0)
    assert {r["apiPath"] for r in recs} == {"/orders/v0"}


def test_carries_no_date_and_does_not_invent_one():
    """A spec states deprecation, never a retirement date. Emitting a date here — even a
    plausible one — is the exact failure the absorb gate exists to prevent."""
    for r in oas.extract(ORDERS_V0):
        assert "retires" not in r and "date" not in r


def test_path_level_deprecated_applies_to_every_method_under_it():
    """OpenAPI allows `deprecated` on the path item. Honouring only the operation form
    would silently under-report — the same class of miss as the leading-slash bug."""
    doc = {"info": {"title": "T", "version": "v1"},
           "paths": {"/legacy/v1/thing": {"deprecated": True,
                                          "get": {"operationId": "getThing"},
                                          "delete": {"operationId": "deleteThing"}}}}
    recs = oas.extract(doc)
    assert {r["operationId"] for r in recs} == {"getThing", "deleteThing"}


def test_server_prefix_is_applied_so_the_family_matches_real_call_sites():
    doc = {"info": {"title": "T", "version": "1"},
           "servers": [{"url": "https://api.example.com/base"}],
           "paths": {"/orders/v0/orders": {"get": {"operationId": "g", "deprecated": True}}}}
    assert oas.extract(doc)[0]["path"] == "/base/orders/v0/orders"


def test_deterministic_order():
    a = oas.extract(ORDERS_V0)
    b = oas.extract(dict(ORDERS_V0))
    assert a == b


@pytest.mark.parametrize("bad", [None, [], "x", {}, {"paths": None}, {"paths": {"/x": None}}])
def test_malformed_documents_do_not_crash_the_refresh(bad):
    assert oas.extract(bad) == []


# ------------------------------------------------------------------ reconciliation
def test_reconcile_separates_confirmed_from_newly_flagged():
    """The middle bucket is the point: families the vendor flags that our catalog has
    never heard of."""
    spec = oas.extract(ORDERS_V0) + oas.extract({
        "info": {"title": "Feeds", "version": "2020-09-04"},
        "paths": {"/feeds/2020-09-04/feeds": {"get": {"operationId": "getFeeds",
                                                      "deprecated": True}}}})
    catalog = [{"vendor": "Amazon SP-API", "path": "/orders/v0", "retires": "2027-03-27"},
               {"vendor": "Amazon SP-API", "path": "/catalog/v0", "retires": "2026-06-30"},
               {"vendor": "eBay", "path": "/other/v1"}]     # other vendor, must be ignored
    out = oas.reconcile(spec, catalog, "Amazon SP-API")

    assert set(out["confirmed"]) == {"/orders/v0"}
    assert set(out["newlyFlagged"]) == {"/feeds/2020-09-04"}
    # our catalog dates /catalog/v0 but this spec set does not flag it -> a human decides
    # unmatched, and without the full path set we cannot tell removed from unflagged
    assert out["specUnflagged"] == ["/catalog/v0"]


def test_reconcile_never_mutates_the_catalog():
    """It returns data. Everything enters the catalog through absorb, and only there."""
    catalog = [{"vendor": "Amazon SP-API", "path": "/orders/v0"}]
    before = [dict(e) for e in catalog]
    oas.reconcile(oas.extract(ORDERS_V0), catalog, "Amazon SP-API")
    assert catalog == before


def test_absent_from_specs_corroborates_removal_rather_than_contradicting_it():
    """MEASURED on Amazon 2026-07-20: a vendor DELETES the model once an API is switched
    off, so a family missing from every spec supports our dated entry. reports/2020-09-04,
    feeds/2020-09-04 and fba/smallAndLight/v1 all behaved this way."""
    out = oas.reconcile([], [{"vendor": "V", "path": "/gone/v0", "retires": "2020-01-01"}],
                        "V", all_spec_paths={"/alive/v1/things"})
    assert out["specRemoved"] == ["/gone/v0"]
    assert out["specUnflagged"] == []


def test_published_but_unflagged_is_a_conflict_not_a_clearance():
    """MEASURED on Amazon 2026-07-20: /fba/inbound/v0 is still published with NO
    deprecated flag, while Amazon's own deprecation page says it stopped working
    2025-01-21. The vendor contradicts itself, and 'not flagged' must never read as
    'not deprecated' — doing so would have proposed deleting six live, dated entries
    for APIs that are genuinely dead."""
    out = oas.reconcile([], [{"vendor": "V", "path": "/fba/inbound/v0",
                              "retires": "2025-01-21"}], "V",
                        all_spec_paths={"/fba/inbound/v0/shipments"})
    assert out["specUnflagged"] == ["/fba/inbound/v0"]
    assert out["specRemoved"] == []


def test_nothing_is_ever_auto_removed_from_the_catalog():
    """Neither bucket deletes. Both are reports a human reads."""
    cat = [{"vendor": "V", "path": "/gone/v0", "retires": "2020-01-01"}]
    before = [dict(e) for e in cat]
    oas.reconcile([], cat, "V", all_spec_paths=set())
    assert cat == before


# ------------------------------------------------------------- the refresh command
def _fake_fetch(tree_paths, docs):
    def fetch(url):
        if "git/trees" in url:
            return {"tree": [{"path": p} for p in tree_paths]}
        for name, doc in docs.items():
            if url.endswith(name):
                return doc
        raise OSError(f"unreachable: {url}")
    return fetch


def test_refresh_reports_and_never_writes():
    from agent import catalog_refresh
    cat = [{"vendor": "Amazon SP-API", "path": "/orders/v0", "retires": "2027-03-27"}]
    before = [dict(e) for e in cat]
    out = catalog_refresh.refresh("Amazon SP-API", catalog=cat, fetch=_fake_fetch(
        ["models/orders-api-model/ordersV0.json"], {"ordersV0.json": ORDERS_V0}))
    assert set(out["confirmed"]) == {"/orders/v0"}
    assert cat == before, "refresh must never mutate the catalog"


def test_an_unreachable_spec_is_reported_not_treated_as_unflagged():
    """The failure this project keeps having: 'could not check' rendering as 'clean'.
    A model that 404s must never make its family look un-deprecated."""
    from agent import catalog_refresh
    out = catalog_refresh.refresh("Amazon SP-API", catalog=[], fetch=_fake_fetch(
        ["models/a/ordersV0.json", "models/b/missing.json"], {"ordersV0.json": ORDERS_V0}))
    assert len(out["specsFailed"]) == 1
    assert out["specsFetched"] == 1
    assert "UNREACHABLE" in catalog_refresh.render(out)


def test_conflict_is_rendered_as_a_conflict_not_a_clearance():
    from agent import catalog_refresh
    cat = [{"vendor": "Amazon SP-API", "path": "/fba/inbound/v0", "retires": "2025-01-21"}]
    doc = {"info": {"title": "FBA Inbound", "version": "v0"},
           "paths": {"/fba/inbound/v0/shipments": {"get": {"operationId": "getShipments"}}}}
    out = catalog_refresh.refresh("Amazon SP-API", catalog=cat, fetch=_fake_fetch(
        ["models/fulfillment-inbound-api-model/fulfillmentInboundV0.json"],
        {"fulfillmentInboundV0.json": doc}))
    assert out["specUnflagged"] == ["/fba/inbound/v0"]
    text = catalog_refresh.render(out)
    assert "CONFLICT" in text and "NOT read this as a clearance" in text


def test_unknown_vendor_is_refused_rather_than_guessed():
    from agent import catalog_refresh
    import pytest as _p
    with _p.raises(KeyError):
        catalog_refresh.refresh("Walmart", fetch=lambda u: {})
