import json
import subprocess
from pathlib import Path
from agent.inventory_scan import scan_folder
from tests import gitleaks_fake


def _no_secrets(args):
    return gitleaks_fake.EMPTY


def _git_init(d, files):
    d.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
                    "--allow-empty", "-q", "-am", "init"], cwd=d, check=True)


def _canned_stripe(path):
    # the engine emits generic URL-literal matches; classification happens in Python
    from tests import astgrep_fake
    return astgrep_fake.canned(astgrep_fake.hit("url-literal", path, 1))


def test_scan_folder_end_to_end(tmp_path):
    root = tmp_path / "repos"
    _git_init(root / "web", {"composer.json": '{"require": {"php": "^8.2"}}',
                             "pay.php": '"https://api.stripe.com/v1/x";\n'})
    state = tmp_path / "state"
    out = scan_folder(str(root), str(state), "2026-07-14",
                      engine="semgrep", run=lambda args: _canned_stripe("pay.php"),
                      secrets_run=_no_secrets)
    doc = out["doc"]
    assert doc["scope"]["reposScanned"] == 1
    repo = doc["repos"][0]
    assert repo["path"] == "web" and repo["runtimes"]["php"]["range"] == "^8.2"
    assert repo["endpoints"][0]["techKey"] == "api:stripe"
    assert doc["unique_apis"] == ["Stripe"]
    assert (state / "inventory.json").exists()                 # IR persisted
    assert "Stripe" in out["doc"]["unique_apis"]


def test_scan_folder_incremental_cache_reused(tmp_path):
    root = tmp_path / "repos"
    _git_init(root / "web", {"composer.json": '{"require": {"php": "^8.2"}}'})
    state = tmp_path / "state"
    calls = {"n": 0}

    def counting_run(args):
        calls["n"] += 1
        return json.dumps([])

    scan_folder(str(root), str(state), "2026-07-14", engine="semgrep", run=counting_run,
               secrets_run=_no_secrets)
    assert calls["n"] == 1                                      # scanned once
    scan_folder(str(root), str(state), "2026-07-21", engine="semgrep", run=counting_run,
               secrets_run=_no_secrets)
    assert calls["n"] == 1                                      # unchanged sha -> cache hit, engine NOT re-run


def _empty_run(args):
    return json.dumps([])


def test_scan_folder_discovers_nested_repos(tmp_path):
    root = tmp_path / "repos"
    _git_init(root / "group" / "deep" / "web", {"composer.json": '{"require": {"php": "^8.2"}}'})
    out = scan_folder(str(root), str(tmp_path / "state"), "2026-07-14",
                      engine="semgrep", run=_empty_run, secrets_run=_no_secrets)
    assert [r["path"] for r in out["doc"]["repos"]] == ["group/deep/web"]


def test_scan_folder_progress_callback(tmp_path):
    root = tmp_path / "repos"
    _git_init(root / "web", {"composer.json": '{"require": {"php": "^8.2"}}'})
    msgs = []
    scan_folder(str(root), str(tmp_path / "state"), "2026-07-14",
                engine="semgrep", run=_empty_run, progress=msgs.append,
                secrets_run=_no_secrets)
    assert any("resolving sources" in m for m in msgs)
    assert any("1 project(s) resolved" in m for m in msgs)
    assert any("web" in m and "scan:" in m for m in msgs)       # per-repo phase line
    assert any("aggregating" in m for m in msgs)


def test_scan_folder_multiple_roots(tmp_path):
    r1, r2 = tmp_path / "a", tmp_path / "b"
    _git_init(r1 / "web", {"composer.json": '{"require": {"php": "^8.2"}}'})
    _git_init(r2 / "api", {"composer.json": '{"require": {"php": "^8.1"}}'})
    out = scan_folder([str(r1), str(r2)], str(tmp_path / "state"), "2026-07-14",
                      engine="semgrep", run=_empty_run, secrets_run=_no_secrets)
    assert sorted(r["path"] for r in out["doc"]["repos"]) == ["api", "web"]
    assert out["doc"]["scope"]["rootCount"] == 2


from agent import cli


def _stub_secrets_scan(monkeypatch):
    """CLI commands never expose a way to inject `secrets_run`, so — like the CLI tests below
    already stub the ast-grep engine — stub gitleaks at the module-attribute level instead of
    the real binary this sandbox doesn't have."""
    import agent.lib.repo_scan as repo_scan_mod
    monkeypatch.setattr(repo_scan_mod, "run_secrets_scan",
                        lambda repo_path, **kw: {"matches": [], "errors": []})


def test_cli_inventory_scan_writes_json(tmp_path, monkeypatch):
    root = tmp_path / "repos"
    _git_init(root / "web", {"composer.json": '{"require": {"php": "^8.2"}}',
                             "pay.php": '"https://api.stripe.com/v1/x";\n'})
    # stub the engine so no real binary is needed
    import agent.inventory_scan as inv
    monkeypatch.setattr(inv.scan_util, "resolve_engine", lambda engine="ast-grep": "ast-grep")
    monkeypatch.setattr(inv.engine_mod, "_default_run", lambda args: _canned_stripe("pay.php"), raising=False)
    _stub_secrets_scan(monkeypatch)

    out_json = tmp_path / "inv.json"
    rc = cli.main(["inventory-scan", "--root", str(root), "--state", str(tmp_path / "state"),
                   "--out-json", str(out_json), "--now", "2026-07-14"])
    assert rc == 0
    doc = json.loads(out_json.read_text())
    assert doc["repos"][0]["path"] == "web" and doc["unique_apis"] == ["Stripe"]


def _stub_secrets_scan_failing(monkeypatch):
    """Like `_stub_secrets_scan` but forces every repo's secrets signal to fail, exactly as
    a missing/timed-out gitleaks does — so this test's pass/fail does not depend on whether
    gitleaks happens to be installed on the machine running the suite."""
    import agent.lib.repo_scan as repo_scan_mod
    monkeypatch.setattr(repo_scan_mod, "run_secrets_scan",
                        lambda repo_path, **kw: {"matches": [],
                                                  "errors": [{"message": "gitleaks missing",
                                                             "path": repo_path}]})


def test_cli_inventory_scan_summary_reports_secrets_errors(tmp_path, monkeypatch, capsys):
    """The `inventory-scan` one-line summary already counted `reposErrored` but said
    nothing about `coverage.secretsErrors` — a repo whose secrets signal failed printed a
    summary line indistinguishable from one where it succeeded and found nothing."""
    root = tmp_path / "repos"
    _git_init(root / "web", {"composer.json": '{"require": {"php": "^8.2"}}'})
    import agent.inventory_scan as inv
    monkeypatch.setattr(inv.scan_util, "resolve_engine", lambda engine="ast-grep": "ast-grep")
    monkeypatch.setattr(inv.engine_mod, "_default_run", _empty_run, raising=False)
    _stub_secrets_scan_failing(monkeypatch)

    rc = cli.main(["inventory-scan", "--root", str(root), "--state", str(tmp_path / "state"),
                   "--out-json", str(tmp_path / "i.json"), "--now", "2026-07-14"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "1 secrets error" in out


def test_cli_inventory_scan_summary_silent_when_no_secrets_errors(tmp_path, monkeypatch):
    root = tmp_path / "repos"
    _git_init(root / "web", {"composer.json": '{"require": {"php": "^8.2"}}'})
    import agent.inventory_scan as inv
    monkeypatch.setattr(inv.scan_util, "resolve_engine", lambda engine="ast-grep": "ast-grep")
    monkeypatch.setattr(inv.engine_mod, "_default_run", _empty_run, raising=False)
    _stub_secrets_scan(monkeypatch)

    rc = cli.main(["inventory-scan", "--root", str(root), "--state", str(tmp_path / "state"),
                   "--out-json", str(tmp_path / "i.json"), "--now", "2026-07-14"])
    assert rc == 0


def test_cli_inventory_scan_repeatable_root(tmp_path, monkeypatch):
    r1, r2 = tmp_path / "a", tmp_path / "b"
    _git_init(r1 / "web", {"composer.json": '{"require": {"php": "^8.2"}}'})
    _git_init(r2 / "api", {"composer.json": '{"require": {"php": "^8.1"}}'})
    import agent.inventory_scan as inv
    monkeypatch.setattr(inv.scan_util, "resolve_engine", lambda engine="ast-grep": "ast-grep")
    monkeypatch.setattr(inv.engine_mod, "_default_run", _empty_run, raising=False)
    _stub_secrets_scan(monkeypatch)

    out_json = tmp_path / "inv.json"
    rc = cli.main(["inventory-scan", "--root", str(r1), "--root", str(r2),
                   "--state", str(tmp_path / "state"), "--out-json", str(out_json),
                   "--now", "2026-07-14"])
    assert rc == 0
    doc = json.loads(out_json.read_text())
    assert sorted(r["path"] for r in doc["repos"]) == ["api", "web"]


def test_cli_inventory_scan_progress_to_stderr(tmp_path, monkeypatch, capsys):
    root = tmp_path / "repos"
    _git_init(root / "web", {"composer.json": '{"require": {"php": "^8.2"}}'})
    import agent.inventory_scan as inv
    monkeypatch.setattr(inv.scan_util, "resolve_engine", lambda engine="ast-grep": "ast-grep")
    monkeypatch.setattr(inv.engine_mod, "_default_run", _empty_run, raising=False)
    rc = cli.main(["inventory-scan", "--root", str(root), "--progress",
                   "--state", str(tmp_path / "state"), "--out-json", str(tmp_path / "i.json"),
                   "--now", "2026-07-14"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "deterministic static-analysis" in captured.err     # expectation-setting banner
    assert "⚙" in captured.err                                 # per-phase log on stderr
    assert "✓" in captured.out                                 # timed summary on stdout


def test_coverage_grade_thresholds():
    from agent.inventory_scan import _coverage_grade

    assert _coverage_grade(attributed=0, unattributed_paths=262, sinks=0) == "LOW"
    assert _coverage_grade(attributed=5, unattributed_paths=3, sinks=0) == "PARTIAL"
    assert _coverage_grade(attributed=0, unattributed_paths=0, sinks=2) == "PARTIAL"   # sinks only
    assert _coverage_grade(attributed=5, unattributed_paths=0, sinks=0) == "HIGH"
    assert _coverage_grade(attributed=0, unattributed_paths=0, sinks=0) == "HIGH"      # nothing to miss


def test_rollup_builds_residue_and_grade():
    from agent.inventory_scan import _rollup_coverage

    repos = [
        {"path": "amazonspapi",
         "endpoints": [{"vendor": "Amazon SP-API"}],
         "residue": {"pathLiterals": [{"sample": "/orders/2026-01-01/orders", "loc": "OrdersApi.php:44"}],
                     "sinks": [{"kind": "egress", "loc": "Client.php:7"}]}},
        {"path": "clean", "endpoints": [{"vendor": "Stripe"}],
         "residue": {"pathLiterals": [], "sinks": []}},
    ]
    coverage = {"reposScanned": 2, "reposErrored": [], "manifestsUnparsed": []}
    _rollup_coverage(coverage, repos, discovered_count=2)
    res = coverage["residue"]
    assert len(res["pathLiterals"]) == 1 and len(res["sinks"]) == 1
    by = {r["repo"]: r for r in res["byRepo"]}
    assert by["amazonspapi"]["grade"] == "PARTIAL"      # has 1 attributed endpoint + residue
    assert by["amazonspapi"]["unattributedPaths"] == 1 and by["amazonspapi"]["unresolvedSinks"] == 1
    assert by["clean"]["grade"] == "HIGH"


def test_coverage_sdkmediated_lists_repos_with_sdks():
    from agent.inventory_scan import _rollup_coverage
    repos = [
        {"path": "a", "sdks": [{"eco": "composer", "pkg": "dts/ebay-sdk-php"}],
         "endpoints": [{"classified": True}, {"classified": False}]},
        {"path": "b", "sdks": [], "endpoints": [{"classified": True}]},          # no SDKs -> absent
        {"path": "c", "sdks": [{"eco": "npm", "pkg": "x"}, {"eco": "npm", "pkg": "y"}],
         "endpoints": []},
    ]
    # _rollup_coverage MUTATES the coverage dict in place and returns None. The dict must be
    # pre-seeded with the keys it reads (reposScanned/reposErrored), matching how scan_folder seeds it.
    coverage = {"reposScanned": 3, "reposErrored": [], "manifestsUnparsed": []}
    _rollup_coverage(coverage, repos, discovered_count=3)
    sm = coverage["sdkMediated"]
    assert {m["repo"] for m in sm} == {"a", "c"}                       # b (0 SDKs) absent
    a = next(m for m in sm if m["repo"] == "a")
    assert a["sdkCount"] == 1 and a["endpointCount"] == 1              # 1 classified of 2 endpoints
    c = next(m for m in sm if m["repo"] == "c")
    assert c["sdkCount"] == 2 and c["endpointCount"] == 0
    assert "privateSources" in coverage                               # existing key unchanged


def test_private_source_that_is_a_fleet_member_is_marked_covered_not_unreachable():
    """A repo's private composer dep that is ITSELF a scanned fleet repo is NOT a blind spot —
    it's read as its own repo. The dashboard listed marketplacehub's amazonspapi/ebayapi deps under
    'couldn't crawl' even though the fleet scans them; the rollup must reconcile against the
    scanned set (by git identity) so covered deps drop out of `repositories` into `covered`."""
    from agent.inventory_scan import _rollup_coverage
    repos = [
        {"path": "marketplacehub", "remote_url": "https://git.x/grp/marketplacehub.git",
         "endpoints": [], "residue": {"pathLiterals": [], "sinks": []},
         "privateSources": {"packages": [], "repositories": [
             "https://git.x/example-org/amazonspapi.git",     # IN fleet (scanned below)
             "https://git.x/akshit/catchapi.git"]}},      # NOT in fleet → still a blind spot
        {"path": "amazonspapi", "remote_url": "https://git.x/example-org/amazonspapi.git",
         "endpoints": [], "residue": {"pathLiterals": [], "sinks": []}},
    ]
    coverage = {"reposScanned": 2, "reposErrored": [], "manifestsUnparsed": []}
    _rollup_coverage(coverage, repos, discovered_count=2)
    ps = next(p for p in coverage["privateSources"] if p["repo"] == "marketplacehub")
    assert ps["repositories"] == ["https://git.x/akshit/catchapi.git"]   # only the blind one
    assert ps["covered"] == ["https://git.x/example-org/amazonspapi.git"]     # the fleet member


def test_scan_folder_error_line_is_adjacent_to_its_repo_at_jobs_one(tmp_path):
    """At --jobs 1 an error must be logged NEXT TO the repo it belongs to.

    Making the fold (rather than the worker) emit the ERROR line kept error output
    deterministic under --jobs > 1, but it also batched every error to the END of the log at
    --jobs 1 — so on a 25-minute serial scan an error no longer sat beside the repo that
    produced it, and the branch's "jobs=1 is today's code exactly" claim was false.
    `test_scan_folder_progress_callback` uses any(), which is why nothing caught it.
    """
    root = tmp_path / "repos"
    for name in ("aaa", "bbb", "ccc"):
        _git_init(root / name, {"composer.json": '{"require": {"php": "^8.2"}}'})

    def exploding_run(args):
        if args[-1].endswith("bbb"):
            raise RuntimeError("engine exploded")
        return json.dumps([])

    msgs = []
    out = scan_folder(str(root), str(tmp_path / "state"), "2026-08-25",
                      engine="semgrep", run=exploding_run, progress=msgs.append, jobs=1,
                      secrets_run=_no_secrets)

    err_idx = [i for i, m in enumerate(msgs) if "⚠ error" in m]
    assert len(err_idx) == 1, msgs
    own_idx = [i for i, m in enumerate(msgs) if "bbb" in m and "scan:" in m]
    assert len(own_idx) == 1, msgs
    assert err_idx[0] == own_idx[0] + 1, (
        "the error line must follow bbb's own progress line immediately, not trail every "
        f"other repo's: {msgs}")
    # ...and it must still be a `ccc` line that comes after, i.e. the error did not move to the end
    assert any("ccc" in m for m in msgs[err_idx[0] + 1:]), msgs
    # the fold still records it, in input order, exactly once
    assert [e["repo"] for e in out["doc"]["coverage"]["reposErrored"]] == ["bbb"]


def test_a_gitleaks_failure_is_isolated_to_the_secrets_signal_and_surfaced_in_coverage(tmp_path):
    """Two halves of the same seam bug: a broken gitleaks must (a) not cost the repo its
    otherwise-successful ast-grep/manifest results, and (b) not vanish. `repo_scan` has always
    computed `note["secretsErrors"]`; nothing carried it into `coverage`, so a run where the
    secrets engine failed on every repo reported zero secrets and said nothing about it — a
    false "clean" for the whole fleet."""
    root = tmp_path / "repos"
    _git_init(root / "web", {"composer.json": '{"require": {"php": "^8.2"}}',
                             "pay.php": '"https://api.stripe.com/v1/x";\n'})

    def broken_gitleaks(args):
        raise FileNotFoundError(2, "No such file or directory", "gitleaks")

    out = scan_folder(str(root), str(tmp_path / "state"), "2026-07-14",
                      engine="semgrep", run=lambda a: _canned_stripe("pay.php"),
                      secrets_run=broken_gitleaks)
    cov = out["doc"]["coverage"]
    assert cov["reposErrored"] == []                                  # (a) isolated
    assert out["doc"]["repos"][0]["endpoints"][0]["techKey"] == "api:stripe"
    assert [e["repo"] for e in cov["secretsErrors"]] == ["web"]       # (b) surfaced
    assert "gitleaks" in cov["secretsErrors"][0]["message"]


def test_a_clean_secrets_scan_leaves_the_coverage_error_list_empty(tmp_path):
    root = tmp_path / "repos"
    _git_init(root / "web", {"composer.json": '{"require": {"php": "^8.2"}}'})
    out = scan_folder(str(root), str(tmp_path / "state"), "2026-07-14",
                      engine="semgrep", run=_empty_run, secrets_run=_no_secrets)
    assert out["doc"]["coverage"]["secretsErrors"] == []


def test_a_repo_whose_secrets_scan_failed_still_gets_cached(tmp_path):
    """A secrets-scan failure must no longer disable this repo's ENTIRE cache. The old
    mechanism (skip `save_repo_cache` whenever `note["secretsErrors"]` was non-empty) meant
    that on any machine without gitleaks, EVERY repo's cache write was skipped, EVERY run —
    silently disabling the whole per-repo incremental cache fleet-wide. The fix carries the
    error state WITH the record (`repo_scan.scan_repo` now sets
    `record["secretsErrors"]`) instead of refusing to write it, so caching is unconditional
    and safe again."""
    root = tmp_path / "repos"
    _git_init(root / "web", {"composer.json": '{"require": {"php": "^8.2"}}'})
    state = tmp_path / "state"

    def broken_gitleaks(args):
        raise FileNotFoundError(2, "No such file or directory", "gitleaks")

    scan_folder(str(root), str(state), "2026-07-14",
               engine="semgrep", run=_empty_run, secrets_run=broken_gitleaks)

    cached_files = list(state.glob("repos_v*/*.json"))
    assert cached_files, ("a secrets-scan failure must still write the per-repo cache — "
                          "only the old, unsafe mechanism skipped this")
    saved = json.loads(cached_files[0].read_text())
    assert saved.get("secretsErrors"), (
        "the cached record must carry its own secretsErrors state, not omit it")


def test_cache_hit_replays_the_remembered_secrets_failure(tmp_path):
    """The important behavioral proof: a cache HIT on a repo whose secrets scan previously
    failed must (a) actually be a cache hit (the ast-grep engine is NOT re-invoked) and
    (b) still report the remembered failure — never silently reset to a false 'clean'
    because a cache hit used to hardcode `secretsErrors: []` regardless of history."""
    root = tmp_path / "repos"
    _git_init(root / "web", {"composer.json": '{"require": {"php": "^8.2"}}'})
    state = tmp_path / "state"
    calls = {"n": 0}

    def counting_run(args):
        calls["n"] += 1
        return json.dumps([])

    def broken_gitleaks(args):
        raise FileNotFoundError(2, "No such file or directory", "gitleaks")

    out1 = scan_folder(str(root), str(state), "2026-07-14",
                       engine="semgrep", run=counting_run, secrets_run=broken_gitleaks)
    assert [e["repo"] for e in out1["doc"]["coverage"]["secretsErrors"]] == ["web"]
    assert calls["n"] == 1

    # second scan of the SAME unchanged HEAD: this must be a genuine cache HIT (the engine
    # must not re-run) — secrets_run is deliberately still `broken_gitleaks` so a real
    # re-scan would ALSO report the failure, which would make this test pass for the wrong
    # reason; `counting_run` not incrementing is what proves the record was served from cache.
    out2 = scan_folder(str(root), str(state), "2026-07-21",
                       engine="semgrep", run=counting_run, secrets_run=broken_gitleaks)
    assert calls["n"] == 1, "a cache hit must not re-invoke the scan engine"
    assert [e["repo"] for e in out2["doc"]["coverage"]["secretsErrors"]] == ["web"], (
        "the cached record must carry its secretsErrors state so a cache hit replays the "
        "SAME failure, rather than resetting it to a false 'clean'")


def test_a_clean_secrets_scan_still_caches_and_replays_correctly(tmp_path):
    """No regression on the happy path: a repo whose secrets scan SUCCEEDED must still be
    cached (as before) and a later cache hit must still replay `secretsErrors: []`."""
    root = tmp_path / "repos"
    _git_init(root / "web", {"composer.json": '{"require": {"php": "^8.2"}}'})
    state = tmp_path / "state"
    calls = {"n": 0}

    def counting_run(args):
        calls["n"] += 1
        return json.dumps([])

    out1 = scan_folder(str(root), str(state), "2026-07-14",
                       engine="semgrep", run=counting_run, secrets_run=_no_secrets)
    assert out1["doc"]["coverage"]["secretsErrors"] == []
    assert calls["n"] == 1

    out2 = scan_folder(str(root), str(state), "2026-07-21",
                       engine="semgrep", run=counting_run, secrets_run=_no_secrets)
    assert calls["n"] == 1, "unchanged HEAD must still be served from cache"
    assert out2["doc"]["coverage"]["secretsErrors"] == []
