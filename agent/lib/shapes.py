"""The shape store: an honest, per-repo account of what the scan could and could NOT see.

The coverage grade answers "did anything go unattributed?". That is not the same
question as "do I even have rules for this repo's languages?" — and conflating them
is how a scanner goes silently blind. A Go repo with no Go egress rules produces no
residue at all, so it would grade HIGH: "clean" and "I cannot see here" look
identical. The shape record separates them:

  attributed   -> what we resolved
  residue      -> what we saw but could not resolve   (the grade's input)
  signalCoverage -> which rule kinds exist for the languages actually present
                    (the thing a grade cannot tell you)

`verdict` is KNOWN only when both hold: every meaningfully-present language has
egress-signal coverage, AND nothing is left unattributed. Anything else is UNKNOWN
with `reasons` drawn from a closed vocabulary, so the eval harness and the runtime
speak the same language about failure modes.

Reasons reuse agent/eval/corpus.TAXONOMY, plus `no-egress-signal` for the gap the
taxonomy never needed a word for (the eval only ever scored PHP corpora).
"""
from __future__ import annotations

import hashlib
import os

# Source extensions we can attribute a language to. A file type absent here is not
# counted in the census — we make no claim about languages we do not model.
_LANG_BY_EXT = {
    ".php": "php", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".py": "python", ".rb": "ruby",
    ".go": "go", ".java": "java", ".cs": "csharp",
}
# Extensions that are plainly source code but which we have no rules for. Counted so
# a repo made of them cannot report KNOWN by virtue of being unreadable.
_CODE_ISH = {".kt", ".kts", ".rs", ".swift", ".ex", ".exs", ".scala", ".dart", ".m",
             ".mm", ".c", ".cc", ".cpp", ".h", ".hpp", ".pl", ".pm", ".lua", ".r",
             ".jl", ".clj", ".erl", ".hs", ".ml", ".fs", ".vb", ".groovy"}
_SKIP_DIRS = {".git", "test", "tests", "spec", "__tests__", "vendor", "node_modules",
              ".venv", "dist", "build", "target", "__pycache__"}

# A language must clear this share of counted source files before its missing
# coverage is held against the repo — one stray .go script in a PHP project is not
# a blind spot worth failing a verdict over.
_MEANINGFUL_SHARE = 0.10

NO_EGRESS_SIGNAL = "no-egress-signal"
UNMODELED_LANGUAGE = "unmodeled-language"


def census(repo_abs: str) -> tuple:
    """(language -> source-file count, count of files in languages we do NOT model).

    The second number matters: a repo written entirely in Kotlin, Rust or Swift has an
    EMPTY census, and an empty census used to sail through the coverage check with
    nothing to iterate — reporting KNOWN for a repo we cannot read a single line of.
    """
    counts: dict = {}
    unmodeled = 0
    for dirpath, dirnames, filenames in os.walk(repo_abs):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            lang = _LANG_BY_EXT.get(ext)
            if lang:
                counts[lang] = counts.get(lang, 0) + 1
            elif ext in _CODE_ISH:
                unmodeled += 1
    return counts, unmodeled


def signal_coverage(languages, rule_kinds_by_lang: dict) -> dict:
    """language -> the rule kinds we actually ship for it."""
    return {lang: sorted(rule_kinds_by_lang.get(lang, [])) for lang in languages}


def meaningful_languages(counts: dict) -> list:
    total = sum(counts.values())
    if not total:
        return []
    return sorted(l for l, n in counts.items() if n / total >= _MEANINGFUL_SHARE)


def residue_fingerprint(residue: dict) -> str:
    """Stable id for a repo's unresolved set, so an attestation survives commits that
    do not change it. Keyed on (file, sample) — NOT line numbers, which shift on any
    edit above them."""
    items = sorted(
        {(loc.rsplit(":", 1)[0], p.get("sample", ""))
         for p in residue.get("pathLiterals", []) for loc in [p.get("loc", "")]}
        | {(loc.rsplit(":", 1)[0], "sink") for s in residue.get("sinks", [])
           for loc in [s.get("loc", "")]}
    )
    blob = "\n".join(f"{f}|{sample}" for f, sample in items)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def verdict(attributed: int, residue: dict, coverage: dict,
            *, attested: bool = False, unmodeled: int = 0) -> tuple:
    """(KNOWN|UNKNOWN, reasons). KNOWN requires BOTH egress coverage for every
    meaningful language AND nothing left unattributed (or a valid attestation)."""
    reasons = []
    if unmodeled and not coverage:
        # every source file is in a language we do not model at all — we have not
        # looked at this repo, and saying KNOWN would be a lie of omission
        reasons.append(UNMODELED_LANGUAGE)
    uncovered = [lang for lang, kinds in coverage.items()
                 if not any(k in ("sink", "path-assembly") for k in kinds)]
    if uncovered:
        reasons.append(NO_EGRESS_SIGNAL)
    n_paths = len(residue.get("pathLiterals", []))
    n_sinks = len(residue.get("sinks", []))
    if n_paths and not attested:
        # a versioned path we could not attribute is a miss, full stop
        reasons.append("config-driven-url")
    elif n_sinks and attributed == 0 and not attested:
        # Sinks are only evidence of blindness when NOTHING resolved. We cannot link a
        # sink to the endpoint it calls without dataflow, so a fully-attributed repo
        # still shows sinks (amazonspapi: 273 call-sites resolved, 7 curl_exec sinks).
        # Counting those as unknown would cry wolf on exactly the repos we see best.
        reasons.append("sdk-only-no-callsite")
    return ("UNKNOWN" if reasons else "KNOWN"), reasons


def build(repo_abs: str, repo_path: str, endpoints: list, residue: dict,
          rule_kinds_by_lang: dict, *, attested: bool = False) -> dict:
    counts, unmodeled = census(repo_abs)
    langs = meaningful_languages(counts)
    cov = signal_coverage(langs, rule_kinds_by_lang)
    attributed = sum(1 for e in endpoints
                     if e.get("vendor") and e["vendor"] != "Unknown")
    v, reasons = verdict(attributed, residue, cov, attested=attested, unmodeled=unmodeled)
    return {
        "repo": repo_path,
        "languages": counts,
        "unmodeledFiles": unmodeled,
        "signalCoverage": cov,
        "attributed": attributed,
        "unattributedPaths": len(residue.get("pathLiterals", [])),
        "unresolvedSinks": len(residue.get("sinks", [])),
        "residueFingerprint": residue_fingerprint(residue),
        "verdict": v,
        "reasons": reasons,
    }


# --- attestations: "this blindness was investigated and resolved" ---------------
# Keyed by the residue FINGERPRINT, not the commit: a repo can be re-scanned freely
# without re-litigating a resolved gap, but the moment new residue appears the
# fingerprint changes, the attestation stops matching, and the verdict reverts to
# UNKNOWN on its own. Resolution is never permanent by accident.
_ATTEST_FILE = "shape_attestations.json"


def _attest_path(state_dir: str) -> str:
    return os.path.join(state_dir, _ATTEST_FILE)


def load_attestations(state_dir: str) -> dict:
    import json
    try:
        with open(_attest_path(state_dir), encoding="utf-8") as fh:
            return json.load(fh) or {}
    except (OSError, ValueError):
        return {}


def repo_key(repo_path: str, repo_abs: str = "") -> str:
    """A repo identity that cannot collide across unrelated repos.

    The discovered name is often a bare basename, so two unrelated repos both called
    `svc` with the same unresolved literal produced the same attestation key — and
    attesting one silently marked the other, never reviewed by anyone, as resolved.
    """
    if not repo_abs:
        return repo_path
    return f"{repo_path}:{hashlib.sha256(os.path.abspath(repo_abs).encode()).hexdigest()[:12]}"


def attest(state_dir: str, repo_path: str, fingerprint: str, *, resolved_by: str,
           date: str, note: str = "", repo_abs: str = "") -> None:
    import json
    data = load_attestations(state_dir)
    repo_path = repo_key(repo_path, repo_abs)
    data[f"{repo_path}@{fingerprint}"] = {"repo": repo_path, "fingerprint": fingerprint,
                                          "resolvedBy": resolved_by, "date": date,
                                          "note": note}
    with open(_attest_path(state_dir), "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)


def is_attested(attestations: dict, repo_path: str, fingerprint: str,
                repo_abs: str = "") -> bool:
    return f"{repo_key(repo_path, repo_abs)}@{fingerprint}" in (attestations or {})


# --- scan profiles: which mode should a human run this folder in? ---------------
# Called a "scan profile", NOT a category — `category` already means the eval
# corpus's vendor grouping (eval/corpus.yaml) and overloading it would confuse
# two unrelated things.
AUTO, HYBRID, MANUAL = "auto", "hybrid", "manual"


def recommend_profile(shape: dict) -> tuple:
    """(profile, why) from a scanned repo's shape.

    auto   — the deterministic tool sees this repo; run it free, in CI, forever.
    hybrid — the tool sees most of it and says what it missed; an agent closes the
             named gap, then absorption makes the next run auto.
    manual — we have no egress rules for a language here, so the tool has nothing
             to be confident about; first contact needs an agent.
    """
    reasons = shape.get("reasons") or []
    if NO_EGRESS_SIGNAL in reasons:
        blind = [l for l, kinds in (shape.get("signalCoverage") or {}).items()
                 if not any(k in ("sink", "path-assembly") for k in kinds)]
        return MANUAL, f"no egress rules for {', '.join(blind) or 'a language present'}"
    if shape.get("verdict") == "UNKNOWN":
        return HYBRID, (f"{shape.get('unattributedPaths', 0)} unattributed path literal(s)"
                        f" — {', '.join(reasons)}")
    return AUTO, "every language covered and nothing left unattributed"


def recommend_from_census(counts: dict, rule_kinds_by_lang: dict,
                          unmodeled: int = 0) -> tuple:
    """Pre-scan recommendation: language census only, no engine run needed."""
    langs = meaningful_languages(counts)
    if not langs:
        if unmodeled:
            return MANUAL, f"{unmodeled} source file(s) in language(s) we do not model at all"
        return AUTO, "no source files we model — nothing to scan"
    blind = [l for l in langs
             if not any(k in ("sink", "path-assembly")
                        for k in rule_kinds_by_lang.get(l, []))]
    if blind:
        return MANUAL, f"no egress rules for {', '.join(blind)}"
    return AUTO, f"egress rules cover {', '.join(langs)}"
