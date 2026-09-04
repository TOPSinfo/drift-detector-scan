"""Guards the runner (`bin/drift-scan`), the intake doctrine (`docs/drift-absorb.md`), and the
Claude-plugin surface (restored as the primary product in the AI-driven pivot). The runner's
engine pin + subcommand dispatch, the absorb gate's guardrails, and the plugin's rewiring
(persistent catalog + the bundled engine + quarantined AI leads) are all load-bearing."""
import os
import stat
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def test_runner_present_and_executable():
    runner = _ROOT / "bin" / "drift-scan"
    assert runner.exists()
    assert os.stat(runner).st_mode & stat.S_IXUSR                # executable bit set
    body = runner.read_text()
    assert "agent.cli inventory-scan" in body                   # drives the real CLI
    assert "requirements-plugin.txt" in body                    # installs the lean runtime deps
    assert (_ROOT / "requirements-plugin.txt").exists()


def test_runner_has_doctor_with_actionable_hint():
    body = (_ROOT / "bin" / "drift-scan").read_text()
    assert '"${1:-}" = "doctor"' in body                        # doctor health-check mode
    assert "astral.sh/uv/install.sh" in body                    # exact uv install remediation


def test_doctor_reports_whether_gitleaks_is_present():
    """REGRESSION: doctor's gitleaks check must ask what the scanner will ACTUALLY
    resolve (mirroring the `engine` line's own `resolve_engine()` call) — a bare
    `command -v gitleaks` (PATH only) would keep reporting "not found" even after a
    successful fetch into the venv's bin/, since bin/drift-scan never puts that
    directory on PATH."""
    body = (_ROOT / "bin" / "drift-scan").read_text()
    doctor_block = body[body.index('echo "drift-detector · doctor"'):
                        body.index("# Freshness.")]
    assert "_resolve_gitleaks" in doctor_block           # asks the venv's own python
    assert '"$VENV/bin/python"' in doctor_block.split("_resolve_gitleaks")[0][-200:]
    assert "gitleaks not found" in doctor_block and "UNKNOWN, not zero" in doctor_block
    assert "not yet" in doctor_block and "fetched on first scan" in doctor_block


def test_runner_self_provisions_gitleaks_like_ast_grep():
    """gitleaks is optional (unlike ast-grep — a missing gitleaks degrades secret
    detection to UNKNOWN, never fails the scan), but a user should not have to install
    it by hand any more than they install ast-grep by hand: pin a version, verify a
    hardcoded checksum before trusting it (same discipline as the Dockerfile's
    AST_GREP_SHA256 — not fetched from the same host as the binary), and place it next
    to ast-grep in the venv's bin/ where secrets_scan._resolve_gitleaks looks for it."""
    body = (_ROOT / "bin" / "drift-scan").read_text()
    assert "GITLEAKS_VERSION" in body
    assert "gitleaks/gitleaks/releases/download" in body       # a direct, predictable URL
    assert "sha256sum -c" in body
    assert body.count("_sha_gl=") >= 4                         # one hardcoded sha per platform
    assert '"$VENV/bin/gitleaks"' in body


def test_runner_only_attempts_the_gitleaks_fetch_once_per_venv():
    """REGRESSION: gitleaks is optional — retrying a network fetch on every single scan
    invocation forever (rather than once) would cost every user who has chosen not to
    install it a network round-trip on every run, not just the first."""
    body = (_ROOT / "bin" / "drift-scan").read_text()
    assert "GITLEAKS_FETCH_MARKER" in body
    assert '[ ! -f "$GITLEAKS_FETCH_MARKER" ]' in body


def test_runner_gitleaks_fetch_never_uses_a_bare_failing_assignment_under_set_e():
    """REGRESSION: a prior version of this block did `x="$(curl ...)"` as a bare
    statement — under `set -e`, curl failing there (no network route to GitHub) aborts
    the ENTIRE script before the scan ever runs, turning "gitleaks isn't reachable" into
    "no scan ran at all" for every user, not just ones who wanted secret detection.
    Verified as a real regression by tracing the pre-fix script with `bash -x` against a
    blackholed network: base exited 0, the broken version exited non-zero and printed
    nothing. The fetch's only network call must be inside a conditional (an `if`/`&&`
    chain), never a bare assignment."""
    body = (_ROOT / "bin" / "drift-scan").read_text()
    gl_block = body[body.index("fetch the gitleaks"):]
    gl_block = gl_block[:gl_block.index('# Run from the caller')]
    for line in gl_block.splitlines():
        stripped = line.strip()
        if stripped.startswith("_") and "=" in stripped and "curl" in stripped:
            assert False, f"a bare command-substitution assignment calls curl: {stripped!r}"


def _runner_case_line() -> str:
    runner = (_ROOT / "bin" / "drift-scan").read_text()
    return next(l for l in runner.splitlines() if l.strip().startswith("audit|run|"))


def test_runner_dispatches_every_subcommand():
    case_line = _runner_case_line()
    for sub in ("audit", "run", "deliver", "schedule", "unschedule", "mute", "preflight", "absorb", "verify"):
        assert sub in case_line                                  # runner dispatches every subcommand
    assert "gitlab-sync" not in case_line                        # connector stripped on hybrid (see master)
    from agent import cli
    assert all(hasattr(cli, n) for n in ("_cmd_audit", "_cmd_run", "_cmd_schedule", "_cmd_unschedule"))


def test_runner_allowlist_covers_the_whole_cli():
    """Derived from agent/cli.py, NOT a hand-kept list — that is the whole point.

    Shipped bug: the check above whitelisted 9 names by hand, so `clean` and `research`
    were added to the CLI and never wired into the runner's case statement. An unlisted
    subcommand does not error; it falls through to the DEFAULT (`inventory-scan`), so
    `drift-scan clean --report` died with a confusing "--root/--state are required"
    instead of running, and the plugin skill's cleanup + /drift-research paths were dead
    on arrival. Any future subcommand is caught here the moment it is added.
    """
    import re
    cli_src = (_ROOT / "agent" / "cli.py").read_text()
    declared = set(re.findall(r'add_parser\("([a-z-]+)"', cli_src))
    dispatched = set(re.findall(r"[a-z-]+", _runner_case_line().split(")")[0]))
    # `inventory-scan` is the runner's default when nothing matches, so it is reachable
    # without appearing in the case list.
    missing = sorted(declared - dispatched - {"inventory-scan"})
    assert not missing, f"CLI subcommands unreachable via bin/drift-scan: {missing}"


def test_referenced_cli_subcommand_exists():
    # the runner defaults to `python -m agent.cli inventory-scan`; ensure that handler exists
    from agent import cli
    assert hasattr(cli, "_cmd_inventory_scan")


def test_catalog_defaults_are_package_relative():
    # loaders must resolve their catalog regardless of the caller's cwd (the runner never chdirs)
    from agent.lib.vendors import _DEFAULT_VENDORS
    from agent.lib.frameworks import _DEFAULT_FRAMEWORKS
    assert Path(_DEFAULT_VENDORS).is_absolute() and Path(_DEFAULT_VENDORS).exists()
    assert Path(_DEFAULT_FRAMEWORKS).is_absolute() and Path(_DEFAULT_FRAMEWORKS).exists()


def test_absorb_doctrine_present_and_states_its_guardrails():
    """The absorb gate's procedure — moved from a plugin command to `docs/` doctrine — is the
    contract that keeps agent output out of the catalogs unreviewed. Its guardrails are
    load-bearing, not decoration (each pins a real way the intake has been burned)."""
    doc = (_ROOT / "docs" / "drift-absorb.md")
    assert doc.exists(), "the intake doctrine must survive the plugin strip"
    cmd = doc.read_text()
    # it drives the real CLI, not an invented flow
    assert "drift-scan" in cmd and "absorb --staged" in cmd and "recommend" in cmd
    assert "absorb --check" in cmd                              # the iteration instrument (measure without committing)
    # the guardrails that exist because they were violated for real
    assert "did not open" in cmd.lower() or "did not fetch" in cmd.lower()
    assert "source" in cmd.lower() and "staged" in cmd.lower()
    assert "Never edit" in cmd and "vendor_sunsets.yaml" in cmd  # never a direct write to the catalogs
    # the overlay hand-off must be wired (absorb must NOT write installed catalogs)
    assert "DRIFT_CATALOG_DIR" in cmd and "DRIFT_OPS_DIR" in cmd
    assert "mr create" in cmd or "merge request" in cmd.lower()  # handed back to drift-ops


def test_plugin_scaffolding_present_and_wired():
    """The Claude-plugin surface is the primary product again (the AI-driven pivot). Validate it's
    present AND correctly rewired: persistent local catalog + the BUNDLED engine as the runner (never
    a PyPI/uvx package) + the AI cross-check kept quarantined (leads, separate artifact, `retired` a
    tri-state not a date)."""
    import json
    pj = _ROOT / ".claude-plugin" / "plugin.json"
    mj = _ROOT / ".claude-plugin" / "marketplace.json"
    assert pj.exists() and mj.exists()
    plugin = json.loads(pj.read_text())
    for rel in plugin.get("commands", []):                       # every listed command must exist
        assert (_ROOT / rel.lstrip("./")).exists(), f"missing command file: {rel}"
    # plugin.json and the marketplace entry MUST agree on version. They silently drifted for
    # multiple releases (marketplace.json stuck at 0.14.1-beta while plugin.json advanced to 0.15.x);
    # `claude plugin update` compares the MARKETPLACE version, so a stale entry blocks updates from
    # ever reaching installed users — the fix landed via reinstall, but the guard is what keeps it fixed.
    market = json.loads(mj.read_text())
    entry = next(p for p in market["plugins"] if p["name"] == plugin["name"])
    assert entry["version"] == plugin["version"], (
        f'version drift: marketplace.json says {entry["version"]!r}, plugin.json says {plugin["version"]!r} '
        f"— bump BOTH together or `claude plugin update` silently no-ops for users"
    )
    main = (_ROOT / "commands" / "drift-detector.md").read_text()
    # the two things the rewiring added: persistent catalog (so absorb survives upgrades) + the
    # BUNDLED engine. The plugin runs its OWN bin/drift-scan, never a PyPI/uvx package — that path
    # once silently ran a divergent published version that failed this plugin's own `verify`.
    assert 'DRIFT_CATALOG_DIR="${DRIFT_CATALOG_DIR:-$HOME/.drift/catalog}"' in main
    assert 'SCAN="${CLAUDE_PLUGIN_ROOT:-}/bin/drift-scan"' in main
    assert "uvx --from" not in main, "the PyPI/uvx runner must never come back — it causes engine/verify skew"
    # the firewall, enforced in the promptfile: AI output is leads in its OWN BLOB inside the one
    # dashboard (there is no second dashboard any more), and a lead's `retired` is a tri-state —
    # never a date (a date is a certified-tier claim only).
    assert "AI Frontier" in main and "leads.json" in main
    assert "probabilistic.html" not in main, "the side-car dashboard is gone; the promptfile must not send users to it"
    assert '"yes"|"no"|"unknown"' in main and "NEVER a date" in main
    assert not (_ROOT / "skills").exists()                       # command-based plugin, no skills/ dir


def test_runner_ignores_a_foreign_agent_package_in_the_callers_cwd(tmp_path):
    """The runner pins the engine via PYTHONPATH, but `python -m` puts the caller's CWD at
    sys.path[0] — AHEAD of PYTHONPATH — so any directory containing an `agent/` package
    silently hijacked the scan.

    This shipped. Running `drift-scan` from the older sibling checkout (which has its own
    `agent/` + catalogs) executed THAT engine's code and attestations while reporting itself
    as a normal run: zenithapp-crm graded 7 vendors UNAUDITED instead of 2, deterministic
    and green and wrong. `verify` cannot catch it — the wrong engine verifies its own output.
    """
    import subprocess
    decoy = tmp_path / "agent"
    decoy.mkdir()
    (decoy / "__init__.py").write_text("")
    (decoy / "cli.py").write_text("print('DECOY ENGINE RAN')\n")
    proc = subprocess.run([str(_ROOT / "bin" / "drift-scan"), "verify", "--state", str(tmp_path / "nope")],
                          cwd=tmp_path, capture_output=True, text=True, timeout=180)
    assert "DECOY ENGINE RAN" not in (proc.stdout + proc.stderr), \
        "the caller's cwd shadowed the pinned engine"


def test_promptfile_describes_the_no_queue_resolution_pass():
    """docs/superpowers/specs/2026-08-13-no-queue-design.md: unresolved hosts no longer sit in
    a queue for a human (or a separate `/drift-research` step) to pick up later — the owner's
    own framing was 'just run it along the scan, I don't want any queued'. The promptfile must
    describe the resolution pass as automatic (no gate, no question), name the real commands
    (`resolve` for the work-list, `run --resolve` for gate+apply+re-scan+deliver in one call),
    and state the load-bearing honesty rules: a retirement date still needs a verbatim-quoted
    source, `unknown` is a legitimate verdict, a failed pass degrades rather than blocks, and a
    catalogued vendor can never be claimed as own-infra."""
    main = (_ROOT / "commands" / "drift-detector.md").read_text()

    # the real commands, not an invented flow
    assert '"$SCAN" resolve --state' in main                 # prints the unresolved work-list
    assert "--resolve" in main and '"$SCAN" run' in main      # run --resolve: gate+apply+re-scan+deliver

    # automatic — no gate, no question, ever
    assert "no queue" in main.lower() or "no-queue" in main.lower()
    assert "want me to research" in main.lower() or "ask first" in main.lower() or \
        "without asking" in main.lower()

    # honesty rule 1: a retirement date still needs a source, verbatim in the excerpt
    assert "verbatim" in main.lower()
    assert "excerpt" in main.lower()

    # honesty rule 2: `unknown` is legitimate, never invented away
    assert "`unknown`" in main or "'unknown'" in main
    assert "needs-human" in main or "needs human" in main.lower()

    # honesty rule 3: a failed pass degrades, never blocks
    assert "degrade" in main.lower()

    # honesty rule 4: a catalogued vendor can never become own-infra
    assert "own-infra" in main.lower() and "catalogued vendor" in main.lower()

    # the old world — queued for a later, separate research step — is gone from this file
    assert "queued for research" not in main.lower()
