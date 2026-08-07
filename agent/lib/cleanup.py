"""Remove the artifacts the tool leaves on a user's machine — without a filesystem-wide search.

Every scan appends its state dir to a run-index ledger (`~/.drift/runs.log`), so `drift-scan clean
--all` knows exactly where the scattered `<folder>/.drift-detector` dirs are without walking `$HOME`.
The learned catalog (`~/.drift/catalog`) is PRESERVED by default — it holds shapes the user absorbed
and would not want silently dropped; only `--catalog` removes it. A guardrail keeps `clean` from ever
deleting a path that isn't ours: a `--state` dir is removed only if it looks like a drift state dir.
"""
from __future__ import annotations

import os
import shutil

from agent.lib import drift_home

_LEDGER = "runs.log"
# A dir is one of ours iff it carries a scan artifact — the guardrail against `clean --state` nuking
# a path that isn't a drift state dir. The plugin's own ".drift-detector" folder name also qualifies.
_MARKERS = ("inventory.json", "drift.json", "audit.json")


def _ledger_path() -> str:
    return os.path.join(drift_home.drift_root(), _LEDGER)


def record_run(state_dir: str) -> None:
    """Append a state dir to the run index (deduped). Best-effort — never raises into a scan."""
    try:
        p = os.path.abspath(state_dir)
        if p in set(read_runs()):
            return
        with open(_ledger_path(), "a", encoding="utf-8") as fh:
            fh.write(p + "\n")
    except OSError:
        pass


def read_runs() -> list:
    try:
        with open(_ledger_path(), encoding="utf-8") as fh:
            return [ln.strip() for ln in fh if ln.strip()]
    except OSError:
        return []


def is_state_dir(path: str) -> bool:
    """The guardrail: is `path` actually one of ours? True iff it is a directory that either is named
    `.drift-detector` or carries a scan artifact. Everything `clean` deletes passes this."""
    if not path or not os.path.isdir(path):
        return False
    if os.path.basename(os.path.normpath(path)) == ".drift-detector":
        return True
    return any(os.path.exists(os.path.join(path, m)) for m in _MARKERS)


def dir_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            fp = os.path.join(root, f)
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    return total


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def plan(*, all_: bool, state: str | None, include_catalog: bool) -> dict:
    """What `clean` WOULD remove. Returns {targets:[{path,size,kind}], preserved:[...], total}.
    Targets are deduped by path; the catalog is listed under `preserved` unless include_catalog."""
    root = drift_home.drift_root()
    targets: list = []

    def add(path: str, kind: str) -> None:
        if os.path.isdir(path):
            targets.append({"path": os.path.abspath(path), "size": dir_size(path), "kind": kind})

    if state and is_state_dir(state):
        add(state, "run")
    if all_:
        for d in read_runs():
            if is_state_dir(d):
                add(d, "run")
        add(os.path.join(root, "reports"), "reports")
        add(os.path.join(root, "eval"), "eval")
        add(os.path.join(os.path.expanduser("~"), ".drift-detector"), "run")
        if include_catalog:
            add(os.path.join(root, "catalog"), "catalog")

    seen, uniq = set(), []
    for t in targets:
        if t["path"] not in seen:
            seen.add(t["path"])
            uniq.append(t)

    preserved = []
    cat = os.path.join(root, "catalog")
    if not include_catalog and os.path.isdir(cat) and (all_ or state):
        preserved.append({"path": os.path.abspath(cat), "size": dir_size(cat), "kind": "catalog"})
    return {"targets": uniq, "preserved": preserved, "total": sum(t["size"] for t in uniq)}


def execute(targets: list) -> list:
    """Remove each target dir; returns the paths removed and prunes them from the run ledger."""
    removed = []
    for t in targets:
        path = t["path"] if isinstance(t, dict) else t
        try:
            shutil.rmtree(path)
            removed.append(os.path.abspath(path))
        except OSError:
            pass
    _prune_ledger(removed)
    return removed


def _prune_ledger(removed: list) -> None:
    gone = set(removed)
    try:
        keep = [d for d in read_runs() if d not in gone and os.path.isdir(d)]
        with open(_ledger_path(), "w", encoding="utf-8") as fh:
            fh.write("".join(d + "\n" for d in keep))
    except OSError:
        pass
