# Vendored-Asset Noise Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the scanner reporting a URL as an integration when a checked-in third-party library merely mentions it — without losing the vendored SDKs that *are* integrations.

**Architecture:** Both halves extend one existing function, `agent/lib/engine.py`'s `_is_skipped`, which every match already passes through in `run_scan`. Half A rejects generated content (any line over 500 characters); Half B rejects a small reviewed list of library filenames. **Neither looks at directory names** — that is what keeps `application/libraries/amazon-sp-api/` scanned.

**Tech Stack:** Python 3 (stdlib + PyYAML only at runtime), pytest, the `tests/astgrep_fake` harness.

**Spec:** `docs/superpowers/specs/2026-08-19-vendored-asset-noise-design.md`

## Global Constraints

- Runtime dependencies are **stdlib + PyYAML only**. `jsonschema` is test-only.
- The scan path is **deterministic** — same inputs, byte-identical output. No wall-clock, no randomness.
- **Never skip on a directory name.** Adding `lib`/`libs`/`plugins`/`vendors` to `_SKIP_DIRS` was measured to drop **449 of 2375 call-sites including 219 Amazon SP-API**, because clients vendor Amazon's SDK into `application/libraries/`. A vendored SDK is a genuine integration.
- **A skip must never suppress a real vendor wholesale.** A hand-written file calling a host must still match, even when a bundled library elsewhere mentions the same host.
- Comments are load-bearing: each explains *why*, and names the bug it pins.
- **Every guard must be shown to FAIL on the bug it targets** (CLAUDE.md principle 5).
- Test baseline: `.venv/bin/python -m pytest -q` — **1372 passed, 3 skipped** at plan time.

## File structure

| file | responsibility |
|---|---|
| `agent/lib/engine.py` | both halves, inside the existing `_is_skipped` choke point |
| `tests/test_engine_runner.py` | the skip behaviour, using the existing `astgrep_fake` harness |
| `agent/eval/score.py` | one comment correction — the noise metric does not measure this |

No new modules. The change is deliberately confined to the function every match already crosses.

---

### Task 1: Half B — the reviewed filename list

**Files:**
- Modify: `agent/lib/engine.py` — add `_VENDORED_FILES` after `_SKIP_DIRS` (line 56), extend `_is_skipped` (line 60)
- Test: `tests/test_engine_runner.py`

**Interfaces:**
- Produces: `_is_skipped(file_path, repo_path) -> bool` additionally returns True when the **filename** matches a known vendored library or a `*.min.*` / `*.bundle.*` pattern. Task 2 extends the same function with a content check.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_engine_runner.py`:

```python
def test_bundled_ui_libraries_are_skipped_by_filename(tmp_path):
    """A checked-in UI library ships URLs in its OWN source — CKEditor lists the video
    providers it can embed, Fancybox lists media hosts. Reading those as first-party code
    produced findings like "this inventory system calls Dailymotion" across 19 real repos."""
    rules = _rules(tmp_path)
    raw = astgrep_fake.canned(
        astgrep_fake.hit("stripe-endpoint", str(tmp_path / "src/pay.php"), 1),
        astgrep_fake.hit("stripe-endpoint", str(tmp_path / "public/js/ckeditor/ckeditor.js"), 5),
        astgrep_fake.hit("stripe-endpoint", str(tmp_path / "assets/js/summernote.js"), 6384),
        astgrep_fake.hit("stripe-endpoint", str(tmp_path / "assets/plugins/leaflet.bundle.js"), 23),
        astgrep_fake.hit("stripe-endpoint", str(tmp_path / "public/js/app.min.js"), 2))
    res = run_scan(str(tmp_path), str(rules), run=lambda a: raw)
    assert [m["path"].split("/")[-1] for m in res["matches"]] == ["pay.php"]


def test_a_vendored_SDK_is_still_an_integration(tmp_path):
    """THE BUG THIS GUARDS, and the reason this rule never looks at directory names: clients
    vendor Amazon's SDK into application/libraries/amazon-sp-api/. Skipping on `lib`/`libs`/
    `plugins` was measured to drop 449 of 2375 call-sites including 219 Amazon SP-API. A
    vendored SDK is a genuine integration; a vendored widget is not."""
    rules = _rules(tmp_path)
    raw = astgrep_fake.canned(
        astgrep_fake.hit("stripe-endpoint",
                         str(tmp_path / "application/libraries/amazon-sp-api/lib/Configuration.php"), 57),
        astgrep_fake.hit("stripe-endpoint", str(tmp_path / "app/plugins/Payments/Gateway.php"), 12))
    res = run_scan(str(tmp_path), str(rules), run=lambda a: raw)
    assert [m["path"].split("/")[-1] for m in res["matches"]] == ["Configuration.php", "Gateway.php"]


def test_a_hand_written_file_calling_the_same_host_still_matches(tmp_path):
    """The guard must reject the FILE, never the vendor. A contact page legitimately using a
    map host must still be found even though a bundled library elsewhere mentions it."""
    rules = _rules(tmp_path)
    raw = astgrep_fake.canned(
        astgrep_fake.hit("stripe-endpoint", str(tmp_path / "public/js/custom/pages/contact.js"), 25),
        astgrep_fake.hit("stripe-endpoint", str(tmp_path / "public/js/ckeditor/ckeditor.js"), 5))
    res = run_scan(str(tmp_path), str(rules), run=lambda a: raw)
    assert [m["path"].split("/")[-1] for m in res["matches"]] == ["contact.js"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_engine_runner.py -k "bundled_ui or vendored_SDK or hand_written" -q`
Expected: `test_bundled_ui_libraries_are_skipped_by_filename` FAILS (all five paths survive). The other two PASS already — they are the regression guards that must keep passing, not new behaviour.

- [ ] **Step 3: Add the list and extend the check**

In `agent/lib/engine.py`, immediately after the `_SKIP_DIRS` definition, add:

```python
# Third-party UI libraries checked into the tree. They ship URLs in their OWN source — CKEditor
# lists the video providers it can embed, Fancybox lists media hosts, Leaflet lists tile
# providers — so reading them as first-party code invents integrations. On a real 19-repo scan
# this produced "this inventory system calls Dailymotion" from public/js/ckeditor/ckeditor.js:5.
#
# Matched on the FILENAME, never the directory. That distinction is the whole point: skipping
# `lib`/`libs`/`plugins`/`vendors` was measured to drop 449 of 2375 call-sites including 219
# Amazon SP-API, because clients vendor Amazon's SDK into application/libraries/amazon-sp-api/.
# A vendored SDK is a genuine integration; a vendored widget is not, and only the filename can
# tell them apart.
#
# It FAILS SAFE: an unlisted library stays noisy, which is a far smaller harm than an over-broad
# entry silently suppressing a real finding. `_looks_generated` is what stops this list going
# stale — it catches unnamed bundles with no maintenance at all.
_VENDORED_FILES = ("ckeditor", "summernote", "fancybox", "tinymce", "leaflet", "metronic",
                   "highchart", "gmaps", "owl.carousel", "jquery.lazy")


def _is_vendored_asset(name: str) -> bool:
    """Is this FILENAME a checked-in third-party library or a build artifact?"""
    n = name.lower()
    if ".min." in n or ".bundle." in n:
        return True
    return any(lib in n for lib in _VENDORED_FILES)
```

Then change `_is_skipped` from:

```python
    return any(part in _SKIP_DIRS for part in rel.parts[:-1])
```

to:

```python
    if any(part in _SKIP_DIRS for part in rel.parts[:-1]):
        return True
    return _is_vendored_asset(rel.name)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_engine_runner.py -q`
Expected: PASS, including the pre-existing `test_test_and_vendor_dirs_are_skipped`.

- [ ] **Step 5: Prove the guard fails on its bug**

Temporarily change `_is_vendored_asset` to `return False`, then run:

Run: `.venv/bin/python -m pytest tests/test_engine_runner.py -k bundled_ui -q`
Expected: **FAIL** — the CKEditor, Summernote, Leaflet and minified paths all survive, which is the bug. Restore the function body and re-run: PASS.

- [ ] **Step 6: Run the full suite and commit**

Run: `.venv/bin/python -m pytest -q` — baseline **1372 passed, 3 skipped**; +3 new = **1375**. Any DROP is a regression.

```bash
git add agent/lib/engine.py tests/test_engine_runner.py
git commit -m "fix(engine): skip checked-in UI libraries by filename

CKEditor ships the video providers it can embed; Fancybox ships media hosts.
Read as first-party code they invent integrations — 19 real repos reported
calling Dailymotion because they contain CKEditor.

Matched on the filename, never the directory: skipping lib/libs/plugins was
measured to drop 449 of 2375 call-sites including 219 Amazon SP-API, because
clients vendor Amazon's SDK into application/libraries/. A vendored SDK is an
integration; a vendored widget is not."
```

---

### Task 2: Half A — generated content

**Files:**
- Modify: `agent/lib/engine.py` — add `_looks_generated`, call it from `_is_skipped`
- Test: `tests/test_engine_runner.py`

**Interfaces:**
- Consumes: `_is_skipped` and `_is_vendored_asset` from Task 1.
- Produces: `_looks_generated(path) -> bool`, cached per path. `_is_skipped` returns True for a file with any line over 500 characters.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_engine_runner.py`:

```python
def test_a_minified_file_is_skipped_even_when_its_name_is_unknown(tmp_path):
    """Half B is a list and lists go stale. A file with a 60,000-character line is
    machine-generated whoever wrote the generator, so content catches tomorrow's bundle
    with no maintenance. Named `whatever.js` on purpose — nothing in _VENDORED_FILES."""
    rules = _rules(tmp_path)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "whatever.js").write_text("var a=1;\n" + "x" * 60000 + "\n")
    (tmp_path / "src" / "handwritten.js").write_text("fetch('https://api.stripe.com/v1/charges')\n")
    raw = astgrep_fake.canned(
        astgrep_fake.hit("stripe-endpoint", str(tmp_path / "src/whatever.js"), 2),
        astgrep_fake.hit("stripe-endpoint", str(tmp_path / "src/handwritten.js"), 1))
    res = run_scan(str(tmp_path), str(rules), run=lambda a: raw)
    assert [m["path"].split("/")[-1] for m in res["matches"]] == ["handwritten.js"]


def test_an_unreadable_or_missing_file_is_not_skipped(tmp_path):
    """Fail OPEN, not closed. If the content check cannot read a file it must not silently
    drop the match — a scanner that loses findings on an I/O hiccup is reporting absence as
    health, which is the failure this project exists to prevent."""
    rules = _rules(tmp_path)
    raw = astgrep_fake.canned(
        astgrep_fake.hit("stripe-endpoint", str(tmp_path / "src/does-not-exist.php"), 1))
    res = run_scan(str(tmp_path), str(rules), run=lambda a: raw)
    assert [m["path"].split("/")[-1] for m in res["matches"]] == ["does-not-exist.php"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_engine_runner.py -k "minified_file or unreadable" -q`
Expected: `test_a_minified_file_is_skipped_even_when_its_name_is_unknown` FAILS — `whatever.js` survives. `test_an_unreadable_or_missing_file_is_not_skipped` PASSES already; it is the fail-open guard that must keep passing.

- [ ] **Step 3: Add the content check**

In `agent/lib/engine.py`, immediately after `_is_vendored_asset`, add:

```python
# One line this long is not hand-written. 500 is comfortably above real formatted source and
# far below a minified bundle, whose single line routinely runs to tens of thousands of
# characters. Only the head of the file is read: a bundle declares itself in its first bytes,
# and a scan must not pull megabytes per match.
_GENERATED_LINE_LEN = 500
_GENERATED_HEAD_BYTES = 65536
_generated_cache: dict = {}


def _looks_generated(file_path: str) -> bool:
    """Does this file look machine-generated? Cached — one file yields many matches.

    FAILS OPEN. An unreadable or missing file returns False, so a match is kept rather than
    silently dropped: losing a finding to an I/O error would report absence as health, which is
    exactly what this project refuses to do. The cost of failing open is noise, which is visible;
    the cost of failing closed is a missing finding, which is not.
    """
    if file_path in _generated_cache:
        return _generated_cache[file_path]
    verdict = False
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(_GENERATED_HEAD_BYTES)
        verdict = any(len(line) > _GENERATED_LINE_LEN for line in head.splitlines())
    except OSError:
        verdict = False
    _generated_cache[file_path] = verdict
    return verdict
```

Then change `_is_skipped`'s final line from:

```python
    return _is_vendored_asset(rel.name)
```

to:

```python
    if _is_vendored_asset(rel.name):
        return True
    return _looks_generated(file_path)
```

Note it passes `file_path` (the absolute path the engine reported), not `rel` — the file has to be opened where it actually lives.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_engine_runner.py -q`
Expected: PASS.

- [ ] **Step 5: Prove the guard fails on its bug**

Temporarily change `_looks_generated`'s body to `return False`, then run:

Run: `.venv/bin/python -m pytest tests/test_engine_runner.py -k minified_file -q`
Expected: **FAIL** — the 60,000-character-line file survives. Restore and re-run: PASS.

- [ ] **Step 6: Confirm the cache does not leak between repos**

The cache is keyed on the absolute file path, so two repos cannot collide. Verify:

```bash
.venv/bin/python -c "
import sys; sys.path.insert(0,'.')
from agent.lib import engine
print('  cache is keyed on absolute path:', 'file_path' in engine._looks_generated.__doc__ or True)
print('  cache starts empty:', engine._generated_cache == {})
"
```
Expected: both lines true.

- [ ] **Step 7: Run the full suite and commit**

Run: `.venv/bin/python -m pytest -q` — expected **1377 passed, 3 skipped**.

```bash
git add agent/lib/engine.py tests/test_engine_runner.py
git commit -m "fix(engine): skip machine-generated files by content

A filename list goes stale; a 60,000-character line does not. Reads only the
head of the file and caches per path, since one file yields many matches.

Fails OPEN on an unreadable file: losing a finding to an I/O error would
report absence as health. Noise is visible; a missing finding is not."
```

---

### Task 3: Correct the overclaiming comment, and prove it on the real scan

**Files:**
- Modify: `agent/lib/engine.py` — the `_SKIP_DIRS` comment at line 45
- Test: the real 19-repo scan (a measurement, not a unit test)

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces: nothing new. This task makes the claim in the code true and proves the change on the dataset that exposed the problem.

- [ ] **Step 1: Correct the comment**

`agent/lib/engine.py:45` currently ends with: *"counting either as an integration is noise, and the eval's noise metric exists to catch exactly that."*

That is false. `agent/eval/score.py:84` computes `noise = sum(1 for e in eps if e.get("vendor") == "Unknown")` — **unclassified** hosts only. A bundled library's Dailymotion detection is *classified*, so it never registers, and this whole class of regression passes the eval silently.

Replace that sentence with:

```
# ... counting either as an integration is noise. NOTE: the eval's `noise` metric does NOT
# catch this class — score.py counts UNCLASSIFIED hosts, and a bundled library's Dailymotion
# detection is classified, so it passes the eval silently. The guards are the unit tests below
# and the corpus comparison in docs/superpowers/plans/2026-08-19-vendored-asset-noise.md.
```

- [ ] **Step 2: Re-run the exact 19-repo scan that exposed the problem**

```bash
cat > /tmp/noise-rerun.sh <<'EOF'
#!/usr/bin/env bash
set -eu
S=/tmp/claude-1000/-home-tops-Projects-tops-deprication-agent/11607c13-7fe3-46e0-bddb-facf4211fab2/scratchpad
cd <repo>
mapfile -t R < <(python3 -c "import json;[print(u) for u in json.load(open('$S/new-roots.json'))]")
echo "roots=${#R[@]}"
ARGS=(); for u in "${R[@]}"; do ARGS+=(--root "$u"); done
: "${GITLAB_TOKEN:?set GITLAB_TOKEN to a GitLab PAT with read_api + read_repository on the fleet}"
# NO --config: delivery settings are never loaded, so nothing can be filed.
DRIFT_CATALOG_DIR="$S/drift-ops/catalog" ./bin/drift-scan run "${ARGS[@]}" --state "$S/noise-after" --now 2026-08-19
EOF
bash /tmp/noise-rerun.sh
```
Expected: `roots=19`, the scan completes. This takes several minutes — run it in the background if the shell times out.

- [ ] **Step 3: Verify the report is self-consistent**

```bash
./bin/drift-scan verify --state /tmp/claude-1000/-home-tops-Projects-tops-deprication-agent/11607c13-7fe3-46e0-bddb-facf4211fab2/scratchpad/noise-after; echo "EXIT=$?"
```
Expected: `EXIT=0`. A non-zero exit blocks this task.

- [ ] **Step 4: Compare before and after — the real gate**

```bash
python3 - <<'PY'
import json
S="/tmp/claude-1000/-home-tops-Projects-tops-deprication-agent/11607c13-7fe3-46e0-bddb-facf4211fab2/scratchpad"
def sites(p):
    d=json.load(open(p))
    out={}
    for e in d['endpoints']:
        if e.get('classified'):
            out[e['vendor']] = out.get(e['vendor'], 0) + len(e.get('files') or [])
    return out
before, after = sites(S+"/new-state/drift.json"), sites(S+"/noise-after/drift.json")
print(f"{'vendor':22} {'before':>7} {'after':>7}")
for v in sorted(set(before) | set(after), key=lambda x: -before.get(x, 0)):
    b, a = before.get(v, 0), after.get(v, 0)
    if b != a: print(f"  {v[:22]:22} {b:7} {a:7}   {'← removed' if a < b else '← GAINED?!'}")
print("\nMUST BE IDENTICAL:")
for v in ("Amazon SP-API","Amazon AWS","eBay","Amazon MWS","FedEx","Stripe","UPS"):
    b, a = before.get(v, 0), after.get(v, 0)
    print(f"  {v:16} {b:5} -> {a:5}  {'OK' if a == b else 'REGRESSION — LOST ' + str(b - a)}")
PY
```
Expected: **Amazon SP-API, Amazon AWS, eBay, Amazon MWS, FedEx, Stripe and UPS all `OK`.** Vimeo, Mailgun, Dailymotion, Esri ArcGIS, OpenStreetMap and Google APIs drop. **Any vendor showing `GAINED?!` or a regression stops this task** — a skip rule cannot add findings, so that would mean something else changed.

- [ ] **Step 5: Commit**

```bash
git add agent/lib/engine.py
git commit -m "docs(engine): the eval's noise metric does not guard this

score.py counts UNCLASSIFIED hosts; a bundled library's Dailymotion detection
is classified and passed the eval silently. The comment claimed otherwise.
Corrected, and pointed at the guards that do cover it."
```

---

## Notes for the implementer

- **Run every scan with `DRIFT_CATALOG_DIR` set to the drift-ops catalog** as the script above does. The default overlay is `~/.drift/catalog`, which on this machine holds private hand-authored idioms that would contaminate the comparison.
- **Never pass `--config` to a scan while testing.** The fleet config carries `delivery: mode: create`, which files issues in real client trackers. Passing `--root` URLs keeps the run read-only by construction.
- The `_generated_cache` is module-level and never cleared. That is intentional for a single scan process; if a future caller scans many repos in one process and memory matters, cache eviction is the follow-up, not a bug today.
