import json

import yaml

from agent.lib.engine import run_scan
from tests import astgrep_fake


def _rules(tmp_path):
    """A real ast-grep rule file — run_scan recovers metadata from it, not from output."""
    p = tmp_path / "rules.yaml"
    p.write_text(yaml.safe_dump(
        {"id": "stripe-endpoint@php", "language": "php",
         "metadata": {"vendor": "Stripe", "techKey": "api:stripe", "kind": "endpoint"},
         "rule": {"kind": "string", "regex": "stripe"}}))
    return p


def test_run_scan_invokes_ast_grep_and_recovers_metadata(tmp_path):
    seen = {}

    def fake_run(args):
        seen["args"] = args
        return astgrep_fake.canned(astgrep_fake.hit("stripe-endpoint", "src/pay.php", 3))

    rules = _rules(tmp_path)
    res = run_scan("/repo", str(rules), engine="ast-grep", run=fake_run)
    assert seen["args"] == ["ast-grep", "scan", "-r", str(rules),
                            "--include-metadata", "--json=compact", "/repo"]
    # this fake emits BARE matches (no metadata), so run_scan falls back to reading the
    # rule file — proving the fallback still recovers {vendor, techKey, kind}. A live
    # engine echoes metadata via --include-metadata and this re-read never runs.
    m = res["matches"][0]
    assert {k: m[k] for k in ("checkId", "vendor", "techKey", "kind", "path", "line")} == {
        "checkId": "stripe-endpoint", "vendor": "Stripe", "techKey": "api:stripe",
        "kind": "endpoint", "path": "src/pay.php", "line": 3}
    assert "text" in m                      # full matched text, for multi-line literals


def test_line_numbers_are_shifted_from_ast_greps_zero_index(tmp_path):
    raw = json.dumps([{"ruleId": "stripe-endpoint@php", "file": "a.php",
                       "range": {"start": {"line": 0}}}])          # first line of the file
    res = run_scan("/repo", str(_rules(tmp_path)), run=lambda a: raw)
    assert res["matches"][0]["line"] == 1                          # not 0


def test_unknown_rule_id_yields_empty_metadata_not_a_crash(tmp_path):
    raw = astgrep_fake.canned(astgrep_fake.hit("never-declared", "a.php", 2))
    res = run_scan("/repo", str(_rules(tmp_path)), run=lambda a: raw)
    m = res["matches"][0]
    assert m["checkId"] == "never-declared" and m["kind"] == "" and m["vendor"] == ""


def test_run_scan_blank_output_is_empty_not_crash(tmp_path):
    res = run_scan("/repo", str(_rules(tmp_path)), run=lambda args: "")
    assert res == {"matches": [], "scanned": [], "errors": []}


def test_missing_rule_file_degrades_to_empty_metadata(tmp_path):
    raw = astgrep_fake.canned(astgrep_fake.hit("stripe-endpoint", "a.php", 1))
    res = run_scan("/repo", str(tmp_path / "nope.yaml"), run=lambda a: raw)
    assert res["matches"][0]["kind"] == ""                         # no crash, just unclassified


def test_test_and_vendor_dirs_are_skipped(tmp_path):
    """Mocks hard-code fake hosts; vendored code isn't ours. Neither is an integration."""
    rules = _rules(tmp_path)
    raw = astgrep_fake.canned(
        astgrep_fake.hit("stripe-endpoint", str(tmp_path / "src/pay.php"), 1),
        astgrep_fake.hit("stripe-endpoint", str(tmp_path / "test/Mocks/Base.php"), 1),
        astgrep_fake.hit("stripe-endpoint", str(tmp_path / "vendor/lib/x.php"), 1),
        astgrep_fake.hit("stripe-endpoint", str(tmp_path / "tests/fixtures/y.php"), 1))
    res = run_scan(str(tmp_path), str(rules), run=lambda a: raw)
    assert [m["path"].split("/")[-1] for m in res["matches"]] == ["pay.php"]


def test_a_fixture_under_a_tests_dir_is_still_scannable_as_its_own_root(tmp_path):
    """Skips are relative to the scanned repo — an engine glob would also match the
    absolute prefix and silently return nothing for such a fixture."""
    root = tmp_path / "tests" / "fixtures" / "repo_a"
    root.mkdir(parents=True)
    raw = astgrep_fake.canned(astgrep_fake.hit("stripe-endpoint", str(root / "Api.php"), 1))
    res = run_scan(str(root), str(_rules(tmp_path)), run=lambda a: raw)
    assert len(res["matches"]) == 1


def test_metadata_from_the_match_is_preferred_over_the_rule_file(tmp_path):
    """The --include-metadata path: when the engine echoes metadata on the match, that is
    used directly and the rule file is NOT re-read (so a match's metadata wins even if the
    ruleset path is unreadable)."""
    import json as _json
    raw = _json.dumps([{"ruleId": "x-endpoint@php", "file": "a.php",
                        "range": {"start": {"line": 0}},
                        "metadata": {"vendor": "FromMatch", "techKey": "api:m", "kind": "endpoint"}}])
    # ruleset path deliberately does not exist — the re-read would yield {}; the match wins
    res = run_scan("/repo", "/no/such/ruleset.yaml", run=lambda a: raw)
    m = res["matches"][0]
    assert m["vendor"] == "FromMatch" and m["techKey"] == "api:m" and m["kind"] == "endpoint"


def test_bundled_ui_libraries_are_skipped_by_filename(tmp_path):
    """A checked-in UI library ships URLs in its OWN source — CKEditor lists the video
    providers it can embed, Fancybox lists media hosts. Reading those as first-party code
    produced findings like "this inventory system calls Dailymotion" across 19 real repos."""
    rules = _rules(tmp_path)
    raw = astgrep_fake.canned(
        astgrep_fake.hit("stripe-endpoint", str(tmp_path / "src/pay.php"), 1),
        astgrep_fake.hit("stripe-endpoint", str(tmp_path / "public/js/ckeditor/ckeditor.js"), 5),
        astgrep_fake.hit("stripe-endpoint", str(tmp_path / "assets/js/summernote.js"), 6384),
        astgrep_fake.hit("stripe-endpoint", str(tmp_path / "assets/plugins/leaflet.bundle.js"), 23),
        astgrep_fake.hit("stripe-endpoint", str(tmp_path / "public/js/app.min.js"), 2))
    res = run_scan(str(tmp_path), str(rules), run=lambda a: raw)
    assert [m["path"].split("/")[-1] for m in res["matches"]] == ["pay.php"]


def test_a_vendored_SDK_is_still_an_integration(tmp_path):
    """THE BUG THIS GUARDS, and the reason this rule never looks at directory names: clients
    vendor Amazon's SDK into application/libraries/amazon-sp-api/. Skipping on `lib`/`libs`/
    `plugins` was measured to drop 449 of 2375 call-sites including 219 Amazon SP-API. A
    vendored SDK is a genuine integration; a vendored widget is not."""
    rules = _rules(tmp_path)
    raw = astgrep_fake.canned(
        astgrep_fake.hit("stripe-endpoint",
                         str(tmp_path / "application/libraries/amazon-sp-api/lib/Configuration.php"), 57),
        astgrep_fake.hit("stripe-endpoint", str(tmp_path / "app/plugins/Payments/Gateway.php"), 12))
    res = run_scan(str(tmp_path), str(rules), run=lambda a: raw)
    assert [m["path"].split("/")[-1] for m in res["matches"]] == ["Configuration.php", "Gateway.php"]


def test_generic_library_names_require_a_word_boundary(tmp_path):
    """THE BUG: a bare substring match against the lowercased filename has no word boundary,
    so a generic library name like `gmaps` or `leaflet` hits legitimate first-party files.
    `GmapsController.php` and `LeafletMapWidget.php` are exactly what a PHP shop names a
    hand-written wrapper for the API it integrates with -- silently suppressing that is the
    exact harm the fail-safe comment above `_VENDORED_FILES` says must never happen. The
    bundled libraries themselves (`gmaps.core.js`, `leaflet.bundle.js`) must still be skipped."""
    rules = _rules(tmp_path)
    raw = astgrep_fake.canned(
        astgrep_fake.hit("stripe-endpoint", str(tmp_path / "app/Http/GmapsController.php"), 10),
        astgrep_fake.hit("stripe-endpoint", str(tmp_path / "app/Widgets/LeafletMapWidget.php"), 20),
        astgrep_fake.hit("stripe-endpoint", str(tmp_path / "public/js/vendor/gmaps.core.js"), 1),
        astgrep_fake.hit("stripe-endpoint", str(tmp_path / "public/js/vendor/leaflet.bundle.js"), 1))
    res = run_scan(str(tmp_path), str(rules), run=lambda a: raw)
    assert [m["path"].split("/")[-1] for m in res["matches"]] == \
        ["GmapsController.php", "LeafletMapWidget.php"]


def test_a_hand_written_file_calling_the_same_host_still_matches(tmp_path):
    """The guard must reject the FILE, never the vendor. A contact page legitimately using a
    map host must still be found even though a bundled library elsewhere mentions it."""
    rules = _rules(tmp_path)
    raw = astgrep_fake.canned(
        astgrep_fake.hit("stripe-endpoint", str(tmp_path / "public/js/custom/pages/contact.js"), 25),
        astgrep_fake.hit("stripe-endpoint", str(tmp_path / "public/js/ckeditor/ckeditor.js"), 5))
    res = run_scan(str(tmp_path), str(rules), run=lambda a: raw)
    assert [m["path"].split("/")[-1] for m in res["matches"]] == ["contact.js"]
