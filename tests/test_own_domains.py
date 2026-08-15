"""own_domains — the LOCAL overlay of confirmed own-infrastructure domains that lets the AI
resolution pass (a later task) settle a `queued` host without ever writing the answer into
drift.json itself: the AI's confirmation lands here as reviewed data, and the deterministic
scanner (own_infra + endpoints) re-derives `own-infra` from it on the next run. See
docs/superpowers/specs/2026-08-13-no-queue-design.md.

Client hostnames NEVER enter the public tree, so this file lives entirely under
$DRIFT_CATALOG_DIR (agent/lib/catalog_overlay.py) — there is no package baseline to layer.
"""
import yaml
import pytest

from agent.lib import catalog_overlay, own_domains, own_infra, dashboard_render
from agent.lib.endpoints import scan_endpoints
from agent.lib.vendors import Vendor, DEFAULT_VERSION_REGEX


def _write_overlay(monkeypatch, tmp_path, entries):
    d = tmp_path / "catalog"
    d.mkdir(exist_ok=True)
    (d / catalog_overlay.OWN_DOMAINS).write_text(yaml.safe_dump(entries))
    monkeypatch.setenv("DRIFT_CATALOG_DIR", str(d))
    return d


_ENTRY = {
    "repo": "acme-org/acmegrocer-foods", "domain": "acmegrocer.com", "by": "ai-resolution",
    "checked": "2026-08-13", "reason": "the project's own product domain",
}


def _url(path, line):
    return {"kind": "url", "path": path, "line": line}


def _write(tmp_path, rel, text):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


# --------------------------------------------------------------------- own_domains.load()
def test_load_is_empty_when_overlay_disabled(monkeypatch):
    monkeypatch.setenv("DRIFT_CATALOG_DIR", "")
    assert own_domains.load() == {}


def test_load_is_empty_when_overlay_file_absent(monkeypatch, tmp_path):
    monkeypatch.setenv("DRIFT_CATALOG_DIR", str(tmp_path))    # dir set, no file
    assert own_domains.load() == {}


def test_load_groups_domains_by_repo(monkeypatch, tmp_path):
    _write_overlay(monkeypatch, tmp_path, [
        _ENTRY,
        {"repo": "acme-org/acmegrocer-foods", "domain": "acmedistribution.com",
         "by": "ai-resolution", "checked": "2026-08-13", "reason": "same project, second domain"},
        {"repo": "org/zenithapp-crm", "domain": "zenithapp.io", "by": "ai-resolution",
         "checked": "2026-08-13", "reason": "APP_URL and repo name both name it"},
    ])
    table = own_domains.load()
    assert table["acme-org/acmegrocer-foods"] == frozenset({"acmegrocer.com", "acmedistribution.com"})
    assert table["org/zenithapp-crm"] == frozenset({"zenithapp.io"})


@pytest.mark.parametrize("missing", ["repo", "domain", "by", "checked", "reason"])
def test_load_rejects_an_entry_missing_a_required_field(monkeypatch, tmp_path, missing):
    entry = dict(_ENTRY)
    del entry[missing]
    _write_overlay(monkeypatch, tmp_path, [entry])
    with pytest.raises(own_domains.OwnDomainError):
        own_domains.load()


def test_load_rejects_a_non_mapping_entry(monkeypatch, tmp_path):
    _write_overlay(monkeypatch, tmp_path, ["acmegrocer.com"])
    with pytest.raises(own_domains.OwnDomainError):
        own_domains.load()


# --------------------------------------------------------------------- own_infra.signals(confirmed=)
def test_confirmed_domain_is_own_infra_strong_not_a_token():
    """Matches like the git-remote org domain (exact or subdomain suffix) — NOT a token
    substring — so a confirmed `acmegrocer.com` claims `api.acmegrocer.com` but a mere
    lookalike host must not match."""
    sig = own_infra.signals(confirmed=frozenset({"acmegrocer.com"}))
    assert own_infra.is_own("acmegrocer.com", sig)
    assert own_infra.is_own("api.acmegrocer.com", sig)          # subdomain
    assert not own_infra.is_own("notacmegrocer.com", sig)       # lookalike, not a suffix match
    assert not own_infra.is_own("acmegrocer.com.evil.io", sig)  # host doesn't END in the domain


def test_confirmed_domain_reason_is_not_a_token_claim():
    """A confirmed overlay domain is a reviewed, strong claim — coverage must land `na`, not
    stay `queued` the way a repo-name TOKEN claim does (dashboard_render._coverage)."""
    sig = own_infra.signals(confirmed=frozenset({"acmegrocer.com"}))
    reason = own_infra.reason("api.acmegrocer.com", sig)
    assert reason is not None
    assert not own_infra.is_token_claim(reason)
    assert dashboard_render._coverage("own-infra", False, reason) == "na"


def test_confirmed_domain_naming_a_catalogued_vendor_is_refused():
    """The non-negotiable guard: a domain that matches a catalogued vendor may never become
    own-infra, no matter what the overlay says — the vendor wins. Mirrors the existing
    acme-mailgun-sync token guard, but for a CONFIRMED overlay entry instead of a repo-name
    token."""
    sig = own_infra.signals(vendor_tokens=frozenset({"mailgun"}),
                            confirmed=frozenset({"mailgun-status.io"}))
    assert "mailgun-status.io" not in sig["confirmed"]
    assert not own_infra.is_own("mailgun-status.io", sig)


# --------------------------------------------------------------------- threaded through scan_endpoints
_STRIPE = Vendor("Stripe", "api:stripe", ("stripe.com",), DEFAULT_VERSION_REGEX)
_MAILGUN = Vendor("Mailgun", "api:mailgun", ("mailgun.net",), DEFAULT_VERSION_REGEX)


def test_confirmed_domain_classifies_own_infra_with_coverage_na_end_to_end(monkeypatch, tmp_path):
    _write_overlay(monkeypatch, tmp_path, [_ENTRY])
    _write(tmp_path, "a.php", '$x=file_get_contents("https://api.acmegrocer.com/products");\n')
    out = scan_endpoints([_url("a.php", 1)], str(tmp_path), [_STRIPE],
                         repo_id="https://git.example.com/acme-org/acmegrocer-foods.git")
    rec = next(e for e in out["endpoints"] if e["domain"] == "api.acmegrocer.com")
    assert rec["hostClass"] == "own-infra"
    assert not own_infra.is_token_claim(rec.get("ownInfraReason"))
    assert dashboard_render._coverage(rec["hostClass"], rec["classified"],
                                      rec.get("ownInfraReason")) == "na"


def test_confirmed_domain_scoped_to_a_different_repo_does_not_apply(monkeypatch, tmp_path):
    _write_overlay(monkeypatch, tmp_path, [_ENTRY])       # scoped to acme-org/acmegrocer-foods
    _write(tmp_path, "a.php", '$x=file_get_contents("https://api.acmegrocer.com/products");\n')
    out = scan_endpoints([_url("a.php", 1)], str(tmp_path), [_STRIPE],
                         repo_id="https://git.example.com/some-org/unrelated-repo.git")
    rec = next(e for e in out["endpoints"] if e["domain"] == "api.acmegrocer.com")
    assert rec["hostClass"] != "own-infra"


def test_missing_overlay_file_changes_nothing_end_to_end(monkeypatch, tmp_path):
    """Overlay disabled / no own_domains file -> own_domains.load() == {} -> confirmed stays
    empty, so the repo's OTHER own-infra signals (token/domain) are exactly what they'd be
    without this feature. Uses a repo identity that shares no token with the host, so the only
    way this host could become own-infra is via a (nonexistent) confirmed entry."""
    monkeypatch.setenv("DRIFT_CATALOG_DIR", "")
    _write(tmp_path, "a.php", '$x=file_get_contents("https://api.acmegrocer.com/products");\n')
    out = scan_endpoints([_url("a.php", 1)], str(tmp_path), [_STRIPE],
                         repo_id="https://git.example.com/some-org/totally-different.git")
    rec = next(e for e in out["endpoints"] if e["domain"] == "api.acmegrocer.com")
    assert rec["hostClass"] != "own-infra"


def test_confirmed_domain_naming_a_catalogued_vendor_does_not_suppress_it_end_to_end(monkeypatch, tmp_path):
    """A wrong overlay entry that (mis)confirms a catalogued vendor's own name as own-infra must
    not swallow that vendor. The vendor's CATALOGUED host wins outright (classified upstream of
    own_infra entirely); the guard is what stops an UNCATALOGUED sibling host (its status page)
    from being claimed via the token collision."""
    _write_overlay(monkeypatch, tmp_path, [
        {"repo": "acme/acme-mailgun-sync", "domain": "mailgun-status.io", "by": "ai-resolution",
         "checked": "2026-08-13", "reason": "wrongly thought to be our own status page"},
    ])
    _write(tmp_path, "a.php", '// see https://mailgun-status.io/incidents for outages\n')
    out = scan_endpoints([_url("a.php", 1)], str(tmp_path), [_MAILGUN],
                         repo_id="https://git.example.com/acme/acme-mailgun-sync.git")
    rec = next(e for e in out["endpoints"] if e["domain"] == "mailgun-status.io")
    assert rec["hostClass"] != "own-infra"
