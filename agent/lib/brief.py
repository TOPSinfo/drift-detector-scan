"""Render an ABSORPTION.md brief for one flagged repo — everything a maintainer (or the
assimilator agent) needs to teach the scanner this repo's shape, in ONE file, so nobody hunts.

A pure, deterministic renderer over inventory.json: byte-identical for identical input, zero
tokens, no network — so it belongs in the scan-path codebase. The flag issue carries a short
bootstrap; this is the full context (uncapped blind spots, the closed families, the rails).
"""
from __future__ import annotations

import re

from agent.lib.shapes import recommend_profile, MANUAL, AUTO

_URL = re.compile(r"^https?://[^/]+/(.+?)(?:\.git)?/?$")

# family -> (what it matches, the required field(s), a real example instance). Kept in lockstep
# with idioms.py::_validate — a new instance of these is DATA; a new family is a code PR.
_FAMILY_DOCS = [
    ("url-assembly",
     "`base . $path` — a base-URL expression concatenated with a path literal.",
     "`base`: an ast-grep pattern for the base expression, e.g. `$A->getHost()`.",
     '{id: acme-host, family: url-assembly, language: php, base: "$A->getHost()", '
     'evidence: "acme/api src/Client.php:40"}'),
    ("url-append",
     "`$var .= $path` — a URL built up by appending onto a named variable.",
     "`target`: the NAME of the variable appended to, e.g. `serviceURL`.",
     '{id: acme-append, family: url-append, language: php, target: "serviceURL", '
     'evidence: "acme/api src/Client.php:52"}'),
    ("operation-marker",
     "an operation named by a marker (XML body root, header literal, SOAPAction, JSON-RPC "
     "method) rather than a URL path — the eBay Trading shape.",
     "`marker`: a regex over string literals, OR `pattern`: an ast-grep pattern.",
     '{id: ebay-trading, family: operation-marker, language: php, marker: '
     '"X-EBAY-API-CALL-NAME", evidence: "example-org/ebayapi src/Ebay/X.php:72"}'),
    ("path-constant",
     "path constants in a config-injected wrapper (host injected at runtime, generic paths) — "
     "repo-scoped and vendor-bound, since there is no host literal to infer the vendor from.",
     "`repo`: the wrapper's project suffix; `vendor`: the bound vendor (must exist in "
     "vendors.yaml); `pathRegex`: which string literals are operation paths.",
     '{id: catch-api-paths, family: path-constant, repo: "example-org/catchapi", '
     'vendor: Catch, pathRegex: "^/api/", evidence: "example-org/catchapi '
     'src/CatchApi/GetOrders.php:9"}'),
]


def _shape_of(inventory: dict, repo: str) -> dict | None:
    for s in (inventory.get("coverage") or {}).get("shapes", []):
        if s.get("repo") == repo:
            return s
    return None


def _display_name(inventory: dict, repo: str) -> str:
    """The clean project path (group/repo) for a repo, from its remote_url — so a fleet clone
    slug like `marketplacehub-marketplacehub-ed5f4fd4` reads as `marketplacehub/marketplacehub`. Falls back to
    the repo key (already clean for a locally-scanned folder)."""
    for r in inventory.get("repos", []):
        if r.get("path") == repo:
            m = _URL.match(str(r.get("remote_url") or ""))
            return m.group(1) if m else repo
    return repo


def build_brief(inventory: dict, repo: str, *, flag_url: str | None = None) -> str:
    shape = _shape_of(inventory, repo) or {"repo": repo, "verdict": "UNKNOWN", "reasons": [],
                                           "languages": {}, "signalCoverage": {}}
    name = _display_name(inventory, repo)

    # a brief is only meaningful for a FLAGGED (UNKNOWN) repo. A KNOWN repo is fully read —
    # say so plainly rather than render the "here's your blind spots" scaffold over nothing.
    if shape.get("verdict") != "UNKNOWN":
        return (f"# Absorption brief — `{name}`\n\n"
                f"**Nothing to absorb — `{name}` is `{shape.get('verdict')}`.** The scanner "
                f"fully reads this repo's integration calls ({shape.get('attributed', 0)} "
                f"attributed, no unresolved residue); there is no shape to teach it. This brief "
                f"is only meaningful for a flagged (UNKNOWN) repo.\n")
    residue = ((inventory.get("coverage") or {}).get("residue")) or {}
    paths = [p for p in residue.get("pathLiterals", []) if p.get("repo") == repo]
    sinks = [s for s in residue.get("sinks", []) if s.get("repo") == repo]
    profile, why = recommend_profile(shape)
    langs = ", ".join((shape.get("languages") or {}).keys()) or "?"
    sigcov = "; ".join(f"{l}: {', '.join(k)}"
                       for l, k in (shape.get("signalCoverage") or {}).items()) or "none"

    L = [f"# Absorption brief — `{name}`", ""]

    L += ["## Why you're here",
          f"The fleet scan flagged `{name}` as a shape the deterministic scanner could not fully "
          "read, so its findings are incomplete (“cannot see” is not “clean”). "
          "Your job: teach the scanner this repo's shape as reviewed, gated YAML — you decide "
          "nothing, the gate does, and a human merges.", ""]
    if flag_url:
        L.append(f"- Flag issue: {flag_url}")
    L += [f"- Residue fingerprint: `{shape.get('residueFingerprint', '')}` — the absorption MR "
          "that resolves this must cite it.", ""]

    L += ["## What the scanner sees — and doesn't",
          f"- **Verdict:** {shape.get('verdict')} — "
          f"{', '.join(shape.get('reasons', [])) or 'unreadable'}",
          f"- **Languages:** {langs}",
          f"- **Signal coverage:** {sigcov}",
          f"- **Attributed:** {shape.get('attributed', 0)} call-site(s)",
          f"- **Unread:** {len(paths)} versioned path literal(s) + {len(sinks)} egress sink(s)", ""]

    L.append("## What's possible here")
    if profile == MANUAL:
        L += [f"**MANUAL — this needs a code release, not an absorption.** {why}. No idiom "
              "instance can teach the scanner a language it has no egress rules for. **Survey** "
              "how this repo makes outbound calls, document what rules a plugin release would "
              "need, and escalate. Do NOT stage a false attribution to make the flag close — "
              "that is the “cannot see = clean” lie this tool exists to refuse.", ""]
    elif profile == AUTO:
        L += ["**AUTO — already KNOWN.** Nothing to absorb; the scanner sees this repo. "
              "(This brief was rendered for a repo that isn't flagged.)", ""]
    else:
        L += [f"**HYBRID — absorbable via idiom instances.** {why}. Open the blind-spot files "
              "below, work out how each URL is assembled, and author idiom instances of the "
              "closed families that attribute them. The only way to raise the attributed count "
              "is to open more files and claim what you verified — the gate rejects "
              "unclaimed attribution by design.", ""]

    L.append("## Blind spots (open these)")
    if paths:
        L.append("Versioned paths seen but not attributed:")
        for p in paths:
            samp = p.get("sample")
            L.append(f"- `{p.get('loc')}`" + (f" — `{samp}`" if samp else ""))
    if sinks:
        L += ["", "Egress sinks with no resolved URL (the assembly is somewhere we can't follow):"]
        for s in sinks:
            L.append(f"- `{s.get('loc')}` ({s.get('kind')})")
    if not paths and not sinks:
        L.append("_(none listed — the residue may be sink-only, or already attested)_")
    L.append("")

    L += ["## The idiom families you may author (a closed set)",
          "A new *instance* of these is DATA (reviewable YAML, gated, mergeable). A shape that "
          "fits NONE of them is a code PR against the plugin — say so and stop.", ""]
    for fam, desc, req, example in _FAMILY_DOCS:
        L += [f"### `{fam}`", desc, f"- **Required:** {req}", f"- **Example:** `{example}`", ""]

    L += ["## The rails",
          "1. Stage specs in `.drift-detector/absorb-staged/` (`idioms.yaml`, `claims.yaml`, "
          "`sunsets.yaml`). Every idiom needs `evidence:` (a real `file:line` you opened); every "
          "sunset needs a `source:` URL you fetched THIS session, or don't write it.",
          "2. Point the gate at the drift-ops overlay so the learning survives:",
          "   ```",
          "   export DRIFT_OPS_DIR=<your drift-ops checkout>",
          "   DRIFT_CATALOG_DIR=\"$DRIFT_OPS_DIR/catalog\" \\",
          f"     drift-scan absorb --staged .drift-detector/absorb-staged --repo {name} \\",
          "       --state .drift-detector --now $(date +%F)",
          "   ```",
          "   Without `DRIFT_CATALOG_DIR` the absorb writes into the installed plugin's own "
          "catalogs — wiped on update, never read by CI. The overlay is the only place it "
          "survives and reaches the fleet.",
          "3. The gate REJECTS: an unsourced date; an idiom that doesn't attribute its claimed "
          "call-sites; an idiom that invents endpoints for another vendor; a change that grows "
          "residue. Never weaken a claim to pass — a narrower true proposal is correct.",
          "4. On a clean gate: commit the overlay to an `absorb/<repo>` branch in drift-ops, open "
          "an MR citing the residue fingerprint above, and let a human merge. The next fleet scan "
          "then sees this repo KNOWN and closes its flag on its own.", "",
          "## Launch",
          "Open this folder in Claude Code and run **`/drift-absorb .`** — it drives the loop "
          "above (staging, the gate, the overlay hand-off).", ""]
    return "\n".join(L)
