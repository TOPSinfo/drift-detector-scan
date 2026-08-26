# Opt-in Parallel Fleet Scan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `--jobs N` (default 1) so a local fleet scan can run its per-repo sweep and its
`git pull` phase concurrently, while CI keeps today's serial behaviour untouched.

**Architecture:** One new helper, `agent/lib/pool.py`, exposing `ordered_map(fn, items, jobs=1)`.
It returns results in **input** order regardless of completion order, and captures per-item
exceptions rather than raising. `jobs=1` takes a literal serial path — no executor is
constructed — so the default is today's code, not "a pool of size one". Two call sites are
converted; the OSV rewrite is explicitly **not** in this plan.

**Tech Stack:** Python 3.11+, stdlib only (`concurrent.futures.ThreadPoolExecutor`), pytest.
Threads, not processes: every parallelised unit either shells out (`ast-grep`, `git`) or waits
on a socket, so the GIL is released for the duration of the work.

## Global Constraints

- **Runtime dependencies are stdlib + PyYAML only.** `jsonschema` is test-only. Do not add a
  dependency for this feature.
- **Deterministic, zero tokens in the scan path.** Same inputs → byte-identical output. No
  wall-clock in logic; `now` is passed in.
- **"Cannot see" ≠ "clean".** A repo that errors must still be recorded in
  `coverage["reposErrored"]`, never silently dropped.
- **Prove a guard against its bug.** Every test below must be seen to FAIL before the
  implementation lands.
- Test command is `.venv/bin/python -m pytest -q` from the repo root (1501 passing, ~26s, no
  network).
- Branch is `perf/parallel-scan`, based on `origin/master` at `18e343c`.
- **Out of scope, do not touch:** `agent/lib/osv.py`, `agent/lib/eol.py`, `.gitlab-ci.yml`.

---

## File Structure

| File | Responsibility |
|---|---|
| `agent/lib/pool.py` (create) | The only concurrency primitive. `ordered_map` and nothing else. |
| `tests/test_pool.py` (create) | Unit tests for the primitive in isolation. |
| `agent/run.py` (modify, ~line 42) | `_pull_repos` gains a `jobs` parameter and maps through the pool. |
| `agent/inventory_scan.py` (modify, ~line 154) | `scan_folder` gains a `jobs` parameter; the per-repo loop body becomes a worker function, and coverage is folded from the ordered results. |
| `agent/cli.py` (modify, ~lines 20-34, 125-127, 1578-1584, 1786-1793) | `--jobs` on `run` and `inventory-scan`, threaded through to the pipeline. |
| `tests/test_parallel_identity.py` (create) | The end-to-end guarantee: serial and parallel produce identical artifacts. |

---

### Task 1: The `ordered_map` primitive

**Files:**
- Create: `agent/lib/pool.py`
- Test: `tests/test_pool.py`

**Interfaces:**
- Consumes: nothing (stdlib only).
- Produces: `ordered_map(fn, items, *, jobs=1) -> list[tuple[Any, BaseException | None]]`.
  Each element is `(result, None)` on success or `(None, exc)` on failure, positionally
  aligned with `items`. Tasks 2 and 3 rely on exactly this shape.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pool.py`:

```python
import time

from agent.lib import pool


def test_ordered_map_returns_results_in_input_order_not_completion_order():
    """Item 0 sleeps longest, so completion order is the REVERSE of input order.

    If results were collected as futures completed, this returns [4,3,2,1,0].
    """
    def slow(i):
        time.sleep((5 - i) * 0.02)
        return i

    out = pool.ordered_map(slow, [0, 1, 2, 3, 4], jobs=5)

    assert [value for value, _exc in out] == [0, 1, 2, 3, 4]
    assert all(exc is None for _value, exc in out)


def test_ordered_map_captures_per_item_errors_against_the_right_index():
    """One item raising must not abort the rest, and the error must stay aligned."""
    def sometimes(i):
        if i == 1:
            raise ValueError("boom")
        return i * 10

    out = pool.ordered_map(sometimes, [0, 1, 2], jobs=3)

    assert out[0] == (0, None)
    assert out[2] == (20, None)
    value, exc = out[1]
    assert value is None
    assert isinstance(exc, ValueError) and str(exc) == "boom"


def test_ordered_map_with_jobs_1_never_constructs_an_executor(monkeypatch):
    """The default must be today's serial code, not a pool of size one.

    That distinction is what keeps the CI risk at zero, so it is asserted rather than
    assumed: constructing an executor at jobs=1 fails this test loudly.
    """
    def explode(*a, **kw):
        raise AssertionError("ThreadPoolExecutor must not be constructed when jobs=1")

    monkeypatch.setattr(pool.concurrent.futures, "ThreadPoolExecutor", explode)

    assert pool.ordered_map(lambda i: i + 1, [1, 2, 3], jobs=1) == [(2, None), (3, None), (4, None)]


def test_ordered_map_on_an_empty_list_is_an_empty_list():
    assert pool.ordered_map(lambda i: i, [], jobs=4) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pool.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.lib.pool'`

- [ ] **Step 3: Write the minimal implementation**

Create `agent/lib/pool.py`:

```python
"""The one concurrency primitive in this codebase.

`--jobs N` is a pure SCHEDULING knob: it changes when work happens, never what is concluded.
That guarantee rests entirely on this module returning results in INPUT order, so a caller
folding them into a report cannot observe which worker finished first.

Threads, not processes: every unit mapped through here either shells out (ast-grep, git) or
waits on a socket, so the GIL is released for the duration of the work. Processes would add
pickling and start-up cost for no gain.
"""
from __future__ import annotations

import concurrent.futures


def ordered_map(fn, items, *, jobs=1) -> list:
    """Apply `fn` to each item; return [(result, exc), ...] aligned with `items`.

    Exceptions are CAPTURED, not raised: both call sites already treat a failing item as a
    recorded error rather than an aborted run ("cannot see" is not "clean"), and a pool that
    raised would turn one bad repo into a dead scan.

    jobs<=1 runs inline and constructs no executor — the default path is a plain loop, which
    is what lets CI keep today's behaviour exactly rather than approximately.
    """
    items = list(items)
    if not items:
        return []
    if jobs is None or jobs <= 1:
        return [_call(fn, item) for item in items]

    results: list = [None] * len(items)
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(jobs, len(items))) as ex:
        futures = {ex.submit(_call, fn, item): i for i, item in enumerate(items)}
        for fut in concurrent.futures.as_completed(futures):
            results[futures[fut]] = fut.result()
    return results


def _call(fn, item) -> tuple:
    try:
        return (fn(item), None)
    except Exception as exc:                # NOT BaseException: KeyboardInterrupt must still
        return (None, exc)                  # stop a 25-minute scan, and both call sites already
                                            # catch Exception, so behaviour is unchanged.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_pool.py -q`
Expected: PASS, 4 tests

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: `1505 passed, 3 skipped`

- [ ] **Step 6: Commit**

```bash
git add agent/lib/pool.py tests/test_pool.py
git commit -m "feat(pool): ordered_map, the one concurrency primitive

Returns results in INPUT order regardless of completion order, which is what
makes --jobs a pure scheduling knob: a caller folding results into a report
cannot observe which worker finished first.

jobs=1 constructs no executor and runs a plain loop, so the default is today's
code rather than a pool of size one - asserted by test, because that is what
keeps the CI risk at zero."
```

---

### Task 2: Parallelise the fleet `git pull`

**Files:**
- Modify: `agent/run.py:42-49`
- Test: `tests/test_pull_repos_jobs.py` (create)

**Interfaces:**
- Consumes: `pool.ordered_map(fn, items, *, jobs=1)` from Task 1.
- Produces: `_pull_repos(roots, pull_run, *, jobs=1)` — the added keyword is passed by
  `run_pipeline` in Task 4.

- [ ] **Step 1: Write the failing test**

Create `tests/test_pull_repos_jobs.py`:

```python
import subprocess

from agent.run import _pull_repos


def _git_init(d):
    d.mkdir(parents=True, exist_ok=True)
    (d / "composer.json").write_text('{"require": {}}')
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
                    "--allow-empty", "-q", "-am", "init"], cwd=d, check=True)


def test_pull_repos_pulls_every_repo_when_parallel(tmp_path):
    for name in ("a", "b", "c"):
        _git_init(tmp_path / name)
    pulled = []

    _pull_repos([tmp_path], pulled.append, jobs=3)

    assert sorted(p.rsplit("/", 1)[-1] for p in pulled) == ["a", "b", "c"]


def test_pull_repos_still_ignores_a_repo_that_will_not_pull(tmp_path):
    """Best-effort is load-bearing: a repo that won't fast-forward is scanned as-is,
    and must not take the whole pull phase down with it."""
    for name in ("a", "b"):
        _git_init(tmp_path / name)
    seen = []

    def runner(path):
        seen.append(path)
        raise RuntimeError("cannot fast-forward")

    _pull_repos([tmp_path], runner, jobs=2)          # must not raise

    assert len(seen) == 2
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_pull_repos_jobs.py -q`
Expected: FAIL — `TypeError: _pull_repos() got an unexpected keyword argument 'jobs'`

- [ ] **Step 3: Write the minimal implementation**

In `agent/run.py`, add `from agent.lib import pool` to the imports, then replace the whole of
`_pull_repos`:

```python
def _pull_repos(roots, pull_run, *, jobs=1):
    runner = pull_run or _default_pull
    paths = [abs_path for abs_path, _identity in discover_repos(roots)]
    # Errors are captured by the pool and deliberately ignored here, exactly as the previous
    # bare `except Exception: pass` did — best-effort; a repo that won't fast-forward is
    # scanned as-is rather than failing the run.
    pool.ordered_map(runner, paths, jobs=jobs)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_pull_repos_jobs.py -q`
Expected: PASS, 2 tests

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: `1507 passed, 3 skipped`

- [ ] **Step 6: Commit**

```bash
git add agent/run.py tests/test_pull_repos_jobs.py
git commit -m "perf(run): allow the fleet git-pull phase to run concurrently

53 serial 'git pull --ff-only' calls are 53 network round-trips before the scan
starts. Each touches only its own working tree, so this is the lowest-risk of
the parallelised phases. Best-effort behaviour is unchanged: a repo that will
not fast-forward is still scanned as-is."
```

---

### Task 3: Parallelise the per-repo AST sweep

**Files:**
- Modify: `agent/inventory_scan.py:103` (signature) and `:154-177` (the loop)
- Test: `tests/test_scan_folder_jobs.py` (create)

**Interfaces:**
- Consumes: `pool.ordered_map` from Task 1.
- Produces: `scan_folder(root, state_dir, now, *, engine=None, run=None, git=None,
  progress=None, jobs=1)` — the added keyword is passed by `run_pipeline` in Task 4.

- [ ] **Step 1: Write the failing test**

Create `tests/test_scan_folder_jobs.py`:

```python
import json
import subprocess

from agent.inventory_scan import scan_folder


def _git_init(d, files):
    d.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        (d / rel).write_text(text)
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
                    "--allow-empty", "-q", "-am", "init"], cwd=d, check=True)


def _empty_engine(args):
    return json.dumps([])


def test_scan_folder_preserves_repo_order_when_parallel(tmp_path):
    """Repo records must come back in discovery order, so record['id'] and every
    downstream index mean the same thing at --jobs 4 as at --jobs 1."""
    root = tmp_path / "repos"
    for name in ("alpha", "bravo", "charlie", "delta"):
        _git_init(root / name, {"composer.json": '{"require": {"php": "^7.4"}}'})

    serial = scan_folder([root], tmp_path / "s1", "2026-08-25", run=_empty_engine, jobs=1)
    parallel = scan_folder([root], tmp_path / "s4", "2026-08-25", run=_empty_engine, jobs=4)

    names_serial = [r["path"] for r in serial["doc"]["repos"]]
    names_parallel = [r["path"] for r in parallel["doc"]["repos"]]
    assert names_parallel == names_serial
    assert [r["id"] for r in parallel["doc"]["repos"]] == [r["id"] for r in serial["doc"]["repos"]]


def test_scan_folder_records_an_erroring_repo_rather_than_dropping_it(tmp_path):
    """'Cannot see' is not 'clean' - a repo that blows up must land in reposErrored."""
    root = tmp_path / "repos"
    for name in ("ok1", "boom", "ok2"):
        _git_init(root / name, {"composer.json": '{"require": {}}'})

    def engine(args):
        if any("boom" in str(a) for a in args):
            raise RuntimeError("engine crashed")
        return json.dumps([])

    out = scan_folder([root], tmp_path / "state", "2026-08-25", run=engine, jobs=3)

    errored = [e["repo"] for e in out["doc"]["coverage"]["reposErrored"]]
    assert any("boom" in name for name in errored)
    assert out["doc"]["coverage"]["reposScanned"] == 3
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_scan_folder_jobs.py -q`
Expected: FAIL — `TypeError: scan_folder() got an unexpected keyword argument 'jobs'`

- [ ] **Step 3: Write the minimal implementation**

In `agent/inventory_scan.py`, add `from agent.lib import pool` to the imports and change the
signature on line 103:

```python
def scan_folder(root, state_dir, now, *, engine=None, run=None, git=None, progress=None,
                jobs=1) -> dict:
```

Then replace the entire `for i, (abs_, name) in enumerate(discovered):` block (through the
`except Exception as exc:` clause that ends it) with:

```python
    def _scan_one(indexed):
        i, (abs_, name) = indexed
        tag = f"[{i + 1:>2}/{n}] {name}"
        sha = scan_util.git_meta(abs_, run=git)["head_sha"]
        cached = ir_store.load_repo_cache(state_dir, name, sha, rules_sig) if sha else None
        if cached is not None:
            _p(f"{tag}  cached (HEAD unchanged)")
            cached = {**cached, "id": i + 1}
            cached["shape"] = _shape_of(abs_, name, cached, rule_kinds, attestations)
            return {"record": cached, "unparsed": []}
        _p(f"{tag}  scan: git · manifests · AST endpoints")
        record, note = scan_repo(abs_, name, i + 1, vendors, rules_path,
                                 engine=engine, run=run, git=git,
                                 idiom_instances=idiom_instances)
        record["sourceKind"] = source_kind.get(abs_, "local-git")
        record["shape"] = _shape_of(abs_, name, record, rule_kinds, attestations)
        if sha:
            ir_store.save_repo_cache(state_dir, name, sha, record, rules_sig)
        return {"record": record, "unparsed": note["unparsed"]}

    # The fold below runs in INPUT order, never completion order: `repos`, `reposErrored` and
    # `manifestsUnparsed` are all order-sensitive, and the whole --jobs guarantee is that a
    # parallel run cannot be distinguished from a serial one by its artifacts.
    outcomes = pool.ordered_map(_scan_one, list(enumerate(discovered)), jobs=jobs)
    for (i, (abs_, name)), (out, exc) in zip(enumerate(discovered), outcomes):
        coverage["reposScanned"] += 1
        if exc is not None:                 # no single repo aborts the scan
            _p(f"[{i + 1:>2}/{n}] {name}  ⚠ error: {exc}")
            coverage["reposErrored"].append({"repo": name, "reason": str(exc)})
            continue
        repos.append(out["record"])
        coverage["manifestsUnparsed"] += [{"repo": name, **u} for u in out["unparsed"]]
```

Note: the error `_p(...)` line deliberately moved OUT of the worker and into the fold, so
error lines are emitted in deterministic order even when the work was concurrent.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_scan_folder_jobs.py -q`
Expected: PASS, 2 tests

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: `1509 passed, 3 skipped`

- [ ] **Step 6: Commit**

```bash
git add agent/inventory_scan.py tests/test_scan_folder_jobs.py
git commit -m "perf(scan): allow the per-repo AST sweep to run concurrently

The loop body becomes a worker; coverage is folded from the results in INPUT
order, so repos, reposErrored and manifestsUnparsed are ordered by discovery
rather than by which repo finished first.

The per-repo error path is preserved exactly - a crashing repo is recorded in
reposErrored, never dropped - and its progress line moved into the fold so
error output stays deterministic even when the work was not."
```

---

### Task 4: Thread `--jobs` through the CLI

**Files:**
- Modify: `agent/run.py` (`run_pipeline` signature and its two internal calls)
- Modify: `agent/cli.py:31` (`_cmd_inventory_scan`), `:125-127` (`_cmd_run`),
  `:1584` (`run` parser), `:1791` (`inventory-scan` parser)
- Test: `tests/test_cli_jobs_flag.py` (create)

**Interfaces:**
- Consumes: `_pull_repos(..., jobs=)` from Task 2, `scan_folder(..., jobs=)` from Task 3.
- Produces: `run_pipeline(..., jobs=1)`; `--jobs N` on both CLI commands.

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_jobs_flag.py`:

```python
from agent.cli import main


def test_run_rejects_a_jobs_value_below_one(capsys):
    rc = main(["run", "--root", ".", "--state", "/tmp/x", "--now", "2026-08-25", "--jobs", "0"])
    assert rc == 2
    assert "--jobs" in capsys.readouterr().err


def test_jobs_defaults_to_one_so_ci_behaviour_is_unchanged():
    """CI passes no --jobs. The default must be the serial path, not CPU count."""
    import argparse

    from agent import cli
    parser_holder = {}

    real = argparse.ArgumentParser.parse_args

    def capture(self, argv=None):
        args = real(self, argv)
        parser_holder["args"] = args
        return args

    argparse.ArgumentParser.parse_args = capture
    try:
        try:
            cli.main(["run", "--state", "/tmp/x", "--now", "2026-08-25"])
        except SystemExit:
            pass
    finally:
        argparse.ArgumentParser.parse_args = real

    assert getattr(parser_holder["args"], "jobs", None) == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cli_jobs_flag.py -q`
Expected: FAIL — `unrecognized arguments: --jobs 0` (argparse exits 2 via SystemExit, and
the second test's assertion on `args.jobs` returns `None`)

- [ ] **Step 3: Write the minimal implementation**

In `agent/cli.py`, add to the `run` parser (after the `--progress` line, ~1584):

```python
    pr.add_argument("--jobs", type=int, default=1,
                    help="repos to scan concurrently (default 1 = serial, which is what CI "
                         "runs). Purely a scheduling knob: results are reassembled in "
                         "discovery order, so any --jobs value produces identical artifacts.")
```

Add the same argument to the `inventory-scan` parser (`pis`, ~1791):

```python
    pis.add_argument("--jobs", type=int, default=1,
                     help="repos to scan concurrently (default 1 = serial)")
```

In `_cmd_run`, guard the value before use (immediately after the `if not roots:` block):

```python
    if getattr(args, "jobs", 1) < 1:
        print("run: --jobs must be 1 or greater", file=sys.stderr)
        return 2
```

and pass it through at line 125:

```python
        out = run_pipeline(roots, args.state, args.now,
                           pull=getattr(args, "pull", False), progress=progress,
                           gitlab_hosts=gitlab_hosts, resolve=resolve_verdicts,
                           jobs=getattr(args, "jobs", 1))
```

In `_cmd_inventory_scan`, line 31:

```python
        out = inventory_scan_mod.scan_folder(args.root, args.state, args.now,
                                             progress=progress,
                                             jobs=getattr(args, "jobs", 1))
```

In `agent/run.py`, add `jobs=1` to the `run_pipeline` signature and pass it to both calls:

```python
def run_pipeline(roots, state_dir, now, *, pull=False,
                 engine=None, run=None, git=None, http=None, progress=None,
                 pull_run=None, gitlab_hosts=frozenset(), resolve=None, jobs=1) -> dict:
```

```python
    if pull:
        _pull_repos(roots, pull_run, jobs=jobs)
```

```python
    scan = scan_folder(roots, state_dir, now, engine=engine, run=run, git=git,
                       progress=progress, jobs=jobs)
```

**Also** pass `jobs=jobs` to the second, post-resolution `scan_folder` call inside
`run_pipeline` (the re-scan after `_apply_resolution` succeeds) — it must be the identical
kind of scan, and a re-scan that silently dropped to serial would make `run --resolve`
inconsistent with the first pass.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_cli_jobs_flag.py -q`
Expected: PASS, 2 tests

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: `1511 passed, 3 skipped`

- [ ] **Step 6: Commit**

```bash
git add agent/cli.py agent/run.py tests/test_cli_jobs_flag.py
git commit -m "feat(cli): --jobs N on run and inventory-scan, default 1

No environment fallback and no auto-detection: CI must not change behaviour
because someone forgot to pin a value, so the default is the serial path and
.gitlab-ci.yml needs no edit at all.

The post-resolution re-scan takes the same jobs value as the first pass - it
must be the identical kind of scan, not silently serial."
```

---

### Task 5: Prove the guarantee end-to-end

**Files:**
- Test: `tests/test_parallel_identity.py` (create)

**Interfaces:**
- Consumes: `run_pipeline(..., jobs=)` from Task 4.
- Produces: nothing. This is the gate the whole feature rests on.

- [ ] **Step 1: Write the failing test**

Create `tests/test_parallel_identity.py`:

```python
"""The guarantee --jobs rests on: scheduling changes when work happens, never what is
concluded. If this test cannot be made to pass, the feature does not ship."""
import json
import subprocess

from agent.run import run_pipeline


def _git_init(d, files):
    d.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        (d / rel).write_text(text)
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
                    "--allow-empty", "-q", "-am", "init"], cwd=d, check=True)


def _empty_engine(args):
    return json.dumps([])


def _no_network(url, *, method="GET", body=None, timeout=20):
    return {}


def _fixture_fleet(root):
    _git_init(root / "web", {"composer.json": '{"require": {"php": "^7.4"}}'})
    _git_init(root / "api", {"composer.json": '{"require": {"guzzlehttp/guzzle": "^6.0"}}'})
    _git_init(root / "ui", {"package.json": '{"dependencies": {"axios": "0.21.0"}}'})
    _git_init(root / "svc", {"composer.json": '{"require": {"php": "^8.1"}}'})
    _git_init(root / "job", {"package.json": '{"dependencies": {"moment": "2.20.0"}}'})


def test_serial_and_parallel_scans_produce_identical_artifacts(tmp_path, monkeypatch):
    import agent.audit as audit_mod
    monkeypatch.setattr(audit_mod.eol, "check", lambda *a, **kw: None)

    root = tmp_path / "repos"
    _fixture_fleet(root)

    serial_state = tmp_path / "serial"
    parallel_state = tmp_path / "parallel"

    run_pipeline([root], str(serial_state), "2026-08-25",
                 run=_empty_engine, http=_no_network, jobs=1)
    run_pipeline([root], str(parallel_state), "2026-08-25",
                 run=_empty_engine, http=_no_network, jobs=4)

    for artifact in ("drift.json", "audit.json", "drift.md"):
        assert (serial_state / artifact).read_bytes() == (parallel_state / artifact).read_bytes(), \
            f"{artifact} differs between --jobs 1 and --jobs 4"
```

- [ ] **Step 2: Run the test to verify it fails**

Before Tasks 1-4 are complete this fails with `TypeError: run_pipeline() got an unexpected
keyword argument 'jobs'`. **If you are running this task after Tasks 1-4, it may pass
immediately — that is not acceptable proof.** Verify it is a real gate by temporarily
breaking ordering in `agent/inventory_scan.py`: change the fold to iterate
`sorted(outcomes, key=lambda o: str(o))` instead of input order, confirm this test FAILS,
then revert.

Run: `.venv/bin/python -m pytest tests/test_parallel_identity.py -q`
Expected: FAIL, and you must have seen it fail for an ordering reason at least once.

- [ ] **Step 3: No implementation needed**

Tasks 1-4 provide the behaviour. If the test fails here, the bug is in Task 3's fold, not in
this test — fix `inventory_scan.py`, never this assertion.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_parallel_identity.py -q`
Expected: PASS, 1 test

- [ ] **Step 5: Run the full suite and verify a real scan**

Run: `.venv/bin/python -m pytest -q`
Expected: `1512 passed, 3 skipped`

Then confirm on the real fleet that the artifacts match and `verify` is green:

```bash
cd /home/tops/Projects/tops/drift
export DRIFT_CATALOG_DIR="$PWD/drift-fleet/catalog"
S=./drift-detector-scan/bin/drift-scan
$S run --config drift-fleet/config/drift.yml --state /tmp/j1 --now 2026-08-25 --jobs 1
$S run --config drift-fleet/config/drift.yml --state /tmp/j8 --now 2026-08-25 --jobs 8
diff /tmp/j1/drift.json /tmp/j8/drift.json && echo "IDENTICAL"
```

Expected: `IDENTICAL`, and the `--jobs 8` run measurably faster.

- [ ] **Step 6: Commit**

```bash
git add tests/test_parallel_identity.py
git commit -m "test: prove serial and parallel scans produce identical artifacts

The guarantee --jobs rests on, asserted rather than argued: the same fixture
fleet at --jobs 1 and --jobs 4 must produce byte-identical drift.json,
audit.json and drift.md.

Seen to fail against a deliberately reordered fold before being accepted, per
the repo's rule that a guard is proved against its bug rather than merely
written."
```

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| `agent/lib/pool.py` `ordered_map` | Task 1 |
| `jobs=1` takes a literal serial path | Task 1, step 3 + test 3 |
| Call site 1 — per-repo AST sweep | Task 3 |
| Call site 2 — fleet `git pull` | Task 2 |
| Call site 3 — OSV batch | **Deliberately excluded** — separate branch, per the split |
| `--jobs N` default 1, no env, no auto-detect | Task 4 |
| Errors captured per item, ordered | Task 1 test 2, Task 3 test 2 |
| Identity of all three artifacts | Task 5 |
| Progress log may interleave | Documented in the spec; not asserted, by design |

**Placeholder scan:** none — every code step carries complete code.

**Type consistency:** `ordered_map` returns `list[tuple[result, exc]]` in Task 1 and is
destructured as `(out, exc)` in Task 3 and as `(value, _exc)` in Task 1's tests. Consistent.
`scan_folder(..., jobs=1)` and `run_pipeline(..., jobs=1)` keyword names match across Tasks
3 and 4.

**Deviation from the spec worth flagging at review:** the spec sketched
`ordered_map(fn, items, *, jobs=1, on_error=None)`. `on_error` is dropped — both call sites
want the outcome list rather than a callback, and an unused parameter is a worse API than a
missing one. YAGNI.
