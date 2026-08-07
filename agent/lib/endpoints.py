"""Turn the broad URL-literal matches into endpoint records (discover-then-classify).

For each matched line we extract every http(s) URL, classify its host against the vendor catalog
(agent.lib.classify_url), drop boilerplate, and aggregate per (techKey|host, host, version).
Known vendors carry their `vendor`/`techKey`; un-catalogued external hosts are surfaced as
`vendor: "Unknown"` so the catalog is never the ceiling.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from agent.lib import classify_url, scope_edges

UNKNOWN = "Unknown"

_STRING_LIT = re.compile(r"""['"]([^'"]*)['"]""")


def _string_literal_of(text: str) -> str:
    """The first quoted string in a matched line — the path a path-constant rule caught."""
    m = _STRING_LIT.search(text or "")
    return m.group(1) if m else ""


def _repo_in_scope(repo_id: str, suffix: str) -> bool:
    """Is the repo being scanned the one an instance is bound to? Matches host-independently on
    the git identity's path suffix (a fleet clone's remote_url), with the clone-folder name
    (`{org}-{repo}-{hash}`) as the fallback for a locally-scanned checkout — mirrors
    sdk_profiles._matches so a profile and an idiom scope the same repo the same way."""
    if not repo_id or not suffix:
        return False
    # case-insensitive: scope_edges.identity() lowercases the path, so a mixed-case org
    # (example-org/magento_api) must still match its instance suffix — a bug that let Magento
    # fall silently to residue while Catch (already-lowercase example-org) worked.
    suf = suffix.lower()
    iden = scope_edges.identity(repo_id)
    if iden and (iden == suf or iden.endswith("/" + suf)):
        return True
    base = os.path.basename(str(repo_id).rstrip("/")).lower()
    dash = suf.replace("/", "-")
    return base == dash or base.startswith(dash + "-")


def _read_line(repo_root: str, path: str, line: int, cache: dict) -> str:
    lines = cache.get(path)
    if lines is None:
        try:
            text = (Path(repo_root) / path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        lines = text.splitlines()
        cache[path] = lines
    return lines[line - 1] if 1 <= line <= len(lines) else ""


def _relpath(path: str, repo_root: str) -> str:
    """Repo-relative form of a match path, so the persisted IR is portable/diff-stable
    (the engine returns absolute paths when scanning an absolute dir). Relative paths pass through."""
    p = Path(path)
    if not p.is_absolute():
        return path
    try:
        return str(p.resolve().relative_to(Path(repo_root).resolve()))
    except ValueError:
        return path


def scan_endpoints(matches: list, repo_root: str, vendors: list, *, max_files: int = 20,
                   idioms: list | None = None, repo_id: str | None = None) -> dict:
    by_tk = {v.techKey: v for v in vendors}
    by_name = {v.vendor: v for v in vendors}
    line_cache: dict = {}
    groups: dict = {}
    seen_known: set = set()

    def add(vendor, techKey, host, version, example, rel, lineno, operation=None,
            inferred=False):
        loc = f"{rel}:{lineno}"
        # One call-site, one record — but only for the SAME (version, operation). The key
        # deliberately ignores host so a full-URL match and the host-only vendor rule firing
        # on the same line collapse into one record (their host fields differ: actual host vs
        # catalog domain). It MUST carry version: without it, the second of two same-vendor
        # versions on one line ('…/sell/v1/x' => '…/sell/v2/x') was silently dropped, and an
        # unversioned sibling (an OAuth literal, a doc link) suppressed the path-signature's
        # versioned add — the retired call vanished, the exact invisibility the signature
        # exists to prevent. Distinct versions are distinct facts; both survive.
        if techKey and (techKey, loc, operation, version) in seen_known:
            return
        if techKey:
            seen_known.add((techKey, loc, operation, version))
        # The API FAMILY, e.g. /fba/inbound/v0 — a fourth axis, for vendors that retire
        # per (family, version). Without it every Amazon "v0" call-site shares one record
        # and one catalog entry would date 78 sites identically, when in truth 34 of them
        # died in 2025 and 4 live until 2027.
        api_path = classify_url.api_path_of(example) if example else ""
        key = (techKey or f"unknown:{host}", host, version, operation, api_path)
        rec = groups.get(key)
        if rec is None:
            rec = {"vendor": vendor, "domain": host, "version": version, "techKey": techKey,
                   "operation": operation, "apiPath": api_path,
                   # OBSERVED means the vendor was read at this call-site; INFERRED means
                   # it was assigned by the single-classified-vendor heuristic, which is
                   # a guess about the repo, not evidence from the line. A reader must be
                   # able to tell them apart.
                   "attribution": "inferred" if inferred else "observed",
                   "example": (example or host).rstrip("\"';,)"), "file_count": 0, "files": [],
                   "classified": bool(techKey)}
            groups[key] = rec
        rec["file_count"] += 1
        if loc not in rec["files"]:        # collect all unique locs; sort + cap at the end
            rec["files"].append(loc)

    # url matches first (full-URL evidence outranks a host-only vendor rule at the same loc),
    # then path+line so PROCESSING order never inherits the engine's match order — which is
    # NOT stable run-to-run. seen_known is first-wins; an unstable walk order would let the
    # engine pick which same-key record survives (a principle-3 violation, not just cosmetic).
    for m in sorted(matches, key=lambda x: (0 if x.get("kind") == "url" else 1,
                                            str(x.get("path", "")), int(x.get("line", 0) or 0))):
        rel = _relpath(m.get("path", ""), repo_root)
        lineno = int(m.get("line", 0) or 0)
        # Prefer the engine's full matched text: a heredoc/multi-line literal carries
        # its URL past the node's START line, and reading only that line loses it
        # entirely — present in neither endpoints nor residue.
        line = m.get("text") or _read_line(repo_root, rel, lineno, line_cache)
        kind = m.get("kind")
        if kind == "url":
            for url in classify_url.extract_urls(line):
                host = classify_url.host_of(url)
                v = classify_url.classify_host(host, vendors)
                if v is None and classify_url.is_ignored(host):
                    continue
                add(v.vendor if v else UNKNOWN, v.techKey if v else "", host,
                    classify_url.version_of(url, v), url, rel, lineno)
            # Interpolated/variable host ("https://{$shop}/admin/api/2024-01/…"): the host is
            # a runtime value so extract_urls truncates and host classification is blind, but a
            # distinctive PATH signature still names the vendor + version. seen_known dedups by
            # (techKey, loc, operation, VERSION): a fully-classified host carrying the SAME
            # version already wins, but an unversioned sibling (an OAuth literal, a doc link)
            # never suppresses the signature's versioned add — that dropped retired calls.
            sig = classify_url.path_signature_match(line, vendors)
            if sig:
                sv, sver, ssample = sig
                add(sv.vendor, sv.techKey, sv.domains[0], sver, ssample, rel, lineno)
        elif kind == "endpoint":
            v = by_tk.get(m.get("techKey", ""))
            d = classify_url.domain_in_line(line, v.domains) if v else ""
            if v and d:
                seg = classify_url.segment_at(line, d)
                add(v.vendor, v.techKey, d, classify_url.version_of(seg, v), seg, rel, lineno)

    # --- operation markers: name the OPERATION for vendors that deprecate per-call ---
    # Same strict guard as the concat idiom: only when the repo has exactly one
    # classified vendor, so an operation is never attributed to the wrong API.
    classified_tks = {r["techKey"] for r in groups.values() if r["techKey"]}
    attributed_ops: set = set()
    if len(classified_tks) == 1:
        v = by_tk.get(next(iter(classified_tks)))
        if v is not None:
            for m in matches:
                if m.get("kind") != "operation-marker":
                    continue
                rel = _relpath(m.get("path", ""), repo_root)
                lineno = int(m.get("line", 0) or 0)
                # the marker may sit past the literal's first line, so search the
                # whole matched text and fall back to the line for engines that omit it
                op = (classify_url.operation_of(m.get("text") or "")
                      or classify_url.operation_of(_read_line(repo_root, rel, lineno, line_cache)))
                if op:
                    add(v.vendor, v.techKey, v.domains[0], None, op, rel, lineno,
                        operation=op, inferred=True)
                    attributed_ops.add(f"{rel}:{lineno}")

    # --- concat idiom: attribute host-less path literals to the repo's SINGLE classified vendor ---
    classified_tks = {r["techKey"] for r in groups.values() if r["techKey"]}
    assembly_files = {_relpath(m.get("path", ""), repo_root)
                      for m in matches if m.get("kind") == "path-assembly"}
    attributed_locs: set = set()
    if len(classified_tks) == 1 and assembly_files:
        v = by_tk.get(next(iter(classified_tks)))
        if v is not None:
            for m in matches:
                if m.get("kind") != "path-literal":
                    continue
                rel = _relpath(m.get("path", ""), repo_root)
                if rel not in assembly_files:
                    continue
                lineno = int(m.get("line", 0) or 0)
                path = classify_url.path_literal_of(
                    m.get("text") or _read_line(repo_root, rel, lineno, line_cache))
                if not path:
                    continue
                add(v.vendor, v.techKey, v.domains[0], classify_url.version_of(path, v),
                    path, rel, lineno, inferred=True)
                attributed_locs.add(f"{rel}:{lineno}")

    # --- path-constant idiom: operations of a config-injected wrapper ---
    # A config-injected host classifies nothing, so — unlike the concat/operation-marker
    # blocks — the vendor is NOT inferred from the repo's classified set. It is the reviewed
    # BINDING on the instance (carried in the match's `vendor` metadata). Two guards keep it
    # honest: the instance's `repo` scope must match THIS repo (its paths are generic, e.g.
    # /api/orders, and would mis-tag a different marketplace), and the repo must show an egress
    # sink (it actually makes HTTP calls). Everything else lands in residue below.
    pc_by_id = {i["id"]: i for i in (idioms or []) if i.get("family") == "path-constant"}
    has_sink = any(m.get("kind") == "sink" for m in matches)
    attributed_pc: set = set()
    if pc_by_id:
        for m in matches:
            if m.get("kind") != "path-constant":
                continue
            inst = pc_by_id.get(m.get("checkId"))
            if inst is None:
                continue
            rel = _relpath(m.get("path", ""), repo_root)
            lineno = int(m.get("line", 0) or 0)
            if inst.get("requiresSink", True) and not has_sink:
                continue
            if not _repo_in_scope(repo_id or repo_root, inst.get("repo", "")):
                continue
            path = _string_literal_of(m.get("text") or
                                      _read_line(repo_root, rel, lineno, line_cache))
            if not path or not re.search(inst["pathRegex"], path):
                continue
            v = by_name.get(m.get("vendor") or inst.get("vendor"))
            if v is None:
                continue
            host = v.domains[0] if v.domains else f"sdk:{inst['repo']}"
            # optional `version`: a wrapper pinned to a specific (often DEPRECATED) API version
            # — e.g. BigCommerce's /api/v2 constants — so a version-scoped sunset can flag it.
            add(v.vendor, v.techKey, host, inst.get("version"), path, rel, lineno,
                operation=path, inferred=True)
            attributed_pc.add(f"{rel}:{lineno}")

    # --- residue: what we could NOT attribute (the conscience) ---
    residue_paths, residue_sinks, residue_ops, residue_pc = [], [], [], []
    for m in matches:
        rel = _relpath(m.get("path", ""), repo_root)
        lineno = int(m.get("line", 0) or 0)
        loc = f"{rel}:{lineno}"
        kind = m.get("kind")
        if kind == "path-literal" and loc not in attributed_locs:
            path = classify_url.path_literal_of(
                m.get("text") or _read_line(repo_root, rel, lineno, line_cache))
            if path:
                residue_paths.append({"sample": path, "loc": loc})
        elif kind == "sink":
            residue_sinks.append({"kind": "egress", "loc": loc})
        elif kind == "operation-marker" and loc not in attributed_ops:
            # the single-vendor guard did not fire (0 or >=2 classified vendors). The
            # marker is still real evidence of an API call; dropping it would make it
            # invisible rather than merely unattributed.
            op = classify_url.operation_of(m.get("text") or
                                           _read_line(repo_root, rel, lineno, line_cache))
            if op:
                residue_ops.append({"operation": op, "loc": loc})
        elif kind == "path-constant" and loc not in attributed_pc:
            # out of scope, no sink, or an unbound vendor: a path constant we saw but did not
            # attribute. Recorded so the gate can require it SHRINK, and so coverage stays honest.
            path = _string_literal_of(m.get("text") or
                                      _read_line(repo_root, rel, lineno, line_cache))
            if path:
                residue_pc.append({"sample": path, "loc": loc})

    # Deterministic output regardless of the engine's match order (which is NOT stable
    # run-to-run — a container double-run proved the endpoints list reordered between runs).
    # Detection is order-independent BY CONSTRUCTION, not by luck: the walk above is sorted
    # (kind, path, line) and the seen_known key carries version, so first-wins can only fire
    # between records that are genuinely the same fact. This block canonicalises the
    # PRESENTATION — "byte-identical output" (CLAUDE.md principle 3) requires it. Sort the
    # endpoints, each record's files (then cap), and the residue.
    def _loc_key(loc):
        path, _, ln = str(loc).rpartition(":")
        return (path, int(ln) if ln.isdigit() else 0)
    for rec in groups.values():
        rec["files"] = sorted(rec["files"], key=_loc_key)[:max_files]
    endpoints = sorted(groups.values(), key=lambda r: (
        r.get("vendor") or "", r.get("domain") or "", str(r.get("version") or ""),
        r.get("apiPath") or "", str(r.get("operation") or ""), r.get("example") or ""))
    for lst in (residue_paths, residue_sinks, residue_ops, residue_pc):
        lst.sort(key=lambda x: _loc_key(x["loc"]))
    return {"endpoints": endpoints,
            "residue": {"pathLiterals": residue_paths, "sinks": residue_sinks,
                        "operations": residue_ops, "pathConstants": residue_pc}}


def build_endpoints(matches: list, repo_root: str, vendors: list, *, max_files: int = 20) -> list:
    return scan_endpoints(matches, repo_root, vendors, max_files=max_files)["endpoints"]
