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
from agent.lib import catalog_overlay, delivery, own_domains
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


def test_unknown_verdict_records_the_ledger_and_touches_no_other_overlay(monkeypatch, tmp_path):
    """An `unknown` writes to the needs-human ledger and NOTHING else.

    This test used to assert `list(d.iterdir()) == []` — "no client evidence -> nothing to
    write". That was the bug: the verdict was returned in the summary and persisted nowhere, so
    the next deterministic scan re-derived the host as `queued` and "we looked and could not
    tell" became indistinguishable from "nobody looked". An unknown IS evidence — evidence that
    a pass ran and reached no verdict — and it is recorded as such. What must still hold, and
    is what this test now guards, is that it asserts nothing about the world: no vendor, no
    own-domain, no sunset."""
    d = _overlay_dir(monkeypatch, tmp_path)
    result = resolve.apply([_unknown_verdict()], now="2026-08-13")
    assert result["written"] == {"own_domain": 0, "vendor_identity": 0, "retiring": 0, "needs_human": 1}
    assert [p.name for p in d.iterdir()] == [catalog_overlay.NEEDS_HUMAN]
    for name in (catalog_overlay.VENDORS, catalog_overlay.OWN_DOMAINS, catalog_overlay.SUNSETS):
        assert not (d / name).exists(), f"unknown leaked into {name}"


def test_an_unknown_with_no_overlay_dir_is_refused_not_silently_dropped(monkeypatch):
    """There is nowhere to record that the pass looked, so the batch is refused rather than
    reporting success and losing the verdict — the failure mode this slice exists to end.
    Empty $DRIFT_CATALOG_DIR is the explicit disable; unset would default to ~/.drift/catalog."""
    monkeypatch.setenv("DRIFT_CATALOG_DIR", "")
    with pytest.raises(resolve.ResolveRejected) as exc:
        resolve.apply([_unknown_verdict()], now="2026-08-13")
    assert any("DRIFT_CATALOG_DIR" in p for p in exc.value.args[0])


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


# --------------------------------------------------------------------- overlay explicitly disabled
def test_catalog_writes_are_refused_without_an_overlay_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("DRIFT_CATALOG_DIR", "")
    with pytest.raises(resolve.ResolveRejected):
        resolve.apply([_own_domain_verdict()], now="2026-08-13")


# --------------------------------------------------------------------- CRITICAL 1: apply is atomic on write failure
def test_apply_with_an_unwritable_target_is_refused_cleanly_all_or_nothing(monkeypatch, tmp_path):
    """vendors.local.yaml is a directory (a real, if unusual, pre-existing state). The old code
    wrote own_domains.local.yaml FIRST, then blew up with a raw IsADirectoryError on the vendors
    write — half-applying the batch and leaking a traceback instead of a clean refusal."""
    d = _overlay_dir(monkeypatch, tmp_path)
    (d / catalog_overlay.VENDORS).mkdir()
    verdicts = [_own_domain_verdict(), _vendor_identity_verdict()]
    with pytest.raises(resolve.ResolveRejected):
        resolve.apply(verdicts, now="2026-08-13")
    # all-or-nothing: the own-domain half (which used to land first) must NOT be written either
    assert own_domains.load() == {}
    assert not (d / catalog_overlay.OWN_DOMAINS).exists()


def test_apply_refuses_the_whole_batch_when_one_target_overlay_is_pre_existing_and_malformed(
        monkeypatch, tmp_path):
    """A pre-existing malformed sunsets overlay must block the WHOLE apply, including the
    own-domain and vendor entries that would otherwise have landed cleanly."""
    d = _overlay_dir(monkeypatch, tmp_path)
    (d / catalog_overlay.SUNSETS).write_text(yaml.safe_dump({"not": "a list"}))
    verdicts = [_own_domain_verdict(), _vendor_identity_verdict(), _retiring_verdict()]
    with pytest.raises(resolve.ResolveRejected):
        resolve.apply(verdicts, now="2026-08-13")
    assert own_domains.load() == {}
    assert not (d / catalog_overlay.VENDORS).exists()


# --------------------------------------------------------------------- IMPORTANT 4: reuse catalog_overlay.load_list
def test_applying_over_a_mapping_shaped_vendors_overlay_is_refused_not_silently_corrupted(
        monkeypatch, tmp_path):
    """`list(a_mapping) + entries` silently turns a mapping-shaped overlay into a list of its
    own KEYS, and every later load_vendors() call then dies with a TypeError. Must be refused,
    and the pre-existing (if malformed) file must be left exactly as it was."""
    d = _overlay_dir(monkeypatch, tmp_path)
    (d / catalog_overlay.VENDORS).write_text(yaml.safe_dump({"GeoMapper": {"domains": ["x"]}}))
    with pytest.raises(resolve.ResolveRejected):
        resolve.apply([_vendor_identity_verdict()], now="2026-08-13")
    raw = yaml.safe_load((d / catalog_overlay.VENDORS).read_text())
    assert raw == {"GeoMapper": {"domains": ["x"]}}


# --------------------------------------------------------------------- IMPORTANT 5: idempotent re-apply
# --------------------------------------------------------------------- MINOR 6: reason must be substantive
def test_own_domain_with_a_trivial_reason_is_refused():
    """A truthiness check lets 'x' through — a one-word non-reason is a guess dressed as a
    verdict, exactly what the `reason` requirement exists to stop."""
    v = _own_domain_verdict(reason="x")
    problems = resolve.check_verdicts([v])
    assert problems
    assert any("reason" in p for p in problems)


def test_own_domain_with_a_substantive_reason_still_passes():
    v = _own_domain_verdict()
    assert resolve.check_verdicts([v]) == []


# --------------------------------------------------------------------- MINOR 6: --now must be YYYY-MM-DD
@pytest.mark.parametrize("bad_now", ["yesterday", "2026/08/13", "13-08-2026", "", "2026-13-40"])
def test_apply_rejects_a_malformed_now(monkeypatch, tmp_path, bad_now):
    _overlay_dir(monkeypatch, tmp_path)
    with pytest.raises(resolve.ResolveRejected):
        resolve.apply([_own_domain_verdict()], now=bad_now)


def test_applying_an_identical_batch_twice_is_a_no_op_not_a_duplicate(monkeypatch, tmp_path):
    d = _overlay_dir(monkeypatch, tmp_path)
    verdicts = [_own_domain_verdict(), _vendor_identity_verdict(), _retiring_verdict()]
    resolve.apply(verdicts, now="2026-08-13")
    result2 = resolve.apply(verdicts, now="2026-08-13")
    assert result2["written"] == {"own_domain": 0, "vendor_identity": 0, "retiring": 0,
                                  "needs_human": 0}
    assert len(yaml.safe_load((d / catalog_overlay.OWN_DOMAINS).read_text())) == 1
    assert len(yaml.safe_load((d / catalog_overlay.VENDORS).read_text())) == 1
    assert len(yaml.safe_load((d / catalog_overlay.SUNSETS).read_text())) == 1
    assert sum(1 for x in load_vendors() if x.vendor == "GeoMapper") == 1


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


def test_a_host_already_attributed_to_a_vendor_is_not_also_queued_as_unnamed():
    """REGRESSION: Salesforce Commerce Cloud has NO catalog domain — OCAPI runs on each
    merchant's own host — so it is named by its path signature and the record is labelled with
    the host observed at the call-site. That host also produces an Unknown record from plain
    URL extraction, and the resolve queue only skipped `classified` RECORDS, not classified
    HOSTS. The result contradicted itself: the report named the vendor and dated its
    deprecation, while the work-order asked a human to go identify the very same host."""
    payload = {"endpoints": [
        {"domain": "shop.example-merchant.com", "repo": "storefront-bridge", "classified": True,
         "techKey": "api:sfcc", "hostClass": "api", "file_count": 1},
        {"domain": "shop.example-merchant.com", "repo": "storefront-bridge", "classified": False,
         "hostClass": "unclassified", "file_count": 1},
        {"domain": "api.unknown-vendor.test", "repo": "storefront-bridge", "classified": False,
         "hostClass": "api-lead", "file_count": 3},
    ]}
    hosts = [h for h, _ in delivery.queued_hosts(payload)]
    assert hosts == ["api.unknown-vendor.test"]
