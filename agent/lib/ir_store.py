"""Persist the inventory IR + a per-repo cache keyed repo@head_sha (the incrementality substrate).
A cache hit (same sha) lets the scanner reuse a repo's record; a changed sha misses -> re-scan."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

# Per-repo cache schema. BUMP when the record shape changes so pre-upgrade caches are
# invalidated (a stale cache without new fields would silently under-report — e.g. a repo
# scanned before privateSources/versionSource existed would look "clean").
_CACHE_SCHEMA = 11     # 10->11: for commits 133de9c..4db48b4 of the secret-detection branch,
                       # v10 records could carry a FAILED secrets scan (`secrets: []`, no
                       # `secretsErrors` key at all) written unconditionally — indistinguishable
                       # from a repo actually checked and found clean. Any state dir populated
                       # during that window must not be trusted; bump past it so those entries
                       # miss and re-scan instead of being served as a silent false clean.
                       # 9->10: records gained `secrets` (gitleaks matches). A record cached before
                       # this feature has no such key, so a repo served from it reports zero
                       # secrets — indistinguishable from a repo that really has none
                       # 8->9: cache key now folds in the RULESET signature (vendors + idioms) so
                       # adding/absorbing an idiom re-scans instead of serving a stale record
                       # 7->8: residue gained pathConstants + path-constant endpoint attribution
                       # 6->7: endpoints/files/residue now canonically sorted (determinism
                       # fix) — a v6 cache holds the OLD match-order list, so invalidate it


def _ir_path(state_dir: str) -> Path:
    return Path(state_dir) / "inventory.json"


def _repo_path(state_dir: str, path: str, head_sha: str, rules_sig: str = "") -> Path:
    # The key folds in rules_sig (a hash of the effective ruleset = vendors + idioms). Without it,
    # a repo scanned once was served from cache forever even after a local idiom was added, so an
    # absorb's "re-run to confirm residue shrank" checked a cache the new idiom never touched.
    key = hashlib.sha256(path.encode("utf-8")).hexdigest()[:16]
    sig = "@" + rules_sig if rules_sig else ""
    return Path(state_dir) / f"repos_v{_CACHE_SCHEMA}" / f"{key}@{head_sha}{sig}.json"


def _write(p: Path, doc: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    # Write to a temp file in the SAME directory, then os.replace() it over the destination,
    # instead of truncating the real path with Path.write_text() in place. os.replace is only
    # atomic within a filesystem, hence same-directory: a reader landing mid-write of the old
    # in-place truncate could load a half-written file. That reader is not hypothetical here —
    # _repo_path keys the cache on identity@sha, not on a repo's directory, so two distinct
    # discovered repos can share one cache path; under --jobs > 1 one worker's write can race
    # another worker's read of that same path, and a torn read raised json.JSONDecodeError,
    # which the pool captured and reported as the repo being unscannable.
    fd, tmp_path = tempfile.mkstemp(dir=p.parent, prefix=p.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True))
        os.replace(tmp_path, p)
    except OSError:
        os.unlink(tmp_path)
        raise


def _read(p: Path):
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def save_ir(state_dir: str, doc: dict) -> None:
    _write(_ir_path(state_dir), doc)


def load_ir(state_dir: str):
    return _read(_ir_path(state_dir))


def save_repo_cache(state_dir: str, path: str, head_sha: str, record: dict,
                    rules_sig: str = "") -> None:
    _write(_repo_path(state_dir, path, head_sha, rules_sig), record)


def load_repo_cache(state_dir: str, path: str, head_sha: str, rules_sig: str = ""):
    return _read(_repo_path(state_dir, path, head_sha, rules_sig))
