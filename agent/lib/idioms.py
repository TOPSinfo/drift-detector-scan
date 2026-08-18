"""Idiom families: the closed set of URL-assembly shapes the scanner can be taught.

A FAMILY is code (an interpreter here); an INSTANCE is data (agent/idioms.yaml).
That split is deliberate. Letting an agent author arbitrary detection logic as data
would reinvent the rule engine, worse — but letting it author a *parameter* of a
family we already implement is reviewable as a YAML diff, and the absorb gate can
verify it mechanically before it is trusted.

Adding a new family is a code change and a pull request. Say so; do not pretend
absorption is unbounded.
"""
from __future__ import annotations

import os
import re

import yaml

from agent.lib import catalog_overlay

_DEFAULT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "idioms.yaml")

FAMILIES = frozenset({"url-assembly", "url-append", "operation-marker", "path-constant",
                      "client-base"})

# `^/(catalog|fba|orders)/` -> the alternation body, so a corroborated instance's `families`
# list can be pinned to its own regex. The leading `^` is REQUIRED, not optional: endpoints.py
# counts distinct families by reading path segment 0 (`path.split("/")[1]`) — it never re-runs
# pathRegex. That counter is only correct if the alternation IS segment 0 by construction. An
# unanchored `/(catalog|fba|orders)/` still matches mid-path, so the two would silently
# disagree at scan time: permissive (segment-0 counts {v1, v2, api} = 3 "families" from one
# real family match, clearing a threshold on false evidence) or restrictive (three genuine
# families under a shared prefix like /api/ all read as segment "api" = 1, refusing a real
# corroborated vendor). Requiring `^` makes segment 0 the alternation by construction, so
# endpoints.py's counter is provably correct instead of coincidentally correct.
_PC_ALTERNATION = re.compile(r"^\^/\(([^)]+)\)/")

# family -> the rule kind its matches carry, i.e. how endpoints.py will read them
# How each language spells string concatenation. url-assembly used to emit PHP's `.`
# unconditionally, so a JavaScript instance compiled to a pattern that could never match:
# the family existed for JS on paper and found nothing in practice. Languages absent here
# emit no rule at all — see to_rules.
_CONCAT_OP = {"php": ".", "javascript": "+", "typescript": "+", "python": "+"}

# JS/TS also build URLs with template literals — `${this.baseURL}/v1/charges`. That is a
# template_string node, NOT a binary `+` expression, so the concat rule above is blind to
# it: verified against the engine, `$A.baseURL + $B` matches the template fixture zero
# times. `$$$` is ast-grep's multi-node metavariable, needed because a real URL often
# interpolates twice (`${base}/v1/refunds/${id}`); the single-node `$B` form catches only
# the first shape. Anchored on the instance's own `base`, so it does not match the
# repo's unrelated templates — checked against `hello ${name}`, `${count} items`, and
# `${config.apiKey}/v1/x`, all of which it correctly ignores.
_TEMPLATE_LANGS = ("javascript", "typescript")

# Python interpolates too, but with an f-string — a different node from a JS template
# literal, and NOT spelled with backticks. So python is deliberately absent from
# _TEMPLATE_LANGS above and gets its own branch: putting it in that tuple would emit
# `` `${base}$$$B` `` on Python, a rule that can never match. `$$$` for the same reason as
# JS: a real URL interpolates twice (f"{base}/v1/refunds/{id}"), and the single-node form
# caught only the simpler shape.
# KNOWN MISSES, deliberately not chased with four more patterns: f'...' (single quotes),
# rf"..."/F"..." (prefixes), and triple-quoted f-strings.
_FSTRING_LANGS = ("python",)

KIND_BY_FAMILY = {"url-assembly": "path-assembly", "url-append": "path-assembly",
                  "operation-marker": "operation-marker", "path-constant": "path-constant",
                  # client-base: a factory stores the host once (axios.create({baseURL})) and
                  # later calls pass only a path. The host and the path never share an
                  # expression, so url-assembly's base+concat shape cannot express it — but the
                  # FILE is assembling URLs, and path-assembly is the kind endpoints.py reads to
                  # decide that. It marks the file; it claims no dataflow between the two lines.
                  "client-base": "path-assembly"}


class IdiomError(ValueError):
    """A malformed instance. Raised loudly: a silently-dropped idiom is a silent blind spot."""


def _validate(inst: dict, where: str) -> None:
    if not isinstance(inst, dict):
        raise IdiomError(f"{where}: not a mapping")
    for req in ("id", "family", "evidence"):
        if not inst.get(req):
            raise IdiomError(f"{where}: missing required field `{req}`")
    fam = inst["family"]
    if fam not in FAMILIES:
        raise IdiomError(f"{where}: unknown family {fam!r} — families are a closed set "
                         f"({', '.join(sorted(FAMILIES))}); a new one is a code change")
    if fam == "client-base":
        for req in ("pattern", "language"):
            if not inst.get(req):
                raise IdiomError(f"{where}: client-base needs `{req}` — the pattern is matched "
                                 f"verbatim by the engine, and it is language-specific")
    if fam == "url-append" and not inst.get("target"):
        raise IdiomError(f"{where}: url-append needs `target` — the NAME of the variable "
                         "appended to (e.g. \"serviceURL\" for `$serviceURL .= $path`). "
                         "Naming it is what keeps the family precise: a bare metavariable "
                         "would match every string append in the codebase.")
    if fam == "url-assembly" and not inst.get("base"):
        raise IdiomError(f"{where}: url-assembly needs `base` (an ast-grep pattern "
                         "for the base expression, e.g. \"$A->getHost()\")")
    if fam == "operation-marker" and not (inst.get("marker") or inst.get("pattern")):
        raise IdiomError(f"{where}: operation-marker needs `marker` (a regex over string "
                         "literals) or `pattern` (an ast-grep pattern)")
    if fam == "path-constant":
        # Vendor-bound always: a config-injected wrapper has no host literal, so the vendor
        # cannot be inferred from the repo — it must be NAMED (and reviewed). pathRegex says
        # which string literals are operation paths.
        for req in ("vendor", "pathRegex"):
            if not inst.get(req):
                raise IdiomError(f"{where}: path-constant needs `{req}` — it is vendor-bound "
                                 "(no host literal to infer the vendor from)")
        # ...and GUARDED, by exactly one of two mechanisms. `repo` scopes the instance to one
        # repository (right for a client's private wrapper, whose generic /api/orders would
        # mis-tag another marketplace). `corroboration` scopes it by evidence instead, so the
        # instance can SHIP: N distinct path families must co-occur in the repo before any of
        # them attributes. Neither guard = a family that tags every repo's /orders/ with this
        # vendor. Both = the weaker one is dead weight nobody reviews.
        has_repo = bool(inst.get("repo"))
        has_corr = inst.get("corroboration") is not None
        if has_repo == has_corr:
            raise IdiomError(f"{where}: path-constant needs exactly one of `repo` "
                             "(scoped to one repository) or `corroboration` (scoped by "
                             "co-occurring evidence, so the instance can ship)")
        if has_corr:
            corr = inst["corroboration"]
            if not isinstance(corr, int) or isinstance(corr, bool) or corr < 2:
                raise IdiomError(f"{where}: `corroboration` must be an integer >= 2 — a "
                                 "threshold of 1 is a single generic path, i.e. no guard")
            fams = inst.get("families")
            if not isinstance(fams, list) or not fams:
                raise IdiomError(f"{where}: a corroborated path-constant needs `families` — "
                                 "the list of path segments whose DISTINCT count is compared "
                                 "against the threshold")
            # `families` and `pathRegex` state the same set twice. Pin them to each other so
            # they cannot drift: an edit to one that forgets the other fails the load loudly.
            m = _PC_ALTERNATION.match(inst["pathRegex"])
            if not m:
                raise IdiomError(f"{where}: a corroborated path-constant needs a pathRegex of "
                                 r"the form `^/(a|b|c)/` — anchored with a leading `^`, so the "
                                 "alternation is path segment 0 and endpoints.py's segment-0 "
                                 "family counter cannot disagree with it")
            if set(m.group(1).split("|")) != set(fams):
                raise IdiomError(f"{where}: `families` must equal the pathRegex alternation "
                                 f"— regex has {sorted(set(m.group(1).split('|')))}, "
                                 f"families has {sorted(set(fams))}")
            # ...and which of those families are SPECIFIC to this vendor. Counting families
            # alone is not enough: 10 of SP-API's 18 are ordinary e-commerce nouns, and a
            # repo wired to eBay (/orders/), Shopify (/products/) and BigCommerce (/catalog/)
            # cleared a threshold of 3 and was attributed to Amazon SP-API — 4 endpoints,
            # verdict KNOWN, on zero Amazon code. Reproduced 2026-08-18. At least one
            # distinctive family must be present before ANY of them attributes.
            dist = inst.get("distinctive")
            if not isinstance(dist, list) or not dist:
                raise IdiomError(f"{where}: a corroborated path-constant needs `distinctive` "
                                 "— the subset of `families` that is specific to this vendor. "
                                 "Generic nouns alone let a multi-vendor repo clear the count")
            if not set(dist) <= set(fams):
                raise IdiomError(f"{where}: `distinctive` must be a subset of `families` — "
                                 f"{sorted(set(dist) - set(fams))} is not in `families`")


def load_idioms(path: str | None = None) -> list:
    with open(path or _DEFAULT, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or []
    if not isinstance(raw, list):
        raise IdiomError("idioms file must be a YAML list of instances")
    # layer the writable overlay (baseline first) on a default load; the dup-id check below
    # then runs over the COMBINED set, so an absorbed idiom cannot silently shadow a baseline
    if path is None:
        raw = list(raw) + catalog_overlay.load_list(catalog_overlay.IDIOMS)
    for i, inst in enumerate(raw):
        _validate(inst, f"idiom #{i} ({inst.get('id') if isinstance(inst, dict) else inst!r})")
    ids = [i["id"] for i in raw]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise IdiomError(f"duplicate idiom ids: {sorted(dupes)}")
    return raw


def to_rules(inst: dict, literal_rule, languages: list) -> list:
    """Compile one instance into ast-grep rule documents.

    `literal_rule(base_id, regex, lang, metadata)` is injected so string-literal
    rules are built exactly like every other one — same node kinds, same
    comment-safety — instead of this module re-deriving them.
    """
    fam, rid = inst["family"], inst["id"]
    kind = {"kind": KIND_BY_FAMILY[fam]}
    langs = [inst["language"]] if inst.get("language") else list(languages)
    docs = []
    if fam == "url-assembly":
        for lang in langs:
            op = _CONCAT_OP.get(lang)
            if not op:
                # Emitting PHP's `.` on a language that concatenates some other way (go,
                # java, csharp) would ship a rule that cannot match, and a rule that cannot
                # match is indistinguishable from a repo with nothing to find. Say nothing
                # rather than say it wrongly.
                continue
            docs.append({"id": f"{rid}@{lang}", "language": lang, "metadata": dict(kind),
                         "rule": {"pattern": f'{inst["base"]} {op} $B'}})
            if lang in _TEMPLATE_LANGS:
                docs.append({"id": f"{rid}@{lang}-template", "language": lang,
                             "metadata": dict(kind),
                             "rule": {"pattern": f'`${{{inst["base"]}}}$$$B`'}})
            if lang in _FSTRING_LANGS:
                docs.append({"id": f"{rid}@{lang}-fstring", "language": lang,
                             "metadata": dict(kind),
                             "rule": {"pattern": f'f"{{{inst["base"]}}}$$$B"'}})
    elif fam == "url-append":
        # assemble-then-append: `$base = $this->ENDPOINT;` ... `$base .= $path;`
        # The two statements are not one expression, so url-assembly's `base . $B`
        # cannot see it. The target variable is named literally — ast-grep treats
        # $UPPERCASE as a metavariable, so a lowercase/mixed name matches only itself.
        for lang in langs:
            docs.append({"id": f"{rid}@{lang}", "language": lang, "metadata": dict(kind),
                         "rule": {"pattern": f'${inst["target"]} .= $B'}})
    elif fam == "operation-marker":
        for lang in langs:
            if inst.get("marker"):
                docs.append(literal_rule(rid, inst["marker"], lang, dict(kind)))
            else:
                docs.append({"id": f"{rid}@{lang}", "language": lang, "metadata": dict(kind),
                             "rule": {"pattern": inst["pattern"]}})
    elif fam == "client-base":
        # The instance's pattern is emitted verbatim, like operation-marker's pattern branch.
        # `language` is required, so langs is always the single declared language.
        for lang in langs:
            docs.append({"id": f"{rid}@{lang}", "language": lang, "metadata": dict(kind),
                         "rule": {"pattern": inst["pattern"]}})
    elif fam == "path-constant":
        # A string-literal rule matching the instance's path shape, carrying the BOUND vendor
        # in metadata (the engine passes `vendor` through, exactly as it does for the per-vendor
        # `endpoint` rules). endpoints.py then attributes the match — repo-scope + sink guarded.
        # The ast-grep regex runs over the node text WITH its quotes ("/api/orders"), so a
        # leading `^` would anchor before the quote and never match — strip it for the rule
        # (a broad candidate surface); endpoints.py re-applies the FULL pathRegex to the
        # unquoted content, so `^/api/` still means "the path starts with /api/".
        meta = {**kind, "vendor": inst["vendor"]}
        rule_rx = inst["pathRegex"][1:] if inst["pathRegex"].startswith("^") else inst["pathRegex"]
        for lang in langs:
            docs.append(literal_rule(rid, rule_rx, lang, meta))
    return docs
