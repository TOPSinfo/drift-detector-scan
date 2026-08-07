import json
import subprocess
from pathlib import Path
from agent.inventory_scan import scan_folder


def _git_init(d, files):
    d.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        (d / rel).write_text(text)
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    subprocess.run(["git", "add", "-A"], cwd=d, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
                    "--allow-empty", "-q", "-am", "c"], cwd=d, check=True)


def _canned(sdks):
    # opengrep finds no endpoints; the diff comes from manifest (sdk) changes
    return json.dumps([])


def test_scan_returns_diff_vs_prior_ir(tmp_path):
    root = tmp_path / "repos"
    web = root / "web"
    _git_init(web, {"package.json": '{"dependencies": {"axios": "^1.6"}}'})
    state = tmp_path / "state"

    run1 = scan_folder(str(root), str(state), "2026-07-14", engine="semgrep",
                       run=lambda a: _canned(None))
    assert run1["diff"]["changes"] == [] and run1["diff"]["reposAdded"] == ["web"]  # first run: baseline

    # bump axios + a NEW commit (so head_sha changes -> cache miss -> re-scan)
    (web / "package.json").write_text('{"dependencies": {"axios": "^1.7"}}')
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
                    "-q", "-am", "bump"], cwd=web, check=True)

    run2 = scan_folder(str(root), str(state), "2026-07-21", engine="semgrep",
                       run=lambda a: _canned(None))
    ch = run2["diff"]["changes"][0]
    assert ch["repo"] == "web"
    assert {"eco": "npm", "pkg": "axios", "from": "^1.6", "to": "^1.7"} in ch["sdkVersionChanges"]


def test_diff_of_identical_inventories_is_empty():
    from agent.lib.inventory_diff import diff_inventories
    doc = {"repos": [{"path": "web", "endpoints": [], "sdks": [], "runtimes": {}}]}
    d = diff_inventories(doc, doc)
    assert d["changes"] == [] and d["reposAdded"] == [] and d["reposRemoved"] == []
