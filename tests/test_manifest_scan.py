from pathlib import Path

from agent.lib.manifest_scan import extract_manifest_records


def _w(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_extracts_from_manifests_and_skips_vendor_dirs(tmp_path):
    _w(tmp_path, "composer.json", '{"require": {"php": "^8.2", "laravel/framework": "^12.0"}}')
    _w(tmp_path, "package.json", '{"dependencies": {"axios": "^1.6"}}')
    _w(tmp_path, "vendor/pkg/composer.json", '{"require": {"evil/dep": "1.0"}}')   # MUST be skipped
    _w(tmp_path, "src/app.php", 'not a manifest')
    records, unparsed = extract_manifest_records(str(tmp_path), "acme/web")
    names = {r.name for r in records}
    assert "php" in names and "laravel/framework" in names and "axios" in names
    assert "evil/dep" not in names                              # vendor/ skipped
    assert unparsed == []
    assert all(r.repo == "acme/web" for r in records)
    php = next(r for r in records if r.name == "php")
    assert php.manifest_path == "composer.json"                 # repo-relative path


def test_invalid_manifest_is_unparsed_not_crash(tmp_path):
    _w(tmp_path, "composer.json", '{invalid json')
    _w(tmp_path, "package.json", '{"dependencies": {"axios": "^1.6"}}')
    records, unparsed = extract_manifest_records(str(tmp_path), "r")
    assert {r.name for r in records} == {"axios"}               # good one still parsed
    assert len(unparsed) == 1 and unparsed[0]["path"] == "composer.json"
