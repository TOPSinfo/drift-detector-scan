"""The resolution gate (agent/resolve.py): the only thing standing between a model's opinion
and the reviewed data the deterministic scanner trusts (docs/superpowers/specs/
2026-08-13-no-queue-design.md). An AI resolution pass produces verdicts for hosts a scan left
`queued`; this gate refuses anything unevidenced — it never sanitises a bad verdict into a
good one, and it never writes a PARTIAL apply.

Fictional identifiers throughout (acmegrocer / zenithapp / geo-mapper), matching this repo's
existing fixture style (tests/test_own_domains.py) — real client names were scrubbed from this
public repo and must never be reintroduced. Stripe/eBay are the tool's OWN vendor catalog
(agent/vendors.yaml), not a client, so they're fair game for "names a catalogued vendor" cases.
"""
import json

import yaml
import pytest

from agent import resolve
from agent.lib import catalog_overlay, own_domains
from agent.lib.vendors import load_vendors


def _overlay_dir(monkeypatch, tmp_path):
    d = tmp_path / "catalog"
    d.mkdir(exist_ok=True)
    monkeypatch.setenv("DRIFT_CATALOG_DIR", str(d))
    return d


def _own_domain_verdict(**over):
    v = {"status": "own-domain", "host": "acmegrocer.com", "repo": "acme-org/acmegrocer-foods",
         "reason": "the project's own product domain; APP_URL and the repo name both name it"}
    v.update(over)
    return v


def _vendor_identity_verdict(**over):
    v = {"status": "vendor-identity", "host": "listingimages.geo-mapper.io", "vendor": "GeoMapper",
         "source_url": "https://geo-mapper.io/docs/api-hosts"}
    v.update(over)
    return v


def _retiring_verdict(**over):
    v = {"status": "retiring", "host": "api.geo-mapper.io", "vendor": "GeoMapper",
         "source_url": "https://geo-mapper.io/changelog", "date": "2026-11-30",
         "excerpt": "GeoMapper API v1 will be retired on November 30, 2026. Migrate to v2."}
    v.update(over)
    return v


def _unknown_verdict(**over):
    v = {"status": "unknown", "host": "weird.zenithapp-crm.internal", "repo": "org/zenithapp-crm",
         "note": "could not determine ownership or vendor identity"}
    v.update(over)
    return v


# --------------------------------------------------------------------- work_list()
def test_work_list_surfaces_queued_hosts_with_repo_call_sites_and_reason():
    drift = {"endpoints": [
        {"domain": "listingimages.thirdparty.io", "repo": "acme-org/acmegrocer-foods",
         "coverage": "queued", "hostClass": "unclassified", "classified": False,
         "files": ["app/Services/Images.php:42"]},
        {"domain": "api.stripe.com", "repo": "acme-org/acmegrocer-foods",
         "coverage": "tracked", "hostClass": "api", "classified": True,
         "files": ["app/Billing.php:10"]},
    ]}
    work = resolve.work_list(drift)
    assert len(work) == 1
    entry = work[0]
    assert entry["host"] == "listingimages.thirdparty.io"
    assert entry["repo"] == "acme-org/acmegrocer-foods"
    assert entry["call_sites"] == ["app/Services/Images.php:42"]
    assert entry["reason"]


def test_work_list_is_empty_when_nothing_is_queued():
    drift = {"endpoints": [{"domain": "api.stripe.com", "repo": "x", "coverage": "tracked",
                            "hostClass": "api", "classified": True, "files": []}]}
    assert resolve.work_list(drift) == []


# --------------------------------------------------------------------- refusal: own-domain, no reason
def test_own_domain_with_no_reason_is_refused(monkeypatch, tmp_path):
    _overlay_dir(monkeypatch, tmp_path)
    v = _own_domain_verdict(reason="")
    problems = resolve.check_verdicts([v])
    assert problems
    assert any("reason" in p for p in problems)
    with pytest.raises(resolve.ResolveRejected):
        resolve.apply([v], now="2026-08-13")


# --------------------------------------------------------------------- refusal: own-domain names a vendor
def test_own_domain_naming_a_catalogued_vendor_is_refused(monkeypatch, tmp_path):
    _overlay_dir(monkeypatch, tmp_path)
    v = _own_domain_verdict(host="api.stripe.com", reason="we think this is ours")
    problems = resolve.check_verdicts([v])
    assert problems
    assert any("Stripe" in p or "stripe" in p.lower() for p in problems)
    with pytest.raises(resolve.ResolveRejected):
        resolve.apply([v], now="2026-08-13")


# --------------------------------------------------------------------- refusal: vendor-identity, no source
def test_vendor_identity_with_no_source_is_refused(monkeypatch, tmp_path):
    _overlay_dir(monkeypatch, tmp_path)
    v = _vendor_identity_verdict(source_url="")
    problems = resolve.check_verdicts([v])
    assert problems
    assert any("source" in p for p in problems)
    with pytest.raises(resolve.ResolveRejected):
        resolve.apply([v], now="2026-08-13")


# --------------------------------------------------------------------- refusal: retiring, date not in excerpt
def test_retiring_with_date_absent_from_excerpt_is_refused(monkeypatch, tmp_path):
    """The exact bug that motivated this project's date gate: the model asserts a date that
    does not actually appear on the page it cites."""
    _overlay_dir(monkeypatch, tmp_path)
    v = _retiring_verdict(date="2026-11-30",
                          excerpt="GeoMapper API v1 will be retired soon. Migrate to v2.")
    problems = resolve.check_verdicts([v])
    assert problems
    assert any("verbatim" in p.lower() or "excerpt" in p.lower() for p in problems)
    with pytest.raises(resolve.ResolveRejected):
        resolve.apply([v], now="2026-08-13")


def test_retiring_date_in_excerpt_passes_the_check():
    v = _retiring_verdict()
    assert resolve.check_verdicts([v]) == []


# --------------------------------------------------------------------- all-or-nothing
def test_one_bad_verdict_blocks_the_whole_apply_and_writes_nothing(monkeypatch, tmp_path):
    d = _overlay_dir(monkeypatch, tmp_path)
    good = _own_domain_verdict()
    bad = _vendor_identity_verdict(source_url="")
    with pytest.raises(resolve.ResolveRejected):
        resolve.apply([good, bad], now="2026-08-13")
    # nothing written: no overlay files created at all
    assert list(d.iterdir()) == []
    assert own_domains.load() == {}


# --------------------------------------------------------------------- unknown is legitimate
def test_unknown_verdict_is_accepted():
    v = _unknown_verdict()
    assert resolve.check_verdicts([v]) == []


def test_unknown_verdict_applies_without_touching_any_overlay(monkeypatch, tmp_path):
    d = _overlay_dir(monkeypatch, tmp_path)
    result = resolve.apply([_unknown_verdict()], now="2026-08-13")
    assert result["written"] == {"own_domain": 0, "vendor_identity": 0, "retiring": 0, "needs_human": 1}
    assert list(d.iterdir()) == []          # no client evidence -> nothing to write


# --------------------------------------------------------------------- well-formed set applies + lands
def test_well_formed_mixed_set_applies_and_lands_in_the_overlays(monkeypatch, tmp_path):
    d = _overlay_dir(monkeypatch, tmp_path)
    verdicts = [_own_domain_verdict(), _vendor_identity_verdict(), _retiring_verdict(),
               _unknown_verdict()]
    result = resolve.apply(verdicts, now="2026-08-13")
    assert result["written"] == {"own_domain": 1, "vendor_identity": 1, "retiring": 1, "needs_human": 1}

    # own-domain landed in the own-domains overlay, scoped to the repo, and the deterministic
    # loader picks it straight up (own_domains.load()) — no code change, no rebuild.
    table = own_domains.load()
    assert table["acme-org/acmegrocer-foods"] == frozenset({"acmegrocer.com"})

    # vendor-identity landed in the vendors overlay and load_vendors() sees it.
    vendors_yaml = yaml.safe_load((d / catalog_overlay.VENDORS).read_text())
    assert vendors_yaml[0]["vendor"] == "GeoMapper"
    assert "listingimages.geo-mapper.io" in vendors_yaml[0]["domains"]
    assert vendors_yaml[0]["source"] == "https://geo-mapper.io/docs/api-hosts"
    loaded = load_vendors()
    assert any(v.vendor == "GeoMapper" for v in loaded)

    # retiring landed in the sunsets overlay, sourced + dated, excerpt carried for audit.
    sunsets_yaml = yaml.safe_load((d / catalog_overlay.SUNSETS).read_text())
    assert sunsets_yaml[0]["vendor"] == "GeoMapper"
    assert sunsets_yaml[0]["retires"] == "2026-11-30"
    assert sunsets_yaml[0]["source"] == "https://geo-mapper.io/changelog"

    # unknown never touches a catalog — it only shows up in the needs-human summary.
    assert result["needs_human"] and result["needs_human"][0]["host"] == "weird.zenithapp-crm.internal"


# --------------------------------------------------------------------- no overlay dir set
def test_catalog_writes_are_refused_without_an_overlay_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("DRIFT_CATALOG_DIR", raising=False)
    with pytest.raises(resolve.ResolveRejected):
        resolve.apply([_own_domain_verdict()], now="2026-08-13")


# --------------------------------------------------------------------- IMPORTANT 3: source_url is shape-checked
@pytest.mark.parametrize("bad_url", ["x", "   ", "file:///etc/passwd", "not-a-url-at-all"])
def test_vendor_identity_source_url_must_be_an_http_url_with_a_host(bad_url):
    """Presence alone isn't enough — 'x', whitespace, a file:// URL, and a bare word all
    used to sail through because the gate only checked truthiness."""
    v = _vendor_identity_verdict(source_url=bad_url)
    problems = resolve.check_verdicts([v])
    assert problems
    assert any("source_url" in p or "source" in p.lower() for p in problems)


@pytest.mark.parametrize("bad_url", ["x", "file:///etc/passwd", "ftp://example.com/x"])
def test_retiring_source_url_must_be_an_http_url_with_a_host(bad_url):
    v = _retiring_verdict(source_url=bad_url)
    problems = resolve.check_verdicts([v])
    assert problems
    assert any("source_url" in p or "source" in p.lower() for p in problems)


def test_vendor_identity_with_a_real_http_url_still_passes():
    v = _vendor_identity_verdict(source_url="https://geo-mapper.io/docs/api-hosts")
    assert resolve.check_verdicts([v]) == []


# --------------------------------------------------------------------- CRITICAL 2: retiring goes through absorb.check_sunsets
def test_retiring_with_malformed_date_field_is_refused_by_the_absorb_gate():
    """resolve.py's retiring path lands in the SAME sunsets.local.yaml staged absorption
    writes, so it must be held to absorb.check_sunsets's rules, not merely date_in_text.
    '20261130' parses fine via date.fromisoformat, and its human-readable form ('November 30,
    2026') can still legitimately appear in the excerpt — date_in_text alone waves it through,
    but check_sunsets's `retires` regex (^\\d{4}-\\d{2}-\\d{2}$) must not."""
    v = _retiring_verdict(date="20261130",
                          excerpt="GeoMapper API v1 will be retired on November 30, 2026.")
    problems = resolve.check_verdicts([v])
    assert problems
    assert any("YYYY-MM-DD" in p for p in problems)
    with pytest.raises(resolve.ResolveRejected):
        resolve.apply([v], now="2026-08-13")
