"""Scan one repo: git metadata + manifests + ast-grep endpoints -> a superset record."""
from __future__ import annotations

from agent.lib import scan_util
from agent.lib.scan_util import git_meta, _default_git
from agent.lib.manifest_scan import extract_manifest_records
from agent.lib.record_routing import partition_records
from agent.lib.engine import run_scan
from agent.lib.endpoints import build_endpoints, scan_endpoints
from agent.lib.superset import to_superset_repo
from agent.lib import lockfile, private_sources


def scan_repo(repo_abs, repo_name, repo_id, vendors, rules_path, *,
              engine, run, git=_default_git, idiom_instances=None):
    meta = git_meta(repo_abs, run=git)
    meta.update({"id": repo_id, "path": repo_name, "provenance": {"engine": "ast-grep"}})

    records, unparsed = extract_manifest_records(repo_abs, repo_name)
    partitioned = partition_records(records)

    scan = run_scan(repo_abs, rules_path, engine=engine, run=run)
    # a path-constant idiom is repo-scoped: pass the repo's git identity (its remote, or the
    # local checkout path as a fallback) so a wrapper's constants attribute only in ITS repo.
    # scan_util.repo_scope_id is the ONE derivation the absorb gate must share (see its docstring).
    scanned_eps = scan_endpoints(scan["matches"], repo_abs, vendors,
                                 idioms=idiom_instances,
                                 repo_id=scan_util.repo_scope_id(repo_abs, meta))
    endpoints = [e for e in scanned_eps["endpoints"] if e.get("domain")]

    record = to_superset_repo(meta, partitioned, endpoints)
    _annotate_resolved(record, repo_abs)
    record["privateSources"] = private_sources.detect(repo_abs)   # what we can't see (say so)
    record["residue"] = scanned_eps["residue"]
    return record, {"unparsed": unparsed, "engineErrors": scan["errors"]}


def _annotate_resolved(record, repo_abs):
    """Attach lockfile-resolved exact versions to sdks[] (falls back to the manifest range)."""
    resolved = lockfile.resolve_versions(repo_abs)
    for s in record.get("sdks", []):
        exact = resolved.get((s["eco"], lockfile.norm(s["eco"], s["pkg"])))
        if exact:
            s["resolved"] = exact
            s["versionSource"] = "lockfile"
        else:
            s["versionSource"] = "manifest"
