from agent.lib.inventory_diff import diff_inventories


def _repo(path, endpoints=None, sdks=None, runtimes=None):
    return {"path": path, "endpoints": endpoints or [], "sdks": sdks or [], "runtimes": runtimes or {}}


def _ep(tk, dom, ver):
    return {"techKey": tk, "domain": dom, "version": ver}


def _sdk(eco, pkg, ver):
    return {"eco": eco, "pkg": pkg, "ver": ver}


def test_repos_added_and_removed():
    prev = {"repos": [_repo("a"), _repo("gone")]}
    curr = {"repos": [_repo("a"), _repo("new")]}
    d = diff_inventories(prev, curr)
    assert d["reposAdded"] == ["new"] and d["reposRemoved"] == ["gone"]


def test_endpoint_and_version_and_sdk_and_runtime_changes():
    prev = {"repos": [_repo("web",
                            endpoints=[_ep("api:amazon-sp-api", "sellingpartnerapi", "v0"),
                                       _ep("api:stripe", "api.stripe.com", "v1")],
                            sdks=[_sdk("npm", "axios", "^1.6"), _sdk("npm", "gone", "^1.0")],
                            runtimes={"php": {"range": "^8.2"}})]}
    curr = {"repos": [_repo("web",
                            endpoints=[_ep("api:amazon-sp-api", "sellingpartnerapi", "v2"),  # bump v0->v2
                                       _ep("api:stripe", "api.stripe.com", "v1"),             # unchanged
                                       _ep("api:ebay", "api.ebay.com", "v1")],                # new API
                            sdks=[_sdk("npm", "axios", "^1.7"),                                # bump
                                  _sdk("npm", "added", "^2.0")],                              # new
                            runtimes={"php": {"range": "^8.3"}})]}                            # runtime change
    d = diff_inventories(prev, curr)
    ch = d["changes"][0]
    assert ch["repo"] == "web"
    assert {"techKey": "api:ebay", "domain": "api.ebay.com", "version": "v1"} in ch["endpointsAdded"]
    assert {"techKey": "api:amazon-sp-api", "domain": "sellingpartnerapi", "version": "v2"} in ch["endpointsAdded"]
    assert {"techKey": "api:amazon-sp-api", "domain": "sellingpartnerapi", "version": "v0"} in ch["endpointsRemoved"]
    assert {"eco": "npm", "pkg": "added", "ver": "^2.0"} in ch["sdksAdded"]
    assert {"eco": "npm", "pkg": "gone", "ver": "^1.0"} in ch["sdksRemoved"]
    assert {"eco": "npm", "pkg": "axios", "from": "^1.6", "to": "^1.7"} in ch["sdkVersionChanges"]
    assert {"product": "php", "from": "^8.2", "to": "^8.3"} in ch["runtimeChanges"]


def test_unchanged_repo_not_listed():
    prev = {"repos": [_repo("web", sdks=[_sdk("npm", "axios", "^1.6")])]}
    curr = {"repos": [_repo("web", sdks=[_sdk("npm", "axios", "^1.6")])]}
    assert diff_inventories(prev, curr)["changes"] == []


def test_empty_baseline_yields_no_changes():
    curr = {"repos": [_repo("web", endpoints=[_ep("api:stripe", "api.stripe.com", "v1")])]}
    d = diff_inventories({}, curr)
    assert d["reposAdded"] == ["web"] and d["changes"] == []      # first run: baseline, not "added" endpoints


def test_endpoint_with_null_techkey_sorts_instead_of_crashing():
    """SDK-client endpoints (agent/sdk_clients.py) carry techKey=None — they are derived
    from the manifest, not from an AST match, so there is no rule key to name them by.

    Shipped bug: _fmt_eps sorted raw tuples, so the FIRST scan in which such an endpoint
    entered or left the delta died with
        TypeError: '<' not supported between instances of 'NoneType' and 'str'
    killing `run` outright (agent/run.py -> inventory_scan.scan_folder -> diff_inventories).
    It survived earlier scans only because an UNCHANGED endpoint set is never sorted, and it
    needs a MIXED delta to fire: two None techKeys compare equal and fall through to the
    domain, so the delta must carry a None techKey ALONGSIDE a string one.
    """
    prev = {"repos": [_repo("crm", endpoints=[_ep("api:mailgun", "api.mailgun.net", "v3")])]}
    curr = {"repos": [_repo("crm", endpoints=[_ep("api:mailgun", "api.mailgun.net", "v3"),
                                              _ep(None, "api.twilio.com", None),
                                              _ep(None, "api.sendgrid.com", None),
                                              _ep("api:ebay", "api.ebay.com", "v1")])]}
    d = diff_inventories(prev, curr)
    added = d["changes"][0]["endpointsAdded"]
    assert {"techKey": None, "domain": "api.sendgrid.com", "version": None} in added
    assert {"techKey": None, "domain": "api.twilio.com", "version": None} in added
    # deterministic order (principle 3): None sorts as "", so the SDK-derived pair leads
    assert [e["domain"] for e in added] == ["api.sendgrid.com", "api.twilio.com", "api.ebay.com"]


def test_endpoint_with_null_domain_also_sorts():
    """Same crash via the other nullable column — guard both, not just the one that bit us."""
    prev = {"repos": [_repo("crm", endpoints=[])]}
    curr = {"repos": [_repo("crm", endpoints=[_ep("api:x", None, None)])]}
    d = diff_inventories(prev, curr)
    assert d["changes"][0]["endpointsAdded"] == [{"techKey": "api:x", "domain": None, "version": None}]
