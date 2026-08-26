"""Two roots, two DIFFERENT checkouts, one repo identity.

`discover_repos`' collision-free-identity contract holds only within ONE call, and
`resolve_sources` calls it once per root — so two roots that each contain a directory named
`web/` both yield the identity `"web"`. The per-repo cache is keyed
sha256(identity)@head_sha@rules_sig, so at the same HEAD those two DISTINCT repos share one
cache file: the second is served the first's record and is reported using another repo's
results. Serially that is deterministically wrong; under --jobs > 1 the hit/miss decision
becomes a race, so the same inputs can produce a different drift.json — the exact breach the
--jobs guarantee forbids.
"""
import json
import subprocess

import pytest

from agent.inventory_scan import scan_folder
from tests import astgrep_fake

# A FIXED identity + date makes two empty commits hash to the same sha, which is what puts the
# two checkouts on one cache key. The files are written but never `git add`ed, so the commit
# tree stays empty while the working tree — what the scanner actually reads — differs.
_FIXED = ["-c", "user.email=t@t", "-c", "user.name=t",
          "-c", "commit.gpgsign=false"]
_ENV_DATE = {"GIT_AUTHOR_DATE": "2026-01-01T00:00:00+0000",
             "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+0000"}


def _git_init_pinned(d, files):
    import os
    d.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        (d / rel).write_text(text)
    env = {**os.environ, **_ENV_DATE}
    subprocess.run(["git", "init", "-q"], cwd=d, check=True, env=env)
    subprocess.run(["git", *_FIXED, "commit", "--allow-empty", "-q", "-m", "init"],
                   cwd=d, check=True, env=env)


def _head(d):
    return subprocess.run(["git", "-C", str(d), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()


def _engine_for(b_dir):
    """Emit a Stripe call-site for repo B only — A's working tree really is empty."""
    def run(args):
        repo_path = args[-1]
        if repo_path == str(b_dir):
            return astgrep_fake.canned(astgrep_fake.hit("url-literal", "pay.php", 1))
        return astgrep_fake.EMPTY
    return run


@pytest.mark.parametrize("jobs", [1, 4])
def test_duplicate_identity_repos_report_their_own_content(tmp_path, jobs):
    a_root, b_root = tmp_path / "a", tmp_path / "b"
    a, b = a_root / "web", b_root / "web"
    _git_init_pinned(a, {"composer.json": '{"require": {"php": "^8.2"}}'})
    _git_init_pinned(b, {"composer.json": '{"require": {"php": "^8.2"}}',
                         "pay.php": '"https://api.stripe.com/v1/x";\n'})
    assert _head(a) == _head(b), "fixture must put both checkouts on the same HEAD sha"

    out = scan_folder([str(a_root), str(b_root)], str(tmp_path / "state"), "2026-08-25",
                      engine="semgrep", run=_engine_for(b), jobs=jobs)
    repos = out["doc"]["repos"]
    assert [r["path"] for r in repos] == ["web", "web"]
    # B's own file was scanned — it is NOT served A's (endpoint-free) cached record.
    counts = [len(r["endpoints"]) for r in repos]
    assert counts == [0, 1], (
        f"expected A=0 endpoints, B=1; got {counts} — the second `web` was served the "
        f"first's cache entry and reported using another repo's results")
    assert repos[1]["endpoints"][0]["techKey"] == "api:stripe"


def test_duplicate_identity_repos_never_write_a_shared_cache_file(tmp_path):
    """The cache is bypassed entirely for a colliding identity — nothing is written that a
    later run could serve to the wrong checkout."""
    a_root, b_root = tmp_path / "a", tmp_path / "b"
    a, b = a_root / "web", b_root / "web"
    _git_init_pinned(a, {"composer.json": '{"require": {"php": "^8.2"}}'})
    _git_init_pinned(b, {"composer.json": '{"require": {"php": "^8.2"}}',
                         "pay.php": '"https://api.stripe.com/v1/x";\n'})
    state = tmp_path / "state"
    scan_folder([str(a_root), str(b_root)], str(state), "2026-08-25",
                engine="semgrep", run=_engine_for(b))
    cached = list(state.glob("repos_v*/*.json"))
    assert cached == [], f"a colliding identity must not be cached at all; found {cached}"

    # ...and a second run still reads each repo's own content rather than a stale record.
    out = scan_folder([str(a_root), str(b_root)], str(state), "2026-08-26",
                      engine="semgrep", run=_engine_for(b))
    assert [len(r["endpoints"]) for r in out["doc"]["repos"]] == [0, 1]


def test_a_unique_identity_still_uses_the_cache(tmp_path):
    """The bypass is scoped to colliding identities only — incrementality is untouched."""
    root = tmp_path / "repos"
    _git_init_pinned(root / "web", {"composer.json": '{"require": {"php": "^8.2"}}'})
    _git_init_pinned(root / "api", {"composer.json": '{"require": {"php": "^8.1"}}'})
    state = tmp_path / "state"
    calls = {"n": 0}

    def counting(args):
        calls["n"] += 1
        return json.dumps([])

    scan_folder(str(root), str(state), "2026-08-25", engine="semgrep", run=counting)
    assert calls["n"] == 2
    scan_folder(str(root), str(state), "2026-08-26", engine="semgrep", run=counting)
    assert calls["n"] == 2, "unchanged HEADs must still hit the per-repo cache"
