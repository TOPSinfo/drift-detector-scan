"""Route work to the person who resolves it. THREE audiences, of two kinds.

FINDING owners — who fixes a drift.json finding in a scanned repo (a PURE function of the
record; verify recomputes it):
  - **DevOps** owns the platform: package vulnerabilities (a manifest/lockfile bump) and
    **runtime** end-of-life (a base-image / language upgrade). Delivered as ISSUES (a ticket
    to action).
  - **Developer** owns the application: vendor API sunsets (integration code) and
    **framework** end-of-life — a Laravel 8→11 or Django LTS jump is app-code migration,
    not an infra bump. Delivered as MRs (code they contribute to their own repo).

The MAINTAINER stream — NOT a finding-owner. The maintainer owns THE TOOL / THE CATALOG, so
their work isn't tied to any one repo's finding; it's what keeps the scanner honest:
  - **absorption** — a repo has a shape the scanner can't read (the shape/`drift:shape` flag).
  - **freshness** — a catalogued vendor's retirement list went STALE, or a gated vendor needs
    a behind-login portal re-check (`drift:freshness`).
Both are delivered to the maintainer and resolved as MRs against the drift-ops catalog. Because
this is not per-finding, `owner()` never returns it — the maintainer is addressed by its own
delivery streams, tagged `drift:maintainer` so all tool-upkeep work filters as one queue.

`owner()` stays a pure function of `kind`/`refKind`, so verify can fail if a stored `owner`
ever disagrees with drift.json — the "one payload, verified projections" guarantee.
"""
from __future__ import annotations

DEVOPS = "devops"
DEVELOPER = "developer"
# the tool-upkeep audience — addressed by the shape/freshness STREAMS, not owner() (see above)
MAINTAINER = "maintainer"
OWNERS = (DEVOPS, DEVELOPER)


def owner(record: dict) -> str:
    """'devops' | 'developer' for a finding or an action. Total and deterministic."""
    kind = record.get("kind")
    if kind == "cve":
        return DEVOPS
    if kind == "eol":
        # runtimes (php, node, python) are DevOps; frameworks (laravel, django) are the
        # developers' app-code migration. refKind is stamped on every eol record; a
        # missing one defaults to the developer (app) queue rather than silently routing
        # a runtime to DevOps.
        return DEVOPS if record.get("refKind") == "runtime" else DEVELOPER
    # sunset (and any future integration kind) is developer work
    return DEVELOPER
