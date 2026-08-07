"""The catalog OVERLAY: a writable $DRIFT_CATALOG_DIR layered on the read-only package
catalogs, so the container/drift-ops can grow the indexes without a rebuild. Off by default
(unset env) → today's behaviour exactly."""
import yaml

from agent.lib import catalog_overlay
from agent.lib.vendors import load_vendors
from agent.lib.idioms import load_idioms
from agent.lib.vendor_sunsets import load_sunsets
from agent.lib.catalog_coverage import load_attestations


def _overlay(monkeypatch, tmp_path, name, data):
    d = tmp_path / "catalog"
    d.mkdir(exist_ok=True)
    (d / name).write_text(yaml.safe_dump(data))
    monkeypatch.setenv("DRIFT_CATALOG_DIR", str(d))
    return d


# ------------------------------------------------------------------- the helper
def test_load_list_is_empty_when_env_unset(monkeypatch):
    monkeypatch.delenv("DRIFT_CATALOG_DIR", raising=False)
    assert catalog_overlay.load_list(catalog_overlay.SUNSETS) == []


def test_load_list_is_empty_when_file_absent(monkeypatch, tmp_path):
    monkeypatch.setenv("DRIFT_CATALOG_DIR", str(tmp_path))    # dir set, no file
    assert catalog_overlay.load_list(catalog_overlay.IDIOMS) == []


def test_malformed_overlay_is_an_error_not_a_silent_skip(monkeypatch, tmp_path):
    _overlay(monkeypatch, tmp_path, catalog_overlay.SUNSETS, {"not": "a list"})
    import pytest
    with pytest.raises(ValueError):
        catalog_overlay.load_list(catalog_overlay.SUNSETS)


# ------------------------------------------------------------------- each loader layers it
def test_sunsets_layer_the_overlay_baseline_first(monkeypatch, tmp_path):
    base = load_sunsets()                                     # package only
    _overlay(monkeypatch, tmp_path, catalog_overlay.SUNSETS, [
        {"vendor": "eBay", "operation": "GetOverlayOp", "retires": "2025-01-01",
         "source": "https://developer.ebay.com/x"}])
    got = load_sunsets()
    assert len(got) == len(base) + 1
    assert got[-1]["vendor"] == "eBay" and got[-1]["operation"] == "GetOverlayOp"  # appended last


def test_vendors_layer_the_overlay(monkeypatch, tmp_path):
    base = load_vendors()
    _overlay(monkeypatch, tmp_path, catalog_overlay.VENDORS, [
        {"vendor": "Acme", "techKey": "api:acme", "domains": ["api.acme.test"]}])
    got = load_vendors()
    assert len(got) == len(base) + 1
    assert got[-1].vendor == "Acme" and got[-1].techKey == "api:acme"


def test_idioms_layer_the_overlay_and_share_the_dup_check(monkeypatch, tmp_path):
    base = load_idioms()
    _overlay(monkeypatch, tmp_path, catalog_overlay.IDIOMS, [
        {"family": "url-assembly", "id": "acme-overlay", "base": "$this->host", "evidence": ["src/x.php:1"]}])
    got = load_idioms()
    assert len(got) == len(base) + 1
    assert got[-1]["id"] == "acme-overlay"


def test_sdk_profiles_layer_the_overlay_baseline_first(monkeypatch, tmp_path):
    # client-scoped SDK profiles belong in the overlay (drift-ops), not the package — so moving
    # them there is loss-less: the loader reads baseline + overlay identically.
    from agent.lib.sdk_profiles import load as load_profiles
    base = load_profiles()
    _overlay(monkeypatch, tmp_path, catalog_overlay.SDK_PROFILES, [
        {"repo": "grp/acme-sdk", "vendor": "Acme", "source": "https://acme.test/docs",
         "versions": [{"version": "2026-01", "evidence": ["src/AcmeClient.php:12"]}]}])
    got = load_profiles()
    assert len(got) == len(base) + 1
    assert got[-1]["repo"] == "grp/acme-sdk"                  # appended last


def test_overlay_sdk_profile_runs_the_same_validation(monkeypatch, tmp_path):
    # an overlay entry is validated exactly like a package one — a malformed absorbed profile
    # is an error, never a silent skip (a dropped profile is a silent gap).
    import pytest
    from agent.lib.sdk_profiles import load as load_profiles, ProfileError
    _overlay(monkeypatch, tmp_path, catalog_overlay.SDK_PROFILES,
             [{"repo": "grp/x", "vendor": "X", "source": "s"}])   # missing required `versions`
    with pytest.raises(ProfileError):
        load_profiles()


def test_overlay_idiom_colliding_with_baseline_id_is_rejected(monkeypatch, tmp_path):
    dup = load_idioms()[0]["id"]                              # an id already in the baseline
    _overlay(monkeypatch, tmp_path, catalog_overlay.IDIOMS, [
        {"family": "url-assembly", "id": dup, "base": "$x->y", "evidence": ["src/y.php:1"]}])
    import pytest
    from agent.lib.idioms import IdiomError
    with pytest.raises(IdiomError):                           # combined dup-check fires
        load_idioms()


def test_attestation_overlay_overrides_a_vendor(monkeypatch, tmp_path):
    _overlay(monkeypatch, tmp_path, catalog_overlay.ATTESTATIONS, [
        {"vendor": "OverlayVendor", "checked": "2026-07-22",
         "source": "https://overlayvendor.test/deprecations"}])
    got = load_attestations()
    assert got.get("OverlayVendor", {}).get("checked") == "2026-07-22"


def test_explicit_path_bypasses_the_overlay(monkeypatch, tmp_path):
    # an explicit path means "exactly this file" — catalog tools/tests must not get the overlay
    _overlay(monkeypatch, tmp_path, catalog_overlay.SUNSETS, [
        {"vendor": "eBay", "operation": "ShouldNotAppear", "retires": "2025-01-01",
         "source": "https://x.test"}])
    from agent.lib.vendor_sunsets import _DEFAULT
    got = load_sunsets(_DEFAULT)                              # explicit package path
    assert not any(s.get("operation") == "ShouldNotAppear" for s in got)


# ------------------------------------------------------------------- the loop closes
def test_absorb_promote_writes_the_overlay_and_next_load_reads_it(monkeypatch, tmp_path):
    """The Learn loop's payoff: absorb.promote lands a sunset in the overlay, and the very
    next load_sunsets() (with $DRIFT_CATALOG_DIR set) sees it — no package edit, no rebuild."""
    from agent import absorb
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / "sunsets.yaml").write_text(yaml.safe_dump([
        {"vendor": "eBay", "operation": "GetAbsorbed", "retires": "2025-01-01",
         "source": "https://developer.ebay.com/x"}]))
    overlay = tmp_path / "catalog"
    overlay.mkdir()
    monkeypatch.setenv("DRIFT_CATALOG_DIR", str(overlay))
    added = absorb.promote(str(staged), idioms_path=str(overlay / catalog_overlay.IDIOMS),
                           sunsets_path=str(overlay / catalog_overlay.SUNSETS))
    assert added["sunsets"] == 1
    assert any(s.get("operation") == "GetAbsorbed" for s in load_sunsets())
