"""Walk a repo working tree and run the manifest extractors -> InventoryRecords."""
from __future__ import annotations

from pathlib import Path

from agent.lib.extractors import extractor_for
# Import extractors so they self-register:
from agent.lib.extractors import npm, composer, python, runtime_pins, go, maven, nuget, bundler, cargo, gradle  # noqa: F401

_SKIP_DIRS = {".git", "node_modules", "vendor", ".venv", "dist", "build", "target", "__pycache__"}


def _walk(root: Path):
    for p in root.rglob("*"):
        if p.is_dir():
            continue
        if any(part in _SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        yield p


_CENTRAL_VERSIONS = "Directory.Packages.props"


def extract_manifest_records(repo_abs: str, repo_name: str):
    root = Path(repo_abs)
    records: list = []
    unparsed: list = []
    central: list = []
    for p in _walk(root):
        is_central = p.name == _CENTRAL_VERSIONS
        fn = extractor_for(p.name)
        if not fn and not is_central:
            continue
        rel = str(p.relative_to(root))
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            unparsed.append({"path": rel, "reason": f"read error: {exc}"})
            continue
        if is_central:
            # Not an extractor: it declares no dependencies of its own, it supplies the
            # versions the csproj files left out (NuGet Central Package Management).
            central.append((rel, content))
            continue
        try:
            records.extend(fn(repo_name, rel, content))
        except ValueError as exc:
            unparsed.append({"path": rel, "reason": str(exc)})

    if central:
        versions: dict = {}
        for rel, content in sorted(central):        # sorted so the merge is deterministic
            try:
                for name, version in nuget.parse_package_versions(content).items():
                    versions.setdefault(name, version)      # first path wins
            except ValueError as exc:
                unparsed.append({"path": rel, "reason": str(exc)})
        # KNOWN MISS: one repo-wide map. MSBuild resolves each csproj against its
        # NEAREST-ANCESTOR props file, so a repo carrying several catalogs that disagree on
        # a version gets the first path's answer here. The common shape is a single catalog
        # at the root; per-project resolution is a later slice, not this one.
        records = nuget.apply_central_versions(records, versions)
    return records, unparsed
