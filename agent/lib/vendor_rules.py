"""Render the ast-grep endpoint rule pack (discover-then-classify + allowlist recall):

- ONE broad rule matches every `http(s)://` string literal → we classify each host in
  Python (agent.lib.classify_url), so un-catalogued vendors still surface.
- PLUS one rule per catalogued vendor matching its domain literals → host-only
  references with no scheme (e.g. `'api.mailgun.net'` in a config) are still caught.
- PLUS the shape rules: versioned resource-path literals, PHP egress sinks, and the
  getHost()-concat idiom.
Matching is by tree-sitter node kind, so it is comment-safe by construction.
"""
from __future__ import annotations

import re

import yaml

from agent.lib.vendors import vendor_slug
from agent.lib import idioms

DEFAULT_LANGUAGES = ["php", "js", "ts", "python", "ruby", "go", "java", "csharp"]


# ---------------------------------------------------------------- ast-grep ----
# ast-grep rules are per-language and match by tree-sitter NODE KIND, so a
# string-literal rule must name the kinds that actually hold a string in each
# grammar. These were verified empirically against ast-grep 0.44.1 — do not
# guess them: a wrong kind means the scanner goes silently blind for that
# language (getting `encapsed_string` wrong lost 9 real PHP call-sites).
# Only CONTAINER kinds are listed; inner-content kinds (string_fragment,
# string_content, heredoc_body) are excluded because matching both double-counts.
AST_STRING_KINDS = {
    "php": ["string", "encapsed_string", "heredoc"],
    "javascript": ["string", "template_string"],
    "typescript": ["string", "template_string"],
    "python": ["string"],
    "ruby": ["string"],
    "go": ["interpreted_string_literal", "raw_string_literal"],
    "java": ["string_literal"],
    "csharp": ["string_literal", "verbatim_string_literal"],
}
_AST_LANG = {"js": "javascript", "ts": "typescript"}      # our short names -> ast-grep's


def _ast_lang(lang: str) -> str:
    return _AST_LANG.get(lang, lang)


def _ast_literal_rule(base_id: str, regex: str, lang: str, metadata: dict) -> dict:
    """A comment-safe string-literal match: any container string kind whose text matches."""
    kinds = AST_STRING_KINDS[lang]
    return {"id": f"{base_id}@{lang}", "language": lang, "metadata": dict(metadata),
            "rule": {"any": [{"kind": k, "regex": regex} for k in kinds]}}


# ── Egress sinks: "this line makes an outbound HTTP call" ──────────────────────────────
#
# Until now only PHP had these, so `shapes.verdict()` returned UNKNOWN/no-egress-signal
# for seven of eight languages — honest, but it meant a JS or Go repo could never be
# scanned with confidence. These close that.
#
# EVERY pattern below was run against a real fixture in that language before being added.
# That is not ceremony: a pattern that looks correct can match nothing silently (PHP's
# `kind: string` matched only single-quoted strings and lost nine call-sites, including a
# vendor host), and a sink rule that matches nothing degrades exactly like having no rule
# at all — except it also reports coverage it does not have.
#
# Deliberately EXCLUDED as too noisy without argument-shape analysis:
#   php     file_get_contents / fopen — usually filesystem
#   go      $C.Do($$$)                — sync.Once.Do and every builder .Do() in Go
#   js      got($$$)                  — a single common word; too easy to shadow
# The rule is the one PHP already followed: a sink that cries wolf is worse than a gap,
# because the gap is reported and the false positive is believed.
#
# Go needs `context` + `selector`: a bare `http.Get($$$)` is not valid Go at top level, so
# ast-grep cannot parse the pattern and silently matches nothing. Verified: the bare form
# returns 0 matches on a file where the call plainly exists.
EGRESS_SINKS = {
    "php": [
        {"pattern": "curl_exec($$$)"},
        {"pattern": "curl_setopt($$$, CURLOPT_URL, $$$)"},
        {"pattern": "new \\GuzzleHttp\\Client($$$)"},
    ],
    "javascript": [
        {"pattern": "fetch($$$)"},
        {"pattern": "axios.$M($$$)"},
        {"pattern": "axios($$$)"},
        {"pattern": "new XMLHttpRequest()"},
        {"pattern": "https.request($$$)"},
        {"pattern": "http.request($$$)"},
    ],
    "typescript": [
        {"pattern": "fetch($$$)"},
        {"pattern": "axios.$M($$$)"},
        {"pattern": "axios($$$)"},
        {"pattern": "new XMLHttpRequest()"},
        {"pattern": "https.request($$$)"},
        {"pattern": "http.request($$$)"},
    ],
    "python": [
        {"pattern": "requests.$M($$$)"},
        {"pattern": "httpx.$M($$$)"},
        {"pattern": "urllib.request.urlopen($$$)"},
    ],
    "go": [
        {"pattern": {"context": "func f(){ http.Get($$$) }", "selector": "call_expression"}},
        {"pattern": {"context": "func f(){ http.Post($$$) }", "selector": "call_expression"}},
        {"pattern": {"context": "func f(){ http.NewRequest($$$) }", "selector": "call_expression"}},
    ],
    "ruby": [
        {"pattern": "Net::HTTP.$M($$$)"},
        {"pattern": "RestClient.$M($$$)"},
        {"pattern": "HTTParty.$M($$$)"},
        {"pattern": "Faraday.new($$$)"},
    ],
    "java": [
        {"pattern": "HttpClient.newHttpClient()"},
        {"pattern": "HttpRequest.newBuilder()"},
        {"pattern": "new URL($$$).openConnection()"},
        {"pattern": "$T.getForObject($$$)"},
    ],
    "csharp": [
        {"pattern": "new HttpClient()"},
        {"pattern": "$C.GetAsync($$$)"},
        {"pattern": "$C.PostAsync($$$)"},
        {"pattern": "WebRequest.Create($$$)"},
    ],
}


def build_astgrep_ruleset(vendors: list | None = None,
                          languages: list = DEFAULT_LANGUAGES,
                          idiom_instances: list | None = None) -> list:
    """The same rule pack in ast-grep's dialect, as a list of rule documents.

    Rule ids are `{base}@{language}` because ast-grep rules are single-language;
    `run_scan` strips the suffix so downstream code still sees the base id.
    """
    langs = [l for l in (_ast_lang(x) for x in languages) if l in AST_STRING_KINDS]
    docs = []
    for lang in langs:
        docs.append(_ast_literal_rule("url-literal", r"https?://", lang, {"kind": "url"}))
    for v in (vendors or []):
        if not v.domains:
            # A self-hosted vendor (Magento etc.) has no host to match — it is identified by a
            # path-constant idiom, not a domain. Skipping avoids an EMPTY endpoint regex, which
            # would match every string literal and attribute the whole codebase to that vendor.
            continue
        rx = "|".join(re.escape(d) for d in v.domains)
        meta = {"vendor": v.vendor, "techKey": v.techKey, "kind": "endpoint"}
        for lang in langs:
            docs.append(_ast_literal_rule(f"{vendor_slug(v.vendor)}-endpoint", rx, lang, meta))
    for lang in langs:
        docs.append(_ast_literal_rule(
            "path-literal", r"/(v[0-9][0-9.]*|[0-9]{4}-[0-9]{2}-[0-9]{2})/", lang,
            {"kind": "path-literal"}))
    # egress sinks — HTTP-unambiguous calls only
    for lang in langs:
        alts = EGRESS_SINKS.get(lang)
        if alts:
            docs.append({"id": f"{lang}-http-sink@{lang}", "language": lang,
                         "metadata": {"kind": "sink"}, "rule": {"any": list(alts)}})
    # URL-assembly and operation-marker idioms come from agent/idioms.yaml, so a new
    # shape is a reviewable data change rather than an edit to this file
    for inst in (idiom_instances if idiom_instances is not None else idioms.load_idioms()):
        docs += idioms.to_rules(inst, _ast_literal_rule, langs)
    return docs


_SERIALIZED: dict = {}      # (vendors, languages) -> the rendered rule file text


def write_ruleset(vendors: list | None, path: str, languages: list = DEFAULT_LANGUAGES,
                  idiom_instances: list | None = None) -> None:
    """Write the rule pack as a multi-document ast-grep rule file.

    One rule per (vendor x language) means ~390 documents, and serializing them
    costs ~150ms — paid on every scan. The text is a pure function of its inputs,
    so it is memoized: a process that scans repeatedly renders it once.

    The cache key includes the idiom instances, because the absorb gate scans the
    SAME repo twice in one process — once with the staged idioms and once without.
    Keying on vendors alone would hand it the first ruleset both times and the gate
    would silently pass everything.
    """
    key = (tuple((v.vendor, v.techKey, tuple(v.domains)) for v in (vendors or [])),
           tuple(languages),
           None if idiom_instances is None else tuple(sorted(i.get("id", "") for i in idiom_instances)))
    text = _SERIALIZED.get(key)
    if text is None:
        text = yaml.safe_dump_all(build_astgrep_ruleset(vendors, languages, idiom_instances),
                                  sort_keys=False)
        _SERIALIZED[key] = text
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def rule_kinds_by_language(vendors: list | None = None,
                           languages: list = DEFAULT_LANGUAGES) -> dict:
    """language -> the set of rule kinds we actually emit for it.

    This is what makes "I have no rules here" distinguishable from "I looked and
    found nothing": the shape verdict reads it to decide whether a language is
    covered at all. Derived from the real ruleset so it can never drift from it.
    """
    out: dict = {}
    for d in build_astgrep_ruleset(vendors, languages):
        lang = d.get("language")
        kind = (d.get("metadata") or {}).get("kind")
        if lang and kind:
            out.setdefault(lang, set()).add(kind)
    return {k: sorted(v) for k, v in out.items()}
