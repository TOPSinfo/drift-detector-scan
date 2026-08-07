"""Scan a folder of clones -> the superset inventory IR (inventory.json) + INVENTORY.md."""
from __future__ import annotations

import hashlib
import os

from agent.lib import engine as engine_mod, ir_store, scan_util
from agent.lib.vendors import load_vendors
from agent.lib.vendor_rules import write_ruleset, rule_kinds_by_language
from agent.lib import shapes
from agent.lib.repo_scan import scan_repo
from agent.lib.repo_discovery import discover_repos, diagnose_root
from agent.lib import source_resolver, sdk_profiles, idioms as idioms_mod
from agent.lib.inv_rollups import build_rollups
from agent.lib.inventory_diff import diff_inventories


def _coverage_grade(attributed: int, unattributed_paths: int, sinks: int,
                    verdict: str | None = None) -> str:
    """Grade a repo's endpoint coverage: HIGH/PARTIAL/LOW.

    DERIVED from the shape verdict when one exists, so the two cannot disagree inside
    one document. A Go-only repo previously reported `verdict: UNKNOWN
    (no-egress-signal)` beside `grade: HIGH` — the grade counts residue, and a repo we
    have no rules for produces none, so it looked perfect. A reader had no way to know
    which number to trust.
    """
    if verdict == "UNKNOWN" and not unattributed_paths:
        return "PARTIAL"          # blind for a reason residue counts cannot express
    if unattributed_paths and attributed == 0:
        return "LOW"
    if unattributed_paths or (attributed == 0 and sinks):
        return "PARTIAL"
    return "HIGH"


def _shape_of(abs_: str, name: str, record: dict, rule_kinds: dict,
              attestations: dict) -> dict:
    """Build a repo's shape, honoring an attestation only while its residue is unchanged."""
    residue = record.get("residue") or {}
    fp = shapes.residue_fingerprint(residue)
    return shapes.build(abs_, name, record.get("endpoints", []), residue, rule_kinds,
                        attested=shapes.is_attested(attestations, name, fp, abs_))


def _rollup_coverage(coverage: dict, repos: list, *, discovered_count: int) -> None:
    """Make the scan say what it did (and didn't) see — repos, endpoint buckets, package
    resolution, and private sources it couldn't scan."""
    eps = [e for r in repos for e in r.get("endpoints", [])]
    pkgs = [s for r in repos for s in r.get("sdks", [])]
    resolved = sum(1 for s in pkgs if s.get("versionSource") == "lockfile")
    # A repo's private composer dep that is ITSELF a scanned fleet member is NOT a blind spot —
    # its calls ARE read, as its own repo. Reconcile each private repo URL against the scanned
    # set (by git identity) so covered deps move out of `repositories` (the "couldn't crawl"
    # list, and its tile count) into `covered`. This is probe's cross-fleet edge, applied to
    # the canonical drift.json so every surface stops over-reporting them.
    from agent.lib import scope_edges
    fleet_ids = {scope_edges.identity(r.get("remote_url")) for r in repos}
    fleet_ids.discard("")
    private = []
    for r in repos:
        ps = r.get("privateSources") or {}
        if not any(ps.values()):
            continue
        urls = ps.get("repositories", [])
        covered = [u for u in urls if scope_edges.identity(u) in fleet_ids]
        unreachable = [u for u in urls if scope_edges.identity(u) not in fleet_ids]
        entry = {"repo": r.get("path"), "packages": ps.get("packages", []),
                 "repositories": unreachable}
        if covered:
            entry["covered"] = covered
        private.append(entry)
    coverage["repos"] = {"discovered": discovered_count, "scanned": coverage["reposScanned"],
                         "errored": len(coverage["reposErrored"])}
    coverage["endpoints"] = {"known": sum(1 for e in eps if e.get("vendor") and e["vendor"] != "Unknown"),
                             "unknownExternal": sum(1 for e in eps if e.get("vendor") == "Unknown")}
    coverage["packages"] = {"total": len(pkgs), "lockfileResolved": resolved,
                            "floorOnly": len(pkgs) - resolved}
    coverage["privateSources"] = private
    coverage["sdkMediated"] = [
        {"repo": r.get("path"),
         "sdkCount": len(r.get("sdks", [])),
         "endpointCount": sum(1 for e in r.get("endpoints", []) if e.get("classified"))}
        for r in repos if len(r.get("sdks", [])) >= 1
    ]
    res_paths, res_sinks, by_repo = [], [], []
    for r in repos:
        rr = r.get("residue") or {"pathLiterals": [], "sinks": []}
        plist = [{"repo": r.get("path"), **p} for p in rr.get("pathLiterals", [])]
        slist = [{"repo": r.get("path"), **s} for s in rr.get("sinks", [])]
        res_paths += plist
        res_sinks += slist
        attributed = sum(1 for e in r.get("endpoints", [])
                         if e.get("vendor") and e["vendor"] != "Unknown")
        by_repo.append({"repo": r.get("path"), "attributed": attributed,
                        "unattributedPaths": len(plist), "unresolvedSinks": len(slist),
                        "grade": _coverage_grade(attributed, len(plist), len(slist),
                                                 (r.get("shape") or {}).get("verdict"))})
    coverage["residue"] = {"pathLiterals": res_paths, "sinks": res_sinks, "byRepo": by_repo}
    coverage["shapes"] = [r["shape"] for r in repos if r.get("shape")]


def scan_folder(root, state_dir, now, *, engine=None, run=None, git=None, progress=None) -> dict:
    # `root` may be a single path or a list of roots; discovery is recursive.
    roots = [root] if isinstance(root, (str, os.PathLike)) else list(root)

    def _p(msg):                            # informative phase log (optional)
        if progress:
            progress(msg)

    run = run if run is not None else engine_mod._default_run
    git = git if git is not None else scan_util._default_git
    engine = engine or scan_util.resolve_engine()      # fail-loud if absent
    os.makedirs(state_dir, exist_ok=True)
    vendors = load_vendors()
    rules_path = os.path.join(state_dir, "rules.generated.yaml")
    # load idioms ONCE and hand the SAME instances to both the ruleset (which surfaces the
    # matches) and scan_repo (which reads a path-constant match's repo scope + bound vendor).
    idiom_instances = idioms_mod.load_idioms()
    write_ruleset(vendors, rules_path, idiom_instances=idiom_instances)
    # the per-repo cache key folds in this signature (the compiled ruleset = vendors + idioms), so
    # adding/absorbing an idiom re-scans the repo instead of serving its stale pre-idiom record.
    with open(rules_path, "rb") as _rf:
        rules_sig = hashlib.sha256(_rf.read()).hexdigest()[:12]

    _p("resolving sources under " + ", ".join(str(r) for r in roots) + " …")
    # A checkout, a plain folder, or a git/GitLab URL (cloned into <state>/sources/) all
    # resolve to scannable projects here; anything that resolves to nothing is an error
    # carried through, never a silent drop.
    resolved = source_resolver.resolve_sources(roots, state_dir)
    discovered = [(abs_, ident) for abs_, ident, _kind in resolved["projects"]]
    source_kind = {abs_: kind for abs_, _ident, kind in resolved["projects"]}
    unscannable = resolved["errors"]
    n = len(discovered)
    _p(f"  {n} project(s) resolved" +
       (f", {len(unscannable)} unreadable" if unscannable else ""))
    repos: list = []
    # what the ruleset can even SEE, per language — the shape verdict needs this to
    # tell "no rules for this language" apart from "looked and found nothing"
    rule_kinds = rule_kinds_by_language(vendors)
    attestations = shapes.load_attestations(state_dir)
    coverage = {"reposScanned": 0, "reposErrored": [], "manifestsUnparsed": []}
    for i, (abs_, name) in enumerate(discovered):
        coverage["reposScanned"] += 1
        tag = f"[{i + 1:>2}/{n}] {name}"
        try:
            sha = scan_util.git_meta(abs_, run=git)["head_sha"]
            cached = ir_store.load_repo_cache(state_dir, name, sha, rules_sig) if sha else None
            if cached is not None:
                _p(f"{tag}  cached (HEAD unchanged)")
                cached = {**cached, "id": i + 1}
                cached["shape"] = _shape_of(abs_, name, cached, rule_kinds, attestations)
                repos.append(cached)
                continue
            _p(f"{tag}  scan: git · manifests · AST endpoints")
            record, note = scan_repo(abs_, name, i + 1, vendors, rules_path,
                                     engine=engine, run=run, git=git,
                                     idiom_instances=idiom_instances)
            record["sourceKind"] = source_kind.get(abs_, "local-git")
            record["shape"] = _shape_of(abs_, name, record, rule_kinds, attestations)
            repos.append(record)
            if sha:
                ir_store.save_repo_cache(state_dir, name, sha, record, rules_sig)
            coverage["manifestsUnparsed"] += [{"repo": name, **u} for u in note["unparsed"]]
        except Exception as exc:            # no single repo aborts the scan
            _p(f"{tag}  ⚠ error: {exc}")
            coverage["reposErrored"].append({"repo": name, "reason": str(exc)})

    # SDK profiles: for a wrapper whose vendor+version live behind constants (the
    # `sdk-only-no-callsite` blind spot), inject synthetic endpoints read from its OWN source
    # (agent/sdk_profiles.yaml) so the audit dates them like any endpoint. Post-loop and never
    # cached, so a profile edit takes effect on the next scan without a cache bump. Attribution
    # `sdk-profile` + evidence at the const's file:line — a read fact, not a fabricated call-site.
    _profiles = sdk_profiles.load()
    if _profiles:
        for r in repos:
            extra = sdk_profiles.endpoints_for(r, _profiles)
            if extra:
                r["endpoints"] = list(r.get("endpoints", [])) + extra

    _p("aggregating inventory + drift delta …")
    coverage["rootsUnscannable"] = unscannable
    _rollup_coverage(coverage, repos, discovered_count=n)
    prior = ir_store.load_ir(state_dir)                # BEFORE save_ir overwrites it
    root_count = len({os.path.realpath(r) for r in roots})   # distinct, not raw
    doc = {"generated": now,
           "scope": {"rootCount": root_count, "reposScanned": coverage["reposScanned"]},
           "repos": repos, "coverage": coverage}
    doc.update(build_rollups(repos))
    ir_store.save_ir(state_dir, doc)
    diff = diff_inventories(prior or {}, doc)
    # On the very first scan (no prior IR) everything is "added" — that's a
    # baseline, not drift, so the report omits the drift section.
    return {"doc": doc, "diff": diff}
