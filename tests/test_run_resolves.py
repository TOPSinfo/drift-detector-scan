"""`run --resolve <verdicts.json>`: scan -> gate + apply the verdicts -> RE-SCAN -> audit ->
render (docs/superpowers/specs/2026-08-13-no-queue-design.md, Task 3 — ".superpowers/sdd/
task-3-brief.md" calls this the load-bearing task).

The design's whole point is that the AI never writes the answer into drift.json — it writes
evidence, `agent.resolve.apply` gates it into reviewed overlay catalog data, and the
DETERMINISTIC scanner re-derives the answer on a second, ordinary scan pass. So the tests here
prove the thing that actually matters: the SECOND scan, not the verdicts, produced the
certified payload, and `verify.check_ai_firewall` — the mechanical proof that no AI-derived
record reached drift.json — still passes on it.

Fictional identifiers only (matching tests/test_resolve_gate.py's style): real client hostnames
were scrubbed from this public repo and must never be reintroduced.

The fake `run=` engine returns one `url-literal` match directly in ast-grep's raw JSON shape
(agent/lib/engine.py's `run_scan` parses `ruleId`/`file`/`range.start.line`/`text`) naming a host
no vendor/own-infra signal can classify, so the first scan leaves it `coverage: queued` without
depending on a real ast-grep binary being on PATH (the harness convention already used by
tests/test_run_pipeline.py's `_empty_engine`).
"""
import json
import subprocess

import pytest

from agent import cli
from agent import resolve as resolve_mod
from agent.lib import verify as verify_mod
from agent.run import run_pipeline

_UNRESOLVED_HOST = "listingimages.thirdparty.io"


def _git_init(d, files):
    d.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(text)
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
                    "--allow-empty", "-q", "-am", "init"], cwd=d, check=True)


def _url_engine(args):
    """Raw ast-grep-shaped JSON: one url-literal match for an uncatalogued, non-own-infra host.
    `args[-1]` is the repo path the engine was asked to scan (agent/lib/engine.py's run_scan
    builds argv as [..., repo_path]); the exact file need not exist on disk since `text` is
    supplied directly and endpoints.py only falls back to reading the file when `text` is empty.
    """
    repo_path = args[-1]
    return json.dumps([{
        "ruleId": "url-literal@php",
        "file": f"{repo_path}/app/Client.php",
        "range": {"start": {"line": 2}},   # 0-indexed -> 1-indexed line 3
        "text": f'$c->get("https://{_UNRESOLVED_HOST}/foo/bar");',
    }])


def _repo(base):
    root = base / "repos"
    _git_init(root / "web", {
        "composer.json": '{"require": {}}',
        "app/Client.php": ('<?php\n$c = new Client();\n'
                           f'$c->get("https://{_UNRESOLVED_HOST}/foo/bar");\n'),
    })
    return root


def _no_network(monkeypatch):
    import agent.audit as audit_mod
    monkeypatch.setattr(audit_mod.eol, "check", lambda *a, **k: None)


def _catalog_dir(monkeypatch, tmp_path, name="catalog"):
    d = tmp_path / name
    d.mkdir(exist_ok=True)
    monkeypatch.setenv("DRIFT_CATALOG_DIR", str(d))
    return d


def _vendor_verdict(**over):
    v = {"status": "vendor-identity", "host": _UNRESOLVED_HOST, "vendor": "GeoMapper",
         "source_url": "https://geo-mapper.io/docs/api-hosts"}
    v.update(over)
    return v


def _own_domain_verdict(**over):
    # `repo` must be "web" — the value work_list()/drift.json's `endpoints[].repo` actually
    # report for this fixture (the record's `path`, since the fixture repo has no git remote
    # and own_infra's repo-scope match falls back to a basename match against it).
    v = {"status": "own-domain", "host": _UNRESOLVED_HOST, "repo": "web",
         "reason": "this is the project's own internal image-processing service, not a vendor"}
    v.update(over)
    return v


def _run(root, state, *, resolve=None, http=None):
    return run_pipeline(str(root), str(state), "2026-08-13", run=_url_engine, engine="semgrep",
                        http=http or (lambda *a, **k: {}), resolve=resolve)


# --------------------------------------------------------------------- sanity: the host IS queued
def test_without_resolve_the_uncatalogued_host_is_left_queued(tmp_path, monkeypatch):
    """Establishes the premise every other test in this file depends on: the fixture repo
    really does leave a host unresolved when no --resolve is given."""
    _no_network(monkeypatch)
    root = _repo(tmp_path)
    state = tmp_path / "state"
    out = _run(root, state)
    assert out["resolve"] is None
    drift = json.loads((state / "drift.json").read_text())
    assert drift["counts"]["coverage"]["queued"] == 1
    assert any(e["domain"] == _UNRESOLVED_HOST and e["coverage"] == "queued"
              for e in drift["endpoints"])


# --------------------------------------------------------------------- THE load-bearing test
def test_resolve_rescans_and_the_certified_payload_passes_the_ai_firewall(tmp_path, monkeypatch):
    """This is the assertion the whole no-queue design stands or falls on: after a verdict is
    gated, applied, and the deterministic re-scan runs, `check_ai_firewall` must still pass on
    the resulting drift.json. If this ever fails, no AI-derived record may reach the certified
    payload has been violated and the architecture (not just this test) is wrong."""
    _no_network(monkeypatch)
    _catalog_dir(monkeypatch, tmp_path)
    root = _repo(tmp_path)
    state = tmp_path / "state"

    out = _run(root, state, resolve=[_vendor_verdict()])

    assert out["resolve"]["status"] == "applied"
    assert out["resolve"]["written"]["vendor_identity"] == 1

    drift = json.loads((state / "drift.json").read_text())
    # coverage.queued == 0: the verdict covered the only unresolved host.
    assert drift["counts"]["coverage"]["queued"] == 0
    resolved = [e for e in drift["endpoints"] if e["domain"] == _UNRESOLVED_HOST]
    assert resolved and resolved[0]["coverage"] == "tracked"
    assert resolved[0]["vendor"] == "GeoMapper"
    assert resolved[0]["classified"] is True

    verify_mod.check_ai_firewall(drift)   # must not raise — see docstring above


def test_resolve_result_comes_from_the_rescan_not_the_verdict(tmp_path, monkeypatch):
    """The re-scan, not the AI's claim, must be what lands the vendor attribution: drift-scan
    verify (which re-parses drift.md/summary.html/dashboard.html against drift.json) must still
    agree with this payload, proving it is a normal, self-consistent scan output — not a
    special-cased injection of the verdict's own fields."""
    _no_network(monkeypatch)
    _catalog_dir(monkeypatch, tmp_path)
    root = _repo(tmp_path)
    state = tmp_path / "state"
    _run(root, state, resolve=[_vendor_verdict()])

    drift = json.loads((state / "drift.json").read_text())
    audit = json.loads((state / "audit.json").read_text())
    violations = verify_mod.verify_payload(drift, audit.get("findings", []))
    assert violations == []


# --------------------------------------------------------------------- coverage.queued == 0
def test_verdicts_covering_every_unresolved_host_leave_coverage_queued_at_zero(tmp_path, monkeypatch):
    _no_network(monkeypatch)
    _catalog_dir(monkeypatch, tmp_path)
    root = _repo(tmp_path)
    state = tmp_path / "state"
    out = _run(root, state, resolve=[_vendor_verdict()])
    assert out["coverage"] is not None            # sanity: audit coverage still reported
    drift = json.loads((state / "drift.json").read_text())
    assert drift["counts"]["coverage"]["queued"] == 0


# --------------------------------------------------------------------- determinism across two scan passes
def test_two_runs_over_identical_inputs_and_verdicts_are_byte_identical(tmp_path, monkeypatch):
    """Two full run_pipeline calls (each doing its OWN scan -> apply -> re-scan), same root,
    same verdicts, same --now, into separate state/catalog dirs, must produce byte-identical
    drift.json. This is what proves the re-scan is genuinely the SAME deterministic scan and not
    some other code path that happens to look similar."""
    _no_network(monkeypatch)
    root = _repo(tmp_path)

    def _once(tag):
        state = tmp_path / f"state-{tag}"
        _catalog_dir(monkeypatch, tmp_path, name=f"catalog-{tag}")
        out = _run(root, state, resolve=[_vendor_verdict()])
        assert out["resolve"]["status"] == "applied"
        return (state / "drift.json").read_bytes()

    first = _once("a")
    second = _once("b")
    assert first == second


# --------------------------------------------------------------------- gate-rejected: abort, don't half-apply
def test_gate_rejected_verdicts_abort_and_leave_the_first_scans_result_intact(tmp_path, monkeypatch):
    """A verdict set that fails the gate (here: a vendor-identity claim with no source_url) must
    not touch the overlay AT ALL, and drift.json must come out exactly as the first (and only
    surviving) scan produced it — not a half-applied catalog, and not a missing report."""
    _no_network(monkeypatch)
    catalog = _catalog_dir(monkeypatch, tmp_path)
    root = _repo(tmp_path)

    baseline_state = tmp_path / "baseline"
    _run(root, baseline_state)
    baseline = (baseline_state / "drift.json").read_bytes()

    state = tmp_path / "state"
    bad = _vendor_verdict(source_url="")
    # sanity: this verdict really does fail the gate on its own
    assert resolve_mod.check_verdicts([bad])

    out = _run(root, state, resolve=[bad])

    assert out["resolve"]["status"] == "rejected"
    assert out["resolve"]["problems"]
    assert (state / "drift.json").read_bytes() == baseline
    assert list(catalog.iterdir()) == []           # nothing written to the overlay
    drift = json.loads((state / "drift.json").read_text())
    assert drift["counts"]["coverage"]["queued"] == 1   # the host is still queued, unresolved


# --------------------------------------------------------------------- --resolve file errors (CLI)
def test_cli_run_resolve_missing_file_fails_cleanly(tmp_path, capsys):
    rc = cli.main(["run", "--root", str(tmp_path), "--state", str(tmp_path / "state"),
                   "--now", "2026-08-13", "--resolve", str(tmp_path / "does-not-exist.json")])
    assert rc == 2
    err = capsys.readouterr().err
    assert "resolve" in err.lower()


def test_cli_run_resolve_malformed_json_fails_cleanly(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json")
    rc = cli.main(["run", "--root", str(tmp_path), "--state", str(tmp_path / "state"),
                   "--now", "2026-08-13", "--resolve", str(bad)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "resolve" in err.lower()
    assert "json" in err.lower()


# --------------------------------------------------------------------- omitting --resolve is unchanged
def test_omitting_resolve_behaves_exactly_as_before(tmp_path, monkeypatch):
    _no_network(monkeypatch)
    root = _repo(tmp_path)
    state_implicit = tmp_path / "implicit"
    state_explicit_none = tmp_path / "explicit-none"

    out_implicit = _run(root, state_implicit)
    out_explicit = _run(root, state_explicit_none, resolve=None)

    assert out_implicit["resolve"] is None
    assert out_explicit["resolve"] is None
    assert ((state_implicit / "drift.json").read_bytes()
           == (state_explicit_none / "drift.json").read_bytes())


# ======================================================================= Fix round 1 (review findings)

# --------------------------------------------------------------------- CRITICAL: own-domain silent no-op
def test_own_domain_verdict_through_resolve_moves_host_to_own_infra_and_queued_zero(tmp_path, monkeypatch):
    """The primary case the design exists for — the review found it's a silent no-op. The
    re-scan reused the per-repo cache (keyed on `rules_sig` = vendors+idioms only); the
    own-domains overlay `apply` just wrote isn't part of that ruleset, so the cache served
    scan 1's PRE-resolution record even though the overlay was written correctly and the CLI
    printed 'resolve applied ... drift.json reflects the re-scan'. An own-domain verdict must
    actually flip the host to `own-infra`/`na` and drop `coverage.queued` to 0."""
    _no_network(monkeypatch)
    _catalog_dir(monkeypatch, tmp_path)
    root = _repo(tmp_path)
    state = tmp_path / "state"

    out = _run(root, state, resolve=[_own_domain_verdict()])

    assert out["resolve"]["status"] == "applied"
    assert out["resolve"]["written"]["own_domain"] == 1

    drift = json.loads((state / "drift.json").read_text())
    assert drift["counts"]["coverage"]["queued"] == 0        # was silently staying at 1
    resolved = [e for e in drift["endpoints"] if e["domain"] == _UNRESOLVED_HOST]
    assert resolved, "the host must still be present, just no longer queued/unclassified"
    assert resolved[0]["hostClass"] == "own-infra"
    assert resolved[0]["coverage"] == "na"

    verify_mod.check_ai_firewall(drift)   # the central claim must still hold after this fix
