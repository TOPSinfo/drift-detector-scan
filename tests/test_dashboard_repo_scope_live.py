"""Live-interpreter regression test for the dashboard's repo-scope card counters.

Mirrors tests/test_engine_live.py's / test_secrets_scan_gitleaks_live.py's pattern for a
guard this repo's own STATIC-TEXT checks on dashboard.app.js (test_dashboard_render.py's
test_repo_scope_and_tile_filters_are_wired_in_all_modes) cannot provide: whether selecting
a repo actually CHANGES the tile numbers is a property of the running JS, not of which
strings appear in the file. A 2026-09-07 bug report caught exactly this gap: matchesRepo
already scoped the row lists (actions/endpoints/private), but the CARD numbers
(allTileGroups/planeDefs/supplyFixes) read the raw, server-computed FLEET-WIDE `counts`
blob directly — selecting root/python-Latest-Drop in a real 57-repo fleet dashboard left
Critical/Fixes/EOL/Secrets showing the fleet totals (490/545/36/474) unchanged, while the
findings table below correctly narrowed to that repo's own rows.

Skipped when no `node` binary is installed. Runs the REAL dashboard.app.js (not a
reimplementation) inside Node's `vm` module, with `document`/`Vue`/`location` stubbed just
enough to capture the Vue options object without an actual DOM/render — then calls its
`computed` functions directly, the same way Vue itself would.
"""
import json
import shutil
import subprocess

import pytest

from agent.lib import dashboard_render as dr

_NODE = shutil.which("node")

_HARNESS = r"""
const vm = require('vm');
const driftData = JSON.parse(process.argv[1]);
const appJsSrc = process.argv[2];
const scope = process.argv[3];

let captured = null;
const sandbox = {
  document: { getElementById: (id) => id === "drift-data" ? { textContent: JSON.stringify(driftData) } : null },
  location: { search: "" },
  localStorage: { getItem: () => null, setItem: () => {} },
  navigator: {},
  window: { innerWidth: 1200 },
  URLSearchParams: URLSearchParams,
  console: console,
  Vue: { createApp: (opts) => { captured = opts; return { mount: () => {} }; }, markRaw: (x) => x },
};
sandbox.window.location = sandbox.location;
vm.runInContext(appJsSrc, vm.createContext(sandbox));

const data = captured.data();
const self = Object.assign({}, data);
self.scope = scope;
Object.keys(captured.methods || {}).forEach((k) => { self[k] = captured.methods[k].bind(self); });
Object.keys(captured.computed || {}).forEach((k) => {
  Object.defineProperty(self, k, { get: () => captured.computed[k].call(self), configurable: true });
});

const supplyTiles = {};
self.allTileGroups.filter((g) => g.plane === "supply")[0].tiles.forEach((t) => { supplyTiles[t.key] = t.n; });
console.log(JSON.stringify(supplyTiles));
"""


def _run(drift_data: dict, scope: str) -> dict:
    out = subprocess.run(
        [_NODE, "-e", _HARNESS, "--", json.dumps(drift_data), dr.APP_JS_SRC, scope],
        capture_output=True, text=True, timeout=30, check=True,
    )
    return json.loads(out.stdout)


def _drift_data() -> dict:
    """Two repos' worth of actions — enough to prove per-repo scoping without the size of
    a real fleet blob. Field shapes match what agent.lib.dashboard_render._build_projection
    actually embeds (repo/kind/status/worst/owner/date). `counts` is the server-precomputed,
    FLEET-WIDE projection for this exact action set (the same numbers _build_projection's
    `counts` dict would compute) — this is what scope="" must keep reading verbatim, and
    what the bug served up UNCHANGED for every scope."""
    return {
        "counts": {"critical": 3, "fixes": 4, "eol": 1, "secrets": 1},
        "actions": [
            {"repo": "repoA", "kind": "cve", "status": "DEPRECATED", "worst": "CRITICAL",
             "owner": "devops", "date": None},
            {"repo": "repoA", "kind": "eol", "status": "DEPRECATED", "worst": "HIGH",
             "owner": "devops", "date": None},
            {"repo": "repoA", "kind": "secret", "status": "EXPOSED", "worst": "CRITICAL",
             "owner": "devops", "date": None},
            {"repo": "repoB", "kind": "cve", "status": "DEPRECATED", "worst": "CRITICAL",
             "owner": "devops", "date": None},
        ],
        "endpoints": [], "private": [], "shapes": [],
    }


@pytest.mark.skipif(_NODE is None, reason="no node binary installed")
def test_selecting_a_repo_changes_the_supply_chain_tile_counts():
    dd = _drift_data()
    fleet = _run(dd, "")
    assert fleet == {"critical": 3, "fixes": 4, "eol": 1, "secrets": 1}, (
        "fleet-wide (scope='') must be unaffected by this fix — same numbers as before")

    repo_a = _run(dd, "repoA")
    assert repo_a == {"critical": 2, "fixes": 3, "eol": 1, "secrets": 1}, (
        "selecting repoA must show ONLY repoA's own findings, not the fleet totals")

    repo_b = _run(dd, "repoB")
    assert repo_b == {"critical": 1, "fixes": 1, "eol": 0, "secrets": 0}, (
        "selecting repoB must show ONLY repoB's own findings")

    assert repo_a != fleet and repo_b != fleet and repo_a != repo_b, (
        "the bug this test targets: all three used to be IDENTICAL because the tiles read "
        "the raw fleet-wide `counts` blob regardless of the selected repo")
