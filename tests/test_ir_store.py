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
