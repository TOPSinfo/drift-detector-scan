"""Persist the inventory IR + a per-repo cache keyed repo@head_sha (the incrementality substrate).
A cache hit (same sha) lets the scanner reuse a repo's record; a changed sha misses -> re-scan."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

# Per-repo cache schema. BUMP when the record shape changes so pre-upgrade caches are
# invalidated (a stale cache without new fields would silently under-report — e.g. a repo
# scanned before privateSources/versionSource existed would look "clean").
_CACHE_SCHEMA = 9      # 8->9: cache key now folds in the RULESET signature (vendors + idioms) so
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
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


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
