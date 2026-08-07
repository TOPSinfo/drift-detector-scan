"""Render a scan into a single self-contained dashboard.html — the interactive cockpit.

Renders ACTIONS (ranked upgrade jobs) + endpoints (the integration/sunset moat) into one
HTML file with inline CSS + vanilla JS + an embedded JSON projection. No server, no CDN, no
build: opens from file://. Pure and deterministic — same (inventory, audit, now) yields
byte-identical output. The caller writes the string to disk.
"""
from __future__ import annotations

import html
import json
import os
import re

from agent.lib.actions import build_actions

_MAX_CVES = 20            # cap the per-action CVE list embedded in the blob

_ASSETS = os.path.join(os.path.dirname(__file__), "..", "assets")


def _read_asset(name: str) -> str:
    with open(os.path.join(_ASSETS, name), encoding="utf-8") as fh:
        return fh.read()


CSS_SRC = _read_asset("dashboard.css")
VUE_SRC = _read_asset("vendor/vue.global.prod.js")
TEMPLATE_SRC = _read_asset("dashboard.template.html")
APP_JS_SRC = _read_asset("dashboard.app.js")


def _actions_of(audit: dict) -> list:
    actions = audit.get("actions")
    if actions is None:                       # audits written before the action model carry only findings
        actions = build_actions([f for f in audit.get("findings", []) if not f.get("suppressed")])
    return actions


def _project_action(a: dict) -> dict:
    cves = []
    for f in a.get("fixes", []):
        if f.get("cve") or f.get("id"):
            cves.append({"id": f.get("cve") or f.get("id"), "title": f.get("detail") or ""})
    return {
        "repo": a.get("repo"), "ref": a.get("ref"), "unit": a.get("unit"),
        "date": a.get("date"), "pkg": a.get("pkg"),
        "kind": a.get("kind"), "refKind": a.get("refKind"), "owner": a.get("owner"),
        "current_version": a.get("current_version"),
        "fix_version": a.get("fix_version"), "command": a.get("command"),
        "recommendation": a.get("recommendation"), "worst": a.get("worst"),
        "status": a.get("status"), "finding_count": a.get("finding_count"),
        "critical_count": a.get("critical_count"), "first_seen": a.get("first_seen"),
        "cves": cves[:_MAX_CVES], "sources": a.get("sources", []), "files": a.get("files", []),
    }


def _endpoints_of(inventory: dict) -> list:
    out = []
    for r in inventory.get("repos", []):
        for e in r.get("endpoints", []):
            out.append({"repo": r.get("path"), "domain": e.get("domain"),
                        "vendor": e.get("vendor"), "version": e.get("version"),
                        "classified": bool(e.get("classified")),
                        "file_count": e.get("file_count"), "files": e.get("files", [])})
    return out


def _gitlab_hosts() -> set:
    return {h.strip() for h in os.environ.get("DRIFT_GITLAB_HOSTS", "").split(",") if h.strip()}


def _repo_label(remote_url, fallback: str) -> str:
    """`https://host/group/repo(.git)` -> `group/repo`, else the fallback (the repo path).
    A display label only — never an identity (that stays the repo path / fingerprint)."""
    m = re.match(r"^https?://[^/]+/(.+?)(?:\.git)?/?$", str(remote_url or ""))
    return m.group(1) if m else fallback


def _permalink(remote_url, head_sha, loc, gitlab_hosts=frozenset()) -> str | None:
    """Build a GitHub/GitLab blob permalink pinned to head_sha, or None (plain text).
    A self-hosted GitLab host isn't guessable from the URL — it's allow-listed. The list comes
    from the drift.yml fleet (its shared host, threaded in as `gitlab_hosts`), plus
    $DRIFT_GITLAB_HOSTS as a fallback/override. Unknown host -> None (never a guessed link)."""
    if not remote_url or not head_sha or not loc:
        return None
    path, _, line = str(loc).rpartition(":")
    if not path or not line.isdigit():        # no "path:line" split -> whole loc is the path
        path, line = str(loc), ""
    m = re.match(r"^https://([\w.-]+)/(.+)$", remote_url)
    if not m:
        return None
    host, owner_repo = m.group(1), m.group(2)
    anchor = f"#L{line}" if line else ""
    if host == "github.com":
        return f"https://github.com/{owner_repo}/blob/{head_sha}/{path}{anchor}"
    if host == "gitlab.com" or "gitlab" in host or host in (set(gitlab_hosts) | _gitlab_hosts()):
        return f"https://{host}/{owner_repo}/-/blob/{head_sha}/{path}{anchor}"
    return None


def _build_projection(inventory: dict, audit: dict, gitlab_hosts=frozenset()) -> dict:
    repo_meta = {r.get("path"): {"remote_url": r.get("remote_url"), "head_sha": r.get("head_sha")}
                 for r in inventory.get("repos", [])}
    actions = [_project_action(a) for a in _actions_of(audit)]
    for a in actions:
        rm = repo_meta.get(a["repo"], {})
        # display by the clean project path (example-org/amazonspapi), not the internal clone slug
        # (example-org-amazonspapi-f5043548). `repo` stays the stable identity for fingerprints.
        a["repoLabel"] = _repo_label(rm.get("remote_url"), a["repo"])
        a["files"] = [{"loc": loc,
                       "href": _permalink(rm.get("remote_url"), rm.get("head_sha"), loc, gitlab_hosts)}
                      for loc in a["files"]]
    endpoints = _endpoints_of(inventory)
    cov = inventory.get("coverage") or {}
    residue = cov.get("residue") or {}
    private, covered_deps = [], []
    for p in cov.get("privateSources", []):
        for pkg in p.get("packages", []):
            private.append({"repo": p.get("repo"), "source": pkg.get("pkg"),
                            "kind": "package", "via": pkg.get("via", "")})
        for url in p.get("repositories", []):
            private.append({"repo": p.get("repo"), "source": url, "kind": "repo", "via": ""})
        # deps that ARE scanned as their own fleet repo — the dependency edge, NOT a blind
        # spot; surfaced separately so they never inflate the "couldn't crawl" tile/list.
        for url in p.get("covered", []):
            covered_deps.append({"repo": p.get("repo"), "source": url})
    counts = {
        "critical": sum(1 for a in actions if a["worst"] == "CRITICAL"),
        "fixes": sum(1 for a in actions if a["status"] == "DEPRECATED"),
        "eol": sum(1 for a in actions if a["kind"] == "eol"),
        "sunsets": sum(1 for a in actions if a["kind"] == "sunset"),
        # PM ask: a vendor API that is ALREADY retired (past its removal date) is a
        # different, more urgent thing than a CVE "fix" or an upcoming deadline — an
        # integration that is broken NOW, not one to plan around. Its own count.
        # A sunset is DEPRECATED only when its date is in the PAST (status_for gives future
        # dates REVIEW), so `DEPRECATED and date` is exactly "retired, date known" — and it
        # recomputes from the action alone, so verify needs no `now`. A deprecated-no-date
        # sunset is deliberately excluded: no announced deadline means not yet past-due.
        "pastDue": sum(1 for a in actions
                       if a["kind"] == "sunset" and a["status"] == "DEPRECATED"
                       and a.get("date")),
        "apis": len({e["vendor"] for e in endpoints if e["classified"]}),
        "unknown": sum(1 for e in endpoints if not e["classified"]),
        "reposAffected": (audit.get("counts") or {}).get("reposAffected", 0),
        # "1 repos" read as "it only scanned one". Both numbers, or neither.
        "reposScanned": (inventory.get("scope") or {}).get("reposScanned", 0),
        "private": len(private),
        # sources you ASKED to scan that could not be read (URL 404/no-access, a typo, a
        # plain folder with no code). "cannot see" is NOT "clean" — this count exists so the
        # report can never render green over a repo it silently failed to open.
        "unscannable": len(cov.get("rootsUnscannable", [])),
        # vendors we CALL but whose retirement list nobody has checked. Counted as
        # unaudited+stale, because both mean "0 findings here is not evidence of clean".
        "unaudited": sum(1 for r in (audit.get("coverage") or {}).get("catalog", [])
                         if r.get("verdict") != "CURRENT"),
        # the two delivery streams, tallied from the actions' owner field. devops =
        # packages + runtimes; developer = API sunsets + frameworks. verify checks these
        # sum back to the fixes/review totals so the two queues can't silently miscount.
        "byOwner": {
            o: {"fixes": sum(1 for a in actions
                             if a.get("owner") == o and a["status"] == "DEPRECATED"),
                "review": sum(1 for a in actions
                              if a.get("owner") == o and a["status"] == "REVIEW")}
            for o in ("devops", "developer")},
    }
    return {
        # the payload IS drift.json; it names its own contract so any consumer — the
        # Markdown renderer, an agent, an external validator — can check the version
        # it is reading against docs/schema/
        "schemaVersion": "drift/v1",
        "generated": audit.get("generated", ""),
        "counts": counts,
        "delta": audit.get("delta"),
        "actions": actions,
        "endpoints": endpoints,
        "private": private,
        "coveredDeps": covered_deps,
        "sdkMediated": cov.get("sdkMediated", []),
        "catalog": (audit.get("coverage") or {}).get("catalog", []),
        "coverageNotes": (audit.get("coverage") or {}).get("notes", []),
        "coverageGrades": [dict(g, repoLabel=_repo_label(
            repo_meta.get(g.get("repo"), {}).get("remote_url"), g.get("repo")))
            for g in residue.get("byRepo", [])],
        "shapes": cov.get("shapes", []),
        "residueSamples": residue.get("pathLiterals", []),
        # the roots the scanner could not open, carried verbatim from inventory coverage so
        # every projection (drift.md, the dashboard) can surface them and verify can enforce
        # that they are surfaced. Each: {root, reason}.
        "rootsUnscannable": cov.get("rootsUnscannable", []),
    }


def _e(s) -> str:
    """HTML-text escape (NOT audit_render._esc, which escapes markdown pipes)."""
    return html.escape("" if s is None else str(s), quote=True)


def _blob(projection: dict) -> str:
    """Serialize the projection and neutralize the one HTML-in-JS hazard: a scan string
    containing </script> would otherwise close the embedding <script> element. Replacing
    < with its \\u003c JSON escape is transparent to JSON.parse."""
    raw = json.dumps(projection, ensure_ascii=False, sort_keys=True)
    return raw.replace("<", "\\u003c")


def build_payload(inventory: dict, audit: dict, *, diff: dict | None = None,
                  gitlab_hosts=frozenset()) -> dict:
    """The dashboard's DATA — everything the page displays, before any HTML exists.

    This is the contract. `drift.json` is this dict and the page embeds this same
    dict, so what a test asserts on is what a reader sees. Rendered HTML cannot be
    verified by anything that does not have eyes: two bugs shipped this week — a tile
    reading `Sunsets 1` over twelve findings, then twelve rows all labelled "eBay" —
    both passed their unit tests because the tests ran a layer below the artifact.
    """
    projection = _build_projection(inventory, audit, gitlab_hosts)
    if diff is not None:                 # the inventory drift DRIFT.md used to carry
        projection["inventoryDrift"] = diff
    return projection


def _empty_bundle() -> dict:
    return {"sbom": {"bomFormat": "CycloneDX", "components": [], "vulnerabilities": []},
            "spdx": {"spdxVersion": "SPDX-2.3", "packages": []},
            "sarif": {"version": "2.1.0",
                      "runs": [{"tool": {"driver": {"rules": []}}, "results": []}]}}


def build_bundle(inventory: dict, audit: dict, now: str) -> dict:
    """The standard-format side-payloads the dashboard embeds, built from the SAME
    inventory/audit so the embedded copies are byte-for-byte what `drift-scan sbom`/`sarif`
    would write. run.py and render_dashboard both go through here."""
    from agent.lib import sbom as _sbom, spdx as _spdx, sarif as _sarif
    return {"sbom": _sbom.build_sbom(inventory, audit, now),
            "spdx": _spdx.build_spdx(inventory, now),
            "sarif": _sarif.build_sarif(audit)}


def render_dashboard(inventory: dict, audit: dict, now: str, *, diff: dict | None = None,
                     gitlab_hosts=frozenset()) -> str:
    """The cockpit: the drift report + the SBOM (CycloneDX/SPDX) + SARIF, one self-contained file."""
    payload = build_payload(inventory, audit, diff=diff, gitlab_hosts=gitlab_hosts)
    return render_payload(payload, now, bundle=build_bundle(inventory, audit, now))


def _blob_script(el_id: str, obj) -> str:
    """An embedded JSON blob, `<`-escaped so a scan string containing </script> can't close
    the element (the same hardening as _blob)."""
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True).replace("<", "\\u003c")
    return f'<script id="{el_id}" type="application/json">{raw}</script>'


def render_payload(projection: dict, now: str, *, bundle: dict | None = None,
                   adhoc: dict | None = None, leads: dict | None = None) -> str:
    """Injector: CSS + the in-DOM Vue template + the data blobs + the vendored Vue runtime
    + the app skeleton. `now` is unused by the body (the page reads `projection["generated"]`,
    which `_build_projection` sets from the same `now` the caller audited with) — kept for
    signature stability with callers (run.py, cli.py) that still pass it.

    `adhoc`/`leads` are the OPTIONAL AI-tier documents (drift-adhoc/v1, drift-leads/v1). They are
    emitted as SEPARATE, id'd blobs after `drift-data`, which stays byte-identical — so
    verify.check_blob_matches_payload (id-anchored, non-greedy) is unaffected: the mechanical proof
    the AI tiers cannot touch the certified one. Absent (None) → the tab is hidden, not shown as "0"
    ("cannot see" ≠ "clean" for the new tiers too)."""
    bundle = bundle or _empty_bundle()
    p = ['<!doctype html>', '<html lang="en">', '<head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width, initial-scale=1">',
         '<title>Drift Detector — DevSecOps Cockpit</title>',
         "<style>" + CSS_SRC + "</style></head><body>",
         TEMPLATE_SRC,
         '<script id="drift-data" type="application/json">' + _blob(projection) + "</script>",
         _blob_script("sbom-data", bundle["sbom"]),
         _blob_script("spdx-data", bundle["spdx"]),
         _blob_script("sarif-data", bundle["sarif"])]
    if adhoc is not None:
        p.append(_blob_script("adhoc-data", adhoc))
    if leads is not None:
        p.append(_blob_script("leads-data", leads))
    p += ["<script>" + VUE_SRC + "</script>",
          "<script>" + APP_JS_SRC + "</script>",
          "</body></html>"]
    return "\n".join(p)
