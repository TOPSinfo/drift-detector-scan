from agent.lib.vendors import Vendor, DEFAULT_VERSION_REGEX
from agent.lib.endpoints import build_endpoints, scan_endpoints
from agent.lib import shapes


def _write(tmp_path, rel, text):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


_SP = Vendor("Amazon SP-API", "api:amazon-sp-api", ("sellingpartnerapi",),
             r'/(v[0-9][0-9.]*|[0-9]{4}-[0-9]{2}-[0-9]{2})')
_STRIPE = Vendor("Stripe", "api:stripe", ("stripe.com",), r'/(v\d+)')
_VENDORS = [_SP, _STRIPE]


def _url(path, line):
    return {"kind": "url", "path": path, "line": line}


def test_endpoints_carry_hostclass(tmp_path):
    """Every endpoint gets a hostClass: catalogued vendor -> 'api'; a found third-party service is
    SHOWN (social/api-lead/unclassified), a bundled asset/lib is excluded. This is what turns the
    'wall of unknowns' into 'here are all your integrations'."""
    _write(tmp_path, "a.php", 'x\n"https://sellingpartnerapi-na.amazon.com/orders/v0/orders";\n')
    _write(tmp_path, "b.html", '<a href="https://wa.me/15551234">chat</a>\n')
    _write(tmp_path, "c.php", '$r = $client->get("https://api.greatschools.org/v2/schools");\n')
    _write(tmp_path, "d.php", '$z = file_get_contents("https://www.zillow.com/homes/list");\n')
    ms = [_url("a.php", 2), _url("b.html", 1), _url("c.php", 1), _url("d.php", 1)]
    out = scan_endpoints(ms, str(tmp_path), _VENDORS)
    by = {e["domain"]: e["hostClass"] for e in out["endpoints"]}
    assert by["sellingpartnerapi-na.amazon.com"] == "api"     # catalogued vendor
    assert by["wa.me"] == "social-widget"                     # share link — a shown integration
    assert by["api.greatschools.org"] == "api-lead"           # api-shaped, in a client call
    assert by["www.zillow.com"] == "unclassified"             # unknown service — SHOWN, not excluded


def test_own_domain_multi_subdomain_is_tagged_own_infra(tmp_path):
    """A registrable domain reached at >=2 distinct hosts is the repo's OWN infra, not a vendor, so
    it drops out of the integration/pending count (the bobavida/orders.acmegrocer.com case). A
    single-host third party is NOT swept in."""
    _write(tmp_path, "a.php", '$x=file_get_contents("https://shop.acmegrocer.com/x");\n')
    _write(tmp_path, "b.php", '$y=file_get_contents("https://orders.acmegrocer.com/y");\n')
    _write(tmp_path, "c.php", '$z=file_get_contents("https://acmegrocer.com/z");\n')
    _write(tmp_path, "d.php", '$r=$client->get("https://api.keepa.com/product");\n')
    ms = [_url("a.php", 1), _url("b.php", 1), _url("c.php", 1), _url("d.php", 1)]
    by = {e["domain"]: e["hostClass"] for e in scan_endpoints(ms, str(tmp_path), _VENDORS)["endpoints"]}
    assert by["shop.acmegrocer.com"] == "own-infra"
    assert by["orders.acmegrocer.com"] == "own-infra"
    assert by["acmegrocer.com"] == "own-infra"
    assert by["api.keepa.com"] == "api-lead"      # single-host third party is NOT swept into own-infra


def test_repo_token_own_infra_claim_records_a_reason(tmp_path):
    """F1 reproduction: `rev-hubspot-connector` -> api.hubspot.com. The repo-name TOKEN signal is
    a heuristic, not the strong git-remote org-domain signal, so the endpoint must carry
    `ownInfraReason` naming it — the field dashboard_render reads to keep the host queued rather
    than silently dropping a real third party out of the research backlog."""
    _write(tmp_path, "a.php", '$r = $client->get("https://api.hubspot.com/crm/v3/objects");\n')
    out = scan_endpoints([_url("a.php", 1)], str(tmp_path), _VENDORS,
                         repo_id="git@git.example.com:example-org/rev-hubspot-connector.git")
    rec = next(e for e in out["endpoints"] if e["domain"] == "api.hubspot.com")
    assert rec["hostClass"] == "own-infra"          # still marked own-infra for display
    assert rec.get("ownInfraReason") == "repo token 'hubspot'"


def test_org_domain_own_infra_claim_records_a_different_reason(tmp_path):
    """The strong signal (a self-hosted forge remote) gets its own distinguishable reason, so a
    reader — or dashboard_render's coverage decision — can tell the two claims apart."""
    _write(tmp_path, "a.php", '$x=file_get_contents("https://anything.devhost.io/x");\n')
    out = scan_endpoints([_url("a.php", 1)], str(tmp_path), _VENDORS,
                         repo_id="https://git.devhost.io/root/zenithapp-crm.git")
    rec = next(e for e in out["endpoints"] if e["domain"] == "anything.devhost.io")
    assert rec["hostClass"] == "own-infra"
    assert rec.get("ownInfraReason") == "git remote org domain 'devhost.io'"


_MAILGUN = Vendor("Mailgun", "api:mailgun", ("mailgun.net",), DEFAULT_VERSION_REGEX)


def test_vendor_named_repo_does_not_swallow_the_vendor_as_own_infra(tmp_path):
    """A repo named after the vendor it integrates with (acme-mailgun-sync) must not have that
    vendor's own name suppress an UNCATALOGUED Mailgun host (e.g. its status page, a different
    domain than the one catalogued) as own-infra. This is the Critical bug the review caught:
    own_infra.signals() drops any derived token that collides with a `vendor_tokens` entry, but
    only if the caller actually passes that set — scan_endpoints must derive it from the vendor
    catalog it already has and wire it through, or the protection is inert."""
    _write(tmp_path, "a.php", '// see https://mailgun-status.io/incidents for outages\n')
    out = scan_endpoints([_url("a.php", 1)], str(tmp_path), [_MAILGUN],
                         repo_id="git@git.example.com:example-org/acme-mailgun-sync.git")
    by = {e["domain"]: e["hostClass"] for e in out["endpoints"]}
    assert by["mailgun-status.io"] != "own-infra"


_GLOBAL_PAYMENTS = Vendor("Global Payments", "api:global-payments", ("globalpayments.com",),
                          DEFAULT_VERSION_REGEX)


def test_multiword_vendor_name_protects_against_concatenated_repo_token(tmp_path):
    """Critical bug: vendor_tokens only carried PER-WORD tokens ('global', 'payments'), but
    own_infra._tokens() splits repo names on [-_.]+ only, so a repo literally named
    'acme-globalpayments-sync' produces the single token 'globalpayments', which never equals
    either per-word vendor token and so was NOT dropped -- silently claiming the vendor's own
    (uncatalogued) host as own-infra. scan_endpoints must also contribute the CONCATENATED form
    of each multi-word vendor name.

    The status host deliberately does NOT match the catalogued domain (globalpayments.com), so
    the endpoint is un-catalogued and must fall through to host_class.classify(own=own_sig) --
    exactly the path the bug lives on."""
    _write(tmp_path, "a.php", '// status page https://globalpayments-status.io/health\n')
    out = scan_endpoints([_url("a.php", 1)], str(tmp_path), [_GLOBAL_PAYMENTS],
                         repo_id="git@git.example.com:example-org/acme-globalpayments-sync.git")
    by = {e["domain"]: e["hostClass"] for e in out["endpoints"]}
    assert by["globalpayments-status.io"] != "own-infra"


def test_repo_token_superset_of_vendor_token_does_not_claim_the_vendor(tmp_path):
    """A repo token that CONTAINS a vendor token ('globalpaymentsapi' contains 'globalpayments')
    is still that vendor's name. Exact equality alone under-protects the concatenated-form fix
    above; own_infra must also drop a repo token that merely contains a vendor token.

    The host itself must be a substring hit on the REPO token (`globalpaymentsapi`), not just the
    vendor token, or the test would pass by accident without ever exercising the contains-check."""
    _write(tmp_path, "a.php", '// status page https://globalpaymentsapi-status.io/health\n')
    out = scan_endpoints([_url("a.php", 1)], str(tmp_path), [_GLOBAL_PAYMENTS],
                         repo_id="git@git.example.com:example-org/acme-globalpaymentsapi-bridge.git")
    by = {e["domain"]: e["hostClass"] for e in out["endpoints"]}
    assert by["globalpaymentsapi-status.io"] != "own-infra"


def test_hyphenated_vendor_name_concatenated_form_is_also_protected(tmp_path):
    """'Amazon SP-API' concatenates to 'amazonspapi'; a repo named acme-amazonspapi-bridge must
    not suppress an uncatalogued Amazon SP-API host (its docs subdomain) as own-infra."""
    _write(tmp_path, "a.php", '// see https://developer-docs.amazonspapi.com/status\n')
    out = scan_endpoints([_url("a.php", 1)], str(tmp_path), [_SP],
                         repo_id="git@git.example.com:example-org/acme-amazonspapi-bridge.git")
    by = {e["domain"]: e["hostClass"] for e in out["endpoints"]}
    assert by["developer-docs.amazonspapi.com"] != "own-infra"


def test_boilerplate_hosts_are_bucketed_not_silently_dropped(tmp_path):
    """The honesty change: formerly-_IGNORE hosts (fonts / CDNs / schemas / doc links) are no longer
    deleted from the stream — they appear as endpoints with a NON-integration hostClass, so 'N
    non-integrations filtered' is visible. Only extraction artifacts / placeholders are dropped."""
    _write(tmp_path, "a.html", '<link href="https://fonts.googleapis.com/css?family=Inter">\n')
    _write(tmp_path, "b.php", '// docs https://www.w3.org/TR/xml/ and http://localhost/health\n')
    out = scan_endpoints([_url("a.html", 1), _url("b.php", 1)], str(tmp_path), _VENDORS)
    by = {e["domain"]: e["hostClass"] for e in out["endpoints"]}
    assert by["fonts.googleapis.com"] == "asset-cdn"   # shown + bucketed, NOT dropped
    assert by["www.w3.org"] == "boilerplate"
    assert "localhost" not in by                        # a genuine non-host is still dropped


def test_output_is_deterministic_regardless_of_match_order(tmp_path):
    """SHIPPED-LATENT BUG: the engine's match order is not stable run-to-run, and endpoints
    were emitted in insertion order — a container double-run produced two drift.json files
    with the SAME endpoints in a DIFFERENT order, breaking the byte-identical guarantee.
    The output must be identical regardless of the order matches arrive in."""
    _write(tmp_path, "a.php", 'x\n"https://api.stripe.com/v1/charges";\n')
    _write(tmp_path, "b.php", 'x\n"https://api.stripe.com/v1/refunds";\n')
    _write(tmp_path, "c.php", 'x\n"https://sellingpartnerapi-na.amazon.com/orders/v0/orders";\n')
    ms = [_url("a.php", 2), _url("b.php", 2), _url("c.php", 2)]
    forward = scan_endpoints(ms, str(tmp_path), _VENDORS)
    reverse = scan_endpoints(list(reversed(ms)), str(tmp_path), _VENDORS)
    assert forward == reverse
    assert [e["example"] for e in forward["endpoints"]] == \
           [e["example"] for e in reverse["endpoints"]]


def test_aggregates_endpoints_with_version_and_filelines(tmp_path):
    _write(tmp_path, "a.php", 'x\n$u = "https://sellingpartnerapi-na.amazon.com/orders/v0/orders";\n')
    _write(tmp_path, "b.php", '$v = "https://api.stripe.com/v1/charges";\n')
    eps = build_endpoints([_url("a.php", 2), _url("b.php", 1)], str(tmp_path), _VENDORS)
    by = {(e["techKey"], e["version"]): e for e in eps}
    sp = by[("api:amazon-sp-api", "v0")]
    assert sp["domain"] == "sellingpartnerapi-na.amazon.com" and sp["files"] == ["a.php:2"]
    assert sp["vendor"] == "Amazon SP-API" and "sellingpartnerapi" in sp["example"]
    assert by[("api:stripe", "v1")]["domain"] == "api.stripe.com"


def test_registrable_suffix_catches_subdomain_variants(tmp_path):
    # the whole point of #1: ebay.com must catch api.sandbox.ebay.com (the old allowlist missed it)
    _write(tmp_path, "c.php", '"https://api.sandbox.ebay.com/ws/api.dll";\n')
    ebay = Vendor("eBay", "api:ebay", ("ebay.com",), r'/(v\d+)')
    eps = build_endpoints([_url("c.php", 1)], str(tmp_path), [ebay])
    assert eps[0]["vendor"] == "eBay" and eps[0]["domain"] == "api.sandbox.ebay.com"


def test_uncatalogued_url_is_unknown_external(tmp_path):
    _write(tmp_path, "d.php", '"https://api.feedonomics.com/v2/import";\n')
    eps = build_endpoints([_url("d.php", 1)], str(tmp_path), _VENDORS)
    assert len(eps) == 1 and eps[0]["vendor"] == "Unknown" and eps[0]["classified"] is False
    assert eps[0]["domain"] == "api.feedonomics.com" and eps[0]["version"] == "v2"


def test_boilerplate_hosts_are_surfaced_and_bucketed_not_dropped(tmp_path):
    """Honesty change (was test_boilerplate_hosts_ignored): formerly-dropped boilerplate now appears
    as endpoints with a NON-integration hostClass, so 'N non-integrations filtered' is visible
    instead of a hidden subtraction."""
    _write(tmp_path, "e.php", '"http://www.w3.org/2001/XMLSchema"; "https://fonts.googleapis.com/css";\n')
    eps = build_endpoints([_url("e.php", 1)], str(tmp_path), _VENDORS)
    by = {e["domain"]: e["hostClass"] for e in eps}
    assert by["www.w3.org"] == "boilerplate"
    assert by["fonts.googleapis.com"] == "asset-cdn"
    assert all(not e["classified"] for e in eps)


def test_known_vendor_kept_even_if_its_registrable_is_on_ignore_list(tmp_path):
    # facebook.com is denoised (marketing) but graph.facebook.com is a real known API — and
    # www.facebook.com now surfaces too, typed 'social' (shown, not dropped).
    _write(tmp_path, "g.php", '"https://graph.facebook.com/v19.0/me"; "https://www.facebook.com/share";\n')
    meta = Vendor("Meta Graph API", "api:meta-graph", ("graph.facebook.com",), r'/(v[0-9.]+)')
    eps = build_endpoints([_url("g.php", 1)], str(tmp_path), [meta])
    by = {e["domain"]: e for e in eps}
    assert by["graph.facebook.com"]["vendor"] == "Meta Graph API"    # catalogued -> api
    assert by["graph.facebook.com"]["hostClass"] == "api"
    assert by["www.facebook.com"]["hostClass"] == "social-widget"    # shown, uncatalogued


def test_same_resource_groups_and_counts(tmp_path):
    """Two call-sites to the SAME resource group into one endpoint. (Same-vendor,
    same-version, DIFFERENT resources now split — a front-loaded version like Stripe's
    /v1/a vs /v1/b names distinct API families, the same granularity Amazon already has,
    and the granularity per-sub-API sunset scoping needs.)"""
    _write(tmp_path, "a.php", '"https://api.stripe.com/v1/charges";\n')
    _write(tmp_path, "b.php", '"https://api.stripe.com/v1/charges";\n')
    eps = build_endpoints([_url("a.php", 1), _url("b.php", 1)], str(tmp_path), [_STRIPE])
    assert len(eps) == 1 and eps[0]["file_count"] == 2 and set(eps[0]["files"]) == {"a.php:1", "b.php:1"}


def test_different_resources_under_one_version_split(tmp_path):
    """The Walmart-shaped case: /v3/insights/refunds and /v3/feeds are distinct APIs on
    separate lifecycles, so they must NOT collapse into one /v3 record."""
    _write(tmp_path, "a.php", '"https://api.stripe.com/v1/charges";\n')
    _write(tmp_path, "b.php", '"https://api.stripe.com/v1/refunds";\n')
    eps = build_endpoints([_url("a.php", 1), _url("b.php", 1)], str(tmp_path), [_STRIPE])
    assert len(eps) == 2
    assert {e["apiPath"] for e in eps} == {"/v1/charges", "/v1/refunds"}


def test_no_version_when_url_has_none(tmp_path):
    _write(tmp_path, "a.php", '"https://api.stripe.com/charges";\n')
    assert build_endpoints([_url("a.php", 1)], str(tmp_path), [_STRIPE])[0]["version"] is None


def test_non_url_matches_ignored(tmp_path):
    assert build_endpoints([{"kind": "sdk", "path": "a.php", "line": 1}], str(tmp_path), _VENDORS) == []


def test_host_only_known_reference_caught_via_endpoint_rule(tmp_path):
    # a config with NO url scheme — 'api.mailgun.net' as a bare host literal (the old allowlist
    # caught this; the broad URL rule alone would miss it, so the per-vendor rule recovers it)
    _write(tmp_path, "services.php", "'mailgun' => ['domain' => 'api.mailgun.net'],\n")
    mg = Vendor("Mailgun", "api:mailgun", ("mailgun.net",), r'/(v\d+)')
    eps = build_endpoints([{"kind": "endpoint", "techKey": "api:mailgun", "path": "services.php", "line": 1}],
                          str(tmp_path), [mg])
    assert len(eps) == 1 and eps[0]["vendor"] == "Mailgun" and eps[0]["files"] == ["services.php:1"]


def test_no_phantom_vendor_from_substring_collision(tmp_path):
    # 'ups.com' (UPS) must NOT match inside 'startups.com'; 'slack.com' not inside 'myslack.com'
    _write(tmp_path, "s.php", '"https://startups.com/x"; $h = "myslack.com";\n')
    vendors = [Vendor("UPS", "api:ups", ("ups.com",), r'/(v\d+)'),
               Vendor("Slack", "api:slack", ("slack.com",), r'/(v\d+)')]
    matches = [{"kind": "url", "path": "s.php", "line": 1},
               {"kind": "endpoint", "techKey": "api:ups", "path": "s.php", "line": 1},
               {"kind": "endpoint", "techKey": "api:slack", "path": "s.php", "line": 1}]
    eps = build_endpoints(matches, str(tmp_path), vendors)
    assert not any(e["vendor"] in ("UPS", "Slack") for e in eps)     # no phantom known integrations
    assert [e["vendor"] for e in eps] == ["Unknown"]                 # startups.com surfaces as Unknown


def test_url_and_vendor_rule_on_same_line_deduped(tmp_path):
    # a real Mailgun URL fires BOTH the url-literal and the mailgun rule at the same spot -> one record
    _write(tmp_path, "m.php", '"https://api.mailgun.net/v3/send";\n')
    mg = Vendor("Mailgun", "api:mailgun", ("mailgun.net",), r'/(v\d+)')
    matches = [{"kind": "url", "path": "m.php", "line": 1},
               {"kind": "endpoint", "techKey": "api:mailgun", "path": "m.php", "line": 1}]
    eps = build_endpoints(matches, str(tmp_path), [mg])
    assert len(eps) == 1 and eps[0]["file_count"] == 1     # not double-counted


def test_most_specific_domain_wins(tmp_path):
    _write(tmp_path, "m.php", '"https://maps.googleapis.com/maps/api/geocode/json";\n')
    vendors = [Vendor("Google APIs", "api:google", ("googleapis.com",), r'/(v\d+)'),
               Vendor("Google Maps", "api:google-maps", ("maps.googleapis.com",), r'/(v\d+)')]
    eps = build_endpoints([_url("m.php", 1)], str(tmp_path), vendors)
    assert len(eps) == 1 and eps[0]["techKey"] == "api:google-maps"     # longest matching domain wins


def test_two_urls_on_one_line_both_extracted(tmp_path):
    _write(tmp_path, "m.php",
           '$u = ["https://api.stripe.com/v1/a","https://sellingpartnerapi-na.amazon.com/orders/v0/b"];\n')
    eps = build_endpoints([_url("m.php", 1)], str(tmp_path), _VENDORS)   # one line -> both URLs classified
    by = {e["techKey"]: e for e in eps}
    assert set(by) == {"api:stripe", "api:amazon-sp-api"}
    assert by["api:stripe"]["version"] == "v1" and by["api:amazon-sp-api"]["version"] == "v0"


def test_endpoint_files_are_repo_relative(tmp_path):
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "req.php").write_text('"https://api.stripe.com/v1/x";\n')
    eps = build_endpoints([_url(str(tmp_path / "lib" / "req.php"), 1)], str(tmp_path), [_STRIPE])
    assert eps[0]["files"] == ["lib/req.php:1"] and eps[0]["version"] == "v1"


def test_path_literal_attributed_when_single_vendor_and_assembly_present(tmp_path):
    _write(tmp_path, "Configuration.php", "$host = 'https://sellingpartnerapi-na.amazon.com';\n")
    _write(tmp_path, "OrdersApi.php",
           "$resource_path = '/orders/2026-01-01/orders';\n"
           "$url = $this->config->getHost() . $resource_path;\n")
    matches = [
        {"kind": "url", "path": "Configuration.php", "line": 1},              # classifies SP-API host
        {"kind": "path-literal", "path": "OrdersApi.php", "line": 1},
        {"kind": "path-assembly", "path": "OrdersApi.php", "line": 2},
    ]
    out = scan_endpoints(matches, str(tmp_path), [_SP, _STRIPE])
    eps = out["endpoints"]
    # the SP-API host endpoint + the attributed path endpoint
    orders = [e for e in eps if e.get("version") == "2026-01-01"]
    assert orders and orders[0]["techKey"] == "api:amazon-sp-api"
    assert "OrdersApi.php:1" in orders[0]["files"]
    assert out["residue"]["pathLiterals"] == []                              # it was attributed, not residue


def test_path_literal_is_residue_when_two_vendors(tmp_path):
    _write(tmp_path, "cfg.php",
           "$a = 'https://sellingpartnerapi-na.amazon.com'; $b = 'https://api.stripe.com';\n")
    _write(tmp_path, "Api.php",
           "$resource_path = '/orders/2026-01-01/orders';\n"
           "$url = $this->config->getHost() . $resource_path;\n")
    matches = [
        {"kind": "url", "path": "cfg.php", "line": 1},                        # line has BOTH hosts -> 2 vendors
        {"kind": "path-literal", "path": "Api.php", "line": 1},
        {"kind": "path-assembly", "path": "Api.php", "line": 2},
    ]
    out = scan_endpoints(matches, str(tmp_path), [_SP, _STRIPE])
    assert not any(e.get("version") == "2026-01-01" for e in out["endpoints"])   # NOT attributed (ambiguous)
    assert out["residue"]["pathLiterals"] == [{"sample": "/orders/2026-01-01/orders", "loc": "Api.php:1"}]


def test_path_literal_is_residue_when_no_assembly_in_file(tmp_path):
    _write(tmp_path, "Configuration.php", "$host = 'https://sellingpartnerapi-na.amazon.com';\n")
    _write(tmp_path, "OrdersApi.php",
           "$resource_path = '/orders/2026-01-01/orders';\n"
           "$url = $this->config->getHost() . $resource_path;\n")
    _write(tmp_path, "Const.php", "$VERSIONED = '/feeds/2021-06-30/documents';\n")
    matches = [
        {"kind": "url", "path": "Configuration.php", "line": 1},
        {"kind": "path-literal", "path": "OrdersApi.php", "line": 1},
        {"kind": "path-assembly", "path": "OrdersApi.php", "line": 2},   # assembly here, NOT in Const.php
        {"kind": "path-literal", "path": "Const.php", "line": 1},        # no assembly in this file
    ]
    out = scan_endpoints(matches, str(tmp_path), [_SP])
    # OrdersApi.php literal attributed (its file has the assembly); Const.php literal is residue
    assert any(e.get("version") == "2026-01-01" for e in out["endpoints"])
    assert out["residue"]["pathLiterals"] == [{"sample": "/feeds/2021-06-30/documents", "loc": "Const.php:1"}]


def test_sinks_are_reported_as_residue(tmp_path):
    matches = [{"kind": "sink", "path": "Client.php", "line": 7}]
    out = scan_endpoints(matches, str(tmp_path), [_SP])
    assert out["residue"]["sinks"] == [{"kind": "egress", "loc": "Client.php:7"}]


def test_build_endpoints_still_returns_a_list(tmp_path):
    _write(tmp_path, "x.php", "$u = 'https://api.stripe.com/v1/charges';\n")
    matches = [{"kind": "url", "path": "x.php", "line": 1}]
    eps = build_endpoints(matches, str(tmp_path), [_STRIPE])
    assert isinstance(eps, list) and eps[0]["techKey"] == "api:stripe"


# --- the operation axis: one host, many operations, independent lifecycles ------

def _op_match(path, line, text):
    return {"kind": "operation-marker", "path": path, "line": line, "text": text}


def test_operation_marker_attributed_to_the_single_classified_vendor(tmp_path):
    _write(tmp_path, "cfg.php", "$h = 'https://api.ebay.com';\n")
    _write(tmp_path, "Cat.php", "$x = '<GetCategoryFeaturesRequest xmlns=\"urn:ebay\">';\n")
    _EBAY = Vendor("eBay", "api:ebay", ("ebay.com",), r"/(v[0-9]+)")
    matches = [{"kind": "url", "path": "cfg.php", "line": 1},
               _op_match("Cat.php", 1, "'<GetCategoryFeaturesRequest xmlns=\"urn:ebay\">'")]
    out = scan_endpoints(matches, str(tmp_path), [_EBAY])
    ops = {e["operation"]: e for e in out["endpoints"] if e.get("operation")}
    assert "GetCategoryFeatures" in ops
    assert ops["GetCategoryFeatures"]["techKey"] == "api:ebay"
    assert "Cat.php:1" in ops["GetCategoryFeatures"]["files"]


def test_operation_marker_not_attributed_when_two_vendors(tmp_path):
    _write(tmp_path, "cfg.php", "$a='https://api.ebay.com'; $b='https://api.stripe.com';\n")
    _write(tmp_path, "Cat.php", "$x = '<GetCategoryFeaturesRequest>';\n")
    _EBAY = Vendor("eBay", "api:ebay", ("ebay.com",), r"/(v[0-9]+)")
    matches = [{"kind": "url", "path": "cfg.php", "line": 1},
               _op_match("Cat.php", 1, "'<GetCategoryFeaturesRequest>'")]
    out = scan_endpoints(matches, str(tmp_path), [_EBAY, _STRIPE])
    assert not any(e.get("operation") for e in out["endpoints"])   # ambiguous -> never guess


def test_operation_read_from_multiline_literal_text(tmp_path):
    """The XML root often sits on line 2+ of the literal; the match's start line
    alone would miss it, so the full matched text is searched."""
    _write(tmp_path, "cfg.php", "$h = 'https://api.ebay.com';\n")
    _write(tmp_path, "Cancel.php", "$body = '<?xml version=\"1.0\"?>\n    <AddDisputeRequest xmlns=\"x\">';\n")
    _EBAY = Vendor("eBay", "api:ebay", ("ebay.com",), r"/(v[0-9]+)")
    matches = [{"kind": "url", "path": "cfg.php", "line": 1},
               _op_match("Cancel.php", 1, "'<?xml version=\"1.0\"?>\n    <AddDisputeRequest xmlns=\"x\">'")]
    out = scan_endpoints(matches, str(tmp_path), [_EBAY])
    assert any(e.get("operation") == "AddDispute" for e in out["endpoints"])


def test_operations_on_one_host_stay_separate_records(tmp_path):
    _write(tmp_path, "cfg.php", "$h = 'https://api.ebay.com';\n")
    _write(tmp_path, "A.php", "x\n")
    _EBAY = Vendor("eBay", "api:ebay", ("ebay.com",), r"/(v[0-9]+)")
    matches = [{"kind": "url", "path": "cfg.php", "line": 1},
               _op_match("A.php", 1, "'<GetCategoriesRequest>'"),
               _op_match("A.php", 1, "'<GetItemRequest>'")]
    out = scan_endpoints(matches, str(tmp_path), [_EBAY])
    ops = {e["operation"] for e in out["endpoints"] if e.get("operation")}
    assert ops == {"GetCategories", "GetItem"}      # same host+version, distinct lifecycles


# --- interpolated-host URLs: host is a runtime variable, path signature saves the vendor ---
_SHOPIFY = Vendor("Shopify", "api:shopify", ("myshopify.com", "shopify.dev"),
                  DEFAULT_VERSION_REGEX, path_signature=r"/admin/api/([0-9]{4}-[0-9]{2})/")


def test_interpolated_host_shopify_version_is_attributed_by_path_signature(tmp_path):
    """SHIPPED BUG: a Shopify Admin API call written as Laravel string interpolation —
    `Http::...->get("https://{$shop}/admin/api/2024-01/shop.json")` — was INVISIBLE. The
    `{$shop}` host truncates URL extraction, so host classification is blind AND the literal
    never reaches residue: the retired-version call `2024-01` vanished from the report
    entirely. The `/admin/api/{version}/` path signature is host-independent and must
    recover vendor=Shopify at version=2024-01 so the lifecycle sunset can fire."""
    _write(tmp_path, "app/Http/Controllers/ShopifyController.php",
           'x\n$r = Http::withHeaders([])->get("https://{$shop}/admin/api/2024-01/shop.json");\n')
    eps = build_endpoints([_url("app/Http/Controllers/ShopifyController.php", 2)],
                          str(tmp_path), [_SHOPIFY])
    sh = [e for e in eps if e["techKey"] == "api:shopify"]
    assert sh, "the interpolated-host Shopify call was not attributed"
    assert sh[0]["version"] == "2024-01"
    assert sh[0]["attribution"] == "observed"   # the path literal IS evidence on the line


def test_path_signature_does_not_fire_on_unrelated_admin_paths(tmp_path):
    """The signature must be distinctive: a non-Shopify `/admin/` path with no `api/<date>`
    segment must NOT be mis-attributed to Shopify (no invented endpoints)."""
    _write(tmp_path, "a.php", 'x\n$r = get("https://{$h}/admin/users/list");\n')
    eps = build_endpoints([_url("a.php", 2)], str(tmp_path), [_SHOPIFY])
    assert not [e for e in eps if e["techKey"] == "api:shopify"]


def test_two_versions_of_one_vendor_on_one_line_both_survive(tmp_path):
    """SHIPPED BUG: the seen_known dedup key was (techKey, loc, operation) — no version — so
    the SECOND same-vendor URL on a line was silently dropped whenever its version differed.
    A migration-mapping line `'…/sell/v1/x' => '…/sell/v2/x'` reported only v1; v2 vanished
    (present in neither endpoints nor residue). Both versions are real call-site facts and
    both must survive — dedup may only collapse records that carry the SAME version."""
    _write(tmp_path, "map.php",
           "x\n'https://api.ebay.com/sell/v1/x' => 'https://api.ebay.com/sell/v2/x',\n")
    ebay = Vendor("eBay", "api:ebay", ("ebay.com",), r'/(v\d+)')
    eps = build_endpoints([_url("map.php", 2)], str(tmp_path), [ebay])
    assert {e["version"] for e in eps} == {"v1", "v2"}


def test_unversioned_host_match_does_not_suppress_the_path_signature_version(tmp_path):
    """SHIPPED BUG: an UNVERSIONED same-vendor match at the same loc suppressed the
    path-signature's VERSIONED add — the dedup key ignored version. Real shape: a line
    carrying a `myshopify.com` OAuth literal (no version) beside the interpolated
    `https://{$shop}/admin/api/2024-01/…` call; the engine emits one url match per literal,
    the OAuth match registers (api:shopify, loc, None) first, and the retired 2024-01 call —
    the exact finding the path signature exists to recover — was deduped away. The versioned
    record must survive an unversioned sibling, in EITHER match order."""
    _write(tmp_path, "app/Shop.php",
           'x\n$c = ["auth" => "https://x.myshopify.com/admin/oauth/token",'
           ' "api" => "https://{$shop}/admin/api/2024-01/shop.json"];\n')
    ms = [  # one engine match per string literal, each carrying its own matched text
        {**_url("app/Shop.php", 2), "text": '"https://x.myshopify.com/admin/oauth/token"'},
        {**_url("app/Shop.php", 2), "text": '"https://{$shop}/admin/api/2024-01/shop.json"'},
    ]
    for order in (ms, list(reversed(ms))):
        eps = build_endpoints(order, str(tmp_path), [_SHOPIFY])
        versions = {e["version"] for e in eps if e["techKey"] == "api:shopify"}
        assert "2024-01" in versions, f"retired call lost: {versions}"
    # the whole-line fallback shape (an engine match with no text) must recover it too
    eps = build_endpoints([_url("app/Shop.php", 2)], str(tmp_path), [_SHOPIFY])
    assert "2024-01" in {e["version"] for e in eps if e["techKey"] == "api:shopify"}


def test_same_loc_dedup_is_order_independent(tmp_path):
    """Principle 3 (byte-identical): first-wins dedup at one loc must not let the engine's
    match order pick which record survives. With version in the dedup key the unversioned and
    versioned facts are distinct records, so forward and reversed match order agree exactly."""
    _write(tmp_path, "app/Shop.php",
           'x\n$c = ["auth" => "https://x.myshopify.com/admin/oauth/token",'
           ' "api" => "https://{$shop}/admin/api/2024-01/shop.json"];\n')
    ms = [
        {**_url("app/Shop.php", 2), "text": '"https://x.myshopify.com/admin/oauth/token"'},
        {**_url("app/Shop.php", 2), "text": '"https://{$shop}/admin/api/2024-01/shop.json"'},
    ]
    fwd = scan_endpoints(ms, str(tmp_path), [_SHOPIFY])
    rev = scan_endpoints(list(reversed(ms)), str(tmp_path), [_SHOPIFY])
    assert fwd == rev


def test_au_nz_marketplaces_are_classified_not_unknown():
    """AU/NZ marketplaces catalogued for detection (marketplacehub-api evidence). A URL literal on
    each host must classify to the vendor, not fall through to Unknown."""
    from agent.lib.vendors import load_vendors
    from agent.lib import classify_url
    vendors = load_vendors()
    cases = {"api-integrations-sandbox.mydeal.com.au": "MyDeal",
             "sellercenter-api-preprod.theiconic.com.au": "THE ICONIC",
             "dev.themarket.co.nz": "TheMarket",
             "nimda-marketplace.aws.kgn.io": "Kogan"}
    for host, vendor in cases.items():
        v = classify_url.classify_host(host, vendors)
        assert v is not None and v.vendor == vendor, f"{host} -> {v and v.vendor}"


# ── path-constant idiom: config-injected wrapper (host injected at runtime, generic paths) ──
# The vendor is BOUND on the instance (no host literal to infer it), repo-scoped (generic
# paths would mis-tag another marketplace), sink-guarded (must actually make HTTP calls).
_CATCH = Vendor("Catch", "api:catch", ("catch.com.au",), DEFAULT_VERSION_REGEX)
_CATCH_INST = {"id": "catch-api-paths", "family": "path-constant",
               "repo": "example-org/catchapi", "vendor": "Catch", "pathRegex": r"^/api/",
               "evidence": "src/CatchApi/GetOrders.php:9"}
_CATCH_REMOTE = "git@git.example.com:example-org/catchapi.git"


def _pc(path, line, text, vendor="Catch", check="catch-api-paths"):
    return {"kind": "path-constant", "checkId": check, "vendor": vendor,
            "path": path, "line": line, "text": text}


def _sink(path, line):
    return {"kind": "sink", "path": path, "line": line}


def test_path_constant_attributes_operations_to_bound_vendor(tmp_path):
    ms = [_pc("src/CatchApi/GetOrders.php", 9, 'protected $API_URL = "/api/orders";'),
          _pc("src/CatchApi/GetProducts.php", 9, 'protected $API_URL = "/api/offers";'),
          _sink("src/CatchApi/CatchApi.php", 298)]
    out = scan_endpoints(ms, str(tmp_path), [_CATCH],
                         idioms=[_CATCH_INST], repo_id=_CATCH_REMOTE)
    eps = [e for e in out["endpoints"] if e["classified"]]
    ops = {e["operation"]: e for e in eps}
    assert set(ops) == {"/api/orders", "/api/offers"}
    o = ops["/api/orders"]
    assert o["vendor"] == "Catch" and o["attribution"] == "inferred"
    assert o["files"] == ["src/CatchApi/GetOrders.php:9"]


def test_path_constant_requires_an_egress_sink(tmp_path):
    # same path constants, but the repo shows NO egress sink -> not attributed (could be
    # anything). It lands in residue, not endpoints — the conscience stays honest.
    ms = [_pc("src/CatchApi/GetOrders.php", 9, 'protected $API_URL = "/api/orders";')]
    out = scan_endpoints(ms, str(tmp_path), [_CATCH],
                         idioms=[_CATCH_INST], repo_id=_CATCH_REMOTE)
    assert [e for e in out["endpoints"] if e["classified"]] == []
    assert any(r["loc"] == "src/CatchApi/GetOrders.php:9"
               for r in out["residue"].get("pathConstants", []))


def test_path_constant_scopes_on_git_identity_not_local_checkout_path(tmp_path):
    # REGRESSION (absorb-gate bug, fixed via scan_util.repo_scope_id): the SAME matches + idiom,
    # scoped by the git IDENTITY, attribute — but scoped by the raw local CHECKOUT PATH they do
    # not, because _repo_in_scope keys on the remote's host/path suffix and a clone folder name
    # (example-org_catchapi-abc123) carries no such identity. The absorb gate used to pass the
    # local path, so a repo-scoped idiom silently never applied (attributedAfter == before).
    ms = [_pc("src/CatchApi/GetOrders.php", 9, 'protected $API_URL = "/api/orders";'),
          _sink("src/CatchApi/CatchApi.php", 298)]
    via_identity = scan_endpoints(ms, str(tmp_path), [_CATCH],
                                  idioms=[_CATCH_INST], repo_id=_CATCH_REMOTE)
    via_local_path = scan_endpoints(ms, str(tmp_path), [_CATCH],
                                    idioms=[_CATCH_INST],
                                    repo_id="/home/ci/clones/example-org_catchapi-abc123")
    assert [e for e in via_identity["endpoints"] if e["classified"]], \
        "git identity must attribute the repo-scoped idiom"
    assert not [e for e in via_local_path["endpoints"] if e["classified"]], \
        "the local checkout path must NOT attribute — proving why the gate needs repo_scope_id()"


def test_path_constant_is_repo_scoped(tmp_path):
    # the SAME Catch rule matching /api/... in a DIFFERENT repo must NOT attribute to Catch
    # (bunnings also has /api/offers — it is Mirakl). Out of scope -> residue, never a finding.
    ms = [_pc("src/Bunnings/GetProducts.php", 9, 'protected $API_URL = "/api/offers";'),
          _sink("src/Bunnings/Bunnings.php", 25)]
    out = scan_endpoints(ms, str(tmp_path), [_CATCH],
                         idioms=[_CATCH_INST], repo_id="git@git.example.com:example-org/bunnings.git")
    assert [e for e in out["endpoints"] if e["classified"]] == []
    assert any(r["loc"] == "src/Bunnings/GetProducts.php:9"
               for r in out["residue"].get("pathConstants", []))


def test_path_constant_ignored_when_no_idioms_passed(tmp_path):
    # backward-compat: callers that don't pass idioms/repo_id are unaffected
    ms = [_pc("a.php", 9, 'protected $API_URL = "/api/orders";'), _sink("a.php", 1)]
    out = scan_endpoints(ms, str(tmp_path), [_CATCH])
    assert [e for e in out["endpoints"] if e["classified"]] == []


def test_repo_in_scope_is_case_insensitive():
    """scope_edges.identity() lowercases the path, so a mixed-case org (example-org/magento_api)
    must still match its instance suffix. A shipped bug: Catch (example-org, already lowercase)
    worked, Magento (example-org) silently fell to residue."""
    from agent.lib.endpoints import _repo_in_scope
    assert _repo_in_scope("https://git.example.com/example-org/magento_api", "example-org/magento_api")
    assert _repo_in_scope("git@git.example.com:example-org/magento_api.git", "example-org/magento_api")
    # a different repo must NOT match
    assert not _repo_in_scope("https://git.example.com/example-org/other_api", "example-org/magento_api")


def test_path_constant_can_pin_a_version(tmp_path):
    """An optional `version` on the instance stamps the attributed endpoints — so a wrapper that
    uses a DEPRECATED API version (BigCommerce v2 constants) attributes at version=v2, and a
    version-scoped sunset can then flag it. Without it, path-constants are version-less."""
    inst = {"id": "bc-v2", "family": "path-constant", "repo": "example-org/bigcommerce-api",
            "vendor": "Catch", "pathRegex": r"/v2", "version": "v2", "evidence": "x:1"}
    ms = [_pc("src/Root/Client.php", 54, "private static $path_prefix = '/api/v2';",
              check="bc-v2"),
          _sink("src/Root/Client.php", 90)]
    out = scan_endpoints(ms, str(tmp_path), [_CATCH],
                         idioms=[inst], repo_id="git@x:example-org/bigcommerce-api.git")
    eps = [e for e in out["endpoints"] if e["classified"]]
    assert eps and eps[0]["version"] == "v2"


def test_path_constant_derives_version_from_the_vendors_path_signature(tmp_path):
    """REGRESSION (example-org/inventory-app): a repo assigning bare Shopify Admin API paths as
    constants ($this->shop_url = '/admin/api/2023-10/shop.json') attributed 40 call-sites at
    version=None, so Shopify's COMPUTED lifecycle could date none of them — 31 sites on
    RETIRED versions rendered as a healthy tracked integration. Attribution without a version
    is "cannot see" dressed as "clean".

    The vendor already declares the extractor: pathSignature group 1 IS the version. The
    `kind == "url"` arm consults it, but a bare path constant yields no URL to extract, so
    that arm never runs. Ask the vendor directly instead. An explicit `version:` still wins."""
    shopify = Vendor("Shopify", "api:shopify", ("myshopify.com",), DEFAULT_VERSION_REGEX,
                     path_signature=r"/admin/api/([0-9]{4}-[0-9]{2})/")
    inst = {"id": "ks-shopify", "family": "path-constant", "repo": "example-org/inventory-app",
            "vendor": "Shopify", "pathRegex": r"^/admin/api/[0-9]{4}-[0-9]{2}/",
            "evidence": "x:1"}
    ms = [_pc("Order_list.php", 30, "$this->shop_url = '/admin/api/2023-10/orders.json';",
              vendor="Shopify", check="ks-shopify"),
          _pc("Post_products.php", 22, "$this->url = '/admin/api/2026-01/products.json';",
              vendor="Shopify", check="ks-shopify"),
          _sink("Shopify.php", 487)]
    out = scan_endpoints(ms, str(tmp_path), [shopify],
                         idioms=[inst], repo_id="git@x:example-org/inventory-app.git")
    got = {e["operation"]: e["version"] for e in out["endpoints"] if e["classified"]}
    assert got == {"/admin/api/2023-10/orders.json": "2023-10",
                   "/admin/api/2026-01/products.json": "2026-01"}


def test_path_constant_explicit_version_beats_the_path_signature(tmp_path):
    """The pathSignature is a FALLBACK. A wrapper pinned by its instance to one version keeps
    that version even where the path also carries one — the curated statement wins."""
    shopify = Vendor("Shopify", "api:shopify", ("myshopify.com",), DEFAULT_VERSION_REGEX,
                     path_signature=r"/admin/api/([0-9]{4}-[0-9]{2})/")
    inst = {"id": "pinned", "family": "path-constant", "repo": "r/r", "vendor": "Shopify",
            "pathRegex": r"^/admin/api/", "version": "2020-01", "evidence": "x:1"}
    ms = [_pc("a.php", 1, "$u = '/admin/api/2023-10/orders.json';",
              vendor="Shopify", check="pinned"),
          _sink("a.php", 2)]
    out = scan_endpoints(ms, str(tmp_path), [shopify], idioms=[inst], repo_id="git@x:r/r.git")
    assert [e["version"] for e in out["endpoints"] if e["classified"]] == ["2020-01"]


def test_path_constant_without_a_path_signature_stays_versionless(tmp_path):
    """Vendors that declare no pathSignature are unaffected — no generic version-sniffing is
    introduced here, so no existing shipped instance changes shape. Catch has none."""
    ms = [_pc("src/CatchApi/GetOrders.php", 9, 'protected $API_URL = "/api/v2/orders";'),
          _sink("src/CatchApi/CatchApi.php", 298)]
    out = scan_endpoints(ms, str(tmp_path), [_CATCH],
                         idioms=[_CATCH_INST], repo_id=_CATCH_REMOTE)
    assert [e["version"] for e in out["endpoints"] if e["classified"]] == [None]


# ── corroboration: a shipped path-constant guarded by evidence, not by repo identity ──
_SPAPI = Vendor("Amazon SP-API", "api:spapi", ("sellingpartnerapi-na.amazon.com",),
                DEFAULT_VERSION_REGEX)
_SPAPI_INST = {"id": "spapi-operation-paths", "family": "path-constant",
               "vendor": "Amazon SP-API", "corroboration": 3,
               "families": ["catalog", "fba", "orders", "reports"],
               "pathRegex": r"^/(catalog|fba|orders|reports)/",
               "distinctive": ["fba"],
               "evidence": "amzapi/selling-partner-api-sdk reports/api.gen.go:492"}


def _spc(path, line, text):
    return _pc(path, line, text, vendor="Amazon SP-API", check="spapi-operation-paths")


def test_corroborated_path_constant_attributes_when_the_threshold_is_met(tmp_path):
    # Four distinct families (catalog, fba, orders, reports) >= corroboration 3 -> attribute.
    ms = [_spc("catalog/api.go", 231, 'basePath := fmt.Sprintf("/catalog/v0/items")'),
          _spc("fbaInbound/api.go", 749, 'basePath := fmt.Sprintf("/fba/inbound/v0/shipments")'),
          _spc("ordersV0/api.go", 88, 'basePath := fmt.Sprintf("/orders/v0/orders")'),
          _spc("reports/api.go", 492, 'basePath := fmt.Sprintf("/reports/2021-06-30/reports")'),
          _sink("pkg/client.go", 40)]
    out = scan_endpoints(ms, str(tmp_path), [_SPAPI],
                         idioms=[_SPAPI_INST], repo_id="git@github.com:acme/anything.git")
    ops = {e["operation"] for e in out["endpoints"] if e["classified"]}
    assert ops == {"/catalog/v0/items", "/fba/inbound/v0/shipments",
                   "/orders/v0/orders", "/reports/2021-06-30/reports"}
    assert all(e["vendor"] == "Amazon SP-API"
               for e in out["endpoints"] if e["classified"])


def test_corroborated_path_constant_refuses_below_the_threshold(tmp_path):
    # THE BUG THIS GUARDS: an eBay repo with a single generic /orders/v1/ path must NOT be
    # tagged Amazon SP-API. Two distinct families < corroboration 3 -> nothing attributes,
    # and the paths land in residue so coverage stays honest rather than silently clean.
    ms = [_spc("src/orders.go", 12, 'p := fmt.Sprintf("/orders/v1/list")'),
          _spc("src/catalog.go", 30, 'p := fmt.Sprintf("/catalog/v1/item")'),
          _sink("src/client.go", 8)]
    out = scan_endpoints(ms, str(tmp_path), [_SPAPI],
                         idioms=[_SPAPI_INST], repo_id="git@github.com:acme/ebay-thing.git")
    assert [e for e in out["endpoints"] if e["classified"]] == []
    residue = {r["loc"] for r in out["residue"].get("pathConstants", [])}
    assert residue == {"src/orders.go:12", "src/catalog.go:30"}


def test_corroboration_counts_distinct_families_not_match_volume(tmp_path):
    # Twenty hits in ONE family is still one family. Volume is not corroboration — a repo
    # with a hundred /orders/ paths has said one thing loudly, not three things.
    ms = [_spc(f"src/o{i}.go", i, f'p := fmt.Sprintf("/orders/v1/x{i}")') for i in range(20)]
    ms.append(_sink("src/client.go", 8))
    out = scan_endpoints(ms, str(tmp_path), [_SPAPI],
                         idioms=[_SPAPI_INST], repo_id="git@github.com:acme/loud.git")
    assert [e for e in out["endpoints"] if e["classified"]] == []


def test_corroborated_path_constant_still_requires_an_egress_sink(tmp_path):
    # The sink guard is independent of the scoping guard and must survive it.
    ms = [_spc("catalog/api.go", 231, 'p := fmt.Sprintf("/catalog/v0/items")'),
          _spc("fbaInbound/api.go", 749, 'p := fmt.Sprintf("/fba/inbound/v0/s")'),
          _spc("ordersV0/api.go", 88, 'p := fmt.Sprintf("/orders/v0/orders")')]
    out = scan_endpoints(ms, str(tmp_path), [_SPAPI],
                         idioms=[_SPAPI_INST], repo_id="git@github.com:acme/nosink.git")
    assert [e for e in out["endpoints"] if e["classified"]] == []


def test_corroborated_instance_needs_no_repo_field(tmp_path):
    # REGRESSION: the host fallback read inst['repo'] unconditionally, so a corroborated
    # instance (which has no `repo`) raised KeyError for any vendor with no domains.
    vendorless = Vendor("Amazon SP-API", "api:spapi", (), DEFAULT_VERSION_REGEX)
    ms = [_spc("catalog/api.go", 231, 'p := fmt.Sprintf("/catalog/v0/items")'),
          _spc("fbaInbound/api.go", 749, 'p := fmt.Sprintf("/fba/inbound/v0/s")'),
          _spc("ordersV0/api.go", 88, 'p := fmt.Sprintf("/orders/v0/orders")'),
          _sink("pkg/client.go", 40)]
    out = scan_endpoints(ms, str(tmp_path), [vendorless],
                         idioms=[_SPAPI_INST], repo_id="git@github.com:acme/anything.git")
    assert len([e for e in out["endpoints"] if e["classified"]]) == 3


def test_a_path_constant_attribution_removes_the_line_from_path_literal_residue(tmp_path):
    # REGRESSION (the 102-attributed-but-122-still-residue bug): the same line can match both
    # a path-literal rule and a path-constant rule. Residue excluded only `attributed_locs`,
    # so a line the idiom HAD attributed was still reported as unattributed. Residue is the
    # conscience — it must shrink when an idiom lands, or the absorb gate cannot see progress.
    loc_text = 'basePath := fmt.Sprintf("/catalog/v0/items")'
    ms = [_spc("catalog/api.go", 231, loc_text),
          {"kind": "path-literal", "path": "catalog/api.go", "line": 231, "text": loc_text},
          _spc("fbaInbound/api.go", 749, 'p := fmt.Sprintf("/fba/inbound/v0/s")'),
          _spc("ordersV0/api.go", 88, 'p := fmt.Sprintf("/orders/v0/orders")'),
          _sink("pkg/client.go", 40)]
    out = scan_endpoints(ms, str(tmp_path), [_SPAPI],
                         idioms=[_SPAPI_INST], repo_id="git@github.com:acme/anything.git")
    assert any(e["operation"] == "/catalog/v0/items"
               for e in out["endpoints"] if e["classified"])
    assert "catalog/api.go:231" not in {r["loc"]
                                        for r in out["residue"].get("pathLiterals", [])}


def test_generic_families_alone_do_not_attribute(tmp_path):
    # REGRESSION, reproduced 2026-08-18 against a real scan: a multi-vendor repo carrying
    # eBay /orders/, Shopify /products/ and BigCommerce /catalog/ + /shipping/ cleared
    # corroboration 3 and was attributed 4 endpoints to Amazon SP-API with verdict KNOWN,
    # on zero Amazon code. Three GENERIC families are not evidence of a vendor.
    inst = dict(_SPAPI_INST, families=["catalog", "fba", "orders", "shipping"],
                pathRegex=r"^/(catalog|fba|orders|shipping)/",
                distinctive=["fba"])
    ms = [_spc("src/ebay.go", 9, 'p := fmt.Sprintf("/orders/v1/order_items")'),
          _spc("src/shopify.go", 14, 'p := fmt.Sprintf("/catalog/v3/summary")'),
          _spc("src/bigcommerce.go", 21, 'p := fmt.Sprintf("/shipping/v2/zones")'),
          _sink("src/client.go", 8)]
    out = scan_endpoints(ms, str(tmp_path), [_SPAPI],
                         idioms=[inst], repo_id="git@github.com:acme/marketplace-hub.git")
    assert [e for e in out["endpoints"] if e["classified"]] == [], \
        "three generic families must not attribute a vendor"
    assert len(out["residue"].get("pathConstants", [])) == 3, \
        "refused matches must land in residue, never be dropped"


def test_one_distinctive_family_among_generics_does_attribute(tmp_path):
    # The other side of the guard: a genuine SP-API repo carries /fba/, which no other
    # marketplace uses as a leading segment. Count met AND a distinctive family present.
    inst = dict(_SPAPI_INST, families=["catalog", "fba", "orders", "shipping"],
                pathRegex=r"^/(catalog|fba|orders|shipping)/",
                distinctive=["fba"])
    ms = [_spc("src/a.go", 9, 'p := fmt.Sprintf("/orders/v0/orders")'),
          _spc("src/b.go", 14, 'p := fmt.Sprintf("/catalog/v0/items")'),
          _spc("src/c.go", 21, 'p := fmt.Sprintf("/fba/inbound/v0/shipments")'),
          _sink("src/client.go", 8)]
    out = scan_endpoints(ms, str(tmp_path), [_SPAPI],
                         idioms=[inst], repo_id="git@github.com:acme/real-seller.git")
    assert len([e for e in out["endpoints"] if e["classified"]]) == 3


def test_shapes_verdict_is_known_for_a_corroborated_fully_attributed_repo():
    # REPLACES test_corroborated_repo_with_findings_still_reports_unknown, which asserted a
    # verdict claim (UNKNOWN/config-driven-url for an attributed-but-still-sink-carrying repo)
    # by never calling shapes.verdict at all — it only checked that a sink survived in residue,
    # so it could not have failed on the behaviour it claimed to pin.
    #
    # ACTUAL measured behaviour: amzapi/selling-partner-api-sdk reports verdict=KNOWN with
    # reasons=[] (attributed=102, unattributedPaths=0, sinks=123). The residue-accounting fix
    # on this branch stopped double-counting a line the path-constant idiom already attributed
    # as unattributed residue, which drove unattributedPaths from 122 to 0 and flipped this
    # repo's class from UNKNOWN to KNOWN.
    #
    # That is correct: shapes.verdict only treats an unresolved sink as evidence of blindness
    # when attributed == 0 (`elif n_sinks and attributed == 0`) — we cannot link a sink to the
    # specific endpoint it calls without dataflow, so a fully-attributed repo legitimately
    # still shows egress sinks. Signature verified against agent/lib/shapes.py:
    #   verdict(attributed, residue, coverage, *, attested=False, unmodeled=0, modeled=0)
    #     -> (KNOWN|UNKNOWN, reasons)
    residue = {"pathLiterals": [], "sinks": [{"loc": f"pkg/client_{i}.go:1"} for i in range(123)]}
    coverage = {"go": ["sink", "path-constant"]}
    result = shapes.verdict(102, residue, coverage, attested=False, unmodeled=0, modeled=200)
    assert result == ("KNOWN", []), \
        "a corroborated repo with clean path residue is KNOWN even though sinks remain"


def test_distinctive_attributes_when_only_one_of_several_listed_families_is_present(tmp_path):
    # `distinctive` is "at least one of N present", not "all of N present" — every existing
    # fixture up to this test used a single-item `distinctive` list, so that branch of the
    # guard (`fams & set(inst.get("distinctive") or ())`) was never exercised with more than
    # one candidate. Three families are listed here; only `fba` is present among the matched
    # paths, and it must still attribute.
    inst = dict(_SPAPI_INST, families=["catalog", "fba", "orders", "shipping"],
                pathRegex=r"^/(catalog|fba|orders|shipping)/",
                distinctive=["fba", "authorization", "uploads"])
    ms = [_spc("src/a.go", 9, 'p := fmt.Sprintf("/orders/v0/orders")'),
          _spc("src/b.go", 14, 'p := fmt.Sprintf("/catalog/v0/items")'),
          _spc("src/c.go", 21, 'p := fmt.Sprintf("/fba/inbound/v0/shipments")'),
          _sink("src/client.go", 8)]
    out = scan_endpoints(ms, str(tmp_path), [_SPAPI],
                         idioms=[inst], repo_id="git@github.com:acme/real-seller-2.git")
    assert len([e for e in out["endpoints"] if e["classified"]]) == 3


# ── pathSignature on bare path literals: the capability with no idiom behind it ──
# The single-vendor branch above cannot fire in a real multi-vendor repo, and a repo-scoped
# idiom only helps the one repo it names. A vendor that DECLARES a pathSignature has already
# said "this path shape is me, whatever the host" — honouring that on a bare path literal is
# what makes the shape readable for every user of the tool, with no client data in the rule.
_SHOPIFY = Vendor("Shopify", "api:shopify", ("myshopify.com",), DEFAULT_VERSION_REGEX,
                  path_signature=r"/admin/api/([0-9]{4}-[0-9]{2})/")


def test_path_signature_attributes_a_bare_path_literal_in_a_multi_vendor_repo(tmp_path):
    """A config-injected wrapper shape, generalised: the host is built at runtime so nothing on the line
    classifies, and the repo talks to several vendors so the single-vendor branch is out.
    The path itself is unmistakably Shopify, and the version comes with it."""
    _write(tmp_path, "cfg.php",
           "$a = 'https://sellingpartnerapi-na.amazon.com'; $b = 'https://api.stripe.com';\n")
    _write(tmp_path, "Shop.php", "$this->shop_url = '/admin/api/2023-10/shop.json';\n")
    _write(tmp_path, "Client.php", "$res = $this->client->request($m, $u);\n")
    ms = [{"kind": "url", "path": "cfg.php", "line": 1},
          {"kind": "path-literal", "path": "Shop.php", "line": 1},
          {"kind": "sink", "path": "Client.php", "line": 1}]
    out = scan_endpoints(ms, str(tmp_path), [_SP, _STRIPE, _SHOPIFY])
    shop = [e for e in out["endpoints"] if e.get("techKey") == "api:shopify"]
    assert shop, "a declared pathSignature must attribute a bare path literal"
    assert shop[0]["version"] == "2023-10"
    assert shop[0]["files"] == ["Shop.php:1"]
    assert out["residue"]["pathLiterals"] == []      # attributed, so no longer blind


def test_path_signature_attribution_requires_an_egress_sink(tmp_path):
    """Same literal, but the repo makes no outbound calls — it could be a fixture, a doc
    string, a test. It stays residue. Same guard the path-constant family carries, and the
    reason a signature match is evidence rather than proof."""
    _write(tmp_path, "Shop.php", "$this->shop_url = '/admin/api/2023-10/shop.json';\n")
    ms = [{"kind": "path-literal", "path": "Shop.php", "line": 1}]
    out = scan_endpoints(ms, str(tmp_path), [_SP, _STRIPE, _SHOPIFY])
    assert [e for e in out["endpoints"] if e.get("techKey") == "api:shopify"] == []
    assert [r["loc"] for r in out["residue"]["pathLiterals"]] == ["Shop.php:1"]


def test_a_vendor_without_a_path_signature_gains_nothing(tmp_path):
    """No generic path-sniffing is introduced. A versioned literal belonging to a vendor that
    declares no signature stays exactly as blind as it was — this must not become a licence
    to guess a vendor from any path."""
    _write(tmp_path, "cfg.php",
           "$a = 'https://sellingpartnerapi-na.amazon.com'; $b = 'https://api.stripe.com';\n")
    _write(tmp_path, "Api.php", "$p = '/v1/charges/2024-01-01/list';\n")
    _write(tmp_path, "Client.php", "$res = $this->client->request($m, $u);\n")
    ms = [{"kind": "url", "path": "cfg.php", "line": 1},
          {"kind": "path-literal", "path": "Api.php", "line": 1},
          {"kind": "sink", "path": "Client.php", "line": 1}]
    out = scan_endpoints(ms, str(tmp_path), [_SP, _STRIPE, _SHOPIFY])
    assert [r["loc"] for r in out["residue"]["pathLiterals"]] == ["Api.php:1"]


# ── model signatures: the AI category deprecates MODELS, not hosts or paths ──────
# Every AI provider checked (OpenAI, Groq, Mistral) publishes a dated deprecation schedule,
# and every date attaches to a MODEL identifier — the one thing a catalog entry could not be
# scoped by. A CRM defaulting to `gpt-3.5-turbo` in four services had zero findings while
# that model's shutdown was two months out.
#
# A model id names its vendor as unambiguously as a pathSignature does, so the vendor
# declares it and the engine attributes it as the OPERATION — which the sunset catalog
# already scopes by (14 entries do today).
_OPENAI = Vendor("OpenAI", "api:openai", ("api.openai.com",), DEFAULT_VERSION_REGEX,
                 model_signature=r"gpt-[0-9][\w.\-]*")


def _model(path, line, text, vendor="OpenAI", tk="api:openai"):
    return {"kind": "model", "vendor": vendor, "techKey": tk,
            "path": path, "line": line, "text": text}


def test_model_literal_is_attributed_as_the_operation(tmp_path):
    _write(tmp_path, "cfg.php", "$base = 'https://api.openai.com/v1';\n")
    _write(tmp_path, "services.php", "'model' => env('AI_MODEL', 'gpt-3.5-turbo'),\n")
    ms = [{"kind": "url", "path": "cfg.php", "line": 1},
          _model("services.php", 1, "'model' => env('AI_MODEL', 'gpt-3.5-turbo'),")]
    out = scan_endpoints(ms, str(tmp_path), [_OPENAI, _SP])
    got = [e for e in out["endpoints"] if e.get("operation") == "gpt-3.5-turbo"]
    assert got, "a declared modelSignature must attribute the model as an operation"
    assert got[0]["vendor"] == "OpenAI"
    assert got[0]["files"] == ["services.php:1"]


def test_model_literal_needs_the_vendor_already_classified_in_the_repo(tmp_path):
    """The guard that stops this inventing integrations. A repo that merely NAMES a model —
    a doc, a comparison table, a migration note — does not call OpenAI. The model id
    corroborates an integration the scan already saw by host; it never creates one."""
    _write(tmp_path, "notes.php", "$s = 'we could switch to gpt-3.5-turbo later';\n")
    ms = [_model("notes.php", 1, "$s = 'we could switch to gpt-3.5-turbo later';")]
    out = scan_endpoints(ms, str(tmp_path), [_OPENAI, _SP])
    assert [e for e in out["endpoints"] if e.get("operation") == "gpt-3.5-turbo"] == []


def test_the_model_id_is_extracted_not_the_whole_literal(tmp_path):
    """The operation must equal the model id exactly, because the sunset join is an exact
    string match. Taking the whole string literal would never match a catalog entry."""
    _write(tmp_path, "cfg.php", "$base = 'https://api.openai.com/v1';\n")
    _write(tmp_path, "svc.php", "$this->model = config('services.ai.model', 'gpt-4o-mini');\n")
    ms = [{"kind": "url", "path": "cfg.php", "line": 1},
          _model("svc.php", 1, "$this->model = config('services.ai.model', 'gpt-4o-mini');")]
    out = scan_endpoints(ms, str(tmp_path), [_OPENAI, _SP])
    assert [e["operation"] for e in out["endpoints"] if e.get("vendor") == "OpenAI"
            and e.get("operation")] == ["gpt-4o-mini"]


def test_a_vendor_without_a_model_signature_is_unaffected(tmp_path):
    """No generic model-sniffing: a vendor that declares none gains nothing."""
    _write(tmp_path, "cfg.php", "$base = 'https://api.openai.com/v1';\n")
    ms = [{"kind": "url", "path": "cfg.php", "line": 1}]
    plain = Vendor("OpenAI", "api:openai", ("api.openai.com",), DEFAULT_VERSION_REGEX)
    out = scan_endpoints(ms, str(tmp_path), [plain])
    assert all(not e.get("operation") for e in out["endpoints"])


def test_model_literal_is_attributed_when_the_vendor_comes_from_the_SDK_manifest(tmp_path):
    """REGRESSION (a corpus repo): a repo that depends on the official client package and
    NEVER writes the host literal is classified `sdk-client` from its manifest — but that
    endpoint is injected after scan_endpoints returns, so the host-only guard rejected its
    models. That repo defaults to gpt-3.5-turbo in three controllers and got no finding.

    "Use the SDK, never write the host" is the common modern shape, so the guard has to accept
    a manifest-declared vendor as corroboration too — it is a read fact, same as a host."""
    _write(tmp_path, "svc.php", "$this->model = config('ai.model', 'gpt-3.5-turbo');\n")
    ms = [_model("svc.php", 1, "$this->model = config('ai.model', 'gpt-3.5-turbo');")]
    out = scan_endpoints(ms, str(tmp_path), [_OPENAI, _SP], sdk_vendors={"OpenAI"})
    got = [e for e in out["endpoints"] if e.get("operation") == "gpt-3.5-turbo"]
    assert got and got[0]["vendor"] == "OpenAI"
    assert got[0]["files"] == ["svc.php:1"]


def test_sdk_declared_vendor_does_not_weaken_the_guard_for_others(tmp_path):
    """Declaring OpenAI's SDK must not license attributing SOMEONE ELSE's model. The guard is
    per-vendor, so a repo with the OpenAI SDK and a stray Groq model id still attributes only
    the OpenAI one."""
    groq = Vendor("Groq", "api:groq", ("api.groq.com",), DEFAULT_VERSION_REGEX,
                  model_signature=r"llama-[0-9][\w.\-]*")
    _write(tmp_path, "svc.php", "$a = 'gpt-3.5-turbo'; $b = 'llama-3.3-70b-versatile';\n")
    ms = [_model("svc.php", 1, "$a = 'gpt-3.5-turbo'; $b = 'llama-3.3-70b-versatile';"),
          _model("svc.php", 1, "$a = 'gpt-3.5-turbo'; $b = 'llama-3.3-70b-versatile';",
                 vendor="Groq", tk="api:groq")]
    out = scan_endpoints(ms, str(tmp_path), [_OPENAI, groq], sdk_vendors={"OpenAI"})
    ops = sorted({e["operation"] for e in out["endpoints"] if e.get("operation")})
    assert ops == ["gpt-3.5-turbo"], f"Groq was not corroborated in this repo: {ops}"


def test_a_pathsignature_vendor_with_no_domains_does_not_crash_the_scan(tmp_path):
    """REGRESSION: the url arm did `sv.domains[0]` unguarded, assuming any vendor carrying a
    pathSignature also has a host. Salesforce Commerce Cloud is the first that does not —
    OCAPI is served from each MERCHANT's own domain, so the vendor has `domains: []` and only
    the path identifies it.

    The scan died with "tuple index out of range" and the repo was recorded in reposErrored —
    honest, but the headline still read "0 action-required", which is the shape of report this
    tool exists to prevent. A vendor definition must never be able to crash a scan."""
    sfcc = Vendor("Salesforce Commerce Cloud", "api:sfcc", (), DEFAULT_VERSION_REGEX,
                  path_signature=r"/dw/(?:shop|data|meta)/(v[0-9]+_[0-9]+)")
    _write(tmp_path, "seed.php",
           "'base_url' => 'https://shop.example-merchant.com/s/AU/dw/shop/v24_5',\n")
    ms = [{"kind": "url", "path": "seed.php", "line": 1}]
    out = scan_endpoints(ms, str(tmp_path), [sfcc, _SP])       # must not raise
    got = [e for e in out["endpoints"] if e.get("techKey") == "api:sfcc"]
    assert got, "the path signature should still attribute it"
    assert got[0]["version"] == "v24_5"


def test_a_declared_asset_host_is_not_claimed_by_a_parent_domain_vendor_rule(tmp_path):
    """REGRESSION: host_reputation.yaml declares fonts.googleapis.com an `asset-cdn` — a font
    stylesheet, not a service the app calls. But the `Google APIs` vendor rule owns the PARENT
    domain googleapis.com, and a vendor match sets classified=True, which forces hostClass to
    "api" without ever consulting the declaration. Every page that loads a Google Font was
    therefore counted as a live Google APIs integration, inflating the integration total and
    putting a vendor on the audit backlog for a <link rel=stylesheet>.

    The exact host is the more specific statement and must win over a parent-domain rule.
    sheets.googleapis.com — a real API, not declared anything — must still attribute."""
    google = Vendor("Google APIs", "api:google", ("googleapis.com",), DEFAULT_VERSION_REGEX)
    _write(tmp_path, "page.html",
           '<link href="https://fonts.googleapis.com/css2?family=Inter" rel="stylesheet">\n'
           "<?php $u = 'https://sheets.googleapis.com/v4/spreadsheets/abc'; ?>\n")
    ms = [{"kind": "url", "path": "page.html", "line": 1},
          {"kind": "url", "path": "page.html", "line": 2}]
    out = scan_endpoints(ms, str(tmp_path), [google])
    by_host = {e["domain"]: e for e in out["endpoints"]}
    assert by_host["fonts.googleapis.com"]["classified"] is False
    assert by_host["fonts.googleapis.com"]["hostClass"] == "asset-cdn"
    assert by_host["sheets.googleapis.com"]["vendor"] == "Google APIs"


def test_an_interpolated_host_does_not_hide_a_path_constant(tmp_path):
    """A path whose host is interpolated into the same string must still match a path-constant
    idiom's pathRegex.

    Found on a real fleet: `->get("{$host}/sellers/v1/marketplaceParticipations")` — the dominant
    Laravel shape — was invisible to the shipped `spapi-operation-paths` idiom, whose regex is
    `^/(…|sellers|…)/`. The leading `{$host}` defeats the `^/` anchor, so the call-site fell into
    residue as `config-driven-url` and the repo reported UNKNOWN.

    The anchor cannot simply be relaxed: the gate REQUIRES the alternation to sit at path segment
    0 so a corroborated idiom's regex cannot disagree with endpoints.py's segment-0 family
    counter. So the path is normalised before matching instead, which preserves that invariant —
    after stripping, the alternation really is segment 0.
    """
    ms = [_pc("src/CatchApi/GetOrders.php", 9,
              'protected $API_URL = "{$this->baseUrl()}/api/orders";'),
          _sink("src/CatchApi/CatchApi.php", 298)]
    out = scan_endpoints(ms, str(tmp_path), [_CATCH],
                         idioms=[_CATCH_INST], repo_id=_CATCH_REMOTE)
    eps = [e for e in out["endpoints"] if e["classified"]]
    assert eps, "an interpolated host hid the path from its own idiom"
    assert eps[0]["vendor"] == "Catch"
    assert eps[0]["operation"] == "/api/orders", (
        f"the stored path should be the real one, not the interpolation prefix: "
        f"{eps[0]['operation']!r}")


def test_a_simple_php_variable_prefix_is_stripped_too(tmp_path):
    """PHP also allows `"$host/path"` without braces."""
    ms = [_pc("src/CatchApi/GetOrders.php", 9, '$u = "$host/api/orders";'),
          _sink("src/CatchApi/CatchApi.php", 298)]
    out = scan_endpoints(ms, str(tmp_path), [_CATCH],
                         idioms=[_CATCH_INST], repo_id=_CATCH_REMOTE)
    assert [e for e in out["endpoints"] if e["classified"]], "a bare $var prefix was not stripped"


def test_a_js_template_literal_is_a_KNOWN_GAP_not_a_silent_success(tmp_path):
    """DOCUMENTED LIMITATION, asserted so it stays visible.

    `_STRING_LIT` is `['"]([^'"]*)['"]` — backticks are not string literals to the scanner, so a
    JS template literal yields NOTHING to strip and cannot reach a path-constant idiom at all.
    That is a separate gap from the interpolated-host one fixed above: extraction, not matching.

    It is left unfixed deliberately. Widening extraction to backticks changes what every idiom
    sees across every JS repo, and no verified JS blind spot has been produced to justify it —
    "claim only what you verified". When someone does widen it, this test fails and they should
    read this note rather than assume they broke something."""
    ms = [_pc("src/api.js", 9, 'const u = `${base}/api/orders`;'),
          _sink("src/api.js", 20)]
    out = scan_endpoints(ms, str(tmp_path), [_CATCH],
                         idioms=[_CATCH_INST], repo_id=_CATCH_REMOTE)
    assert [e for e in out["endpoints"] if e["classified"]] == [], (
        "backtick extraction now works — good, but update this test and the note in it")


def test_a_path_with_no_interpolation_is_untouched(tmp_path):
    """The ordinary case must not change — this is the shape every existing idiom matches."""
    ms = [_pc("src/CatchApi/GetOrders.php", 9, 'protected $API_URL = "/api/orders";'),
          _sink("src/CatchApi/CatchApi.php", 298)]
    out = scan_endpoints(ms, str(tmp_path), [_CATCH],
                         idioms=[_CATCH_INST], repo_id=_CATCH_REMOTE)
    eps = [e for e in out["endpoints"] if e["classified"]]
    assert eps and eps[0]["operation"] == "/api/orders"


def test_an_interpolation_that_is_not_a_host_prefix_is_left_alone(tmp_path):
    """Only a LEADING interpolation immediately followed by `/` is a hidden host. One in the
    middle of a path is a path parameter and must survive — stripping it would corrupt the
    operation a reader is shown."""
    ms = [_pc("src/CatchApi/GetOrders.php", 9,
              'protected $API_URL = "/api/orders/{$orderId}/refund";'),
          _sink("src/CatchApi/CatchApi.php", 298)]
    out = scan_endpoints(ms, str(tmp_path), [_CATCH],
                         idioms=[_CATCH_INST], repo_id=_CATCH_REMOTE)
    eps = [e for e in out["endpoints"] if e["classified"]]
    assert eps and eps[0]["operation"] == "/api/orders/{$orderId}/refund"


def test_sibling_hosts_on_a_vendor_domain_are_not_swept_into_own_infra(tmp_path):
    """The >=2-sibling sweep must obey the SAME vendor guard as the repo-token path above.

    `own_infra.signals()` drops any repo-derived token that equals or contains a catalogued
    vendor name, because keeping it "silently deletes a real vendor from the audit backlog —
    this project's cardinal sin". `_tag_own_infra` never consulted that guard: it counted two
    distinct unclassified hosts under one registrable domain and declared the domain own, with
    no reference to the repo's identity at all.

    MEASURED ON THE LIVE FLEET (2026-09-01): `www.amazon.ae` and `sellercentral.amazon.ae`
    were both unclassified in one repo, so `amazon.ae` hit the threshold and Amazon's storefront
    and seller portal were classified as that client's OWN infrastructure — 52 endpoints across
    two repos, deleted from the audit backlog by a heuristic, not by anyone's decision.

    The premise "you reach a third party at a single host" is simply false for a marketplace
    with per-locale domains.
    """
    _write(tmp_path, "a.php", '$x=file_get_contents("https://www.amazon.ae/dp/x");\n')
    _write(tmp_path, "b.php", '$y=file_get_contents("https://payments.amazon.ae/y");\n')
    ms = [_url("a.php", 1), _url("b.php", 1)]
    by = {e["domain"]: e["hostClass"] for e in scan_endpoints(ms, str(tmp_path), _VENDORS)["endpoints"]}
    # Neither host is CATALOGUED (the catalogued domain is sellingpartnerapi), so both arrive
    # unclassified and the sweep sees two siblings under `amazon.ae`. The registrable label
    # `amazon` is a vendor-name token, so the sweep must refuse the claim.
    assert by["www.amazon.ae"] != "own-infra", "Amazon's storefront is not the client's own infra"
    assert by["payments.amazon.ae"] != "own-infra"


def test_the_sibling_sweep_still_works_for_a_genuine_own_domain(tmp_path):
    """The guard must not disarm the heuristic it protects — an unrelated domain still sweeps."""
    _write(tmp_path, "a.php", '$x=file_get_contents("https://shop.acmegrocer.com/x");\n')
    _write(tmp_path, "b.php", '$y=file_get_contents("https://orders.acmegrocer.com/y");\n')
    ms = [_url("a.php", 1), _url("b.php", 1)]
    by = {e["domain"]: e["hostClass"] for e in scan_endpoints(ms, str(tmp_path), _VENDORS)["endpoints"]}
    assert by["shop.acmegrocer.com"] == "own-infra"
    assert by["orders.acmegrocer.com"] == "own-infra"


def test_unrelated_hosts_on_a_multi_part_tld_are_not_siblings(tmp_path):
    """`_registrable` took the last TWO labels, so every `.com.au` host collapsed to `com.au` —
    and two UNRELATED third parties on that TLD looked like two hosts of one domain, sweeping
    both into own-infra. Same for .co.uk, .co.nz, .com.br, .co.jp.

    Measured on the live fleet 2026-09-01: 22 own-infra endpoints sat under a registrable domain
    of literally `com.au`. `own_infra._registrable` in this same package already handles public
    suffixes correctly; this sweep just wasn't using it.
    """
    _write(tmp_path, "a.php", '$x=file_get_contents("https://www.alpha.com.au/x");\n')
    _write(tmp_path, "b.php", '$y=file_get_contents("https://www.beta.com.au/y");\n')
    ms = [_url("a.php", 1), _url("b.php", 1)]
    by = {e["domain"]: e["hostClass"] for e in scan_endpoints(ms, str(tmp_path), _VENDORS)["endpoints"]}
    assert by["www.alpha.com.au"] != "own-infra", "two unrelated .com.au vendors are not siblings"
    assert by["www.beta.com.au"] != "own-infra"


def test_two_hosts_on_the_same_multi_part_tld_domain_still_sweep(tmp_path):
    """The correction must keep the heuristic working where it is actually right."""
    _write(tmp_path, "a.php", '$x=file_get_contents("https://shop.acmegrocer.com.au/x");\n')
    _write(tmp_path, "b.php", '$y=file_get_contents("https://orders.acmegrocer.com.au/y");\n')
    ms = [_url("a.php", 1), _url("b.php", 1)]
    by = {e["domain"]: e["hostClass"] for e in scan_endpoints(ms, str(tmp_path), _VENDORS)["endpoints"]}
    assert by["shop.acmegrocer.com.au"] == "own-infra"
    assert by["orders.acmegrocer.com.au"] == "own-infra"
