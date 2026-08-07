"""ABSORPTION.md — the deterministic brief for a flagged repo. Pure, no network."""
from agent.lib import brief


def _inv(repo="svc", verdict="UNKNOWN", reasons=("config-driven-url",), sigcov=None):
    return {"coverage": {
        "shapes": [{"repo": repo, "verdict": verdict, "reasons": list(reasons),
                    "languages": {"php": 40}, "signalCoverage": sigcov or {"php": ["sink", "path-literal"]},
                    "attributed": 3, "residueFingerprint": "cafef00d00000000"}],
        "residue": {
            "pathLiterals": [{"repo": repo, "loc": "src/A.php:12", "sample": "/v2/orders"},
                             {"repo": repo, "loc": "src/B.php:40", "sample": "/v2/items"},
                             {"repo": "other", "loc": "x.php:1", "sample": "/z"}],
            "sinks": [{"repo": repo, "loc": "src/C.php:9", "kind": "egress"}]}}}


def test_brief_has_the_load_bearing_sections():
    md = brief.build_brief(_inv(), "svc")
    for section in ("# Absorption brief", "Why you're here", "What the scanner sees",
                    "What's possible", "Blind spots", "idiom families", "The rails", "Launch"):
        assert section in md, section


def test_hybrid_repo_is_marked_absorbable():
    md = brief.build_brief(_inv(reasons=("config-driven-url",)), "svc")
    assert "HYBRID" in md and "absorbable via idiom instances" in md


def test_manual_repo_says_it_needs_a_code_release():
    # no-egress-signal → MANUAL: an idiom instance cannot teach an unmodeled language
    md = brief.build_brief(_inv(reasons=("no-egress-signal",), sigcov={"go": ["path-literal"]}), "svc")
    assert "MANUAL" in md and "code release" in md and "Survey" in md


def test_blind_spots_are_uncapped_and_scoped_to_the_repo():
    md = brief.build_brief(_inv(), "svc")
    assert "src/A.php:12" in md and "src/B.php:40" in md and "src/C.php:9" in md
    assert "/z" not in md                                   # another repo's residue is excluded


def test_the_three_families_and_their_required_fields_are_documented():
    md = brief.build_brief(_inv(), "svc")
    assert "url-assembly" in md and "`base`" in md
    assert "url-append" in md and "`target`" in md
    assert "operation-marker" in md and "`marker`" in md


def test_rails_name_the_overlay_and_the_gate():
    md = brief.build_brief(_inv(), "svc")
    assert "DRIFT_CATALOG_DIR" in md and "drift-scan absorb" in md and "residue fingerprint" in md.lower()
    assert "cafef00d00000000" in md                         # the fingerprint the MR must cite


def test_flag_url_is_linked_when_given():
    md = brief.build_brief(_inv(), "svc", flag_url="https://git.x/root/drift/-/issues/5")
    assert "https://git.x/root/drift/-/issues/5" in md


def test_output_is_byte_identical():
    assert brief.build_brief(_inv(), "svc") == brief.build_brief(_inv(), "svc")


def test_clean_repo_name_from_remote_url():
    inv = _inv("marketplacehub-marketplacehub-ed5f4fd4")
    inv["repos"] = [{"path": "marketplacehub-marketplacehub-ed5f4fd4",
                     "remote_url": "https://git.x/marketplacehub/marketplacehub.git"}]
    md = brief.build_brief(inv, "marketplacehub-marketplacehub-ed5f4fd4")
    assert "`marketplacehub/marketplacehub`" in md                  # clean path, not the clone slug
    assert "ed5f4fd4" not in md


def test_known_repo_brief_says_nothing_to_absorb():
    md = brief.build_brief(_inv(verdict="KNOWN", reasons=()), "svc")
    assert "Nothing to absorb" in md and "KNOWN" in md
    assert "Blind spots" not in md                          # no scaffold over nothing
