# Explicit Branch Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this
> plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a deployment name the branch a repository is scanned on, and make a repository the
scanner could not read say so instead of reporting `KNOWN`.

**Architecture:** Two independent halves. Tasks 1–2 fix an existing defect in
`agent/lib/shapes.py` — a repo with no readable files reports `KNOWN` — and ship on their own.
Tasks 3–6 add the branch: `fleet` config entries gain an optional `{url, branch}` mapping form,
`resolve_sources` threads the branch to `_default_clone`, and the report states which ref was
actually read.

**Tech Stack:** Python 3.11+, stdlib + PyYAML at runtime, `pytest` for tests.

## Global Constraints

- **Runtime dependencies are stdlib + PyYAML only.**
- **I/O is injected.** `resolve_sources` takes `clone=` and `expand_group=`; every test uses fakes
  and touches neither network nor git.
- **Existing configs must keep working.** A `fleet` of bare strings parses unchanged. Task 3's
  first test pins this.
- **"Cannot see" ≠ "clean" (principle 1).** This is the whole point of Tasks 1–2 and of the
  missing-branch behaviour in Task 5.
- **Prove a guard against its bug (principle 5).** Every test below must be seen to FAIL on the
  defect it targets before it is accepted.
- **Determinism.** Nothing here may introduce ordering that varies run to run.
- **No client identifiers in any file.** Public repo.

## Ground truth, read before writing code

- `agent/lib/shapes.py:138` — `if coverage and attributed == 0 and …` appends `NO_EGRESS_SIGNAL`.
  The `coverage and` guard is why an empty repo escapes: with no languages, `coverage` is `{}`,
  the branch is skipped, `reasons` stays empty, and `verdict` returns `KNOWN`.
- `verdict` already receives `modeled` (`sum(counts.values())`) and `unmodeled` from `build`
  (`shapes.py:178-180`), so "nothing to read at all" is `modeled == 0 and unmodeled == 0`. It does
  **not** receive `counts` itself; do not add it, the two integers are sufficient.
- A repo of *unmodeled* code (`.rs`, `.kt`) already gets `UNMODELED_LANGUAGE` at line 123, so it
  must not also collect the new reason.
- `agent/lib/ops_config.py:217-229` validates `fleet` as a list of `https://` strings sharing one
  host, and returns `{"fleet": [str(u) for u in fleet], "host": …}`.
- `agent/cli.py:117` and `agent/cli.py:781` are the only two consumers: `roots = args.root or cfg["fleet"]`.
- `agent/lib/source_resolver.py:82` clones with `git clone --depth 1 <url> <dest>`; line 74 updates
  an existing clone with `git fetch --depth 1 origin` — **no refspec**, so `FETCH_HEAD` resolves to
  the default branch.
- `agent/lib/gitlab.py:58` `is_group_url` is only a shape gate ("has a path"). Whether a URL is a
  namespace is known only from `expand_group` returning a list rather than `None`.

## File Structure

- `agent/lib/shapes.py` — **modified.** New `NO_READABLE_SOURCE` constant and one branch in `verdict`.
- `agent/lib/verify.py` — **modified.** One invariant: empty `languages` may not be `KNOWN`.
- `agent/lib/ops_config.py` — **modified.** `fleet` accepts the mapping form; returns `(url, branch)` pairs.
- `agent/cli.py` — **modified**, two lines: unpack the pairs at `:117` and `:781`.
- `agent/lib/source_resolver.py` — **modified.** Roots carry an optional branch; group + branch is
  a root error; `_default_clone` takes `branch=`.
- `agent/inventory_scan.py` — **modified**, one line: pass the resolved branch into the repo record.
- `tests/test_shape_unreadable.py` — **created.** Tasks 1–2.
- `tests/test_ops_config_branch.py` — **created.** Task 3.
- `tests/test_source_branch.py` — **created.** Tasks 4–5.
- `tests/test_ref_is_default.py` — **created.** Task 6.

---

### Task 1: A repository with nothing readable is not `KNOWN`

**Files:**
- Modify: `agent/lib/shapes.py:54-60` (constants), `agent/lib/shapes.py:110-155` (`verdict`)
- Test: `tests/test_shape_unreadable.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `shapes.NO_READABLE_SOURCE == "no-readable-source"`, appended by `verdict` when
  `modeled == 0 and unmodeled == 0`. Task 2 asserts the same rule from `verify`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_shape_unreadable.py`:

```python
"""A repo the scanner could not read must never report KNOWN.

REGRESSION, found on a real fleet and reproduced in tools/make_demo_fleet.py: `ops-runbooks`
holds a README and no code. The census finds no files, `signalCoverage` is empty, `verdict`
collects no reasons, and the repo reports KNOWN — "we looked, it's fine". Meanwhile
`design-tokens`, which HAS JavaScript but calls nothing, is honestly UNKNOWN. A repo we could
not read scored healthier than one we could.

`verdict`'s own comment already states the rule for the readable case — "we did not look
successfully; we merely looked. Saying KNOWN there is the lie of omission principle 1 forbids" —
but its `if coverage and …` guard skips the empty case entirely.

The PM-reported symptom is a default branch holding only a README, but the defect is wider: any
unreadable repo, for any reason, currently renders as a clean zero.
"""
from agent.lib import shapes


def test_a_repo_with_nothing_readable_is_unknown():
    v, reasons = shapes.verdict(0, {}, {}, modeled=0, unmodeled=0)
    assert v == "UNKNOWN", "a repo with no readable file reported KNOWN — 'cannot see' as 'clean'"
    assert shapes.NO_READABLE_SOURCE in reasons


def test_the_reason_names_what_happened_not_what_was_found():
    """`no-egress-signal` means 'read it, found no calls'. This one means 'there was nothing to
    read'. Collapsing them would lose the only distinction that matters to a reader."""
    _, reasons = shapes.verdict(0, {}, {}, modeled=0, unmodeled=0)
    assert reasons == [shapes.NO_READABLE_SOURCE], (
        f"expected exactly the unreadable reason, got {reasons}")


def test_a_repo_with_code_but_no_calls_keeps_its_own_reason():
    """The readable-but-quiet case must NOT be reclassified — it is already honest."""
    cov = {"javascript": ["sink", "url", "path-assembly"]}
    v, reasons = shapes.verdict(0, {}, cov, modeled=4, unmodeled=0)
    assert v == "UNKNOWN"
    assert shapes.NO_EGRESS_SIGNAL in reasons
    assert shapes.NO_READABLE_SOURCE not in reasons, (
        "a repo we DID read must not be labelled unreadable")


def test_a_repo_of_unmodeled_code_keeps_unmodeled_language():
    """Rust/Kotlin-only repos already have a reason. They are not 'nothing to read' — there is
    plenty to read, we just ship no rules for it. Two different problems, two different words."""
    v, reasons = shapes.verdict(0, {}, {}, modeled=0, unmodeled=12)
    assert v == "UNKNOWN"
    assert shapes.UNMODELED_LANGUAGE in reasons
    assert shapes.NO_READABLE_SOURCE not in reasons


def test_a_readable_repo_with_findings_is_still_known():
    """The guard must not make everything UNKNOWN."""
    cov = {"php": ["sink", "url", "path-assembly"]}
    v, reasons = shapes.verdict(3, {}, cov, modeled=9, unmodeled=0)
    assert v == "KNOWN", f"a normal repo was reclassified: {reasons}"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_shape_unreadable.py -q`
Expected: FAIL — `AttributeError: module 'agent.lib.shapes' has no attribute 'NO_READABLE_SOURCE'`.
After adding only the constant (not the branch), the first two fail on `verdict` returning
`("KNOWN", [])`. That second failure is the real red: it is the shipped defect.

- [ ] **Step 3: Write the minimal implementation**

In `agent/lib/shapes.py`, beside the other reason constants (~line 54):

```python
NO_READABLE_SOURCE = "no-readable-source"
```

In `verdict`, immediately after `total_files = modeled + unmodeled` and **before** the
`UNMODELED_LANGUAGE` check:

```python
    # Nothing to read at all — no file the census recognised, modelled or not. Distinct from
    # every other reason here: those describe what we found (or failed to attribute) in code we
    # DID read. This one says the repo never offered any. It is the state a README-only default
    # branch produces, and until now it produced no reason at all and therefore KNOWN — the
    # scanner reporting "we looked, it's fine" about a repo it could not look at, which is
    # principle 1 exactly. Returns immediately: every check below reasons about content, and
    # there is none, so any further reason would be describing an absence twice.
    if total_files == 0:
        return "UNKNOWN", [NO_READABLE_SOURCE]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_shape_unreadable.py -q`
Expected: `5 passed`

- [ ] **Step 5: Run the full suite and check what moved**

Run: `.venv/bin/python -m pytest -q`
Expected: `1531 passed, 3 skipped` plus the 5 new = **1536 passed**. If any *existing* test fails,
read it before changing it — a fixture that asserted `KNOWN` for an empty repo was asserting the
bug, and its expectation should change with a comment saying so. A fixture that asserted `KNOWN`
for a repo with real content is a genuine regression in this change.

Then confirm the real-world effect on the demo fleet:

```bash
SP=/tmp/claude-1000/-home-tops-Projects-tops-drift/<session>/scratchpad
./bin/drift-scan run --root $SP/fleet --state $SP/branch-check --now 2026-08-26
.venv/bin/python -c "
import json,collections
d=json.load(open('$SP/branch-check/inventory.json'))
for r in d['repos']:
    s=r.get('shape') or {}
    if not r.get('languages') and not (s.get('languages')):
        print(r['path'], s.get('verdict'), s.get('reasons'))"
```

Expected: `ops-runbooks UNKNOWN ['no-readable-source']`, where it previously read `KNOWN []`.

- [ ] **Step 6: Commit**

```bash
git add agent/lib/shapes.py tests/test_shape_unreadable.py
git commit -m "fix(shapes): a repo with nothing readable is UNKNOWN, not KNOWN

A repository holding only a README reported KNOWN — 'we looked, it is fine' —
because verdict's checks are all guarded on \`coverage\`, and a repo with no
languages has none, so it collected no reasons at all. A repo we could NOT read
scored healthier than one we could and found nothing in.

verdict's own comment states the rule for the readable case: 'we did not look
successfully; we merely looked. Saying KNOWN there is the lie of omission
principle 1 forbids.' The empty case simply fell through it.

no-readable-source is deliberately its own reason rather than reusing
no-egress-signal: 'read it, found no calls' and 'there was nothing to read' are
different facts about a repo, and only the second means the report is blind.
Unmodeled-language repos keep their own reason — there is plenty to read there,
we just ship no rules for it."
```

---

### Task 2: `verify` refuses a document that says otherwise

**Files:**
- Modify: `agent/lib/verify.py`
- Test: `tests/test_shape_unreadable.py` (append)

**Interfaces:**
- Consumes: `shapes.NO_READABLE_SOURCE` (Task 1).
- Produces: a `verify` invariant named `check_unreadable_not_known`, failing a document where a
  repo has empty `languages` and verdict `KNOWN`.

- [ ] **Step 1: Read how an existing invariant is registered**

Run: `grep -n "def check_" agent/lib/verify.py | head -20`
Follow the shape of an existing check exactly — its signature, how it reports a failure, and how
it is registered in the invariant list. Do not invent a second registration style.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_shape_unreadable.py`:

```python
def test_verify_refuses_a_document_calling_an_unreadable_repo_known():
    """The rule lives in two places on purpose. shapes.verdict is where it is computed; verify is
    where a hand-edited or stale drift.json gets caught. A projection that disagrees with the
    contract is exactly what verify exists to refuse."""
    from agent.lib import verify
    doc = {"repos": [
        {"path": "readme-only", "languages": {},
         "shape": {"verdict": "KNOWN", "reasons": [], "languages": {}}},
    ]}
    failures = verify.check_unreadable_not_known(doc)
    assert failures, (
        "verify accepted a repo with no readable source marked KNOWN — the invariant is inert")
    assert "readme-only" in str(failures)


def test_verify_accepts_the_corrected_shape():
    from agent.lib import verify
    doc = {"repos": [
        {"path": "readme-only", "languages": {},
         "shape": {"verdict": "UNKNOWN", "reasons": ["no-readable-source"], "languages": {}}},
    ]}
    assert not verify.check_unreadable_not_known(doc)
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_shape_unreadable.py -q -k verify`
Expected: FAIL — `AttributeError: module 'agent.lib.verify' has no attribute 'check_unreadable_not_known'`

- [ ] **Step 4: Write the minimal implementation**

Add to `agent/lib/verify.py`, following the signature and failure-reporting style of the
neighbouring checks read in Step 1:

```python
def check_unreadable_not_known(doc: dict) -> list:
    """A repo with no readable source may not carry verdict KNOWN.

    Computed in shapes.verdict; asserted here because every published surface is a projection of
    this document, and a projection that says a blind repo is fine is the one error a reader
    cannot detect for themselves.
    """
    bad = []
    for r in doc.get("repos") or []:
        shape = r.get("shape") or {}
        langs = shape.get("languages")
        if langs is None:
            langs = r.get("languages") or {}
        if not langs and shape.get("verdict") == "KNOWN":
            bad.append(f"{r.get('path')}: verdict KNOWN with no readable source")
    return bad
```

Register it in the invariant list alongside the others, exactly as Step 1 showed.

- [ ] **Step 5: Run the tests and the full suite**

Run: `.venv/bin/python -m pytest tests/test_shape_unreadable.py -q` → `7 passed`
Run: `.venv/bin/python -m pytest -q` → `1538 passed, 3 skipped`
Run: `./bin/drift-scan verify --state $SP/branch-check` → still green, now with the new invariant
counted in its summary line.

- [ ] **Step 6: Commit**

```bash
git add agent/lib/verify.py tests/test_shape_unreadable.py
git commit -m "feat(verify): refuse a report that calls an unreadable repo KNOWN

The rule is computed in shapes.verdict; this is where a stale or hand-edited
drift.json gets caught. Every published surface is a projection of that document,
and a projection claiming a blind repo is fine is the one error a reader has no
way to detect for themselves."
```

---

### Task 3: `fleet` accepts `{url, branch}`

**Files:**
- Modify: `agent/lib/ops_config.py:217-236`
- Modify: `agent/cli.py:117`, `agent/cli.py:781`
- Test: `tests/test_ops_config_branch.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `load_config(...)["fleet"]` is now `list[tuple[str, str | None]]` — `(url, branch)`,
  branch `None` for a bare-string entry. Tasks 4–5 consume this shape. There is no dual-shape
  return; both callers in `cli.py` are updated in this task.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ops_config_branch.py`:

```python
"""`fleet` entries may name a branch. Strings must keep working untouched.

Many repos on this fleet keep a README on their default branch and the real code on `dev` or
`develop`, so the scan reads a placeholder. The config is the only place that can state which
branch is real: guessing it (most files, most recent commit) is the failure being fixed, not a fix.
"""
import pytest

from agent.lib import ops_config


def _write(tmp_path, body):
    p = tmp_path / "drift.yml"
    p.write_text(body)
    return str(p)


_BASE = """
version: 1
delivery:
  mode: dry-run
"""


def test_a_plain_string_entry_still_parses(tmp_path):
    """The compatibility guarantee: every config in the wild today is a list of strings."""
    cfg = ops_config.load_config(_write(tmp_path, _BASE + """
fleet:
  - https://git.example.com/team/repo-a
  - https://git.example.com/team/repo-b
"""))
    assert cfg["fleet"] == [("https://git.example.com/team/repo-a", None),
                            ("https://git.example.com/team/repo-b", None)]


def test_a_mapping_entry_carries_its_branch(tmp_path):
    cfg = ops_config.load_config(_write(tmp_path, _BASE + """
fleet:
  - https://git.example.com/team/repo-a
  - url: https://git.example.com/team/repo-b
    branch: develop
"""))
    assert cfg["fleet"] == [("https://git.example.com/team/repo-a", None),
                            ("https://git.example.com/team/repo-b", "develop")]


def test_a_mapping_without_a_url_is_refused(tmp_path):
    with pytest.raises(ops_config.ConfigError, match="url"):
        ops_config.load_config(_write(tmp_path, _BASE + """
fleet:
  - branch: develop
"""))


def test_an_unknown_key_in_the_mapping_is_named(tmp_path):
    """Consistent with the top-level validator, which refuses unknown keys rather than ignoring
    them — a silently-ignored `ref:` would read as configured and do nothing."""
    with pytest.raises(ops_config.ConfigError, match="tag"):
        ops_config.load_config(_write(tmp_path, _BASE + """
fleet:
  - url: https://git.example.com/team/repo-a
    tag: v1.0
"""))


def test_an_empty_branch_is_refused(tmp_path):
    with pytest.raises(ops_config.ConfigError, match="branch"):
        ops_config.load_config(_write(tmp_path, _BASE + """
fleet:
  - url: https://git.example.com/team/repo-a
    branch: ""
"""))


def test_the_host_rule_still_applies_across_both_forms(tmp_path):
    """One fleet, one host — the mapping form must not become a way around it."""
    with pytest.raises(ops_config.ConfigError, match="host"):
        ops_config.load_config(_write(tmp_path, _BASE + """
fleet:
  - https://git.example.com/team/repo-a
  - url: https://other.example.com/team/repo-b
    branch: develop
"""))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_ops_config_branch.py -q`
Expected: FAIL — the string test fails on shape (`[...str] != [...tuple]`) and every mapping test
fails with `fleet entry {...} must be an https:// URL`, because a dict does not start with `https://`.

- [ ] **Step 3: Write the minimal implementation**

In `agent/lib/ops_config.py`, add beside the other module constants:

```python
_FLEET_KEYS = {"url", "branch"}
```

Replace the `fleet` validation block (currently lines 217-229) with:

```python
    fleet = raw.get("fleet")
    if not isinstance(fleet, list) or not fleet:
        raise ConfigError(f"{path}: `fleet` must be a non-empty list of https repo/group URLs")
    hosts = set()
    entries: list = []
    for item in fleet:
        # Two accepted forms. The string form is every config that exists today and must keep
        # parsing byte-for-byte the same; the mapping form exists because a repo's default branch
        # is sometimes a README placeholder and the code lives elsewhere, and only the config can
        # state which branch is real.
        if isinstance(item, dict):
            unknown = set(item) - _FLEET_KEYS
            if unknown:
                raise ConfigError(f"{path}: fleet entry {item!r} has unknown key(s) "
                                  f"{sorted(unknown)} (allowed: {sorted(_FLEET_KEYS)})")
            u = item.get("url")
            if not u:
                raise ConfigError(f"{path}: fleet entry {item!r} needs a `url`")
            branch = item.get("branch")
            if branch is not None and (not isinstance(branch, str) or not branch.strip()):
                raise ConfigError(f"{path}: fleet entry {u!r} has an empty `branch` — omit the "
                                  f"key to use the remote's default branch")
        else:
            u, branch = item, None
        if not str(u).startswith("https://"):
            raise ConfigError(f"{path}: fleet entry {u!r} must be an https:// URL")
        h = _host_of(u)
        if not h:
            raise ConfigError(f"{path}: cannot parse a host from {u!r}")
        hosts.add(h)
        entries.append((str(u), branch))
    if len(hosts) != 1:
        raise ConfigError(f"{path}: all fleet URLs must share one host, got {sorted(hosts)}")
```

and change the returned `fleet` to `entries`:

```python
    return {
        "fleet": entries,
```

In `agent/cli.py`, both call sites change from taking bare URLs to unpacking pairs. At line 117
and line 781, replace:

```python
        roots = args.root or cfg["fleet"]                # flag overrides config
```

with:

```python
        # cfg["fleet"] is [(url, branch|None)]; --root supplies bare paths/urls with no branch,
        # so it is normalised to the same shape rather than the two forms diverging downstream.
        roots = [(r, None) for r in args.root] if args.root else cfg["fleet"]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_ops_config_branch.py -q`
Expected: `6 passed`

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: `1544 passed, 3 skipped`. Existing config tests that asserted a list of strings must be
updated to pairs — that is this task's contract change, not a regression. Any test that fails
because `resolve_sources` received tuples is expected and is fixed in Task 4; if that blocks,
complete Task 4 before re-running the full suite.

- [ ] **Step 6: Commit**

```bash
git add agent/lib/ops_config.py agent/cli.py tests/test_ops_config_branch.py
git commit -m "feat(config): a fleet entry may name the branch to scan

A repo's default branch is sometimes a README placeholder with the real code on
dev or develop, so the scan reads nothing and — before the shapes fix — called it
clean. The config is the only place that can state which branch is real; guessing
it from file counts or commit dates is the failure being fixed, not a fix.

Strings stay valid, so no existing config changes. load_config now returns
(url, branch|None) pairs, and --root normalises to the same shape so the two
forms cannot diverge downstream. Unknown keys inside the mapping are refused by
name, matching the top-level validator: a silently-ignored 'ref:' would read as
configured and do nothing."
```

---

### Task 4: Roots carry a branch; a group with a branch fails

**Files:**
- Modify: `agent/lib/source_resolver.py:87-167` (`resolve_sources`)
- Test: `tests/test_source_branch.py` (create)

**Interfaces:**
- Consumes: `(url, branch)` pairs from Task 3.
- Produces: `resolve_sources(roots, state_dir, *, clone=None, expand_group=None)` where `roots` is
  `list[tuple[str, str | None]]`, and `clone` is called as `clone(url, dest, branch=branch)`.
  Task 5 implements the real `clone`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_source_branch.py`:

```python
"""The configured branch has to reach the clone, and a branch on a group has to be refused.

A group URL expands to many repos. `develop` meaning the same thing in all of them is an
assumption nobody verified, and both forgiving alternatives are worse: failing every repo without
that branch turns one config line into twenty errors, and falling back per-repo produces a scan
where some repos were read on develop and others on main with nothing in the report saying which.
"""
from agent.lib import source_resolver


def _fake_clone(seen):
    def clone(url, dest, *, branch=None):
        seen.append((url, branch))
        return False, "not cloned (test)"      # errors out, we only assert the call
    return clone


def test_the_configured_branch_reaches_the_clone(tmp_path):
    seen = []
    source_resolver.resolve_sources(
        [("https://git.example.com/team/repo-a", "develop")], str(tmp_path),
        clone=_fake_clone(seen), expand_group=lambda u: None)
    assert seen == [("https://git.example.com/team/repo-a", "develop")]


def test_an_entry_with_no_branch_asks_for_none(tmp_path):
    seen = []
    source_resolver.resolve_sources(
        [("https://git.example.com/team/repo-a", None)], str(tmp_path),
        clone=_fake_clone(seen), expand_group=lambda u: None)
    assert seen == [("https://git.example.com/team/repo-a", None)]


def test_a_branch_on_a_group_fails_that_root_and_clones_nothing(tmp_path):
    """Refused where the answer is actually known — expand_group returning a list IS the only
    way to learn a URL is a namespace, so this cannot be checked at config-load time."""
    seen = []
    out = source_resolver.resolve_sources(
        [("https://git.example.com/team-group", "develop")], str(tmp_path),
        clone=_fake_clone(seen),
        expand_group=lambda u: [{"url": "https://git.example.com/team-group/r1.git",
                                 "path": "r1", "archived": False}])
    assert seen == [], "a group entry with a branch must not clone anything"
    assert out["errors"], "the root must be reported, not silently skipped"
    reason = out["errors"][0]["reason"]
    assert "branch" in reason and "develop" in reason, (
        f"the error must name the branch that caused it, got {reason!r}")


def test_a_group_without_a_branch_still_expands(tmp_path):
    seen = []
    source_resolver.resolve_sources(
        [("https://git.example.com/team-group", None)], str(tmp_path),
        clone=_fake_clone(seen),
        expand_group=lambda u: [{"url": "https://git.example.com/team-group/r1.git",
                                 "path": "r1", "archived": False}])
    assert seen == [("https://git.example.com/team-group/r1.git", None)]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_source_branch.py -q`
Expected: FAIL — `resolve_sources` iterates `for root in roots` and calls `str(root)`, so a tuple
becomes the literal string `"('https://…', 'develop')"`, which `is_url` rejects; the tests fail on
`seen == []` and on unexpected error text.

- [ ] **Step 3: Write the minimal implementation**

In `agent/lib/source_resolver.py`, change `_clone_url` to take the branch and pass it through:

```python
    def _clone_url(url: str, branch: str | None = None) -> None:
        """Clone one repo URL into <state>/sources and add its projects (or an error)."""
        iden = scope_edges.identity(url)
        if iden:
            if iden in cloned_ids:
                return
            cloned_ids.add(iden)
        dest = sources_root / slug(url)
        ok, msg = clone(url, str(dest), branch=branch)
        if not ok:
            errors.append({"root": url, "reason": f"could not clone {url!r}: {msg} — this "
                           "reuses your machine's git auth; can you `git clone` it in a "
                           "terminal?"})
            return
        _add_local(str(dest), url, from_url=True)
```

and replace the root loop's header and its group arm:

```python
    for root in roots:
        # roots are (url_or_path, branch|None). A bare string is still accepted so a caller that
        # has not been updated fails loudly here rather than silently scanning default branches.
        if isinstance(root, (tuple, list)):
            raw_root, branch = root[0], (root[1] if len(root) > 1 else None)
        else:
            raw_root, branch = root, None
        s = str(raw_root)
        if is_url(s):
            group = expand_group(s) if gitlab.is_group_url(s) else None
            if group is not None:
                # A namespace is only knowable here — expand_group returning a list IS the test,
                # which is why this cannot live in load_config. One branch name cannot be assumed
                # to mean the same thing across every repo under a group, and a per-repo fallback
                # would produce a scan mixing branches with nothing in the report to say which.
                if branch:
                    errors.append({"root": s, "reason": (
                        f"{s!r} expands to a group of {len(group)} project(s), so `branch: "
                        f"{branch}` cannot be applied — one branch name is not guaranteed to "
                        f"mean the same thing in every repo under it. List the repos "
                        f"individually with their own branches.")})
                    continue
                active = [p for p in group if not p["archived"]]
                if not active:
                    skipped = f" ({len(group)} archived, skipped)" if group else ""
                    errors.append({"root": s, "reason": f"GitLab group {s!r} has no active "
                                   f"projects to scan{skipped}."})
                    continue
                for proj in active:
                    _clone_url(proj["url"])
            else:
                _clone_url(s, branch)
        else:
            p = Path(s)
            if not p.exists() or p.is_file():
                errors.append({"root": s, "reason": diagnose_root(s)})
                continue
            _add_local(s, s, from_url=False)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_source_branch.py -q`
Expected: `4 passed`

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: `1548 passed, 3 skipped`. Existing `resolve_sources` tests pass bare strings; the
`isinstance` branch above keeps them working, which is deliberate — they assert behaviour this
task does not change.

- [ ] **Step 6: Commit**

```bash
git add agent/lib/source_resolver.py tests/test_source_branch.py
git commit -m "feat(sources): thread the configured branch to the clone

A branch on a GROUP entry fails that root instead of being applied. Whether a URL
is a namespace is knowable only here — expand_group returning a list IS the test,
which is why this cannot be checked when the config loads. One branch name is not
guaranteed to mean the same thing in twenty repos, and a per-repo fallback would
produce a scan mixing branches with nothing in the report saying which was which.

The failure lands in the existing errors list, so it surfaces through
rootsUnscannable, which run already prints: 'a typo'd or unreachable root buried
in a good run must not disappear.'"
```

---

### Task 5: Clone and re-fetch the named branch

**Files:**
- Modify: `agent/lib/source_resolver.py:55-85` (`_default_clone`)
- Test: `tests/test_source_branch.py` (append)

**Interfaces:**
- Consumes: the `branch=` keyword from Task 4.
- Produces: `_default_clone(url, dest, *, branch=None)` returning `(ok, message)` unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_source_branch.py`:

```python
import subprocess


def _record_git(calls, rc=0, stderr=""):
    """Stand in for subprocess.run so the argv can be asserted without touching git."""
    class R:
        def __init__(self, code, err):
            self.returncode, self.stderr, self.stdout = code, err, ""

    def run(cmd, **kw):
        calls.append(cmd)
        return R(rc, stderr)
    return run


def test_a_fresh_clone_asks_git_for_the_branch(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", _record_git(calls))
    ok, _ = source_resolver._default_clone("https://git.example.com/t/r",
                                           str(tmp_path / "dest"), branch="develop")
    assert ok
    argv = calls[-1]
    assert "clone" in argv
    assert "--branch" in argv and argv[argv.index("--branch") + 1] == "develop"
    assert "--single-branch" in argv


def test_an_existing_clone_refetches_the_branch_not_the_default(tmp_path, monkeypatch):
    """THE trap in this change. The current fetch has no refspec, so FETCH_HEAD resolves to the
    remote's default branch — an already-cloned repo would silently drift back to main on every
    run after the first, with nothing in the artifacts to show it."""
    dest = tmp_path / "dest"
    (dest / ".git").mkdir(parents=True)
    calls = []
    monkeypatch.setattr(subprocess, "run", _record_git(calls))
    source_resolver._default_clone("https://git.example.com/t/r", str(dest), branch="develop")
    fetch = [c for c in calls if "fetch" in c][0]
    assert fetch[-1] == "develop", (
        f"fetch must name the branch as its refspec, got {fetch!r} — without it FETCH_HEAD is "
        f"the default branch and the configured branch is ignored from the second run onward")


def test_a_missing_branch_is_an_error_not_a_fallback(tmp_path, monkeypatch):
    """Someone asked for a specific branch and did not get it. Scanning a different one and
    reporting findings would be the tool being more confident than its evidence."""
    calls = []
    monkeypatch.setattr(subprocess, "run", _record_git(
        calls, rc=128, stderr="fatal: Remote branch develop not found in upstream origin"))
    ok, msg = source_resolver._default_clone("https://git.example.com/t/r",
                                             str(tmp_path / "dest"), branch="develop")
    assert not ok, "a missing branch must fail the repo, never fall back to the default"
    assert "develop" in msg, f"the message must name the branch asked for, got {msg!r}"


def test_no_branch_keeps_todays_argv_exactly(tmp_path, monkeypatch):
    """The default path must not change: every fleet entry that names no branch is every entry
    that exists today."""
    calls = []
    monkeypatch.setattr(subprocess, "run", _record_git(calls))
    source_resolver._default_clone("https://git.example.com/t/r", str(tmp_path / "dest"))
    argv = calls[-1]
    assert "--branch" not in argv and "--single-branch" not in argv
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_source_branch.py -q -k "clone or refetch or missing or todays"`
Expected: FAIL — `_default_clone() got an unexpected keyword argument 'branch'`.

- [ ] **Step 3: Write the minimal implementation**

Replace `_default_clone`'s signature and its two git invocations:

```python
def _default_clone(url: str, dest: str, *, branch: str | None = None) -> tuple[bool, str]:
    """Clone (or update) `url` into `dest` using the machine's own git auth.

    A GITLAB_TOKEN / DRIFT_GIT_TOKEN in the environment is used via a transient in-memory
    credential helper so it authenticates the clone without ever landing in .git/config
    (the stored remote stays tokenless) or in the tool's state.

    `branch` names the ref to scan. Absent, git picks the remote's default HEAD — which is
    today's behaviour and stays byte-for-byte unchanged.
    """
    dest_p = Path(dest)
    env = os.environ.copy()
    tok = env.get("GITLAB_TOKEN") or env.get("DRIFT_GIT_TOKEN")
    cred = []
    if tok and str(url).startswith("http"):
        env["DRIFT_CLONE_TOKEN"] = tok
        cred = ["-c", "credential.helper=!f(){ echo username=oauth2; "
                      'echo "password=$DRIFT_CLONE_TOKEN"; }; f']
    try:
        if (dest_p / ".git").exists():
            # The refspec is load-bearing. A bare `fetch origin` resolves FETCH_HEAD to the
            # remote's DEFAULT branch, so an already-cloned repo would ignore the configured
            # branch on every run after the first — and nothing in the artifacts would show it,
            # because the scan would look like a perfectly ordinary successful scan.
            fetch = ["git", *cred, "-C", dest, "fetch", "--depth", "1", "origin"]
            if branch:
                fetch.append(branch)
            r = subprocess.run(fetch, capture_output=True, text=True, timeout=300, env=env)
            if r.returncode != 0:
                if branch:
                    # Do NOT keep the existing clone here: it is on some other branch, and
                    # scanning it would report the wrong code under the right repo's name.
                    return False, (f"branch {branch!r} could not be fetched: "
                                   f"{r.stderr.strip()[:120]}")
                return True, f"kept existing clone (fetch failed: {r.stderr.strip()[:120]})"
            subprocess.run(["git", "-C", dest, "reset", "--hard", "FETCH_HEAD"],
                           capture_output=True, text=True, timeout=60, env=env)
            return True, "updated"
        dest_p.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["git", *cred, "clone", "--depth", "1"]
        if branch:
            cmd += ["--branch", branch, "--single-branch"]
        cmd += [str(url), dest]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300, env=env)
        if r.returncode != 0 and branch:
            return False, (f"branch {branch!r} not found on the remote: "
                           f"{(r.stderr or r.stdout).strip()[:160]}")
        return r.returncode == 0, (r.stderr or r.stdout).strip()[:200]
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, str(exc)[:200]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_source_branch.py -q`
Expected: `8 passed`

- [ ] **Step 5: Run the full suite and verify against a real remote**

Run: `.venv/bin/python -m pytest -q` → `1552 passed, 3 skipped`

Then a real clone, which no unit test covers:

```bash
cd /tmp && rm -rf branchtest && mkdir branchtest && cd branchtest
python3 -c "
import sys; sys.path.insert(0, '/home/tops/Projects/tops/drift/drift-detector-scan')
from agent.lib.source_resolver import _default_clone
print(_default_clone('https://github.com/ast-grep/ast-grep', 'sg', branch='main'))
print(_default_clone('https://github.com/ast-grep/ast-grep', 'sg', branch='main'))   # 2nd run
print(_default_clone('https://github.com/ast-grep/ast-grep', 'sg2', branch='no-such-branch'))
"
git -C sg rev-parse --abbrev-ref HEAD
```

Expected: first two succeed, the second printing `updated`; `sg2` fails with a message naming
`no-such-branch`; the checked-out ref is `main`.

- [ ] **Step 6: Commit**

```bash
git add agent/lib/source_resolver.py tests/test_source_branch.py
git commit -m "feat(sources): clone and re-fetch the configured branch

--branch --single-branch on a fresh clone, and — the load-bearing half — an
explicit refspec on the fetch used for an EXISTING clone. A bare 'fetch origin'
resolves FETCH_HEAD to the remote's default branch, so a repo cloned once would
have ignored its configured branch on every run afterwards, and nothing in the
artifacts would have shown it: the scan would look like an ordinary success.

A branch that does not exist fails the repo rather than falling back. Someone
asked for specific code and did not get it; scanning something else and reporting
findings against it is the tool being more confident than its evidence. The same
applies to the existing-clone path, which must not keep a checkout sitting on
another branch."
```

---

### Task 6: The report says which ref it read

**Files:**
- Modify: `agent/lib/scan_util.py:44-53` (`git_meta`), `agent/inventory_scan.py`
- Test: `tests/test_ref_is_default.py` (create)

**Interfaces:**
- Consumes: the resolved branch from Task 4.
- Produces: a repo record whose `ref_is_default` is `False` when a branch was configured, and
  whose `ref` names it.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ref_is_default.py`:

```python
"""A scan of `develop` must not read as a scan of `main`.

`ref_is_default` was hardcoded True with the comment "best-effort locally (v1 simplification)".
Once a branch can be configured, that constant becomes a false statement in a published artifact:
without it, an override is unfalsifiable from the report — you would have to read the config to
learn what was actually scanned.
"""
import subprocess

from agent.lib import scan_util


def _repo(tmp_path, branch):
    d = tmp_path / "r"
    d.mkdir()
    (d / "composer.json").write_text('{"require": {"php": "^8.2"}}')
    run = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run(["git", "init", "-q", "-b", branch, str(d)], check=True)
    subprocess.run([*run, "-C", str(d), "add", "-A"], check=True)
    subprocess.run([*run, "-C", str(d), "commit", "-q", "-m", "x"], check=True)
    return str(d)


def test_git_meta_reports_the_ref_it_actually_read(tmp_path):
    meta = scan_util.git_meta(_repo(tmp_path, "develop"))
    assert meta["ref"] == "develop"


def test_ref_is_default_is_false_when_a_branch_was_configured(tmp_path):
    meta = scan_util.git_meta(_repo(tmp_path, "develop"), configured_branch="develop")
    assert meta["ref_is_default"] is False, (
        "a repo scanned on a configured branch still claimed to be on its default — the override "
        "is then invisible in every published surface")


def test_ref_is_default_stays_true_when_no_branch_was_configured(tmp_path):
    meta = scan_util.git_meta(_repo(tmp_path, "main"))
    assert meta["ref_is_default"] is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_ref_is_default.py -q`
Expected: FAIL — `git_meta() got an unexpected keyword argument 'configured_branch'`.

- [ ] **Step 3: Write the minimal implementation**

In `agent/lib/scan_util.py`:

```python
def git_meta(repo_abs: str, *, run=_default_git, configured_branch: str | None = None) -> dict:
    def g(*a):
        return run(["-C", repo_abs, *a]) or ""
    return {
        "head_sha": g("rev-parse", "HEAD"),
        "remote_url": normalize_remote(g("remote", "get-url", "origin")),
        "ref": g("rev-parse", "--abbrev-ref", "HEAD"),
        "last_activity_at": g("log", "-1", "--format=%cI"),
        # False exactly when the deployment named a branch. Previously hardcoded True with the
        # note "best-effort locally (v1 simplification)"; once a branch can be configured that
        # constant is a false statement in a published artifact, and it is the only thing that
        # makes an override falsifiable from the report rather than from the config file.
        "ref_is_default": configured_branch is None,
    }
```

In `agent/inventory_scan.py`, carry the branch from the resolved source through to the record.
`resolve_sources` already returns `(abs_dir, identity, kind)` triples; extend the project tuple to
carry the branch as a fourth element and pass it into `scan_repo`'s `git_meta` call. Follow the
existing unpacking sites — `discovered = [(abs_, ident) for abs_, ident, _kind in resolved["projects"]]`
at `inventory_scan.py:143` and `source_kind` on the next line — and add a `source_branch` map
keyed the same way, read where `git_meta` is called in `agent/lib/repo_scan.py:16`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_ref_is_default.py -q`
Expected: `3 passed`

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: `1555 passed, 3 skipped`

- [ ] **Step 6: Commit**

```bash
git add agent/lib/scan_util.py agent/inventory_scan.py agent/lib/repo_scan.py tests/test_ref_is_default.py
git commit -m "feat(scan): say which ref was actually read

ref_is_default was hardcoded True — 'best-effort locally (v1 simplification)'.
Once a branch can be configured, that constant is a false statement in a
published artifact. It is now false exactly when a branch was named, which is
what makes an override falsifiable from the report instead of from the config
file: a scan of develop can no longer read as a scan of main."
```

---

### Task 7: Document it

**Files:**
- Modify: `CHANGELOG.md` (`## Unreleased`)
- Modify: `docs/superpowers/specs/2026-08-26-explicit-branch-design.md` (status line)

- [ ] **Step 1: Add the CHANGELOG entries**

Under `### Added`, matching the surrounding prose style — a bold lede, then why:

```markdown
- **A fleet entry may name the branch to scan.** A repository's default branch is not always where
  its code lives: on a real fleet several projects keep a README on `master` and develop on `dev`,
  so the scan read a placeholder. A `fleet` entry may now be `{url: …, branch: develop}` instead of
  a bare URL; strings stay valid, so no existing config changes. A branch that does not exist on
  the remote **fails that repository** rather than falling back to the default — someone asked for
  specific code and did not get it, and scanning something else while reporting findings against
  it is the failure this tool exists to refuse. A branch on a *group* URL is refused too: one
  branch name is not guaranteed to mean the same thing across every repo under a namespace. The
  report records which ref was read, so a scan of `develop` cannot read as a scan of `main`.
```

Under `### Fixed`:

```markdown
- **A repository the scanner could not read reported `KNOWN`.** A repo holding only a README —
  no manifest, no source in any language the ruleset covers — collected no findings and no
  reasons, and was published as `KNOWN`: "we looked, it is fine". A repo that *was* read and
  genuinely contained no API calls was honestly `UNKNOWN`, so the repo we could not see scored
  healthier than the one we could. `verdict`'s checks were all guarded on having languages, and an
  empty repo has none. It now carries `no-readable-source` and is `UNKNOWN`, `verify` refuses a
  document that says otherwise, and this **will move counts** on any fleet containing such repos —
  correctly, and for the first time visibly.
```

- [ ] **Step 2: Update the design doc's status**

Change `**Status:** design approved, not implemented` to name the branch and the plan, as the
`--jobs` design doc does.

- [ ] **Step 3: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: `1555 passed, 3 skipped`

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md docs/superpowers/specs/2026-08-26-explicit-branch-design.md
git commit -m "docs: changelog explicit branch selection and the unreadable-repo fix

The Fixed entry says plainly that counts will move. A correction that silently
changes published figures is indistinguishable from a regression to whoever reads
the report next week."
```

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| `fleet` accepts `{url, branch}`, strings still valid | Task 3 |
| Mapping validated: `url` required, unknown keys refused, empty branch refused | Task 3 |
| `branch` on a group refused **at resolve time** | Task 4 |
| `--branch --single-branch` on a fresh clone | Task 5 |
| Explicit refspec on the existing-clone fetch | Task 5 |
| Missing branch errors the repo, others still scanned | Task 5 + existing `reposErrored` machinery |
| `no-readable-source`, forcing `UNKNOWN` | Task 1 |
| `verify` invariant | Task 2 |
| `ref_is_default` becomes truthful | Task 6 |
| Coverage count of unreadable repos | **Partly** — Task 1 makes them `UNKNOWN` and therefore
  visible in the existing shape counts. A dedicated `coverage.reposUnreadable` figure was in the
  spec's §3 and is NOT implemented; see below. |

**Placeholder scan:** none. Task 6 Step 3 describes the `inventory_scan` change by naming the
exact call sites rather than pasting code, because that file changed under the `--jobs` work and
the surrounding lines should be read fresh; every other code step is complete.

**Type consistency:** `load_config()["fleet"]` is `list[tuple[str, str | None]]` in Task 3 and is
destructured as `(raw_root, branch)` in Task 4. `clone(url, dest, *, branch=None)` is called that
way in Task 4 and defined that way in Task 5. `git_meta(..., configured_branch=None)` in Task 6
matches its test.

**Deviation from the spec, flagged for review:** the spec's §3 says "the count of repos in the
third state is surfaced in coverage so a reader sees '18 repos scanned, 3 with nothing readable'".
This plan does not add a dedicated counter — Task 1 makes those repos `UNKNOWN` with a distinct
reason, which the existing shape reporting already surfaces, and a second counter for the same
fact is a second thing to keep in sync. If the digest should state it as its own figure, that is
a small follow-up task against `_rollup_coverage`, not a change to any task here.
