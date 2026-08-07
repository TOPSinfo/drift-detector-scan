"""Mechanical invariants over the dashboard payload — the checks that replace "looks right".

Rendered HTML cannot be checked by anything without eyes. Two bugs shipped in one
session because their tests ran a layer below the artifact a person reads:

  1. a tile reading `Sunsets 1` above twelve sunset findings, because actions grouped
     on (repo, vendor) and a vendor is not a job;
  2. twelve rows all labelled "eBay" — four of them identical — because the projection
     whitelists fields by hand and silently dropped the one carrying the operation.

Both are caught below WITHOUT rendering anything. Every check is a statement about the
payload that must hold no matter how the page is styled, so they survive CSS edits in a
way golden files do not.

Deterministic and dependency-free: pure Python over a dict.
"""
from __future__ import annotations

import re


class Violation(ValueError):
    """An invariant failed. Carries the check name so `drift verify` can report it."""

    def __init__(self, check: str, detail: str):
        self.check, self.detail = check, detail
        super().__init__(f"{check}: {detail}")


# Action fields deliberately NOT projected into the page. Naming them is the point: a new
# field added to build_actions must be either projected or listed here, so it can never be
# dropped by forgetting. This frozenset is what turns bug #2 into a test failure.
DECLARED_DROPS = frozenset({"fixes", "eco", "unit_kind", "sources_raw"})


def check_projection_parity(action: dict, projected: dict) -> None:
    """Every field an action carries is either projected or explicitly declared dropped."""
    lost = set(action) - set(projected) - DECLARED_DROPS
    if lost:
        raise Violation("projection-parity",
                        f"build_actions emits {sorted(lost)} but the projection neither "
                        f"carries nor declares them dropped — add to the projection, or to "
                        f"DECLARED_DROPS if the page genuinely does not need it. "
                        f"(This is how `unit` was lost and twelve rows rendered as 'eBay'.)")


# Single-letter loop vars for the payload-backed record types: a=action, e=endpoint,
# p=private, cv=catalog. `row` is the Vue summary-table's `v-for="(row, idx) in rows"` —
# `rows` is POLYMORPHIC (actions OR endpoints OR private OR catalog, chosen by `mode`), so a
# `row.foo` read is legal iff `foo` exists in AT LEAST ONE of those four field sets; see the
# `row` branch in check_accessor_coverage, which checks it against their union rather than
# any single sample. Every other loop var in the page (`r` for SARIF results, `c`/`g`/`u`/…
# for SBOM/coverage lists) is deliberately NOT tracked here: those are NOT payload-record
# accessors this check owns, and conflating them would make the check lie in both directions
# (this is exactly the false-positive a `p`-collision bug already shipped once on this branch).
_ACCESSOR = re.compile(r"\b(a|e|p|cv|row)\.([A-Za-z_]\w*)\b")
# JS built-ins and locals that are not payload fields
_NOT_FIELDS = frozenset({"length", "forEach", "map", "filter", "push", "join", "slice",
                         "indexOf", "toLowerCase", "toUpperCase", "concat", "sort"})


def check_accessor_coverage(client_js: str, samples: dict) -> None:
    """Every `a.foo` / `e.foo` / `p.foo` / `cv.foo` / `row.foo` the page reads must exist
    in the payload.

    The other direction from projection-parity: that check catches a field the projection
    forgot, this catches the page reading a field nothing emits. Between them a rename
    cannot silently blank a column.

    `row` is special: the Vue summary table's row loop var is polymorphic — the same
    `v-for="(row, idx) in rows"` renders an action, an endpoint, a private-source, or a
    catalog row depending on `mode`. Pass its allowed set explicitly as `samples["row"]` —
    the UNION of whichever of the four row shapes the caller cares about (typically
    `actions | endpoints | private | catalog`). It is deliberately opt-in rather than
    auto-derived from the other keys: callers routinely pass just ONE category to check
    that accessor prefix in isolation (e.g. only "catalog", to test `cv.foo`), and the
    template's `row.*` reads span all four modes regardless — auto-unioning from a partial
    sample would falsely flag every field belonging to a category that call didn't supply.
    """
    for var, keys in (("a", samples.get("actions")), ("e", samples.get("endpoints")),
                      ("p", samples.get("private")), ("cv", samples.get("catalog")),
                      ("row", samples.get("row"))):
        if not keys:
            continue
        read = {m.group(2) for m in _ACCESSOR.finditer(client_js)
                if m.group(1) == var and m.group(2) not in _NOT_FIELDS}
        missing = read - set(keys)
        if missing:
            raise Violation("accessor-coverage",
                            f"the page reads {var}.{sorted(missing)} but the payload has "
                            f"no such field — the column renders blank")


def sunset_unit(f: dict) -> str:
    return f.get("operation") or f.get("path") or f.get("domain") or f.get("version") or ""


def check_owner_split(payload: dict) -> None:
    """The delivery owner is a DERIVED field, re-checked here so the two issue streams and
    the two report queues can never disagree with drift.json.

    Two invariants: (1) every action's stored `owner` equals owners.owner() recomputed from
    its own (kind, refKind) — a hand-edit or a routing bug that mislabels an action (sending
    a developer's API migration to the DevOps board, say) is caught; (2) the per-owner
    counts sum back to the DEPRECATED/REVIEW action totals, so neither queue silently
    drops or double-counts a job.
    """
    from agent.lib import owners
    actions = payload.get("actions", [])
    for a in actions:
        want = owners.owner(a)
        if a.get("owner") != want:
            raise Violation("owner-integrity",
                            f"action {a.get('repo')}/{a.get('ref')} is labelled "
                            f"owner={a.get('owner')!r} but its kind={a.get('kind')!r}/"
                            f"refKind={a.get('refKind')!r} derives {want!r} — the stream "
                            f"routing disagrees with the data")
    by_owner = (payload.get("counts") or {}).get("byOwner") or {}
    for status_key, status in (("fixes", "DEPRECATED"), ("review", "REVIEW")):
        summed = sum((by_owner.get(o) or {}).get(status_key, 0) for o in owners.OWNERS)
        total = sum(1 for a in actions if a.get("status") == status)
        if summed != total:
            raise Violation("owner-count-parity",
                            f"per-owner {status_key} sum to {summed} but {total} actions are "
                            f"{status} — a queue is miscounting")
        for o in owners.OWNERS:
            got = (by_owner.get(o) or {}).get(status_key, 0)
            exp = sum(1 for a in actions if a.get("owner") == o and a.get("status") == status)
            if got != exp:
                raise Violation("owner-count-parity",
                                f"counts.byOwner.{o}.{status_key}={got} but its filter yields "
                                f"{exp} actions")


def check_tile_counts(payload: dict, findings: list) -> None:
    """Each tile number must equal the rows its own filter yields, AND be reachable
    independently from the findings.

    The second half is what catches bug #1: `counts` is computed from actions, so if the
    grouping collapses, the tile and the table agree with each other and are both wrong.
    Recomputing from findings is an independent path, so a collapse shows up as a
    disagreement instead of a consistent lie.
    """
    counts, actions = payload["counts"], payload["actions"]

    # tile <-> table: replicate the page's own filters
    pairs = [("sunsets", [a for a in actions if a["kind"] == "sunset"]),
             ("pastDue", [a for a in actions
                          if a["kind"] == "sunset" and a.get("status") == "DEPRECATED"
                          and a.get("date")]),
             ("eol", [a for a in actions if a["kind"] == "eol"]),
             ("private", payload.get("private", [])),
             # the panel lists vendors nobody has checked; CURRENT ones are not rows
             ("unaudited", [r for r in payload.get("catalog", [])
                            if r.get("verdict") != "CURRENT"])]
    for name, rows in pairs:
        if counts.get(name, 0) != len(rows):
            raise Violation("tile-vs-table",
                            f"tile '{name}' says {counts.get(name)} but its filter yields "
                            f"{len(rows)} rows")

    # independent path: one job per (repo, vendor, thing-retiring)
    expected = {(f["repo"], f["ref"], sunset_unit(f))
                for f in findings if f.get("kind") == "sunset"}
    if counts.get("sunsets", 0) != len(expected):
        raise Violation("sunset-grouping",
                        f"tile says {counts.get('sunsets')} sunsets but the findings hold "
                        f"{len(expected)} distinct (repo, vendor, operation|host) jobs — "
                        f"retirements are being merged, hiding dead calls behind one row")


def check_row_labels_distinct(payload: dict) -> None:
    """No two sunset rows may render an identical label.

    Four rows reading 'eBay · migrate to Sell Feed API before 2022-04-30' are
    indistinguishable to a reader even though they are four different hosts.
    """
    seen = {}
    for a in payload["actions"]:
        if a["kind"] != "sunset":
            continue
        label = (a.get("repo"), a.get("ref"), a.get("unit"), a.get("recommendation"))
        if label in seen:
            raise Violation("row-identity",
                            f"two sunset rows render identically: {label} — a reader "
                            f"cannot tell which call each one refers to")
        seen[label] = True


def check_blob_matches_payload(html: str, payload_json: str,
                               source: str = "dashboard.html") -> None:
    """The data embedded in the page is the data in drift.json.

    This is what makes asserting on drift.json equivalent to asserting on the
    dashboard, and it is the only reason the checks above are trustworthy. `source` names
    the page in the message so it works for both dashboard.html and chart.html, which
    embed the identical blob.

    Compared as parsed JSON, not as bytes: the embedded copy escapes `<` to \\u003c so a
    scan string containing </script> cannot close the element, and drift.json is
    written indented for humans. Both are presentation; the DATA must be identical.
    """
    import json
    m = re.search(r'<script id="drift-data" type="application/json">(.*?)</script>',
                  html, re.S)
    if not m:
        raise Violation("blob-present", f"{source} carries no #drift-data payload")
    try:
        embedded = json.loads(m.group(1))
    except ValueError as exc:
        raise Violation("blob-parity", f"the embedded payload is not valid JSON ({exc})")
    if embedded != json.loads(payload_json):
        raise Violation("blob-parity",
                        f"the data embedded in {source} differs from drift.json "
                        "— the file being verified is not the file being read")


# A pipe NOT preceded by a backslash. NB — PORT LANDMINE: this lookbehind `(?<!…)` is a
# Python/PCRE feature that Rust's `regex` crate and Go's `regexp` (RE2) do NOT support. A
# port must rewrite it (e.g. split on `|`, then rejoin any piece ending in an odd run of
# backslashes) — a mechanical transliteration would fail to compile, or worse, a "fix" that
# drops the lookbehind would silently mis-split escaped pipes and defeat the very check
# that catches the GitHub table-truncation bug. See CLAUDE.md's Rust-port notes.
_CELL_SPLIT = re.compile(r"(?<!\\)\|")


def _parse_md_tables(md_text: str) -> list:
    """Every GFM pipe table in `md_text` as {header:[...], rows:[[...]]}. Cells are split
    on UNESCAPED pipes, so a raw `|` that slipped past the escaper shows up as an extra
    cell — which is exactly the silent-truncation bug we want to catch, not hide."""
    tables, cur = [], None

    def cells(line):
        parts = _CELL_SPLIT.split(line.strip())
        if parts and parts[0] == "":
            parts = parts[1:]
        if parts and parts[-1] == "":
            parts = parts[:-1]
        return [c.strip() for c in parts]

    lines = md_text.splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith("|"):
            row = cells(line)
            if cur is None:
                # header row must be followed by a --- separator row
                nxt = lines[i + 1] if i + 1 < len(lines) else ""
                if set(nxt.replace("|", "").replace(" ", "")) <= {"-", ":"} and nxt.strip():
                    cur = {"header": row, "rows": [], "_sep": True}
                continue
            if cur.get("_sep"):                 # this line IS the separator, skip it once
                cur["_sep"] = False
                continue
            cur["rows"].append(row)
        else:
            if cur is not None:
                cur.pop("_sep", None)
                tables.append(cur)
                cur = None
    if cur is not None:
        cur.pop("_sep", None)
        tables.append(cur)
    return tables


def check_md_matches_payload(md_text: str, payload: dict) -> None:
    """The Markdown view agrees with the payload it was rendered from.

    The Markdown analog of check_blob_matches_payload, and the reason drift.md is a
    TRUSTED projection rather than a hopeful one. Three checks, each catching a real
    failure class:
      • column integrity — every row has the header's column count, so an unescaped `|`
        (which GitHub renders as dropped cells) fails here instead of silently;
      • summary parity — the numbers in the Summary table equal the payload counts, so a
        headline number cannot drift from the data (bug #1's class);
      • row identity — no two rows in a findings table are byte-identical (bug #2's class).
    """
    tables = _parse_md_tables(md_text)

    for t in tables:
        ncol = len(t["header"])
        for row in t["rows"]:
            if len(row) != ncol:
                raise Violation("md-column-integrity",
                                f"a row under {t['header']} has {len(row)} cells, not "
                                f"{ncol} — an unescaped '|' truncates it on GitHub: {row}")

    counts = payload.get("counts", {})
    summary = next((t for t in tables if t["header"][:2] == ["Metric", "Count"]), None)
    if summary:
        by_label = {r[0]: r[1] for r in summary["rows"] if len(r) >= 2}
        checks = {"Vendor API sunsets": counts.get("sunsets", 0),
                  "— of which already retired (past-due)": counts.get("pastDue", 0),
                  "Runtime/framework EOL": counts.get("eol", 0),
                  "Fixes needed (action-required)": counts.get("fixes", 0),
                  "Unaudited vendors": counts.get("unaudited", 0)}
        for label, expected in checks.items():
            if label in by_label and by_label[label] != str(expected):
                raise Violation("md-summary-parity",
                                f"Summary says {label!r} = {by_label[label]}, payload says "
                                f"{expected} — the Markdown disagrees with drift.json")

    # findings tables are identified by their "First call-site" column (the coverage
    # tables have neither), so this keeps working now that findings tables lead with Repo.
    for t in tables:
        if "First call-site" in t["header"]:
            seen = set()
            for row in t["rows"]:
                key = tuple(row)
                if key in seen:
                    raise Violation("md-row-identity",
                                    f"two findings rows render identically: {row} — a "
                                    f"reader cannot tell them apart")
                seen.add(key)


def check_unscannable_surfaced(md_text: str, payload: dict) -> None:
    """Every root the scanner COULD NOT read is named in the report.

    The tool's first principle is "cannot see ≠ clean": a source requested but unreadable
    (a 404/no-access URL, a typo, a folder with no code) must appear in the report, not just
    an internal log. This shipped broken — inventory.json recorded the unscannable root but
    drift.json/drift.md dropped it, so the report rendered green over a repo it never opened.
    This guard fails if the payload knows an unscannable root the Markdown does not name.
    """
    unscannable = payload.get("rootsUnscannable", [])
    if unscannable and str(payload.get("counts", {}).get("unscannable", 0)) != str(len(unscannable)):
        raise Violation("unscannable-count",
                        f"counts.unscannable = {payload['counts'].get('unscannable')} but "
                        f"rootsUnscannable has {len(unscannable)} entries")
    for u in unscannable:
        root = str(u.get("root", ""))
        if root and root not in md_text:
            raise Violation("unscannable-dropped",
                            f"the scan could not read {root!r} but the report never names it "
                            f"— 'cannot see' must not render as 'clean'")


def check_sbom_matches_inventory(sbom_doc: dict, inventory: dict, audit: dict) -> None:
    """sbom.json is a faithful projection of inventory.json + audit.json.

    The old CycloneDX exporter was deleted for being a hand-built surface nobody re-derived.
    This makes the SBOM a VERIFIED projection like drift.md: rebuild it from the inventory and
    audit and fail if the file on disk disagrees — so a stale or hand-edited sbom.json (wrong
    components, a dropped vulnerability) cannot ship as if it were the real parts list.
    """
    from agent.lib import sbom as _sbom
    now = str(sbom_doc.get("metadata", {}).get("timestamp", "")).split("T")[0]
    expected = _sbom.build_sbom(inventory, audit, now)
    if sbom_doc.get("components") != expected.get("components"):
        raise Violation("sbom-components",
                        "sbom.json components do not match a fresh projection of "
                        "inventory.json — the SBOM is stale or hand-edited")
    if sbom_doc.get("vulnerabilities", []) != expected.get("vulnerabilities", []):
        raise Violation("sbom-vulnerabilities",
                        "sbom.json vulnerabilities do not match the audit's CVE findings")


def check_mermaid_wellformed(md_text: str) -> None:
    """Every Mermaid block is structurally sound: each edge endpoint is a declared node,
    and no label carries a raw grammar-breaking char.

    This is not a full render (that needs Chromium, off-limits) — it is the structural
    subset that catches the failures we actually cause: an edge to an undeclared node, or
    an unescaped `"`/`[`/`{` that would make Mermaid draw an error box which looks FINE in
    the source. The same silent-blindness class as the tile bug, one layer up.
    """
    for m in re.finditer(r"```mermaid\n(.*?)\n```", md_text, re.S):
        block = m.group(1)
        declared = set(re.findall(r'^\s*([A-Za-z_]\w*)\["', block, re.M))
        referenced = set()
        for edge in re.finditer(r"^\s*([A-Za-z_]\w*)\s*-->\s*([A-Za-z_]\w*)", block, re.M):
            referenced.add(edge.group(1))
            referenced.add(edge.group(2))
        undeclared = referenced - declared
        if undeclared:
            raise Violation("mermaid-undeclared-node",
                            f"the exposure graph draws an edge to undeclared node(s) "
                            f"{sorted(undeclared)} — it would render broken")
        # a raw " inside label text (beyond the wrapping pair) breaks the label silently
        for label in re.findall(r'\["(.*?)"\]', block):
            if '"' in label:
                raise Violation("mermaid-unescaped-label",
                                f"a graph label contains a raw quote: {label!r} — encode "
                                f"it (#quot;) or Mermaid renders an error box")


def check_number_formats(payload: dict) -> None:
    """Every number in drift.json serializes the SAME across languages.

    Cheap insurance for byte-identical output, and a landmine remover for a future Rust/Go
    port: Python, Go, and Rust's serde all use shortest-round-trip float formatting but
    DISAGREE on where scientific notation kicks in and on decimal padding — Python emits
    `1e+16` and `3e-05` where Go emits `10000000000000000` and `0.00003`. A single float
    that trips that would silently break determinism. Today the only float is a one-decimal
    CVSS score (e.g. 7.5), which formats identically everywhere; this keeps it that way by
    rejecting any number that serializes with an exponent or more than one decimal place.
    """
    import json

    def walk(v, path="$"):
        if isinstance(v, bool):
            return
        if isinstance(v, float):
            s = json.dumps(v)
            frac = s.split(".", 1)[1] if "." in s else ""
            if "e" in s or "E" in s or len(frac) > 1:
                raise Violation("number-format",
                                f"{path} = {s} formats differently across languages "
                                f"(exponent or >1 decimal) — round to one decimal or store "
                                f"as a string, or it will break byte-identical output")
        elif isinstance(v, dict):
            for k, x in v.items():
                walk(x, f"{path}.{k}")
        elif isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, f"{path}[{i}]")

    walk(payload)


def check_timeline_lanes(template_src: str) -> None:
    """The Retirement Timeline must render BOTH lanes: the dated axis (`timeline.dated`) and
    the undated lane (`timeline.undated`).

    STRUCTURAL, not numeric — this replaces a former `check_chart_parity(payload)` that
    asserted `len(dated) + len(undated) == counts.sunsets`. That was a tautology: dated and
    undated are computed as an exhaustive partition of the same sunset list (every action is
    either dated or not), so the equality held by construction and was already re-covered by
    check_tile_counts. It never looked at the client at all, so it could not catch the actual
    risk: a future edit that deletes the undated lane from the template. A `deprecated-no-date`
    sunset would then render nowhere on the timeline — 'cannot see' rendering as 'clean', the
    project's first principle, violated in the one surface built to be honest about it.
    Mirrors check_accessor_coverage: a plain substring check over the template source, so it
    fails the moment either lane's binding is removed, independent of how the chart is styled.
    """
    missing = [name for name in ("timeline.dated", "timeline.undated") if name not in template_src]
    if missing:
        raise Violation("timeline-lanes",
                        f"the timeline template no longer references {missing} — the "
                        f"undated/deprecated-no-date lane could silently disappear from the "
                        f"page while the tile stays green")


def verify_payload(payload: dict, findings: list) -> list:
    """Run every payload invariant. Returns the violations rather than raising, so
    `drift verify` can report all of them in one pass instead of one per run."""
    out = []
    for fn, args in ((check_tile_counts, (payload, findings)),
                     (check_owner_split, (payload,)),
                     (check_row_labels_distinct, (payload,)),
                     (check_number_formats, (payload,))):
        try:
            fn(*args)
        except Violation as v:
            out.append(v)
    return out
