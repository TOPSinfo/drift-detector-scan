import json
import subprocess
from pathlib import Path
from agent.inventory_scan import scan_folder


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
                      engine="semgrep", run=lambda args: _canned_stripe("pay.php"))
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

    scan_folder(str(root), str(state), "2026-07-14", engine="semgrep", run=counting_run)
    assert calls["n"] == 1                                      # scanned once
    scan_folder(str(root), str(state), "2026-07-21", engine="semgrep", run=counting_run)
    assert calls["n"] == 1                                      # unchanged sha -> cache hit, engine NOT re-run


def _empty_run(args):
    return json.dumps([])


def test_scan_folder_discovers_nested_repos(tmp_path):
    root = tmp_path / "repos"
    _git_init(root / "group" / "deep" / "web", {"composer.json": '{"require": {"php": "^8.2"}}'})
    out = scan_folder(str(root), str(tmp_path / "state"), "2026-07-14",
                      engine="semgrep", run=_empty_run)
    assert [r["path"] for r in out["doc"]["repos"]] == ["group/deep/web"]


def test_scan_folder_progress_callback(tmp_path):
    root = tmp_path / "repos"
    _git_init(root / "web", {"composer.json": '{"require": {"php": "^8.2"}}'})
    msgs = []
    scan_folder(str(root), str(tmp_path / "state"), "2026-07-14",
                engine="semgrep", run=_empty_run, progress=msgs.append)
    assert any("resolving sources" in m for m in msgs)
    assert any("1 project(s) resolved" in m for m in msgs)
    assert any("web" in m and "scan:" in m for m in msgs)       # per-repo phase line
    assert any("aggregating" in m for m in msgs)


def test_scan_folder_multiple_roots(tmp_path):
    r1, r2 = tmp_path / "a", tmp_path / "b"
    _git_init(r1 / "web", {"composer.json": '{"require": {"php": "^8.2"}}'})
    _git_init(r2 / "api", {"composer.json": '{"require": {"php": "^8.1"}}'})
    out = scan_folder([str(r1), str(r2)], str(tmp_path / "state"), "2026-07-14",
                      engine="semgrep", run=_empty_run)
    assert sorted(r["path"] for r in out["doc"]["repos"]) == ["api", "web"]
    assert out["doc"]["scope"]["rootCount"] == 2


from agent import cli


def test_cli_inventory_scan_writes_json(tmp_path, monkeypatch):
    root = tmp_path / "repos"
    _git_init(root / "web", {"composer.json": '{"require": {"php": "^8.2"}}',
                             "pay.php": '"https://api.stripe.com/v1/x";\n'})
    # stub the engine so no real binary is needed
    import agent.inventory_scan as inv
    monkeypatch.setattr(inv.scan_util, "resolve_engine", lambda engine="ast-grep": "ast-grep")
    monkeypatch.setattr(inv.engine_mod, "_default_run", lambda args: _canned_stripe("pay.php"), raising=False)

    out_json = tmp_path / "inv.json"
    rc = cli.main(["inventory-scan", "--root", str(root), "--state", str(tmp_path / "state"),
                   "--out-json", str(out_json), "--now", "2026-07-14"])
    assert rc == 0
    doc = json.loads(out_json.read_text())
    assert doc["repos"][0]["path"] == "web" and doc["unique_apis"] == ["Stripe"]


def test_cli_inventory_scan_repeatable_root(tmp_path, monkeypatch):
    r1, r2 = tmp_path / "a", tmp_path / "b"
    _git_init(r1 / "web", {"composer.json": '{"require": {"php": "^8.2"}}'})
    _git_init(r2 / "api", {"composer.json": '{"require": {"php": "^8.1"}}'})
    import agent.inventory_scan as inv
    monkeypatch.setattr(inv.scan_util, "resolve_engine", lambda engine="ast-grep": "ast-grep")
    monkeypatch.setattr(inv.engine_mod, "_default_run", _empty_run, raising=False)

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
