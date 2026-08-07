"""Walk a repo working tree and run the manifest extractors -> InventoryRecords."""
from __future__ import annotations

from pathlib import Path

from agent.lib.extractors import extractor_for
# Import extractors so they self-register:
from agent.lib.extractors import npm, composer, python, runtime_pins  # noqa: F401

_SKIP_DIRS = {".git", "node_modules", "vendor", ".venv", "dist", "build", "target", "__pycache__"}


def _walk(root: Path):
    for p in root.rglob("*"):
        if p.is_dir():
            continue
        if any(part in _SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        yield p


def extract_manifest_records(repo_abs: str, repo_name: str):
    root = Path(repo_abs)
    records: list = []
    unparsed: list = []
    for p in _walk(root):
        fn = extractor_for(p.name)
        if not fn:
            continue
        rel = str(p.relative_to(root))
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            unparsed.append({"path": rel, "reason": f"read error: {exc}"})
            continue
        try:
            records.extend(fn(repo_name, rel, content))
        except ValueError as exc:
            unparsed.append({"path": rel, "reason": str(exc)})
    return records, unparsed
