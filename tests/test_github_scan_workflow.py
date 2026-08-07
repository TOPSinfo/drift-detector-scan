"""The GitHub Actions scan pipeline: ephemeral compute on GitHub, private data on GitLab.
Static guards on the workflow file (the run happens on GitHub, but the properties that would
silently break it — engine drift, a leaked token, a missing reachability gate — are in the
file)."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WF_PATH = ROOT / ".github" / "workflows" / "scan.yml"
WF_TEXT = WF_PATH.read_text()


def test_workflow_is_valid_yaml():
    yaml.safe_load(WF_TEXT)          # must parse (note: YAML 1.1 turns the `on:` key into True)


def test_runs_scheduled_and_on_demand():
    assert "workflow_dispatch" in WF_TEXT and "schedule" in WF_TEXT


def test_engine_pinned_sha_verified_and_matches_the_runner():
    v = re.search(r"AST_GREP_VERSION:\s*\"([0-9.]+)\"", WF_TEXT).group(1)
    assert re.search(r'AST_GREP_SHA256:\s*"[0-9a-f]{64}"', WF_TEXT)
    assert "sha256sum -c" in WF_TEXT and "releases/latest" not in WF_TEXT
    runner = re.search(r"DRIFT_AST_GREP_VERSION:-([0-9.]+)",
                       (ROOT / "bin" / "drift-scan").read_text()).group(1)
    assert v == runner


def test_checks_reachability_before_scanning():
    """GitHub runners are on the public internet; the first step must prove it can reach the
    private GitLab (and that the token works) with a clear error, not fail cryptically mid-run."""
    assert "/api/v4/version" in WF_TEXT
    assert WF_TEXT.index("/api/v4/version") < WF_TEXT.index("agent.cli run")


def test_config_preflight_gates_before_the_scan():
    """A misconfigured deployment (unset token, named-but-missing webhook) must fail in
    seconds, before the 10-minute scan — the preflight runs after drift.yml is on disk and
    before `agent.cli run`."""
    assert "config-preflight --config" in WF_TEXT
    assert WF_TEXT.index("config-preflight") < WF_TEXT.index("agent.cli run")


def test_scans_then_verifies_then_persists():
    assert "agent.cli run" in WF_TEXT and "agent.cli verify" in WF_TEXT
    assert WF_TEXT.index("agent.cli run") < WF_TEXT.index("agent.cli verify")
    assert "git push origin" in WF_TEXT          # state pushed back to drift-ops


def test_overlay_is_wired_from_drift_ops():
    assert "DRIFT_CATALOG_DIR:" in WF_TEXT and "drift-ops/catalog" in WF_TEXT
    assert "drift-ops/config/drift.yml" in WF_TEXT


def test_delivery_is_wired_after_verify_and_config_driven():
    assert "agent.cli deliver --config" in WF_TEXT              # mode/host/project from drift.yml
    assert "DRIFT_DELIVER" not in WF_TEXT                       # no GitHub-variable dance anymore
    assert WF_TEXT.index("agent.cli verify") < WF_TEXT.index("agent.cli deliver")  # deliver after verify


def test_scan_reads_the_fleet_from_config():
    assert "agent.cli run --config" in WF_TEXT and "drift.yml" in WF_TEXT


def test_writes_a_run_summary_page():
    assert "GITHUB_STEP_SUMMARY" in WF_TEXT           # the shareable rendered report on the run
    assert "state/drift.md" in WF_TEXT


def test_token_comes_from_a_secret_never_a_literal():
    assert "secrets.GITLAB_TOKEN" in WF_TEXT
    assert not re.search(r"glpat-[A-Za-z0-9_-]{15,}", WF_TEXT)


def test_only_reads_this_repo_writes_go_to_gitlab():
    wf = yaml.safe_load(WF_TEXT)
    assert wf["permissions"]["contents"] == "read"      # no write-back to the GitHub repo


def test_pages_publish_is_gated_demo_only():
    """Publishing the dashboard to PUBLIC GitHub Pages exposes the vuln posture (repo names,
    CVEs, versions). It MUST stay gated on the PUBLISH_PAGES variable so it never runs for real
    client data by default — this guard fails if someone drops the gate."""
    wf = yaml.safe_load(WF_TEXT)
    job = wf["jobs"]["publish-pages"]
    assert job["if"] == "vars.PUBLISH_PAGES == 'true'"
    assert job["needs"] == "scan"                        # publishes what the scan persisted


def test_no_internal_host_is_hardcoded_in_the_public_workflow():
    """This file is public (a Claude plugin). The GitLab host + persistence path must come from
    repo VARIABLES, not be baked in — a hardcoded internal hostname is an infra disclosure. The
    bug this guards: a literal host like `GITLAB_HOST: git.acme.internal` baked into the file."""
    assert "${{ vars.GITLAB_HOST }}" in WF_TEXT
    assert "${{ vars.DRIFT_OPS_PATH }}" in WF_TEXT
    # that no *specific* internal host/path is hardcoded anywhere is enforced tree-wide by
    # tests/test_no_internal_identifiers.py — not re-named here, so this file stays clean itself.
    # an unset variable must fail loudly in the first step, not clone a malformed URL
    assert "${GITLAB_HOST:?" in WF_TEXT and "${DRIFT_OPS_PATH:?" in WF_TEXT


def test_third_party_actions_are_sha_pinned():
    """A mutable `@v4` tag can be moved to point at malicious code (supply-chain). Every
    third-party action in EVERY workflow must be pinned to a full 40-hex commit SHA. Guards
    against a bare `uses: actions/checkout@v4` slipping back in — checked tree-wide, because
    container.yml once shipped with unpinned `@v3`/`@v6` tags while scan.yml was pinned."""
    workflows = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    assert workflows                                      # there ARE workflow files
    unpinned = []
    for wf in workflows:
        for u in re.findall(r"uses:\s*([^\s#]+)", wf.read_text()):
            if "/" not in u or u.startswith("./"):
                continue                                  # local action, not third-party
            ref = u.split("@", 1)[1] if "@" in u else ""
            if not re.fullmatch(r"[0-9a-f]{40}", ref):
                unpinned.append(f"{wf.name}: {u}")
    assert not unpinned, "third-party actions not pinned to a 40-hex SHA:\n" + "\n".join(unpinned)
