"""Scan a folder of clones -> the superset inventory IR (inventory.json)."""
from __future__ import annotations

import hashlib
import os

from agent.lib import (catalog_overlay, engine as engine_mod, ir_store, pool, repo_discovery,
                       scan_util)
from agent.lib.vendors import load_vendors
from agent.lib.vendor_rules import write_ruleset, rule_kinds_by_language
from agent.lib import shapes
from agent.lib.repo_scan import scan_repo
from agent.lib.repo_discovery import discover_repos, diagnose_root
from agent.lib import source_resolver, sdk_profiles, sdk_clients, idioms as idioms_mod
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


def scan_folder(root, state_dir, now, *, engine=None, run=None, git=None, progress=None,
                jobs=1) -> dict:
    # `root` may be a single path or a list of roots; discovery is recursive.
    roots = [root] if isinstance(root, (str, os.PathLike)) else list(root)
    # A root is either a bare path/url or a (path_or_url, branch|None) pair since a fleet entry
    # could name a branch. `roots` is passed on whole — resolve_sources needs the branch — but
    # anything that wants a PATH takes it from here, because os.path.realpath(tuple) raises and
    # a log line would otherwise print the tuple repr.
    root_paths = repo_discovery.locations(roots)

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
    # the per-repo cache key folds in this signature, so adding/absorbing an idiom (or any other
    # catalog input a scan reads) re-scans the repo instead of serving its stale record.
    with open(rules_path, "rb") as _rf:
        ruleset_sig = hashlib.sha256(_rf.read()).hexdigest()[:12]     # compiled ruleset = vendors + idioms
    # ...but NOT everything a repo's classification depends on lives in the compiled ruleset: the
    # own-domains overlay (agent/lib/own_domains.py, read inside scan_endpoints via
    # agent/lib/endpoints.py) can flip a host from queued/unclassified to own-infra without
    # touching a single ast-grep rule. A cache keyed on ruleset_sig alone stayed blind to it — a
    # gated, correctly-written own-domain verdict through `run --resolve` was a silent no-op,
    # because the re-scan's cache lookup still matched scan 1's pre-resolution record. Folding in
    # the WHOLE overlay directory's content (not naming own_domains specifically) makes this
    # structural: any future overlay kind that a scan starts reading invalidates the cache by
    # construction, not because someone remembered to list it here.
    overlay_sig = catalog_overlay.overlay_signature()
    rules_sig = hashlib.sha256(f"{ruleset_sig}|{overlay_sig}".encode("utf-8")).hexdigest()[:12]

    _p("resolving sources under " + ", ".join(str(r) for r in root_paths) + " …")
    # A checkout, a plain folder, or a git/GitLab URL (cloned into <state>/sources/) all
    # resolve to scannable projects here; anything that resolves to nothing is an error
    # carried through, never a silent drop.
    resolved = source_resolver.resolve_sources(roots, state_dir)
    discovered = [(abs_, ident) for abs_, ident, _kind in resolved["projects"]]
    source_kind = {abs_: kind for abs_, _ident, kind in resolved["projects"]}
    # abs_dir -> the branch the config asked for; absent when none was named. Carries the
    # fact to git_meta so `ref_is_default` states something true instead of a constant.
    source_branch = resolved.get("branches") or {}
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
    # Repo identities collide ACROSS roots. `discover_repos` guarantees collision-free
    # identities only within ONE call, and `resolve_sources` calls it once per root — so two
    # roots that each contain a `web/` both yield the identity `"web"`. `ir_store._repo_path`
    # keys the per-repo cache on sha256(identity)@head_sha@rules_sig, so two DISTINCT
    # checkouts sitting at the same commit share one cache file: the second is served the
    # first's record and is reported using another repo's results. Serially that is
    # deterministically wrong; under --jobs > 1 the hit/miss decision becomes a RACE, so the
    # same inputs can produce a different drift.json — the one thing --jobs promises it
    # cannot do.
    #
    # The cache is therefore BYPASSED for a colliding identity: never loaded, never saved,
    # always scanned fresh. That is deterministic at every --jobs value and repairs the
    # pre-existing serial mis-attribution too. Cost is one un-cached scan per colliding repo,
    # paid only by a fleet that actually has duplicate names; every unique identity keeps its
    # incrementality untouched. (Making identity globally unique is the proper root fix, but
    # it changes every cache key and every rendered repo label — deliberately out of scope.)
    _seen: dict = {}
    for _abs, _ident in discovered:
        _seen[_ident] = _seen.get(_ident, 0) + 1
    ambiguous = {ident for ident, count in _seen.items() if count > 1}

    def _scan_one(indexed):
        # The ERROR line is logged HERE, beside the repo's other progress lines, and the
        # exception is then re-raised for the pool to capture. Emitting it from the fold
        # instead made every error batch to the END of the log even at --jobs 1, so on a
        # 25-minute serial scan an error no longer sat next to the repo that produced it.
        # Only the LOGGING lives here: `coverage["reposErrored"]` is still appended by the
        # fold, in input order, so the artifacts stay byte-identical at any --jobs value.
        # At --jobs > 1 these lines interleave with other workers' — the progress log is the
        # one surface the identity guarantee explicitly does not cover.
        try:
            return _scan_one_inner(indexed)
        except Exception as exc:                # noqa: BLE001 — re-raised; the pool records it
            i, (_abs, name) = indexed
            _p(f"[{i + 1:>2}/{n}] {name}  ⚠ error: {exc}")
            raise

    def _scan_one_inner(indexed):
        i, (abs_, name) = indexed
        tag = f"[{i + 1:>2}/{n}] {name}"
        sha = scan_util.git_meta(abs_, run=git)["head_sha"]
        cacheable = bool(sha) and name not in ambiguous
        cached = ir_store.load_repo_cache(state_dir, name, sha, rules_sig) if cacheable else None
        if cached is not None:
            _p(f"{tag}  cached (HEAD unchanged)")
            cached = {**cached, "id": i + 1}
            cached["shape"] = _shape_of(abs_, name, cached, rule_kinds, attestations)
            return {"record": cached, "unparsed": []}
        _p(f"{tag}  scan: git · manifests · AST endpoints" +
           ("  (uncached: duplicate repo name across roots)" if name in ambiguous else ""))
        record, note = scan_repo(abs_, name, i + 1, vendors, rules_path,
                                 engine=engine, run=run, git=git,
                                 idiom_instances=idiom_instances,
                                 configured_branch=source_branch.get(abs_))
        record["sourceKind"] = source_kind.get(abs_, "local-git")
        record["shape"] = _shape_of(abs_, name, record, rule_kinds, attestations)
        if cacheable:
            ir_store.save_repo_cache(state_dir, name, sha, record, rules_sig)
        return {"record": record, "unparsed": note["unparsed"]}

    # The fold below runs in INPUT order, never completion order: `repos`, `reposErrored` and
    # `manifestsUnparsed` are all order-sensitive, and the whole --jobs guarantee is that a
    # parallel run cannot be distinguished from a serial one by its artifacts.
    outcomes = pool.ordered_map(_scan_one, list(enumerate(discovered)), jobs=jobs)
    for (i, (abs_, name)), (out, exc) in zip(enumerate(discovered), outcomes, strict=True):
        coverage["reposScanned"] += 1
        if exc is not None:                 # no single repo aborts the scan (logged in _scan_one)
            coverage["reposErrored"].append({"repo": name, "reason": str(exc)})
            continue
        repos.append(out["record"])
        coverage["manifestsUnparsed"] += [{"repo": name, **u} for u in out["unparsed"]]

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

    # SDK clients: for a CONSUMER repo that DEPENDS ON a known API-client package (twilio/sdk,
    # @sendgrid/mail, …) but reaches the API through the SDK — no scannable host literal — inject a
    # synthetic endpoint carrying the vendor's real host, attributed `sdk-client` and evidenced at
    # the manifest file. The dependency IS the read fact. This closes the SDK-mediated blind spot
    # the AI plane surfaces (Twilio/SendGrid), for the deterministic scan.
    _clients = sdk_clients.load()
    if _clients:
        for r in repos:
            extra = sdk_clients.endpoints_for(r, _clients)
            if extra:
                r["endpoints"] = list(r.get("endpoints", [])) + extra

    _p("aggregating inventory + drift delta …")
    coverage["rootsUnscannable"] = unscannable
    _rollup_coverage(coverage, repos, discovered_count=n)
    prior = ir_store.load_ir(state_dir)                # BEFORE save_ir overwrites it
    root_count = len({os.path.realpath(r) for r in root_paths})   # distinct, not raw
    doc = {"generated": now,
           "scope": {"rootCount": root_count, "reposScanned": coverage["reposScanned"]},
           "repos": repos, "coverage": coverage}
    doc.update(build_rollups(repos))
    ir_store.save_ir(state_dir, doc)
    diff = diff_inventories(prior or {}, doc)
    # On the very first scan (no prior IR) everything is "added" — that's a
    # baseline, not drift, so the report omits the drift section.
    return {"doc": doc, "diff": diff}
