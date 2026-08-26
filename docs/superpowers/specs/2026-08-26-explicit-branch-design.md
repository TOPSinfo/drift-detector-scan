# Explicit branch selection, and the empty branch nobody could see

**Date:** 2026-08-26
**Status:** **implemented** on `feat/explicit-branch` — plan
`docs/superpowers/plans/2026-08-26-explicit-branch.md`. Two deviations taken during
execution, both recorded in the commits: the group refusal moved to resolve time (a
namespace is knowable only from `expand_group`), and "nothing readable" is tested as
`modeled == 0 and unmodeled == 0` **and** empty coverage, because the file counts default
to zero and their absence is not evidence of an empty repo.

## Problem

The scanner clones a repository's **default branch and nothing else**. `source_resolver.py:82`
runs `git clone --depth 1 <url> <dest>` with no `--branch`, so whatever the remote's HEAD points
at is what gets scanned.

On this fleet that assumption does not hold. Many projects' `master`/`main` carries a README and
nothing else — the working code lives on `dev`, `develop` or a release branch. The scan reads the
placeholder, finds no manifests and no source, and reports the repo.

**It reports it as fine.** That is the part that matters. Reproduced in the documentation fleet
committed at `tools/make_demo_fleet.py`:

| repo | what it contains | `languages` | `reasons` | verdict |
|---|---|---|---|---|
| `ops-runbooks` | a README, no code at all | `{}` | `[]` | **`KNOWN`** |
| `design-tokens` | JavaScript, no API calls | `{javascript: 1}` | `[no-egress-signal]` | `UNKNOWN` |

A repo the scanner **could not read** is `KNOWN` — "we looked, it's fine". A repo it *did* read and
found nothing in is honestly `UNKNOWN`. The two are the wrong way round, and the first is
CLAUDE.md principle 1 exactly: *"cannot see" ≠ "clean"*. An empty branch is currently
indistinguishable from a clean one on every surface the tool publishes.

So there are two defects here, not one, and the second exists independently of branches: any
unreadable repo, for any reason, currently renders as a clean zero.

## Goal

Let a deployment state which branch a repository should be scanned on, and make a repository the
scanner could not read say so.

## Non-goals

- **No auto-detection of "the branch with the most code."** Choosing a branch by heuristic is a
  guess, and a wrong guess silently scans the wrong code — which is the failure being fixed, not
  a fix for it.
- **No branch discovery through the GitLab API.** It would work, but it makes the scan depend on
  a second API surface to learn something the config can state exactly, and it would not work for
  the non-GitLab remotes `source_resolver` already supports.
- **No per-branch scanning** (scanning two branches of one repo and diffing them). Out of scope.
- **No change to how local-path roots are resolved.** A local checkout is already on whatever
  branch the operator put it on; this spec governs clones.

## Design

### 1 · Config surface

`fleet` entries accept a string **or** a mapping. Strings remain valid, so no existing config
changes:

```yaml
fleet:
  - https://git.example.com/team/repo-a          # unchanged — the remote's default branch
  - url: https://git.example.com/team/repo-b     # new form
    branch: develop
  - https://git.example.com/a-group           # a group — a `branch` here fails the ROOT (see below)
```

Validation lives in `agent/lib/ops_config.py`, beside the existing rules that already refuse
unknown top-level keys and a fleet spanning more than one host. The mapping form:

- requires `url`, an `https://` URL, validated exactly as the string form is;
- accepts `branch`, a non-empty string;
- refuses any other key, naming it — consistent with `_TOP`'s behaviour.

**Where the group refusal actually happens.** `load_config` is offline and cannot tell a group
URL from a repository URL: `gitlab.expand_group` learns that only by calling the API, returning
`None` when the path is a single project. No static heuristic works either — a nested group
(`/group/subgroup`) has the same two-segment shape as `/user/repo`. So the refusal belongs at
**resolve** time, not load time: when `resolve_sources` expands a root and `expand_group` returns
a namespace while that entry carried a `branch`, the root fails with a reason naming the entry.
That flows through `resolved["errors"]` into `coverage.rootsUnscannable`, which `run` already
prints — "a typo'd or unreachable root buried in a good run must not disappear", as the existing
comment there puts it. `load_config` still validates the mapping's *shape*; only the
group-versus-repo judgement moves.

`load_config` returns `fleet` as a list of `(url, branch|None)` pairs rather than a list of
strings. Every caller is updated; there is no dual-shape return.

**Why `branch` on a group is refused rather than applied.** A group URL expands to many
repositories through `gitlab.expand_group`. `develop` meaning the same thing in all twenty of
them is an assumption nobody verified, and the two forgiving alternatives are both worse: failing
every repo without that branch turns one config line into twenty errors, and falling back per-repo
produces a scan where some repos were read on `develop` and others on `main`, with nothing in the
report distinguishing them. If a group genuinely needs one branch, listing its repos individually
is the honest way to say so.

### 2 · Cloning a named branch

`_default_clone(url, dest)` becomes `_default_clone(url, dest, *, branch=None)`.

- **Fresh clone:** `git clone --depth 1 --branch <b> --single-branch <url> <dest>`.
  `--single-branch` matters: without it a shallow clone still writes remote-tracking refs for
  other branches, which is wasted transfer on a fleet this size.
- **Existing clone:** `git fetch --depth 1 origin <b>` then `git reset --hard FETCH_HEAD`. The
  current code fetches with no refspec, which resolves `FETCH_HEAD` to the default branch — so an
  already-cloned repo would otherwise ignore the configured branch entirely on every run after
  the first. This is the subtle half of the change.
- **A configured branch that does not exist on the remote is an error for that repository.** It
  is recorded in `coverage.reposErrored` with a reason naming the branch, printed on stderr by
  `run`, and — if every discovered repo errors — exits 4, all via the machinery already added for
  `--jobs`. Someone asked for a specific branch and did not get it; scanning a different one and
  reporting findings would be the tool being more confident than its evidence.

`resolve_sources` threads the branch from the config pair to `clone`. Its injected `clone`
parameter gains the same keyword, so the existing offline tests keep working.

### 3 · A repository the scanner could not read

`agent/lib/shapes.py` gains one reason: **`no-readable-source`**, set when the repo's
`languages` map is empty — no file in any language the ruleset covers. That forces the verdict to
`UNKNOWN`.

This is a **fix to an existing defect**, not merely support for the new feature. It applies to any
repo the scanner could not read, whatever the cause: an empty branch, a repo of only Markdown, a
language the ruleset does not cover. Today all of those report `KNOWN`.

The distinction the vocabulary must preserve:

| Situation | `languages` | Verdict | Meaning |
|---|---|---|---|
| Code read, integrations found | non-empty | `KNOWN` | looked, found them |
| Code read, no egress at all | non-empty | `UNKNOWN` + `no-egress-signal` | looked, found nothing |
| **Nothing to read** | `{}` | **`UNKNOWN` + `no-readable-source`** | **could not look** |

The count of repos in the third state is surfaced in coverage so a reader sees "18 repos scanned,
3 with nothing readable" rather than inferring it. `verify` gains an invariant: a repo with empty
`languages` may not carry verdict `KNOWN`.

### 4 · Saying which branch was read

Each repo record already carries `ref` (from `git rev-parse --abbrev-ref HEAD`). `ref_is_default`
sits beside it hardcoded `True`, with the comment *"best-effort locally (v1 simplification)"*.

It becomes real: `false` when the repo was cloned with a configured branch. The report states the
branch for any repo where `ref_is_default` is false, so a scan of `develop` cannot be read as a
scan of `main`. Without this, an override is unfalsifiable from the artifacts — you would have to
read the config to know what was scanned.

## Testing

Written test-first. Each guard is proved against its own bug before being accepted.

1. `load_config` accepts a bare string entry unchanged — the compatibility guarantee.
2. `load_config` accepts `{url, branch}` and returns the pair.
3. `resolve_sources` fails a root that carries a `branch` and expands to a namespace, with the
   entry named, and the failure reaches `coverage.rootsUnscannable`. Asserted against an injected
   `expand_group` returning a project list, so no network is involved.
4. `load_config` refuses an unknown key inside the mapping.
5. A fresh clone with a branch passes `--branch <b> --single-branch` — asserted against a fake
   `clone` that records its argv, since the real one is network-bound.
6. **An existing clone re-fetches the configured branch**, not the default. This is the one a
   naive implementation gets wrong, and a scan would silently drift back to `main` on the second
   run with nothing in the artifacts to show it.
7. A configured branch missing from the remote errors that repo and leaves the others scanned.
8. A repo with no files in any covered language gets `UNKNOWN` + `no-readable-source`, never
   `KNOWN`. Run against `ops-runbooks` in the demo fleet, which reproduces the bug today.
9. A repo with code but no egress keeps `UNKNOWN` + `no-egress-signal` — the two states stay
   distinct rather than collapsing into one.
10. `verify` fails a hand-built document where a repo has empty `languages` and verdict `KNOWN`.

## Risks

| Risk | Mitigation |
|---|---|
| Existing clones keep silently using the default branch | Test 6 asserts the fetch refspec directly |
| `no-readable-source` reclassifies repos and moves published counts | It is a correction; the CHANGELOG says so plainly, and the count of affected repos is stated |
| The mapping form breaks a config nobody re-reads | Strings stay valid and test 1 pins it |
| A group entry with `branch` is only caught once the API is reachable | Accepted: it is the same class as any unresolvable root, and it surfaces the same way. An offline check would have to guess group-ness, and guessing is what this spec exists to remove |
| `--single-branch` changes what a re-run sees on an existing clone | Only new clones use it; existing clones are driven by the explicit fetch refspec |

## Open question, deliberately deferred

Whether the fleet config should also be able to say *"this repo has no code, do not expect
findings"* — an acknowledged-empty marker, so a known-placeholder repo stops appearing in the
`no-readable-source` count every week. That is an attestation, and attestations in this codebase
carry an approver, a basis and an expiry. It should follow the pattern the vendor dispositions
already established, not be invented here.
