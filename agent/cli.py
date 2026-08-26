"""CLI for the Drift Detector.

Builds the code-level third-party integration inventory (the IR /
inventory.json), audits it, and renders the single report surface
(dashboard.html). Driven by the bundled `bin/drift-scan` runner.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

from agent import inventory_scan as inventory_scan_mod
from agent.lib import scan_util


def _capped_jobs(requested: int, command: str = "run") -> int:
    """Clamp a --jobs value to the CPU count, printing a one-line notice to stderr when it
    had to reduce what the user asked for. `requested <= 1` passes through untouched — the
    cap is a ceiling on concurrency, never a floor, and never a new default.

    `command` names the subcommand in that notice: the prefix used to be the literal string
    "run", so `inventory-scan --jobs 999` printed a message about a command the user had not
    typed.

    Why cap at all: `ast-grep` (the scan engine) is itself internally parallel, so `--jobs N`
    runs N of those inside the machine's own core count — oversubscribed. On a loaded machine
    that can push a single repo's scan past `agent/lib/engine.py`'s fixed 600s timeout, which
    the pool records as a `reposErrored` entry exactly like a real scan failure; the same repo
    would pass cleanly at `--jobs 1`. Capping to `os.cpu_count()` bounds that, though it does
    not eliminate contention with whatever else is running on the box.
    """
    if requested <= 1:
        return requested
    cap = os.cpu_count() or 1
    if requested > cap:
        print(f"{command}: --jobs {requested} capped to {cap} (this machine's CPU count) — "
              f"ast-grep is itself internally parallel, so more workers than cores "
              f"oversubscribes the CPU and can push a repo past the engine's 600s timeout",
              file=sys.stderr)
        return cap
    return requested


def _cmd_inventory_scan(args) -> int:
    progress = None
    if getattr(args, "progress", False):
        print("drift-detector · deterministic static-analysis (local · 0 LLM tokens)",
              file=sys.stderr, flush=True)

        def progress(msg):
            print(f"⚙ {msg}", file=sys.stderr, flush=True)

    t0 = time.perf_counter()
    try:
        out = inventory_scan_mod.scan_folder(args.root, args.state, args.now,
                                             progress=progress,
                                             jobs=_capped_jobs(getattr(args, "jobs", 1),
                                                               "inventory-scan"))
    except RuntimeError as exc:
        print(f"inventory-scan failed: {exc}", file=sys.stderr)
        return 2
    dt = time.perf_counter() - t0
    with open(args.out_json, "w", encoding="utf-8") as fh:
        json.dump(out["doc"], fh, ensure_ascii=False, indent=2, sort_keys=True)
    d = out["doc"]
    print(f"✓ {len(d['repos'])} repos · {len(d.get('unique_apis', []))} APIs · "
          f"{len(d.get('unique_packages', []))} packages · "
          f"{len(d['coverage']['reposErrored'])} errors · {dt:.1f}s")
    return 0


def _cmd_audit(args) -> int:
    from agent.audit import audit_inventory
    from agent.lib.dashboard_render import render_dashboard

    with open(args.in_json, encoding="utf-8") as fh:
        doc = json.load(fh)
    http = None
    if getattr(args, "offline", False):
        def http(*a, **k):
            raise ConnectionError("offline")
    if getattr(args, "progress", False):
        print("drift-detector audit · OSV.dev + endoflife.date (deterministic · 0 LLM tokens)",
              file=sys.stderr, flush=True)

    audit = audit_inventory(doc, args.now, http=http) if http else audit_inventory(doc, args.now)
    from agent.lib.findings_state import apply_lifecycle
    apply_lifecycle(audit, os.path.dirname(os.path.abspath(args.in_json)), args.now)

    if getattr(args, "out_json", None):
        with open(args.out_json, "w", encoding="utf-8") as fh:
            json.dump(audit, fh, ensure_ascii=False, indent=2, sort_keys=True)
    if getattr(args, "out_html", None):
        with open(args.out_html, "w", encoding="utf-8") as fh:
            fh.write(render_dashboard(doc, audit, args.now))
    c = audit["counts"]
    print(f"✓ audit: 🔴 {c.get('DEPRECATED', 0)} action-required · 🟠 {c.get('REVIEW', 0)} review · "
          f"across {c.get('reposAffected', 0)} repos")
    return 0


def _cmd_run(args) -> int:
    from agent.run import run_pipeline
    roots = args.root
    gitlab_hosts = frozenset()
    if getattr(args, "config", None):
        from agent.lib import ops_config
        try:
            cfg = ops_config.load(args.config)
        except (OSError, ops_config.ConfigError) as exc:
            print(f"run: bad --config — {exc}", file=sys.stderr)
            return 2
        roots = args.root or cfg["fleet"]                # flag overrides config
        # the fleet's shared host IS the permalink host — so call-site links resolve to the
        # SAME GitLab the repos were cloned from, configured in drift.yml, not a CI env var
        gitlab_hosts = frozenset({cfg["host"]})
    if not roots:
        print("run: no repos to scan — pass --root or a --config with a fleet", file=sys.stderr)
        return 2
    if getattr(args, "jobs", 1) < 1:
        print("run: --jobs must be 1 or greater", file=sys.stderr)
        return 2
    jobs = _capped_jobs(getattr(args, "jobs", 1), "run")
    resolve_verdicts = None
    if getattr(args, "resolve", None):
        try:
            with open(args.resolve, encoding="utf-8") as fh:
                resolve_payload = json.load(fh)
        except OSError as exc:
            print(f"run: --resolve {args.resolve!r} could not be read — {exc}", file=sys.stderr)
            return 2
        except ValueError as exc:      # json.JSONDecodeError
            print(f"run: --resolve {args.resolve!r} is not valid JSON — {exc}", file=sys.stderr)
            return 2
        # same unwrap `resolve --apply` uses: a bare verdicts list, or {"verdicts": [...]}
        # (exactly the shape `resolve --apply` writes to resolution.json)
        resolve_verdicts = (resolve_payload.get("verdicts", resolve_payload)
                            if isinstance(resolve_payload, dict) else resolve_payload)
        # A JSON *string* (or number/bool) unwraps to itself above, and `resolve.check_verdicts`
        # happily iterates it — a string iterates its CHARACTERS, so a plain-text --resolve file
        # used to fail deep inside the gate with a baffling `verdict #1 ('e'): not a mapping`
        # instead of a clear, immediate refusal naming the actual problem.
        if not isinstance(resolve_verdicts, list):
            print(f"run: --resolve {args.resolve!r} must contain a list of verdicts (or "
                  f"{{'verdicts': [...]}}), got {type(resolve_verdicts).__name__}",
                  file=sys.stderr)
            return 2
    progress = None
    if getattr(args, "progress", False):
        print("drift-detector · scan → audit → deliver (deterministic · 0 LLM tokens)",
              file=sys.stderr, flush=True)

        def progress(msg):
            print(f"⚙ {msg}", file=sys.stderr, flush=True)
    try:
        out = run_pipeline(roots, args.state, args.now,
                           pull=getattr(args, "pull", False), progress=progress,
                           gitlab_hosts=gitlab_hosts, resolve=resolve_verdicts,
                           jobs=jobs)
    except RuntimeError as exc:
        print(f"run failed: {exc}", file=sys.stderr)
        return 2
    # Nothing scanned is NEVER a clean bill. A URL, a typo, or a plain non-git folder
    # otherwise printed a green checkmark over zero repos — the failure the PM hit and
    # the exact "cannot see == clean" collapse this tool exists to refuse.
    if out.get("scope", {}).get("reposScanned", 0) == 0:
        print("✗ scanned 0 repositories — this is NOT a clean result.", file=sys.stderr)
        for u in (out.get("rootsUnscannable") or []):
            print(f"    {u['reason']}", file=sys.stderr)
        print("  Nothing was audited. Point at a git checkout (or a folder containing one).",
              file=sys.stderr)
        return 4                           # 'found nothing to scan' is 'couldn't verify'

    # A repo that blew up mid-sweep is not a repo that came back clean. The scan has always
    # recorded these in coverage.reposErrored; until now nothing a caller sees read them — not
    # the banner, not the exit code — and `reposScanned` counts them, so a run in which EVERY
    # repo errored printed `✓ scan+audit: 🔴 0 · 🟠 0` and exited 0. That is the same
    # "cannot see == clean" collapse as the zero-repos case above, and --jobs makes it newly
    # reachable: oversubscribing ast-grep can push a repo past the engine's 600s timeout, which
    # lands in exactly this list. stderr and the exit code ONLY — the artifacts are untouched,
    # because their byte-identity across --jobs values is a proven guarantee of this branch.
    errored = out.get("reposErrored") or []
    if errored:
        names = [e.get("repo", "?") for e in errored]
        head, rest = names[:8], max(0, len(names) - 8)
        print(f"⚠ {len(errored)} repo(s) errored and were NOT read: "
              f"{', '.join(head)}{f' (+{rest} more)' if rest else ''} — their findings are "
              f"MISSING, not absent.", file=sys.stderr)
        for e in errored[:8]:
            print(f"    {e.get('repo', '?')}: {e.get('reason', '')}", file=sys.stderr)
        discovered = out.get("reposDiscovered") or 0
        if discovered and len(errored) >= discovered:
            print(f"✗ all {discovered} discovered repositories errored — this is NOT a clean "
                  f"result.", file=sys.stderr)
            print("  Nothing was actually read. Fix the cause above and re-run; if this "
                  "started with --jobs, try a lower value or --jobs 1.", file=sys.stderr)
            return 4                       # 'read nothing' is 'couldn't verify', same as above

    # A root that failed to resolve is surfaced even when OTHERS scanned fine — a typo'd
    # or unreachable root buried in a good run must not disappear.
    for u in (out.get("rootsUnscannable") or []):
        print(f"⚠ skipped: {u['reason']}", file=sys.stderr)

    # Distinct, non-zero exit codes for the non-clean `--resolve` outcomes: without these an
    # automated caller had no way to tell "resolved" from "refused" short of scraping stderr —
    # `run` exited 0 either way. Separate from (and checked before) the --fail-on-deprecated
    # gate below, which can still tighten this further (exit 3/4) but never loosens it back to 0.
    resolve_rc = 0
    rr = out.get("resolve")
    if rr and rr["status"] == "applied":
        w = rr["written"]
        print(f"✓ resolve applied: {w['own_domain']} own-domain, {w['vendor_identity']} "
              f"vendor-identity, {w['retiring']} retiring, {w['needs_human']} needs-human — "
              f"re-scanned; drift.json reflects the re-scan", file=sys.stderr)
    elif rr and rr["status"] == "rejected":
        print("⚠ resolve: GATE REJECTED — nothing was applied, drift.json reflects the scan "
              "BEFORE resolution:", file=sys.stderr)
        for p in rr["problems"]:
            print("  •", p, file=sys.stderr)
        resolve_rc = 5                     # 'refused' must be distinguishable from 'resolved'
    elif rr and rr["status"] == "degraded":
        w = rr["written"]
        print(f"⚠ resolve: applied ({w['own_domain']} own-domain, {w['vendor_identity']} "
              f"vendor-identity, {w['retiring']} retiring) but the RE-SCAN failed "
              f"({rr['detail']}) — drift.json reflects the scan BEFORE resolution; the catalog "
              f"overlay was still updated, so a plain re-run will pick it up", file=sys.stderr)
        resolve_rc = 6                     # 'partially applied, re-scan blew up' — its own code
    elif rr and rr["status"] == "error":
        print(f"⚠ resolve: could not apply the verdicts ({rr['detail']}) — drift.json reflects "
              f"the scan BEFORE resolution", file=sys.stderr)

    # record where this run wrote, so `drift-scan clean --all` can later find the scattered
    # <folder>/.drift-detector dirs without a $HOME-wide search. Best-effort; never fails a scan.
    from agent.lib import cleanup as _cleanup
    _cleanup.record_run(args.state)

    c = out["auditCounts"]                          # raw per-finding tallies (drive the CI gate)
    # DISPLAY the CANONICAL, post-dedup counts (what drift.json/the report shows), falling back to
    # the raw tallies if a caller didn't supply them — the raw ones over-report and contradict the
    # report the user then reads (a fresh scan run always supplies canonical `counts`).
    cc = out.get("counts") or {}
    fixes = cc.get("fixes", c.get("DEPRECATED", 0))
    review = cc.get("review", c.get("REVIEW", 0))
    print(f"✓ scan+audit: 🔴 {fixes} action-required · 🟠 {review} review")
    # A degraded run (an audit source unreachable) must NEVER read as clean — surface it LOUDLY on
    # every run, not just under the CI gate. 'Couldn't check' is not 'clean' (principle 1).
    cov = out.get("coverage", {})
    if cov.get("osvErrors") or cov.get("eolErrors"):
        print(f"⚠ DEGRADED: {cov.get('osvErrors', 0)} CVE + {cov.get('eolErrors', 0)} EOL source "
              f"check(s) failed this run — some findings are UNCONFIRMED (served from cache or "
              f"skipped), and absent ones are NOT proven clean. Re-run with network access.",
              file=sys.stderr)
    if getattr(args, "fail_on_deprecated", False):
        if cov.get("osvErrors") or cov.get("eolErrors"):
            print("✗ gate: audit sources (OSV/endoflife) were unreachable — cannot certify clean "
                  "(exit 4). Re-run with network access.", file=sys.stderr)
            return 4                       # 'couldn't check' is NOT 'clean'
        if c.get("DEPRECATED", 0) > 0:     # gate on the raw signal: ANY deprecated finding fails
            print(f"✗ gate: {c['DEPRECATED']} DEPRECATED finding(s) (excluding muted) — failing (exit 3)",
                  file=sys.stderr)
            return 3
    return resolve_rc


def _cmd_clean(args) -> int:
    """Remove the tool's artifacts — scattered run outputs + ~/.drift caches. Keeps the absorbed
    catalog unless --catalog. `--report` summarizes without deleting (the plugin polls this to
    proactively offer a cleanup)."""
    from agent.lib import cleanup

    if getattr(args, "report", False):
        pl = cleanup.plan(all_=True, state=None, include_catalog=False)
        n, total = len(pl["targets"]), pl["total"]
        print(f"reclaimable: {n} run output(s) · {cleanup.human_size(total)}")
        print("CLUTTER " + json.dumps({"count": n, "bytes": total}))    # machine line for the plugin
        return 0

    if not args.all and not args.state:
        print("clean: pass --state <dir> (one run) or --all (everything the tool recorded), "
              "or --report to just summarize.", file=sys.stderr)
        return 2
    if args.state and not args.all and not cleanup.is_state_dir(args.state):
        print(f"clean: refusing — '{args.state}' is not a drift state dir (no inventory.json/"
              f"drift.json, not a .drift-detector). Nothing removed.", file=sys.stderr)
        return 2

    pl = cleanup.plan(all_=args.all, state=args.state, include_catalog=getattr(args, "catalog", False))
    if not pl["targets"]:
        print("nothing to clean.")
        return 0
    print(f"will remove {len(pl['targets'])} item(s) · {cleanup.human_size(pl['total'])}:")
    for t in pl["targets"]:
        print(f"  {cleanup.human_size(t['size']):>10}  {t['path']}")
    for p in pl["preserved"]:
        print(f"     (kept)  {p['path']}  — your absorbed catalog; pass --catalog to remove it too")
    if not getattr(args, "yes", False):
        try:
            resp = input("proceed? [y/N] ").strip().lower()
        except EOFError:
            resp = "n"
        if resp not in ("y", "yes"):
            print("aborted — nothing removed.")
            return 0
    removed = cleanup.execute(pl["targets"])
    print(f"✓ removed {len(removed)} item(s) · reclaimed {cleanup.human_size(pl['total'])}.")
    return 0


def _cmd_schedule(args) -> int:
    from pathlib import Path
    from agent.lib import schedule as sched
    plugin_root = str(Path(__file__).resolve().parent.parent)
    try:
        line = sched.install_cron(args.root, args.state, args.at, plugin_root=plugin_root,
                                  pull=getattr(args, "pull", False))
    except Exception as exc:      # missing/failed crontab -> actionable message, not a traceback
        print(f"schedule failed: {exc}\n  Is 'crontab' installed and the cron service running?",
              file=sys.stderr)
        return 2
    print("installed cron:\n  " + line)
    return 0


def _cmd_unschedule(args) -> int:
    from agent.lib import schedule as sched
    try:
        removed = sched.remove_cron(args.state)
    except Exception as exc:
        print(f"unschedule failed: {exc}", file=sys.stderr)
        return 2
    print("removed schedule" if removed else "no schedule found")
    return 0


def _cmd_plan(args) -> int:
    """Resolve the sources and report what WOULD scan — without scanning.

    The approval gate before a run: clones URLs, classifies local paths (git repo / plain
    folder / cloned / error), and prints one line per source so a human can confirm the
    right things resolved before any audit happens. Exit 0 if at least one project
    resolves, 4 if nothing does — a plan that resolves to nothing is not a clean plan.
    """
    from agent.lib import source_resolver
    resolved = source_resolver.resolve_sources(args.root, args.state)
    projects, errors = resolved["projects"], resolved["errors"]
    kind_label = {"local-git": "git repo", "remote": "cloned (git)",
                  "local-plain": "plain folder — no history/permalinks"}
    print(f"drift plan · {len(projects)} project(s) will scan"
          + (f", {len(errors)} unreadable" if errors else ""))
    for abs_, ident, kind in projects:
        print(f"  ✓ {ident:<28} {kind_label.get(kind, kind):<34} {abs_}")
    for e in errors:
        print(f"  ✗ {e['reason']}")
    if not projects:
        print("Nothing would scan — fix the sources above before running.", file=sys.stderr)
        return 4
    return 0


def _cmd_catalog_check(args) -> int:
    """Re-check vendors' live sources against our catalog (the freshness loop).

    Reports only. Exit 0 when everything is up to date, 3 when a vendor lists a new or
    moved retirement (or a computed rule has drifted) — action a human should take — and
    4 if a source was unreachable, since 'could not check' is never 'up to date'.
    """
    from agent import catalog_check
    report = catalog_check.check_all(now=args.now)
    print(catalog_check.render(report))
    if any(r.get("error") for r in report):
        return 4
    return 3 if catalog_check.needs_attention(report) else 0


def _cmd_catalog_refresh(args) -> int:
    """Reconcile a vendor's published API specs against our sunset catalog.

    Reports, never writes. Exit 0 clean, 3 when the vendor contradicts itself (our
    catalog dates a family the vendor still publishes unflagged) — that is not an error
    in our data, it is a disagreement a human has to resolve, and it should be loud
    rather than buried in output nobody reads.
    """
    from agent import catalog_refresh
    try:
        result = catalog_refresh.refresh(args.vendor)
    except KeyError as exc:
        print(f"catalog-refresh: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"catalog-refresh: could not reach the vendor's specs ({exc}). "
              f"Nothing was concluded — an unreachable source is not a clean one.",
              file=sys.stderr)
        return 4
    print(catalog_refresh.render(result))
    return 3 if result["specUnflagged"] else 0


# Vendors whose single "current" attestation would be DISHONEST — many products on
# independent lifecycles, retirements happen constantly (Google retires services monthly).
# A `current` verdict for these is refused; they must be scoped per product first, then
# attested per product. (Fable review 2026-08-11: an over-broad green on Google would be
# the tool's first dishonest verdict.)
_MEGA_VENDORS = {
    "Google APIs", "Google Cloud", "Amazon AWS", "Amazon Web Services",
    "Microsoft Azure", "Azure", "Oracle Cloud", "IBM Cloud",
}
# Source kinds that make a `current` verdict trustworthy — the page that WOULD reveal a
# retirement if there were one. A product/marketing page or a login redirect does NOT
# qualify: the Seller Snap attestation cited a 302-to-login and is exactly the weak source
# this guard rejects (Fable review 2026-08-11).
_CURRENT_SOURCE_KINDS = {"deprecation-page", "changelog", "versioning-policy",
                         "api-reference", "release-notes"}


def _unattested_vendors(vendors_path=None, attest_path=None) -> list:
    """[{vendor, domains}] for every vendor in vendors.yaml with NO attestation — the batch
    research work-list. Each is a proven future demo blank (detected but never checked)."""
    from agent.lib import vendors as _vendors, catalog_coverage
    att = catalog_coverage.load_attestations(attest_path)
    out = []
    for v in _vendors.load_vendors(vendors_path):
        name = getattr(v, "vendor", None)
        if name and name not in att:
            out.append({"vendor": name, "domains": list(getattr(v, "domains", []) or [])})
    return out


def _append_attestations(path: str, new_atts: list) -> None:
    """Merge attestations into a YAML file (list of {vendor,checked,source,by,note}), dedup by
    vendor (newest wins), sorted. Matches catalog_attestations.yaml's shape so the file can be
    reviewed as a diff and merged into the committed catalog."""
    import yaml
    existing = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            existing = yaml.safe_load(fh) or []
    by_vendor = {a["vendor"]: a for a in existing if isinstance(a, dict) and a.get("vendor")}
    for a in new_atts:
        by_vendor[a["vendor"]] = a
    ordered = sorted(by_vendor.values(), key=lambda a: a["vendor"])
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(ordered, fh, default_flow_style=False, sort_keys=False, allow_unicode=True)


def _research_vendors(args) -> int:
    """Batch/catalog research — the work-list is vendors.yaml (unattested), not a scanned repo.
    List mode prints the vendors to research; --apply gates a completed pass and writes `current`
    verdicts as attestations (mega-vendors refused, weak sources rejected) and reports `retiring`
    verdicts for `absorb`."""
    spec = args.vendors
    if not args.apply:
        work = _unattested_vendors()
        if spec != "all-unattested":
            want = {s.strip() for s in spec.split(",") if s.strip()}
            work = [w for w in work if w["vendor"] in want]
        print(json.dumps(work, indent=2))
        print(f"# {len(work)} vendor(s) to research (unattested)", file=sys.stderr)
        return 0
    if not args.now:
        print("research --vendors --apply: pass --now <YYYY-MM-DD> (the date you fetched the sources)",
              file=sys.stderr)
        return 2
    from agent import absorb
    with open(args.apply, encoding="utf-8") as fh:
        payload = json.load(fh)
    verdicts = payload.get("verdicts", payload) if isinstance(payload, dict) else payload
    problems, attestations, sunsets, skipped = [], [], [], []
    for v in verdicts:
        vendor = v.get("vendor") or v.get("host")
        status = v.get("status")
        if status == "retiring":
            if not v.get("source_url"):
                problems.append(f"{vendor}: 'retiring' with no source_url"); continue
            if not v.get("date"):
                problems.append(f"{vendor}: 'retiring' with no date"); continue
            if not v.get("excerpt"):
                problems.append(f"{vendor}: 'retiring' with no excerpt"); continue
            if not absorb.date_in_text(v.get("date"), v.get("excerpt")):
                problems.append(f"{vendor}: date {v.get('date')} not in the fetched excerpt "
                                f"(verbatim-date check)"); continue
            sunsets.append(v)
            attestations.append({"vendor": vendor, "checked": args.now, "source": v["source_url"],
                                 "by": "ai-research", "note": f"retirement found ({v.get('date')})"})
        elif status == "current":
            if vendor in _MEGA_VENDORS:
                problems.append(f"{vendor}: mega-vendor — a blanket 'current' is dishonest; scope "
                                f"per product first"); continue
            if not v.get("source_url"):
                problems.append(f"{vendor}: 'current' with no source_url"); continue
            if not v.get("excerpt"):
                problems.append(f"{vendor}: 'current' with no excerpt — need the page text you read"); continue
            if v.get("source_kind") not in _CURRENT_SOURCE_KINDS:
                problems.append(f"{vendor}: 'current' source_kind={v.get('source_kind')!r} is not a "
                                f"deprecation/changelog/versioning page (weak-source guard)"); continue
            attestations.append({"vendor": vendor, "checked": args.now, "source": v["source_url"],
                                 "by": "ai-research", "note": (v.get("note") or v.get("excerpt") or "")[:180]})
        else:
            skipped.append(f"{vendor} ({status})")
    if problems:
        print("research: GATE REJECTED — these verdicts are not admissible:", file=sys.stderr)
        for p in problems:
            print("  •", p, file=sys.stderr)
        return 3
    if args.attest and attestations:
        _append_attestations(args.attest, attestations)
    print(f"✓ batch research: {len(attestations)} attestation(s) → {args.attest or '(no --attest)'}; "
          f"{len(sunsets)} sunset(s) to absorb; {len(skipped)} skipped")
    for s in sunsets:
        print(f"  🔴 sunset: {s.get('vendor')} — {s.get('date')} — {s.get('source_url')}")
    if skipped:
        print("  skipped (not-an-api / unverified):", ", ".join(skipped))
    return 0


def _cmd_research(args) -> int:
    """The research loop's deterministic half. Three modes:

      research --state <dir>                 → print the QUEUED work-list (untracked API services)
                                               as JSON — the input an AI research pass consumes.
      research --state <dir> --apply v.json  → gate-validate a completed pass and write research.json
                                               into the state (the AI-Frontier record). The gate: a
                                               'retiring' verdict MUST carry a source_url + parseable
                                               date — never an invented one. Zero tokens; the AI ran
                                               elsewhere, this only validates + records what it found.
      research --vendors all-unattested      → print the CATALOG work-list: every vendor in
                                               vendors.yaml with no attestation (no repo needed). Add
                                               --apply v.json --attest <out> --now <date> to gate the
                                               pass and write `current` verdicts as attestations
                                               (mega-vendors refused; weak sources rejected). This is
                                               the batch pre-warm — pre-audit the mainstream vendors so
                                               a demo shows "tracked-current" not "unaudited blank".
    """
    # ── Batch / catalog mode: research vendors from vendors.yaml, not a scanned repo. ──
    if getattr(args, "vendors", None):
        return _research_vendors(args)
    if not args.state:
        print("research: --state <dir> is required (or use --vendors for the catalog work-list)", file=sys.stderr)
        return 2
    drift_path = os.path.join(args.state, "drift.json")
    if not os.path.exists(drift_path):
        print(f"research: no drift.json in {args.state} — run a scan first", file=sys.stderr)
        return 3
    with open(drift_path, encoding="utf-8") as fh:
        drift = json.load(fh)
    if not args.apply:
        queued = sorted({e.get("domain") for e in drift.get("endpoints", [])
                         if e.get("coverage") == "queued"})
        print(json.dumps(queued, indent=2))
        print(f"# {len(queued)} vendor(s) queued for research", file=sys.stderr)
        return 0
    with open(args.apply, encoding="utf-8") as fh:
        payload = json.load(fh)
    verdicts = payload.get("verdicts", payload) if isinstance(payload, dict) else payload
    from agent import absorb
    problems = []
    for v in verdicts:
        if v.get("status") == "retiring":
            if not v.get("source_url"):
                problems.append(f"{v.get('host')}: 'retiring' with no source_url")
            elif not v.get("date"):
                problems.append(f"{v.get('host')}: 'retiring' with no date")
            elif not v.get("excerpt"):
                problems.append(f"{v.get('host')}: 'retiring' with no excerpt — need the page text that states the date")
            elif not absorb.date_in_text(v.get("date"), v.get("excerpt")):
                problems.append(f"{v.get('host')}: date {v.get('date')} does NOT appear in the fetched "
                                f"excerpt (verbatim-date check) — the model may have inferred it")
    if problems:
        print("research: GATE REJECTED — a retirement needs a fetched source + a real date:", file=sys.stderr)
        for p in problems:
            print("  •", p, file=sys.stderr)
        return 3
    record = {"checked": args.now, "researched": len(verdicts), "verdicts": verdicts}
    with open(os.path.join(args.state, "research.json"), "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=1)
    n_ret = sum(1 for v in verdicts if v.get("status") == "retiring")
    print(f"✓ research recorded: {len(verdicts)} verdict(s), {n_ret} sunset(s) found — written to "
          f"{os.path.join(args.state, 'research.json')}")
    print("  re-run `render`/`run` on this state to surface them in the AI Frontier plane.")
    return 0


def _cmd_resolve(args) -> int:
    """The no-queue resolution gate (docs/superpowers/specs/2026-08-13-no-queue-design.md).
    Two modes:

      resolve --state <dir>                        → print the UNRESOLVED work-list (every
                                                      endpoint still coverage=='queued' — host,
                                                      repo, call-sites, why) as JSON. What an AI
                                                      resolution pass consumes.
      resolve --state <dir> --apply v.json --now D  → gate-validate every verdict in v.json and,
                                                      ONLY if every one passes, land it as
                                                      reviewed overlay data (own-domains /
                                                      vendors / sunsets under $DRIFT_CATALOG_DIR)
                                                      that the deterministic scanner re-derives
                                                      on its next run. One rejected verdict
                                                      blocks the whole apply — nothing is
                                                      written. Zero tokens; the AI ran elsewhere,
                                                      this only validates + records what it found.
    """
    if not args.state:
        print("resolve: --state <dir> is required", file=sys.stderr)
        return 2
    drift_path = os.path.join(args.state, "drift.json")
    if not os.path.exists(drift_path):
        print(f"resolve: no drift.json in {args.state} — run a scan first", file=sys.stderr)
        return 3
    with open(drift_path, encoding="utf-8") as fh:
        drift = json.load(fh)
    from agent import resolve as resolve_mod
    if not args.apply:
        work = resolve_mod.work_list(drift)
        print(json.dumps(work, indent=2))
        print(f"# {len(work)} host(s) unresolved", file=sys.stderr)
        return 0
    if not args.now:
        print("resolve --apply: pass --now <YYYY-MM-DD> (the date you're recording this pass)",
              file=sys.stderr)
        return 2
    with open(args.apply, encoding="utf-8") as fh:
        payload = json.load(fh)
    verdicts = payload.get("verdicts", payload) if isinstance(payload, dict) else payload
    try:
        result = resolve_mod.apply(verdicts, now=args.now)
    except resolve_mod.ResolveRejected as exc:
        print("resolve: GATE REJECTED — nothing was written:", file=sys.stderr)
        for p in exc.args[0]:
            print("  •", p, file=sys.stderr)
        return 3
    record = {"checked": args.now, "resolved": len(verdicts), "verdicts": verdicts}
    with open(os.path.join(args.state, "resolution.json"), "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=1)
    w = result["written"]
    print(f"✓ resolve applied: {w['own_domain']} own-domain, {w['vendor_identity']} "
          f"vendor-identity, {w['retiring']} retiring, {w['needs_human']} needs-human — "
          f"written to {os.path.join(args.state, 'resolution.json')}")
    if w["own_domain"] or w["vendor_identity"] or w["retiring"]:
        print(f"  overlay updated under {os.environ.get('DRIFT_CATALOG_DIR')}")
    print("  re-run `run`/`render` on this state to re-derive coverage deterministically.")
    return 0


def _cmd_verify(args) -> int:
    """Check a produced report against itself: do the tiles agree with the tables, does
    the page carry the data the JSON claims, is every row distinguishable?

    Exists so "the dashboard is correct" stops being a claim anyone makes by looking at
    it. Two bugs shipped in one day because rendered HTML cannot be verified by reading
    the source — a tile said `Sunsets 1` over twelve findings, then twelve rows rendered
    with the same label. Both are mechanically detectable from the payload, and this is
    where that happens. Exit 0 clean, 3 violations, 4 nothing to verify.
    """
    import json as _json
    from agent.lib import verify as _verify

    state = args.state
    try:
        def _slurp(name):
            with open(os.path.join(state, name), encoding="utf-8") as fh:
                return fh.read()
        payload = _json.loads(_slurp("drift.json"))
        audit = _json.loads(_slurp("audit.json"))
        html = _slurp("dashboard.html")
        drift_md = _slurp("drift.md")
        # The coverage tree lives on its OWN page (summary.html), not the cockpit — see
        # agent/lib/summary_render.py. The tree checks below parse THIS, not `html`.
        summary_html = _slurp("summary.html")
    except OSError as exc:
        print(f"drift verify: nothing to verify — {exc}", file=sys.stderr)
        return 4

    violations = _verify.verify_payload(payload, audit.get("findings", []))
    checks = [(_verify.check_blob_matches_payload, (html, _json.dumps(payload))),
              (_verify.check_md_matches_payload, (drift_md, payload)),
              (_verify.check_unscannable_surfaced, (drift_md, payload)),
              (_verify.check_mermaid_wellformed, (drift_md,)),
              (_verify.check_tree_matches_payload, (summary_html, payload)),
              (_verify.check_tree_parity, (summary_html, drift_md)),
              (_verify.check_tree_definitions, (summary_html,)),
              (_verify.check_tree_rows, (summary_html, payload)),
              (_verify.check_summary_headline, (summary_html, payload)),
              (_verify.check_no_queue_label, (html,))]
    # chart.html is the OPTIONAL online view: absent is fine, but if present its embedded
    # payload must equal drift.json exactly — the charts must draw from the real data.
    try:
        chart = _slurp("chart.html")
        checks.append((_verify.check_blob_matches_payload,
                       (chart, _json.dumps(payload), "chart.html")))
    except OSError:
        pass
    # adhoc.json is the OPTIONAL shaped tier: absent is fine (most states have none), but if
    # present it must name THIS drift.json by the sha256 of its bytes on disk.
    try:
        adhoc_doc = _json.loads(_slurp("adhoc.json"))
        with open(os.path.join(state, "drift.json"), "rb") as _fh:
            checks.append((_verify.check_adhoc_hash_binds_certified, (adhoc_doc, _fh.read())))
    except OSError:
        pass
    # sbom.json is the OPTIONAL CycloneDX projection: absent is fine, but if present it must
    # equal a fresh projection of inventory.json + audit.json (never a stale/hand-edited BOM).
    try:
        sbom_doc = _json.loads(_slurp("sbom.json"))
        inventory = _json.loads(_slurp("inventory.json"))
        checks.append((_verify.check_sbom_matches_inventory, (sbom_doc, inventory, audit)))
    except OSError:
        pass
    for check, args_ in checks:
        try:
            check(*args_)
        except _verify.Violation as v:
            violations.append(v)

    if violations:
        print(f"✗ {len(violations)} invariant(s) violated:")
        for v in violations:
            print(f"  [{v.check}] {v.detail}")
        return 3
    n = payload.get("counts", {})
    # "unchecked", not "unaudited": the count is every non-CURRENT vendor, and since BLOCKED
    # exists that includes vendors we DID check and were refused. Naming the blocked share
    # here keeps the one line a reader sees from overstating how much is merely undone.
    blocked = n.get("blocked", 0)
    unchecked = f"{n.get('unaudited', 0)} unchecked-vendor(s)"
    if blocked:
        unchecked += f" ({blocked} blocked on access)"
    print(f"✓ report is self-consistent — {n.get('sunsets', 0)} sunsets, "
          f"{n.get('eol', 0)} eol, {unchecked}; "
          f"drift.md, summary.html, dashboard.html and drift.json all agree")
    return 0


def _cmd_preflight(args) -> int:
    from agent.lib.repo_discovery import discover_repos
    from agent.lib import private_sources
    repos = discover_repos([args.root])
    print(f"scan-readiness · {args.root}")
    print(f"  repos discovered: {len(repos)}")
    flagged, n_pkg, n_src = [], 0, 0
    for abs_path, name in repos:
        ps = private_sources.detect(abs_path)
        if ps["packages"] or ps["repositories"]:
            flagged.append((name, ps))
            n_pkg += len(ps["packages"])
            n_src += len(ps["repositories"])
    if flagged:
        print(f"  ⚠ {len(flagged)} repo(s) declare private package sources needing access "
              f"({n_pkg} git/file deps · {n_src} private composer repos):")
        for name, ps in flagged[:20]:
            bits = [p["pkg"] for p in ps["packages"]] + ps["repositories"]
            print(f"    - {name}: {', '.join(bits[:6])}" + (" …" if len(bits) > 6 else ""))
        print("  → these need source access; clone them locally and add them as a --root to scan them.")
    else:
        print("  ✓ no private package sources detected — full source coverage.")
    return 0


def _cmd_probe(args) -> int:
    """Pre-scan scope gate: resolve the fleet and report what a run WILL and WON'T read —
    which sources resolve, how deep the walk goes, and (the piece no scan computes) which
    private deps a repo pulls in that are NOT themselves in the fleet. Exit 0 clean, 3 on an
    unacknowledged blind spot, 4 if nothing resolves. The setup ritual: edit drift.yml, probe,
    then run. Consolidates plan (resolve) + preflight (private sources) + recommend (census)."""
    import json
    import subprocess
    from agent.lib import (source_resolver, private_sources, shapes, scope_edges,
                           probe as probe_mod)
    from agent.lib.vendors import load_vendors
    from agent.lib.vendor_rules import rule_kinds_by_language

    roots, accept, host = args.root, [], None
    if getattr(args, "config", None):
        from agent.lib import ops_config
        try:
            cfg = ops_config.load(args.config)
        except (OSError, ops_config.ConfigError) as exc:
            print(f"probe: bad --config — {exc}", file=sys.stderr)
            return 2
        roots = args.root or cfg["fleet"]
        accept, host = cfg["probe"]["accept"], cfg["host"]
    if not roots:
        print("probe: no fleet — pass --root or a --config with a fleet", file=sys.stderr)
        return 2

    resolved = source_resolver.resolve_sources(roots, args.state)
    projects, errors = resolved["projects"], resolved["errors"]

    prior = {}
    try:
        with open(os.path.join(args.state, "inventory.json"), encoding="utf-8") as fh:
            prior = {s["repo"]: s for s in (json.load(fh).get("coverage") or {}).get("shapes", [])}
    except (OSError, ValueError):
        pass

    kinds = rule_kinds_by_language(load_vendors())

    def _modeled(lang):
        return any(k in ("sink", "path-assembly") for k in kinds.get(lang, []))

    def _remote(abs_):
        try:
            r = subprocess.run(["git", "-C", abs_, "remote", "get-url", "origin"],
                               capture_output=True, text=True, timeout=10)
            return r.stdout.strip() if r.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            return ""

    fleet_ids, repos, consumers, unmodeled_langs, lang_signal = set(), [], [], {}, {}
    for abs_, ident, _kind in projects:
        rid = scope_edges.identity(_remote(abs_))
        if rid:
            fleet_ids.add(rid)
        counts, _u = shapes.census(abs_)
        for lang in shapes.meaningful_languages(counts):
            m = _modeled(lang)
            lang_signal[lang] = lang_signal.get(lang, True) and m   # any repo unmodeled → False
            if not m:
                unmodeled_langs.setdefault(lang, []).append(ident)
        repos.append({"name": ident, "verdict": (prior.get(ident) or {}).get("verdict")})
        ps = private_sources.detect(abs_)
        if ps["repositories"]:
            consumers.append({"repo": ident, "deps": ps["repositories"]})

    edges = scope_edges.find_missing(consumers, fleet_ids)
    result = probe_mod.assess({
        "host": host, "projects": projects, "errors": errors, "repos": repos, "edges": edges,
        "unmodeledLangs": unmodeled_langs, "languageSignal": lang_signal, "accept": accept})
    print(result["text"])
    # --summary-md appends a markdown view (for $GITHUB_STEP_SUMMARY, so the scope map shows on
    # the CI run's Summary page). Append, never truncate — the summary file accumulates steps.
    if getattr(args, "summary_md", None):
        try:
            with open(args.summary_md, "a", encoding="utf-8") as fh:
                fh.write(result["markdown"] + "\n")
        except OSError as exc:
            print(f"probe: could not write --summary-md ({exc})", file=sys.stderr)
    return result["exit_code"]


_TRISTATE = ("yes", "no", "unknown")
# M2: numeric ISO/slash forms (2026-03-01, 2026/03/01) were the whole gate — a model that spells
# the date out in prose ("Sunset on March 1, 2026") or writes it DD/MM/YYYY or MM/DD/YYYY
# ("01/03/2026") sailed straight through into a free-text field (`note`) and rendered as an
# ungated date in the dashboard's Evidence column. `_MONTHISH` covers both day-then-month and
# month-then-day orderings, full and abbreviated month names (Sep/Sept both accepted). Kept
# deliberately narrow to full day+month+year triples — a bare year ("the 2019 rewrite") or a
# spec number ("RFC 2606") must still pass, or the gate pushes users to skip it.
_MONTHISH = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
            r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)")
_DATEISH = re.compile(
    r"\d{4}-\d{2}-\d{2}"                                           # 2026-03-01
    r"|\d{4}/\d{2}/\d{2}"                                           # 2026/03/01
    r"|\d{1,2}/\d{1,2}/\d{4}"                                       # 01/03/2026 or 03/01/2026
    r"|" + _MONTHISH + r"\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}"   # March 1, 2026 / Mar 1, 2026
    r"|\d{1,2}(?:st|nd|rd|th)?\s+" + _MONTHISH + r"\.?,?\s+\d{4}",  # 1 March 2026 / 1 Mar 2026
    re.IGNORECASE)


def _cmd_leads(args) -> int:
    """Validate an AI cross-check pass into <state>/leads.json (drift-leads/v1).

    Replaces the old `probabilistic` subcommand and its side-car HTML: leads now ride in the
    dashboard's AI Frontier tab as their own blob. Pure + deterministic: no network, no tokens.
    Refuses malformed input, and refuses a DATE in a lead — a date is a certified-tier claim, and
    a lead may only say WHETHER (`retired` is the tri-state yes/no/unknown).
    """
    from agent.lib.probabilistic import compare
    drift_path = os.path.join(args.state, "drift.json")
    try:
        with open(drift_path, encoding="utf-8") as fh:
            drift = json.load(fh)
    except (OSError, json.JSONDecodeError):
        print(f"leads: no/unreadable drift.json in {args.state} — run a scan first", file=sys.stderr)
        return 2
    try:
        with open(args.ai_results, encoding="utf-8") as fh:
            ai = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"leads: cannot read --ai-results ({exc})", file=sys.stderr)
        return 2
    if not isinstance(ai, dict) or not isinstance(ai.get("repos"), list):
        print("leads: --ai-results malformed — expected {meta, repos:[...]}", file=sys.stderr)
        return 2
    problems = []
    for entry in ai["repos"]:
        if not isinstance(entry, dict) or "repo" not in entry:
            print('leads: --ai-results malformed — every repos[] entry needs a "repo" key',
                  file=sys.stderr)
            return 2
        for i in entry.get("integrations") or []:
            i = i if isinstance(i, dict) else {}
            host = i.get("host") or i.get("vendor") or "?"
            # The date guard must cover EVERY string field of the record, not just `retired` —
            # `retired` is already fully covered by the tri-state check below (anything that
            # isn't yes/no/unknown is refused there, dates included, making a second date check
            # on that one field redundant). The actual leak was elsewhere: a free-text field
            # (`note`, `evidence`, ...) rendered straight into the dashboard's Evidence column,
            # so `{"retired":"yes","note":"Sunset on 2026-03-01 per the changelog"}` sailed
            # through untouched and put an ungated date in front of a reader.
            for field, val in i.items():
                if isinstance(val, str) and _DATEISH.search(val):
                    problems.append(f"{host}: {field!r} carries a date ({val!r}) — a lead says "
                                    f"WHETHER, never WHEN; a dated claim must go through the "
                                    f"absorb gate")
            r = str(i.get("retired", "")).strip().lower()
            if r not in _TRISTATE:
                problems.append(f"{host}: 'retired' is {r!r}, not one of yes/no/unknown")
    if problems:
        print("leads: REFUSED — a lead may not carry a certified-tier claim:", file=sys.stderr)
        for p in problems:
            print("  •", p, file=sys.stderr)
        return 2
    cmp = compare(ai, drift.get("endpoints", []),
                  scanned_repos=[g.get("repo") for g in drift.get("coverageGrades", [])
                                 if g.get("repo")])
    tl = cmp["tallies"]
    tally = {"agree": tl["agree"], "aiOnly": tl["aiOnly"], "toolOnly": tl["toolOnly"]}
    doc = {"schema": "drift-leads/v1", "checked": args.now,
           "meta": ai.get("meta") or {}, "repos": ai["repos"], "tally": tally}
    out = os.path.join(args.state, "leads.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1, sort_keys=True)
    print(f"✓ leads recorded: {tally['agree']} agree · {tally['aiOnly']} AI-only · "
          f"{tally['toolOnly']} tool-only — written to {out}")
    print("  re-run `render`/`run` on this state to surface them in the AI Frontier tab.")
    return 0


def _cmd_freshness(args) -> int:
    """The maintainer FRESHNESS work-order: which DETECTED vendors need a human re-check
    (STALE or unaudited, and no machine can re-fetch their source) and exactly what to fetch
    for each — the human lane, where `catalog-check` is the auto lane. exit 0 nothing due,
    3 when a maintainer action is needed (mirrors catalog-check)."""
    import json as _json
    from agent.lib import freshness
    from agent import catalog_check
    try:
        with open(os.path.join(args.state, "audit.json"), encoding="utf-8") as fh:
            audit = _json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"freshness: cannot read audit.json in {args.state} — run a scan first ({exc})",
              file=sys.stderr)
        return 2
    records = (audit.get("coverage") or {}).get("catalog", [])
    due = freshness.due_for_refresh(records, set(catalog_check.CHECKS), catalog_check.UNAUTOMATED)
    md = freshness.work_order_md(due, args.now)
    if getattr(args, "out", None):
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(md)
        print(f"✓ freshness work-order ({len(due)} vendor(s) due) → {args.out}")
    else:
        print(md)
    return 3 if due else 0


def _cmd_coverage_report(args) -> int:
    """The management digest: the absorption scoreboard as a document someone can be sent.

    Reads drift.json — the CANONICAL report — never audit.json, so the digest cannot quote a
    figure the published contract does not carry. Verifies itself against that payload before
    writing: a digest is mailed to people who will never open the report it summarises, so it
    is the surface where an unnoticed disagreement does the most damage.

    exit 0 written, 2 no report to summarise.
    """
    import json as _json
    from agent.lib import coverage_digest, verify
    path = os.path.join(args.state, "drift.json")
    try:
        with open(path, encoding="utf-8") as fh:
            payload = _json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"coverage-report: cannot read drift.json in {args.state} — run a scan first "
              f"({exc})", file=sys.stderr)
        return 2
    md = coverage_digest.render(payload, now=args.now)
    verify.check_digest_matches_coverage(md, payload)   # never write a digest that disagrees
    out = getattr(args, "out", None) or os.path.join(args.state, "coverage-digest.md")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(md)
    print(f"\u2713 coverage digest \u2192 {out}")
    return 0


def _cmd_recommend(args) -> int:
    """Suggest a scan profile per repo — for when the user can't decide which mode to run.

    Uses the shape verdicts from a previous scan when one exists (precise), and falls
    back to a language census when it doesn't (no engine needed, still honest).
    """
    import json
    from agent.lib.repo_discovery import discover_repos
    from agent.lib.vendors import load_vendors
    from agent.lib.vendor_rules import rule_kinds_by_language
    from agent.lib import shapes

    kinds = rule_kinds_by_language(load_vendors())
    prior = {}
    state = getattr(args, "state", None) or os.path.join(args.root, ".drift-detector")
    try:
        with open(os.path.join(state, "inventory.json"), encoding="utf-8") as fh:
            prior = {s["repo"]: s for s in (json.load(fh).get("coverage") or {}).get("shapes", [])}
    except (OSError, ValueError):
        pass

    repos = discover_repos([args.root])
    matched = sum(1 for _, name in repos if name in prior)
    print(f"scan profiles · {args.root}")
    if matched:
        print(f"  {len(repos)} repo(s); {matched} with shape verdicts from a previous scan"
              + (f", {len(repos) - matched} from a language census" if matched < len(repos) else ""))
    else:
        print(f"  {len(repos)} repo(s); language census only "
              "(no matching prior scan — repo identities depend on the --root used)")
    print()
    tally = {}
    for abs_path, name in repos:
        sh = prior.get(name)
        if sh:
            profile, why = shapes.recommend_profile(sh)
            langs = ",".join(sh.get("languages", {}))
            extra = f"{sh['verdict']}"
        else:
            counts, unmodeled = shapes.census(abs_path)
            profile, why = shapes.recommend_from_census(counts, kinds, unmodeled)
            langs = ",".join(shapes.meaningful_languages(counts)) or "-"
            extra = "unscanned"
        tally[profile] = tally.get(profile, 0) + 1
        print(f"  {name:<28} {profile:<7} [{extra}] {langs}")
        print(f"      {why}")
    print("\n  " + " · ".join(f"{n} {p}" for p, n in sorted(tally.items())))
    if tally.get(shapes.MANUAL) or tally.get(shapes.HYBRID):
        print("  → repos not on `auto` need an agent pass; the tool says exactly what it missed.")
    return 0


def _cmd_absorb_report(args) -> int:
    """Render the absorb trail — the climb across attempts — or prune one repo's rows.

    A debug projection, deliberately outside the certified path: it reads only the trail, and
    `verify` never reads it back. Exit 0 always for the read path; there is no failure state in
    reading a record. `--forget` is the one path that writes, so it is the one path that can
    fail — `forget()` returns -1 (never raises) if the trail could not be rewritten, and that
    must surface as a clear message and non-zero exit, not a silent "removed -1 attempt(s)" that
    reads as success.
    """
    from agent.lib import absorb_trail

    # BUG THIS GUARDS AGAINST: the writer (`_cmd_absorb`, below) keys trail rows on
    # `scan_util.repo_scope_id(args.repo)` — the git REMOTE url, falling back to the local path
    # only when there's no remote. This command used to match `--repo` / `--forget` against the
    # raw string verbatim. The documented loop (commands/drift-absorb.md) passes a FOLDER PATH
    # as $REPO, so rows stored under "git@host:acme/api.git" were invisible to
    # `--repo /home/me/acme-api`, and `--forget /home/me/acme-api` printed "removed 0
    # attempt(s)" and exited 0 while every row stayed on disk — a client-data deletion control
    # silently failing. Normalise here: if the incoming value names an existing directory, run
    # it through the SAME repo_scope_id() the writer used, so it resolves to the same key. A
    # value that is not a directory (already a scope id, or a repo that no longer exists on
    # disk) is used as given.
    def _resolve(value):
        if value and os.path.isdir(value):
            return scan_util.repo_scope_id(value)
        return value

    if getattr(args, "forget", None):
        forget_id = _resolve(args.forget)
        n = absorb_trail.forget(args.state, forget_id)
        if n < 0:
            print(f"absorb-report: could not rewrite the trail to forget {forget_id} "
                  "(check the trail file/directory is writable)", file=sys.stderr)
            return 1
        if n == 0:
            # Make a no-op prune impossible to mistake for a successful one: list what IS in
            # the trail so an id mismatch (the bug above) is visible instead of reading as a
            # quiet success.
            present = sorted({r.get("repo") for r in absorb_trail.read(args.state)})
            print(f"absorb-report: removed nothing — no attempts recorded for {forget_id}. "
                  f"repo id(s) in the trail: {', '.join(present) if present else '(none)'}")
            return 0
        print(f"absorb-report: removed {n} attempt(s) for {forget_id}")
        return 0
    print(absorb_trail.render(absorb_trail.read(args.state, repo=_resolve(getattr(args, "repo", None)))))
    return 0


def _maybe_record_trail(args, *, repo: str, staged: list, delta: dict) -> None:
    """Record this --check attempt to the absorb trail, if --trail was asked for.

    Opt-in on purpose: `absorb --check` is documented as writing nothing (commands/
    drift-absorb.md and absorb.py's docstring both say so), and quietly falsifying that is the
    drift this project spends its effort preventing. Failures here are warnings, never errors —
    the gate's verdict is the product and a debugging by-product may not break it.
    """
    if not getattr(args, "trail", False):
        return
    if not getattr(args, "state", None):
        print("absorb: --trail needs --state; no trail written", file=sys.stderr)
        return
    from agent.lib import absorb_trail
    if not absorb_trail.append(args.state, repo=repo, staged=staged, delta=delta,
                               now=getattr(args, "now", None)):
        print("absorb: could not write the trail (continuing — the verdict is unaffected)",
              file=sys.stderr)


def _cmd_absorb(args) -> int:
    """Gate a staged proposal into the tool. Deterministic, zero tokens.

    An agent may PROPOSE (idiom instances, sunset entries); nothing is trusted
    because an agent said it. This re-scans the repo with the staged specs and
    refuses anything that cannot show its work.
    """
    import tempfile
    from agent import absorb
    from agent.lib import idioms as idioms_mod, shapes
    from agent.lib.vendors import load_vendors
    from agent.lib.vendor_rules import write_ruleset
    from agent.lib.engine import run_scan
    from agent.lib.endpoints import scan_endpoints

    staged_idioms = absorb._load(os.path.join(args.staged, "idioms.yaml"))
    staged_sunsets = absorb._load(os.path.join(args.staged, "sunsets.yaml"))
    claims = absorb._load(os.path.join(args.staged, "claims.yaml")) or []

    problems = absorb.check_idioms(staged_idioms) + absorb.check_sunsets(staged_sunsets)
    if problems:
        print("✗ absorb rejected — the proposal is malformed:", file=sys.stderr)
        for p in problems:
            print(f"    {p}", file=sys.stderr)
        return 3

    vendors = load_vendors()
    engine = scan_util.resolve_engine()

    # a repo-scoped idiom is matched on the git IDENTITY, not the local checkout path — the gate
    # MUST derive repo_id exactly as the scan pipeline does (scan_util.repo_scope_id), or an idiom
    # scoped to `org/repo` silently never applies for a clone whose folder name differs, leaving
    # attributedAfter == attributedBefore and every claim wrongly flagged "still unattributed".
    repo_ident = scan_util.repo_scope_id(args.repo)

    def scan(extra_idioms):
        insts = idioms_mod.load_idioms() + list(extra_idioms or [])
        with tempfile.TemporaryDirectory() as td:
            rules = os.path.join(td, "rules.yaml")
            write_ruleset(vendors, rules, idiom_instances=insts)
            res = run_scan(args.repo, rules, engine=engine)
        # pass the staged idioms + repo id so a path-constant instance (repo-scoped,
        # vendor-bound) is actually exercised by the gate, not silently ignored
        return scan_endpoints(res["matches"], args.repo, vendors,
                              idioms=insts, repo_id=repo_ident)

    m = absorb.measure_against_repo(args.repo, staged_idioms, claims, scan=scan)

    # --check: the iteration instrument. Report the attributed-call delta and the gate verdict,
    # write NOTHING (no promote, no attestation, no overlay). This is what an absorbing agent
    # loops on — climb attributedAfter, watch residue shrink — before the one real run.
    if getattr(args, "check", False):
        import json as _json
        d_attr = m["attributedAfter"] - m["attributedBefore"]
        d_res = m["residueAfter"] - m["residueBefore"]
        met, miss = len(m["claims"]["met"]), len(m["claims"]["missing"])
        print("absorb --check (dry run — nothing written)")
        print(f"  attributed call-sites : {m['attributedBefore']} → {m['attributedAfter']}  "
              f"({d_attr:+d})")
        print(f"  unattributed residue  : {m['residueBefore']} → {m['residueAfter']}  ({d_res:+d})")
        print(f"  claims                : {met}/{met + miss} met"
              + (f" — {miss} MISSING" if miss else ""))
        if m["problems"]:
            print("  ✗ would be REJECTED:")
            for p in m["problems"]:
                print(f"      {p}")
        else:
            print("  ✓ would pass the gate")
        print("DELTA " + _json.dumps({k: m[k] for k in
              ("attributedBefore", "attributedAfter", "residueBefore", "residueAfter",
               "claims", "invented", "unclaimed", "problems")}, sort_keys=True))
        _maybe_record_trail(args, repo=repo_ident,
                            staged=[i.get("id") for i in (staged_idioms or [])],
                            delta={k: m[k] for k in
                                   ("attributedBefore", "attributedAfter", "residueBefore",
                                    "residueAfter", "claims", "invented", "unclaimed",
                                    "problems")})
        return 3 if m["problems"] else 0

    problems = m["problems"]
    if problems:
        print("✗ absorb rejected — the proposal did not hold up against the repo:", file=sys.stderr)
        for p in problems:
            print(f"    {p}", file=sys.stderr)
        return 3

    # promote to the writable OVERLAY. Default ~/.drift/catalog (via overlay_dir); override with
    # $DRIFT_CATALOG_DIR for the container / drift-ops case. NEVER the package — site-packages
    # get wiped on the next pip/uvx upgrade (a silently-lost learned catalog).
    from agent.lib import catalog_overlay, drift_home
    overlay = catalog_overlay.overlay_dir() or drift_home.catalog_home()
    os.makedirs(overlay, exist_ok=True)
    idioms_dest = os.path.join(overlay, catalog_overlay.IDIOMS)
    sunsets_dest = os.path.join(overlay, catalog_overlay.SUNSETS)
    where = f"the catalog overlay ({overlay})"
    added = absorb.promote(args.staged, idioms_path=idioms_dest, sunsets_path=sunsets_dest)
    print(f"✓ absorbed: {added['idioms']} idiom(s), {added['sunsets']} sunset(s) — "
          f"verified against the repo, promoted to {where}")
    if args.state:
        after = scan(staged_idioms)
        fp = shapes.residue_fingerprint(after["residue"])
        # repo_abs MUST be passed: inventory_scan._shape_of looks the attestation up with the
        # repo's abspath (shapes.repo_key(name, abs_)), so writing a bare-name key here means
        # the next scan never sees it and absorb never 'sticks'. Same qualifier, both sides.
        shapes.attest(args.state, args.repo_name or os.path.basename(args.repo.rstrip("/")),
                      fp, resolved_by="absorb", date=args.now or "", repo_abs=args.repo,
                      note=f"{added['idioms']} idiom(s) absorbed")
        print(f"  attestation written for residue {fp}")

    # shape memory: log this absorption to the overlay so `precedents` can point the next
    # structurally-similar repo at the idiom instances that closed this one. Best-effort — a
    # missing shape or no overlay just skips it, never fails the absorption.
    if overlay and added["idioms"] and args.state:
        import json as _json
        from agent.lib import precedents as _prec
        try:
            with open(os.path.join(args.state, "inventory.json"), encoding="utf-8") as fh:
                _inv = _json.load(fh)
            rname = args.repo_name or os.path.basename(args.repo.rstrip("/"))
            _shapes = (_inv.get("coverage") or {}).get("shapes", [])
            shp = next((s for s in _shapes if s.get("repo") == rname
                        or str(s.get("repo", "")).endswith("/" + rname)), None)
            if shp is None and len(_shapes) == 1:      # single-repo scan state → the only shape
                shp = _shapes[0]
            if shp:
                _prec.append_absorption(
                    os.path.join(overlay, _prec.ABSORPTIONS),
                    _prec.record(shp, [i.get("id") for i in staged_idioms], repo=rname,
                                 date=args.now or "",
                                 attributed_delta=m["attributedAfter"] - m["attributedBefore"]))
                print("  logged to shape memory (absorptions.yaml)")
        except (OSError, ValueError):
            pass
    return 0


def _cmd_mute(args) -> int:
    from agent.lib.findings_state import add_to_baseline, remove_from_baseline
    if args.remove:
        remove_from_baseline(args.state, args.fingerprint)
        print(f"unmuted {args.fingerprint}")
    else:
        add_to_baseline(args.state, args.fingerprint)
        print(f"muted {args.fingerprint} (excluded from action counts until unmuted)")
    return 0


def _write_json(path, doc) -> str:
    import json as _json
    with open(path, "w", encoding="utf-8") as fh:
        _json.dump(doc, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    return path


def _cmd_sbom(args) -> int:
    """Emit an SBOM in CycloneDX and/or SPDX — components (packages, runtimes, frameworks) plus
    (CycloneDX) the CVE findings as vulnerabilities (SBOM + VEX). A verified projection of
    inventory.json + audit.json; `verify` re-derives it and fails if it drifts. `--format`
    cyclonedx (default, → sbom.json) | spdx (→ sbom.spdx.json) | all."""
    import json as _json
    from agent.lib import sbom as _sbom, spdx as _spdx
    try:
        with open(os.path.join(args.state, "inventory.json"), encoding="utf-8") as fh:
            inventory = _json.load(fh)
        with open(os.path.join(args.state, "audit.json"), encoding="utf-8") as fh:
            audit = _json.load(fh)
    except OSError as exc:
        print(f"sbom: nothing to build from — run a scan first ({exc})", file=sys.stderr)
        return 4
    now = args.now or inventory.get("generated") or ""
    fmt = getattr(args, "format", "cyclonedx") or "cyclonedx"
    single = args.out if fmt != "all" else None
    if fmt in ("cyclonedx", "all"):
        doc = _sbom.build_sbom(inventory, audit, now)
        out = _write_json(single or os.path.join(args.state, "sbom.json"), doc)
        nc, nv = len(doc.get("components", [])), len(doc.get("vulnerabilities", []))
        print(f"✓ CycloneDX: {nc} component(s), {nv} vuln(s) → {out}")
    if fmt in ("spdx", "all"):
        doc = _spdx.build_spdx(inventory, now)
        out = _write_json(single or os.path.join(args.state, "sbom.spdx.json"), doc)
        print(f"✓ SPDX {doc['spdxVersion']}: {len(doc['packages'])} package(s) → {out}")
    return 0


def _cmd_sarif(args) -> int:
    """Emit a SARIF 2.1.0 report of the findings (CVEs, vendor sunsets, EOL) with real file:line
    locations — the format GitHub code scanning and IDEs render inline. A verified projection of
    the audit findings. Writes <state>/sarif.json (or --out)."""
    import json as _json
    from agent.lib import sarif as _sarif
    try:
        with open(os.path.join(args.state, "audit.json"), encoding="utf-8") as fh:
            audit = _json.load(fh)
    except OSError as exc:
        print(f"sarif: nothing to build from — run a scan first ({exc})", file=sys.stderr)
        return 4
    doc = _sarif.build_sarif(audit)
    # the .sarif.json extension is what GitHub code scanning + the SARIF web viewer/validator
    # require (a plain .json is rejected).
    out = _write_json(args.out or os.path.join(args.state, "drift.sarif.json"), doc)
    n = len(doc["runs"][0]["results"])
    print(f"✓ SARIF {doc['version']}: {n} result(s) → {out}")
    return 0


def _cmd_brief(args) -> int:
    """Render ABSORPTION.md for a flagged repo — the full context (shape, uncapped blind spots,
    the closed idiom families, the rails) a maintainer/agent needs to absorb it. A deterministic
    projection of inventory.json; writes <state>/ABSORPTION.md (or --out)."""
    import json as _json
    from agent.lib import brief as _brief
    try:
        with open(os.path.join(args.state, "inventory.json"), encoding="utf-8") as fh:
            inventory = _json.load(fh)
    except OSError as exc:
        print(f"brief: nothing to render — run a scan first ({exc})", file=sys.stderr)
        return 4
    md = _brief.build_brief(inventory, args.repo, flag_url=getattr(args, "flag_url", None))
    out = args.out or os.path.join(args.state, "ABSORPTION.md")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(md)
    print(f"✓ absorption brief for {args.repo} → {out}")
    return 0


def _cmd_precedents(args) -> int:
    """Shape memory: prior absorptions of a STRUCTURALLY-SIMILAR shape (same language + residue
    reasons), so the assimilator can reuse the idiom family that closed them. Reads the repo's
    shape from inventory.json + the overlay's absorptions.yaml. Zero AI, deterministic."""
    import json as _json
    from agent.lib import precedents as _prec, catalog_overlay
    try:
        with open(os.path.join(args.state, "inventory.json"), encoding="utf-8") as fh:
            inventory = _json.load(fh)
    except OSError as exc:
        print(f"precedents: run a scan first ({exc})", file=sys.stderr)
        return 4
    shape = next((s for s in (inventory.get("coverage") or {}).get("shapes", [])
                  if s.get("repo") == args.repo), None)
    if shape is None:
        print(f"precedents: no shape for {args.repo!r} in the scan", file=sys.stderr)
        return 3
    overlay = catalog_overlay.overlay_dir()
    path = args.catalog or (os.path.join(overlay, _prec.ABSORPTIONS) if overlay else None)
    hits = _prec.find_precedents(shape, _prec.load_absorptions(path) if path else [])
    print(f"precedents for {args.repo} (bucket: {_prec.bucket_key(shape)}):")
    if not hits:
        print("  no prior absorption of this shape — you're the first. Author the idiom from "
              "the blind-spot files.")
        return 0
    print(f"  {len(hits)} prior absorption(s) closed a similar shape:")
    for h in hits:
        d = f" — +{h['attributedDelta']} traced" if h.get("attributedDelta") is not None else ""
        print(f"  • {h['repo']} ({h.get('date', '?')}) — idioms: "
              f"{', '.join(h.get('idioms', []))}{d}")
    print("  Read those idiom instances in the overlay (idioms.local.yaml) — the same family "
          "likely applies here.")
    return 0


def _cmd_config_preflight(args) -> int:
    """A 5-second gate BEFORE the scan: are the token env vars the config names actually set,
    is a configured webhook present, and does the delivery token reach GitLab? Fails here
    (exit 2) instead of 10 minutes into a scan that can't deliver. --no-network skips the
    reachability probe (the static checks still run)."""
    import os as _os
    from agent.lib import ops_config, preflight, gitlab_api

    try:
        cfg = ops_config.load(args.config)
    except (OSError, ops_config.ConfigError) as exc:
        print(f"preflight: bad --config — {exc}", file=sys.stderr)
        return 2

    probe = None
    if not args.no_network:
        def probe(host, token):
            try:
                v = gitlab_api.GitLab(host, token).version()
                return (bool(v), f"reachable (v{v.get('version')})" if v
                        else "unreachable, or the delivery token was rejected")
            except Exception as exc:                     # network/DNS/TLS — a real block, reported
                return (False, str(exc))

    problems, advisories = preflight.check(cfg, dict(_os.environ), probe=probe)
    for a in advisories:
        print(f"  ⚠ {a}")
    if problems:
        print("✗ preflight — the deployment is not ready to run:", file=sys.stderr)
        for p in problems:
            print(f"    {p}", file=sys.stderr)
        return 2
    net = "config valid" if args.no_network else f"{cfg['host']} reachable"
    print(f"✓ preflight — {net}, tokens present")
    return 0


def _cmd_deliver(args) -> int:
    """Project the verified findings into GitLab: per-repo DevOps + Developer issues, assigned.

    Runs AFTER `verify` (delivery is a projection of the verified payload — only verified
    data leaves the machine). --dry-run prints the plan and writes nothing. Idempotent: a
    re-scan updates issues in place, never duplicates. Exit 0 ok, 4 nothing to deliver,
    3 if any issue failed to file (see `done["failed"]`) — a delivery that couldn't reach
    every repo is not a clean one.
    """
    import json as _json
    import os as _os
    from agent.lib import delivery, gitlab_api

    # settings come from --config (drift.yml) unless an explicit flag overrides
    host, devops_project = args.gitlab_host, args.devops_project
    mode = "dry-run" if args.dry_run else "live"
    dev_as_issues = args.dev_as_issues
    deliver_var = None                              # env-var NAME the delivery token is read from
    shape_stream = False                            # flag UNKNOWN repos for absorption (config opt-in)
    freshness_stream = False                        # file the catalog work-order (config opt-in)
    resolve_stream = False                          # file the vendor-resolution queue (config opt-in)
    granularity = "comprehensive"                   # how findings become issues (config opt-in)
    if getattr(args, "config", None):
        from agent.lib import ops_config
        try:
            cfg = ops_config.load(args.config)
        except (OSError, ops_config.ConfigError) as exc:
            print(f"deliver: bad --config — {exc}", file=sys.stderr)
            return 2
        host = host or cfg["host"]
        devops_project = devops_project or cfg["delivery"]["devops_project"]
        dev_as_issues = dev_as_issues or cfg["delivery"]["dev_as_issues"]
        deliver_var = cfg["auth"]["deliver"]
        shape_stream = cfg["delivery"]["shape_stream"]
        freshness_stream = cfg["delivery"]["freshness_stream"]
        resolve_stream = cfg["delivery"]["resolve_stream"]
        granularity = cfg["delivery"]["granularity"]
        if not args.dry_run:                        # an explicit --dry-run always wins
            mode = cfg["delivery"]["mode"]
    if mode == "off":
        print("delivery mode: off — skipping")
        return 0
    if not host or not devops_project:
        print("deliver: need --gitlab-host and --devops-project (or a --config)", file=sys.stderr)
        return 2

    try:
        with open(_os.path.join(args.state, "drift.json"), encoding="utf-8") as fh:
            payload = _json.load(fh)
        with open(_os.path.join(args.state, "inventory.json"), encoding="utf-8") as fh:
            inventory = _json.load(fh)
    except OSError as exc:
        print(f"drift deliver: nothing to deliver — {exc}", file=sys.stderr)
        return 4

    repo_meta = {}
    for r in inventory.get("repos", []):
        pp = delivery.project_path(r.get("remote_url"))
        if pp:
            repo_meta[r.get("path")] = {"project": pp}

    # the delivery token: the config-named var first (split-token deployments), then the
    # single-token fallback that has always worked
    token = (_os.environ.get(deliver_var) if deliver_var else None) \
        or _os.environ.get("GITLAB_TOKEN") or _os.environ.get("DRIFT_GIT_TOKEN")
    gl = gitlab_api.GitLab(host, token)

    # assignees: the DevOps account (config-wide) + each repo's resolved owner (Maintainer+
    # access, else the config fallback) — resolved BEFORE build_plan regardless of
    # --dry-run so the printed plan shows real threading, never a stub.
    devops_assignee = dev_fallback = None
    if getattr(args, "config", None):
        devops_assignee = cfg["delivery"].get("devopsAssignee")
        dev_fallback = cfg["delivery"].get("developerFallbackAssignee")
    devops_id = gl.user_id(devops_assignee) if devops_assignee else None
    fallback_id = gl.user_id(dev_fallback) if dev_fallback else None
    dev_owner = {}
    for repo, meta in repo_meta.items():
        try:
            dev_owner[repo] = delivery.resolve_owner(gl.members(meta["project"]), fallback_id)
        except Exception:
            dev_owner[repo] = fallback_id            # owner lookup failed -> fallback, never crash
    assignees = {"devops": devops_id, "developer": dev_owner}

    dev_projects = sorted({m["project"] for m in repo_meta.values()})
    existing = delivery.fetch_existing(gl, devops_project, dev_projects)
    links = {"run": getattr(args, "run_url", None), "report": getattr(args, "report_url", None)}
    plan = delivery.build_plan(payload, repo_meta, existing, devops_project,
                               dev_as_issues=dev_as_issues, links=links,
                               shape_stream=shape_stream, freshness_stream=freshness_stream,
                               resolve_stream=resolve_stream,
                               assignees=assignees, granularity=granularity)

    print(f"delivery mode: {mode}")
    print(delivery.plan_summary(plan))
    print()
    print(delivery.plan_detail(plan))

    if mode == "dry-run":
        print("\n(dry run — nothing written)")
        return 0

    done = delivery.execute_plan(gl, plan)
    print(f"\n✓ delivered: {done['created']} created · {done['updated']} updated · "
          f"{done['closed']} closed")
    if done["failed"]:
        print(f"✗ {len(done['failed'])} issue(s) failed to file:", file=sys.stderr)
        for project, reason in done["failed"]:
            print(f"    {project}: {reason}", file=sys.stderr)
        return 3
    return 0


def _cmd_notify(args) -> int:
    """Push a one-line scan summary to a Google Chat space (or any {text} webhook). Opt-in:
    no webhook (--webhook / $DRIFT_CHAT_WEBHOOK) → no-op, exit 0."""
    import json as _json
    import os as _os
    from agent.lib import notify

    webhook = args.webhook or _os.environ.get("DRIFT_CHAT_WEBHOOK")
    if not webhook and getattr(args, "config", None):
        # honor the env-var NAME the config gives (notify.gchat). A bad config here must not
        # crash the pipeline's tail — notify is best-effort by design.
        from agent.lib import ops_config
        try:
            gchat = ops_config.load(args.config)["notify"]["gchat"]
            if gchat:
                webhook = _os.environ.get(gchat)
        except (OSError, ops_config.ConfigError):
            pass
    if not webhook:
        print("notify: no webhook configured — skipping")
        return 0
    try:
        with open(_os.path.join(args.state, "drift.json"), encoding="utf-8") as fh:
            payload = _json.load(fh)
    except OSError as exc:
        # best-effort push: no report (e.g. the scan failed upstream) is a skip, NOT an error
        # — notify must never turn a failure into a second red.
        print(f"notify: no report to send — skipping ({exc})")
        return 0
    card = notify.chat_card(payload, report_url=args.report_url, run_url=args.run_url)
    try:
        notify.post(webhook, card)
    except Exception as exc:                    # a chat outage must not fail the pipeline
        print(f"notify: post failed (non-fatal) — {exc}", file=sys.stderr)
        return 0
    print("notify: sent ✓")
    return 0


def _cmd_adhoc_report(args) -> int:
    """Write the ad-hoc (gate-validated) shape record to <state>/adhoc.json — the AI Frontier tab's
    SHAPED tier. It no longer writes a side-car HTML page: there is one dashboard.
    Assembles the MIDDLE-tier artifact from a validated ad-hoc pass — the certified `drift.json`,
    the ad-hoc re-scan's `drift.json`, the staged idioms + claims, and the gate's DELTA. `drift.json`
    is NEVER touched (sibling document, exactly like `leads.json`, the AI Frontier tab's other tier)."""
    import json as _json
    from agent import absorb as _absorb
    from agent.lib import adhoc
    try:
        # Read the certified file as BYTES and parse those same bytes. The hash in adhoc.json
        # binds to the file on disk, so `sha256sum drift.json` reproduces it; re-dumping the
        # parsed dict would yield a digest matching no file anyone can point at.
        with open(os.path.join(args.state, "drift.json"), "rb") as fh:
            certified_bytes = fh.read()
        certified = _json.loads(certified_bytes.decode("utf-8"))
        adhoc_drift = _json.load(open(os.path.join(args.adhoc_state, "drift.json"), encoding="utf-8"))
        gate = _json.load(open(args.gate_delta, encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"adhoc-report: bad input — {exc}", file=sys.stderr)
        return 2
    idioms = _absorb._load(os.path.join(args.staged, "idioms.yaml")) or []
    claims = _absorb._load(os.path.join(args.staged, "claims.yaml")) or []
    per = adhoc.compare(adhoc_drift, claims, gate, idioms, args.repo)
    doc = adhoc.bundle(certified, [per], args.now, certified_bytes=certified_bytes)
    with open(os.path.join(args.state, "adhoc.json"), "w", encoding="utf-8") as fh:
        _json.dump(doc, fh, indent=2, sort_keys=True)
    tier = "✗ over-broad (NOT validated)" if per["problems"] else "✓ gate-validated"
    print(f"adhoc-report: {tier} · {per['attributedNew']} call-site(s) shaped · "
          f"{per['datedCount']} dated by catalog → {args.state}/adhoc.json")
    return 3 if per["problems"] else 0


def _cmd_render(args) -> int:
    """Re-render dashboard.html AND summary.html from the state dir: the certified drift.json +
    optional AI-tier docs (adhoc.json / leads.json) for the cockpit. The certified `drift-data`
    blob is byte-identical to run.py's render, so `verify` stays green — the AI tiers are
    strictly additive, never a change to the certified one. This is the seam that lets the
    ad-hoc pass (a second scan) fold its tier into the ONE cockpit.

    summary.html is included because `verify` now REQUIRES it (task-5b Finding 2): a state dir
    predating that change, or one hand-staged with just drift.json, used to leave `render` unable
    to produce the one file `verify` was naming as missing — the obvious repair did not repair.
    """
    import json as _json
    from agent.lib.dashboard_render import build_bundle, render_payload
    from agent.lib.summary_render import render_summary

    def _load(name, required=True):
        try:
            with open(os.path.join(args.state, name), encoding="utf-8") as fh:
                return _json.load(fh)
        except OSError:
            if required:
                raise
            return None
    try:
        payload = _load("drift.json")
        inv, audit = _load("inventory.json"), _load("audit.json")
    except OSError as exc:
        print(f"render: nothing to render — {exc}", file=sys.stderr)
        return 2
    adhoc = _load("adhoc.json", required=False)
    leads = _load("leads.json", required=False)
    research = _load("research.json", required=False)
    html = render_payload(payload, args.now, bundle=build_bundle(inv, audit, args.now),
                          adhoc=adhoc, leads=leads, research=research)
    with open(os.path.join(args.state, "dashboard.html"), "w", encoding="utf-8") as fh:
        fh.write(html)
    with open(os.path.join(args.state, "summary.html"), "w", encoding="utf-8") as fh:
        fh.write(render_summary(payload, args.now))
    tiers = "certified" + (" + shaped" if adhoc else "") + (" + leads" if leads else "") \
            + (" + research" if research else "")
    print(f"render: dashboard.html + summary.html rewritten ({tiers})")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="drift-detector")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run")           # scan -> audit -> deliver, deterministic (cron entrypoint)
    pr.add_argument("--root", action="append")   # or supply the fleet via --config
    pr.add_argument("--config", help="drift.yml — the fleet comes from its `fleet:` list")
    pr.add_argument("--state", required=True)
    pr.add_argument("--now", required=True)
    pr.add_argument("--pull", action="store_true")
    pr.add_argument("--progress", action="store_true")
    pr.add_argument("--jobs", type=int, default=1,
                    help="repos to scan concurrently (default 1 = serial, which is what CI "
                         "runs; a larger value is capped to this machine's CPU count, with a "
                         "notice on stderr if it was reduced). Results are reassembled in "
                         "discovery order, so any --jobs value produces identical artifacts — "
                         "absent resource exhaustion: ast-grep is itself internally parallel, "
                         "so heavy oversubscription can push a slow repo past the engine's "
                         "600s timeout and it gets counted errored, which serial would not.")
    pr.add_argument("--fail-on-deprecated", action="store_true",
                    help="exit 3 if any un-muted DEPRECATED finding (CI gate)")
    pr.add_argument("--resolve",
                    help="verdicts.json from an AI resolution pass (or `resolve --apply`'s own "
                         "resolution.json) — gate it, apply it, and RE-SCAN so drift.json comes "
                         "entirely from the deterministic re-scan, never the verdicts directly "
                         "(docs/superpowers/specs/2026-08-13-no-queue-design.md)")
    pr.set_defaults(func=_cmd_run)

    pdl = sub.add_parser("deliver")       # findings -> in-repo GitLab issues (DevOps + Developer)
    pdl.add_argument("--state", required=True)
    pdl.add_argument("--config", help="drift.yml — supplies host + delivery settings")
    pdl.add_argument("--gitlab-host")     # or from --config (derived from the fleet host)
    pdl.add_argument("--devops-project",
                     help="GitLab project path where DevOps issues are filed (or from --config)")
    pdl.add_argument("--dry-run", action="store_true",
                     help="print the create/update/close plan without writing anything")
    pdl.add_argument("--run-url", help="link back to the scan run (provenance in each issue/MR)")
    pdl.add_argument("--report-url", help="link to the full report (provenance in each issue/MR)")
    # Accepted and IGNORED: the Developer stream is always filed as in-repo issues now (the
    # draft-MR path is retired). Kept so existing scripts and CI files do not break on an
    # unknown flag; the help says so rather than describing behaviour that no longer exists.
    pdl.add_argument("--dev-as-issues", action="store_true",
                     help="deprecated, no effect — the Developer stream is always filed as "
                          "issues; accepted so older invocations keep working")
    pdl.set_defaults(func=_cmd_deliver)

    pn = sub.add_parser("notify")         # push a one-line summary to a Google Chat webhook
    pn.add_argument("--state", required=True)
    pn.add_argument("--webhook", help="Google Chat webhook URL (or $DRIFT_CHAT_WEBHOOK)")
    pn.add_argument("--config", help="drift.yml — resolves the webhook from notify.gchat's env var")
    pn.add_argument("--report-url")
    pn.add_argument("--run-url")
    pn.set_defaults(func=_cmd_notify)

    par = sub.add_parser("adhoc-report")  # POC: the ad-hoc / gate-validated middle tier -> adhoc.json
    par.add_argument("--state", required=True)          # certified state (drift.json + where output lands)
    par.add_argument("--adhoc-state", required=True)    # the ad-hoc re-scan's state dir
    par.add_argument("--staged", required=True)         # dir with idioms.yaml + claims.yaml
    par.add_argument("--gate-delta", required=True)     # the DELTA json captured from `absorb --check`
    par.add_argument("--repo", required=True)
    par.add_argument("--now", required=True)
    par.set_defaults(func=_cmd_adhoc_report)

    prn = sub.add_parser("render")        # re-render dashboard.html from state + optional AI-tier docs
    prn.add_argument("--state", required=True)
    prn.add_argument("--now", required=True)
    prn.set_defaults(func=_cmd_render)

    psb = sub.add_parser("sbom")          # SBOM: CycloneDX (+ CVE vulns) and/or SPDX
    psb.add_argument("--state", required=True)
    psb.add_argument("--format", choices=("cyclonedx", "spdx", "all"), default="cyclonedx")
    psb.add_argument("--out", help="output path (single format only; default <state>/sbom[.spdx].json)")
    psb.add_argument("--now", help="timestamp date (default: inventory.generated)")
    psb.set_defaults(func=_cmd_sbom)

    psa = sub.add_parser("sarif")         # SARIF 2.1.0 findings (file:line) for code scanning
    psa.add_argument("--state", required=True)
    psa.add_argument("--out", help="output path (default <state>/sarif.json)")
    psa.set_defaults(func=_cmd_sarif)

    pbr = sub.add_parser("brief")         # ABSORPTION.md for a flagged (UNKNOWN) repo
    pbr.add_argument("--state", required=True)
    pbr.add_argument("--repo", required=True, help="the flagged repo path (as in the shape record)")
    pbr.add_argument("--out", help="output path (default <state>/ABSORPTION.md)")
    pbr.add_argument("--flag-url", help="link back to the flag issue")
    pbr.set_defaults(func=_cmd_brief)

    ppr = sub.add_parser("precedents")    # prior absorptions of a similar shape (structural bucket)
    ppr.add_argument("--state", required=True)
    ppr.add_argument("--repo", required=True)
    ppr.add_argument("--catalog", help="absorptions.yaml path (default: the $DRIFT_CATALOG_DIR overlay)")
    ppr.set_defaults(func=_cmd_precedents)

    pcp = sub.add_parser("config-preflight")   # 5s gate: tokens + reachability + config, PRE-scan
    pcp.add_argument("--config", required=True)
    pcp.add_argument("--no-network", action="store_true",
                     help="skip the GitLab reachability probe (static checks still run)")
    pcp.set_defaults(func=_cmd_config_preflight)

    psc = sub.add_parser("schedule")
    psc.add_argument("--root", required=True)
    psc.add_argument("--state", required=True)
    psc.add_argument("--at", default="0 7 * * 0")
    psc.add_argument("--pull", action="store_true")
    psc.set_defaults(func=_cmd_schedule)

    pu = sub.add_parser("unschedule")
    pu.add_argument("--state", required=True)
    pu.set_defaults(func=_cmd_unschedule)

    pcl = sub.add_parser("clean")         # remove the tool's artifacts — keeps the absorbed catalog
    pcl.add_argument("--state", help="one run's state dir to remove (guardrailed to drift dirs)")
    pcl.add_argument("--all", action="store_true",
                     help="every run output the tool recorded + ~/.drift/{reports,eval} + ~/.drift-detector")
    pcl.add_argument("--catalog", action="store_true", help="also remove ~/.drift/catalog (absorbed shapes)")
    pcl.add_argument("--report", action="store_true", help="summarize reclaimable clutter, delete nothing")
    pcl.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    pcl.set_defaults(func=_cmd_clean)

    pmu = sub.add_parser("mute")
    pmu.add_argument("--state", required=True)
    pmu.add_argument("--fingerprint", required=True)
    pmu.add_argument("--remove", action="store_true")
    pmu.set_defaults(func=_cmd_mute)

    pab = sub.add_parser("absorb")        # gate a staged agent proposal into the tool
    pab.add_argument("--staged", required=True)
    pab.add_argument("--repo", required=True)
    pab.add_argument("--repo-name")
    pab.add_argument("--state")
    pab.add_argument("--now")
    pab.add_argument("--check", action="store_true",
                     help="dry run: report the attributed-call delta + gate verdict, write "
                          "nothing (the iteration instrument for an absorbing agent)")
    pab.add_argument("--trail", action="store_true",
                     help="with --check: append this attempt to <state>/absorb-trail.jsonl so "
                          "the climb can be reviewed later (a debug by-product; --check "
                          "without it still writes nothing)")
    pab.set_defaults(func=_cmd_absorb)

    par2 = sub.add_parser("absorb-report")   # the absorb trail -> Markdown (debug projection)
    par2.add_argument("--state", required=True)
    par2.add_argument("--repo", help="only this repo's attempts")
    par2.add_argument("--forget", help="drop this repo's attempts (do it once its idiom merges)")
    par2.set_defaults(func=_cmd_absorb_report)

    prc = sub.add_parser("recommend")     # which scan profile should this folder run?
    prc.add_argument("--root", required=True)
    prc.add_argument("--state")
    prc.set_defaults(func=_cmd_recommend)

    ppf = sub.add_parser("preflight")
    ppf.add_argument("--root", required=True)
    ppf.set_defaults(func=_cmd_preflight)

    pcr = sub.add_parser("catalog-refresh")   # vendor specs vs our curated catalog
    pcr.add_argument("--vendor", required=True)
    pcr.set_defaults(func=_cmd_catalog_refresh)

    pcc = sub.add_parser("catalog-check")     # re-check live vendor sources (freshness)
    pcc.add_argument("--now", required=True)
    pcc.set_defaults(func=_cmd_catalog_check)

    pv = sub.add_parser("verify")         # do the report's numbers agree with its data?
    pv.add_argument("--state", required=True)
    pv.set_defaults(func=_cmd_verify)

    prs = sub.add_parser("research")      # list the queued work-list, or record a gate-validated pass
    prs.add_argument("--state")           # per-scan mode: the state dir with drift.json
    prs.add_argument("--vendors")         # catalog mode: "all-unattested" or a comma-list of vendor names
    prs.add_argument("--apply")           # verdicts.json from an AI research pass
    prs.add_argument("--attest")          # catalog mode: YAML file to write `current` attestations into
    prs.add_argument("--now", default=None)
    prs.set_defaults(func=_cmd_research)

    prv = sub.add_parser("resolve")       # the no-queue resolution gate: work-list, or apply gated verdicts
    prv.add_argument("--state", required=True)
    prv.add_argument("--apply")           # verdicts.json from an AI resolution pass
    prv.add_argument("--now", default=None)
    prv.set_defaults(func=_cmd_resolve)

    ppl = sub.add_parser("plan")          # resolve sources + report what WOULD scan
    ppl.add_argument("--root", action="append", required=True)
    ppl.add_argument("--state", required=True)
    ppl.set_defaults(func=_cmd_plan)

    ppb = sub.add_parser("probe")         # pre-scan scope GATE: what will/won't be read
    ppb.add_argument("--root", action="append")
    ppb.add_argument("--config", help="drift.yml — fleet + probe.accept acknowledgements")
    ppb.add_argument("--state", required=True)
    ppb.add_argument("--summary-md", help="append a markdown scope map here (e.g. $GITHUB_STEP_SUMMARY)")
    ppb.set_defaults(func=_cmd_probe)

    pfr = sub.add_parser("freshness")     # maintainer work-order: vendors due for a human re-check
    pfr.add_argument("--state", required=True)
    pfr.add_argument("--now", required=True)
    pfr.add_argument("--out", help="write the work-order here (default: stdout)")
    pfr.set_defaults(func=_cmd_freshness)

    pcov = sub.add_parser("coverage-report")   # management digest: the absorption scoreboard
    pcov.add_argument("--state", required=True)
    pcov.add_argument("--now", required=True)
    pcov.add_argument("--out", help="write the digest here (default: <state>/coverage-digest.md)")
    pcov.set_defaults(func=_cmd_coverage_report)

    lds = sub.add_parser("leads")           # AI cross-check -> leads.json (AI Frontier tab)
    lds.add_argument("--state", required=True)
    lds.add_argument("--ai-results", required=True, help="ai_results.json from the AI driver")
    lds.add_argument("--now", required=True)
    lds.set_defaults(func=_cmd_leads)

    pa = sub.add_parser("audit")
    pa.add_argument("--in", dest="in_json", required=True)
    pa.add_argument("--now", required=True)
    pa.add_argument("--out-json")
    pa.add_argument("--out-html")
    pa.add_argument("--offline", action="store_true")
    pa.add_argument("--progress", action="store_true")
    pa.set_defaults(func=_cmd_audit)

    pis = sub.add_parser("inventory-scan")
    pis.add_argument("--root", action="append", required=True,
                     help="folder to scan for git repos (recursive); repeat for multiple roots")
    for a in ("--state", "--out-json", "--now"):
        pis.add_argument(a, required=True)
    pis.add_argument("--progress", action="store_true",
                     help="emit an informative per-phase log to stderr")
    pis.add_argument("--jobs", type=int, default=1,
                     help="repos to scan concurrently (default 1 = serial; a larger value is "
                          "capped to this machine's CPU count, with a notice on stderr if it "
                          "was reduced)")
    pis.set_defaults(func=_cmd_inventory_scan)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
