"""Shape memory — structural bucketing over the absorptions log. Deterministic, no vectors."""
from agent.lib import precedents as prec


def _shape(langs=("php",), reasons=("config-driven-url",)):
    return {"languages": {l: 40 for l in langs}, "reasons": list(reasons)}


def test_bucket_key_groups_by_language_and_reasons():
    a = prec.bucket_key(_shape(("php",), ("config-driven-url",)))
    b = prec.bucket_key(_shape(("php",), ("config-driven-url",)))
    c = prec.bucket_key(_shape(("go",), ("config-driven-url",)))
    d = prec.bucket_key(_shape(("php",), ("no-egress-signal",)))
    assert a == b                                    # same shape → same bucket
    assert a != c and a != d                         # different language / reason → different
    # order-independent (sorted)
    assert prec.bucket_key(_shape(("php", "js"))) == prec.bucket_key(_shape(("js", "php")))


def test_find_precedents_matches_the_bucket_newest_first():
    log = [
        {"bucket": prec.bucket_key(_shape()), "repo": "a", "date": "2026-01-01", "idioms": ["x"]},
        {"bucket": prec.bucket_key(_shape()), "repo": "b", "date": "2026-06-01", "idioms": ["y"]},
        {"bucket": prec.bucket_key(_shape(("go",))), "repo": "c", "date": "2026-07-01", "idioms": ["z"]},
    ]
    hits = prec.find_precedents(_shape(), log)
    assert [h["repo"] for h in hits] == ["b", "a"]   # same bucket, newest first; 'c' excluded


def test_record_captures_bucket_idioms_and_delta():
    r = prec.record(_shape(), ["sp-api-host"], repo="sp/x", date="2026-07-28", attributed_delta=35)
    assert r["bucket"] == prec.bucket_key(_shape())
    assert r["idioms"] == ["sp-api-host"] and r["repo"] == "sp/x" and r["attributedDelta"] == 35


def test_append_dedupes_by_repo_and_idioms(tmp_path):
    p = str(tmp_path / "absorptions.yaml")
    rec = prec.record(_shape(), ["x"], repo="a", date="2026-07-28")
    prec.append_absorption(p, rec)
    prec.append_absorption(p, rec)                   # same repo+idioms → not duplicated
    assert len(prec.load_absorptions(p)) == 1
    prec.append_absorption(p, prec.record(_shape(), ["y"], repo="b", date="2026-07-27"))
    log = prec.load_absorptions(p)
    assert len(log) == 2 and [e["repo"] for e in log] == ["b", "a"]   # sorted by date


def test_no_precedents_on_an_empty_log():
    assert prec.find_precedents(_shape(), []) == []
