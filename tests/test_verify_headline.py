"""The verify headline must not let a failed clone read as progress."""
import json

from agent import cli


def _state(tmp_path, unscannable):
    payload = {"generated": "2026-09-02", "counts": {
        "sunsets": 10, "eol": 2, "unaudited": 14, "blocked": 5,
        "fixes": 0, "reposScanned": 52, "reposAffected": 0},
        "actions": [], "shapes": [], "endpoints": [], "catalog": [],
        "rootsUnscannable": unscannable}
    (tmp_path / "drift.json").write_text(json.dumps(payload))
    return payload


def test_an_unreadable_repo_is_named_in_the_headline(tmp_path, capsys, monkeypatch):
    """`unaudited` fell 24 -> 14 on 2026-09-02 and TEN of those were one repo failing to clone,
    not work anyone did. The counts cover less of the fleet, and the headline said only that
    things had improved. A reader comparing weeks would have been wrong."""
    p = _state(tmp_path, [{"root": "https://g/example-org/acme-crm", "reason": "reset"}])
    monkeypatch.setattr(cli, "_load_payload", lambda *a, **k: p, raising=False)
    line = cli._verify_headline(p)
    assert "1 repo(s) could not be read" in line
    assert "cover less" in line.lower()


def test_a_complete_scan_says_nothing_extra(tmp_path):
    p = _state(tmp_path, [])
    line = cli._verify_headline(p)
    assert "could not be read" not in line
    assert "14 unchecked-vendor(s)" in line and "5 blocked on access" in line
