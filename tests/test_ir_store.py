import json
from pathlib import Path

from agent.lib import ir_store


def test_ir_round_trip_and_missing(tmp_path):
    assert ir_store.load_ir(str(tmp_path)) is None
    doc = {"repos": [{"path": "a/b"}], "unique_apis": ["Stripe"]}
    ir_store.save_ir(str(tmp_path), doc)
    assert ir_store.load_ir(str(tmp_path)) == doc


def test_repo_cache_keyed_by_sha(tmp_path):
    rec = {"path": "acme/web", "head_sha": "abc", "sdks": []}
    assert ir_store.load_repo_cache(str(tmp_path), "acme/web", "abc") is None   # first run
    ir_store.save_repo_cache(str(tmp_path), "acme/web", "abc", rec)
    assert ir_store.load_repo_cache(str(tmp_path), "acme/web", "abc") == rec     # unchanged sha -> hit
    assert ir_store.load_repo_cache(str(tmp_path), "acme/web", "def") is None    # changed sha -> miss (re-scan)


def test_repo_cache_misses_when_ruleset_signature_changes(tmp_path):
    # REGRESSION: the cache key folds in the RULESET signature (vendors + idioms). Without it, a
    # repo scanned once served its stale pre-idiom record forever — so absorbing a local idiom and
    # re-running "to confirm the residue shrank" checked a cache the new idiom never touched, and
    # the shape looked like it did nothing. Same path + sha, different ruleset -> MUST miss.
    rec = {"path": "acme/web", "endpoints": []}
    ir_store.save_repo_cache(str(tmp_path), "acme/web", "abc", rec, rules_sig="rulesA")
    assert ir_store.load_repo_cache(str(tmp_path), "acme/web", "abc", rules_sig="rulesA") == rec
    # a changed ruleset (a new/absorbed idiom) must re-scan, not serve the stale baseline record
    assert ir_store.load_repo_cache(str(tmp_path), "acme/web", "abc", rules_sig="rulesB") is None


def test_a_pre_secrets_cache_schema_entry_is_invalidated_not_served_as_clean(tmp_path):
    """REGRESSION: for commits 133de9c..4db48b4 of this branch, _CACHE_SCHEMA was 10 and the
    cache write was UNCONDITIONAL even when a repo's secrets scan had FAILED — so a v10 cache
    entry can exist with `secrets: []` and no `secretsErrors` key at all, indistinguishable
    from a repo that was actually checked and found clean. Loading such an entry by its OLD
    schema-10 path must still work (proving the poisoned shape is real, not hypothetical); the
    live schema must have moved past 10 so a repo actually re-scans instead of being served
    that stale false-clean record."""
    poisoned = {"path": "acme/web", "secrets": []}          # no "secretsErrors" key at all
    old_schema_dir = Path(str(tmp_path)) / "repos_v10"
    old_schema_dir.mkdir(parents=True)
    # write directly at the v10 path this record would have used back then
    import hashlib
    file_key = hashlib.sha256("acme/web".encode("utf-8")).hexdigest()[:16]
    (old_schema_dir / f"{file_key}@abc.json").write_text(json.dumps(poisoned))

    assert ir_store._CACHE_SCHEMA > 10, (
        "a v10 cache entry could carry a secrets scan FAILURE with no secretsErrors key — "
        "the schema must have moved past 10 so it is never read back as a clean record")
    # the live loader, at the CURRENT schema, must miss (re-scan), never load the poisoned file
    assert ir_store.load_repo_cache(str(tmp_path), "acme/web", "abc") is None


def test_repo_path_with_slashes_is_file_safe(tmp_path):
    rec = {"path": "group/sub/proj"}
    ir_store.save_repo_cache(str(tmp_path), "group/sub/proj", "s1", rec)
    assert ir_store.load_repo_cache(str(tmp_path), "group/sub/proj", "s1") == rec


def test_colliding_paths_do_not_share_cache(tmp_path):
    # "group_a/proj" and "group/a_proj" would collide under a naive "/"->"_" scheme
    ir_store.save_repo_cache(str(tmp_path), "group_a/proj", "s", {"which": "A"})
    ir_store.save_repo_cache(str(tmp_path), "group/a_proj", "s", {"which": "B"})
    assert ir_store.load_repo_cache(str(tmp_path), "group_a/proj", "s") == {"which": "A"}
    assert ir_store.load_repo_cache(str(tmp_path), "group/a_proj", "s") == {"which": "B"}
