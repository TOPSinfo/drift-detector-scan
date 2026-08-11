"""Guards the batch/catalog research mode (`drift-scan research --vendors`) — Fable's move #1:
pre-audit the mainstream vendors so a demo shows "tracked-current", not an "unaudited" blank.

The gates are load-bearing and each pins a specific trust hazard Fable found in the codebase:
  - a `current` attestation must cite a REAL deprecation/versioning page, never a login redirect
    (the live Seller Snap attestation cited a 302-to-login — the exact bug the weak-source guard
    rejects);
  - mega-vendors (Google/AWS) can't be attested `current` wholesale — that would be the tool's
    first dishonest verdict (Google retires services constantly);
  - `retiring` still needs a source + a date that appears VERBATIM in the fetched excerpt.
"""
import argparse
import json

from agent import cli


def _apply(tmp_path, verdicts, vendors="all-unattested", now="2026-08-11"):
    vf = tmp_path / "v.json"
    vf.write_text(json.dumps(verdicts))
    out = tmp_path / "att.yaml"
    ns = argparse.Namespace(vendors=vendors, apply=str(vf), attest=str(out), now=now, state=None)
    return cli._research_vendors(ns), out


def test_unattested_work_list_excludes_attested_vendors():
    work = cli._unattested_vendors()
    names = {w["vendor"] for w in work}
    assert "Amazon SP-API" not in names          # attested in catalog_attestations.yaml
    assert names                                 # but the list is non-empty (unattested tail exists)
    assert all(isinstance(w["domains"], list) for w in work)


def test_mega_vendor_current_is_refused(tmp_path):
    rc, _ = _apply(tmp_path, [{"vendor": "Google APIs", "status": "current",
                               "source_url": "https://developers.google.com/",
                               "excerpt": "no deprecations", "source_kind": "deprecation-page"}])
    assert rc == 3                               # a blanket Google "current" is dishonest → rejected


def test_weak_source_current_is_refused(tmp_path):
    # the Seller Snap pattern: a login/redirect page is not a page that would reveal a retirement
    rc, _ = _apply(tmp_path, [{"vendor": "Seller Snap", "status": "current",
                               "source_url": "https://api.sellersnap.io/", "excerpt": "sign in",
                               "source_kind": "login"}])
    assert rc == 3


def test_current_without_excerpt_is_refused(tmp_path):
    rc, _ = _apply(tmp_path, [{"vendor": "Etsy", "status": "current",
                               "source_url": "https://developers.etsy.com/", "excerpt": "",
                               "source_kind": "changelog"}])
    assert rc == 3


def test_valid_current_writes_ai_research_attestation(tmp_path):
    import yaml
    rc, out = _apply(tmp_path, [{"vendor": "Stripe", "status": "current",
                                 "source_url": "https://stripe.com/docs/upgrades",
                                 "excerpt": "API versions are dated; older versions keep working.",
                                 "source_kind": "versioning-policy"}])
    assert rc == 0
    atts = yaml.safe_load(out.read_text())
    assert any(a["vendor"] == "Stripe" and a["by"] == "ai-research" and a["checked"] == "2026-08-11"
               for a in atts)


def test_retiring_needs_verbatim_date_in_excerpt(tmp_path):
    rc, _ = _apply(tmp_path, [{"vendor": "Foo", "status": "retiring", "date": "2027-01-01",
                               "source_url": "https://x/", "excerpt": "this API retires soon"}])
    assert rc == 3                               # date not present verbatim → rejected


def test_append_attestations_dedups_newest_wins(tmp_path):
    import yaml
    p = tmp_path / "a.yaml"
    cli._append_attestations(str(p), [{"vendor": "A", "checked": "2026-01-01", "source": "u"}])
    cli._append_attestations(str(p), [{"vendor": "A", "checked": "2026-02-02", "source": "u2"},
                                      {"vendor": "B", "checked": "2026-01-01", "source": "u"}])
    atts = {a["vendor"]: a for a in yaml.safe_load(p.read_text())}
    assert atts["A"]["checked"] == "2026-02-02"  # newest wins
    assert "B" in atts
