"""Run the ast-grep scan engine (injected for tests) and normalize its JSON.

ast-grep is a static Rust/tree-sitter binary: ~90x faster than semgrep on a real
repo and ~165x faster to start, with no Python runtime of its own. Two of its
conventions have to be translated here, and both are easy to get silently wrong:

  • lines are 0-INDEXED (everything downstream is 1-indexed);
  • rule metadata travels in the results via `--include-metadata` (ast-grep 0.44+),
    so each rule's {kind, vendor, techKey} flows through the SAME channel as the
    match — no second read of the rule file in production. If the engine did not
    echo metadata (an older build, or an injected test fake), we fall back to
    reading the rule file back, lazily.

Rule ids are `{base}@{language}` because ast-grep rules are single-language; the
suffix is stripped so downstream code sees the base id.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml


def _default_run(args: list) -> str:  # pragma: no cover - spawns the real engine
    proc = subprocess.run(args, capture_output=True, text=True, timeout=600)
    return proc.stdout


def _rule_metadata(ruleset_path: str) -> dict:
    """base rule id -> {kind, vendor, techKey}, read back from the rule file.

    FALLBACK ONLY: with `--include-metadata` the engine echoes this in the results
    (see run_scan). This path exists for an engine that doesn't, and for injected
    test fakes that emit bare matches.
    """
    try:
        with open(ruleset_path, encoding="utf-8") as fh:
            docs = list(yaml.safe_load_all(fh))
    except (OSError, yaml.YAMLError):
        return {}
    return {str(d["id"]).split("@")[0]: (d.get("metadata") or {})
            for d in docs if isinstance(d, dict) and d.get("id")}


# Directories whose contents are not production integrations. Test fixtures and
# mocks hard-code fake hosts ("production.com", "sandbox.com") and vendored code
# belongs to someone else — counting either as an integration is noise, and the
# eval's noise metric exists to catch exactly that. semgrep skipped tests by
# default; ast-grep does not, so the skip is explicit here.
#
# Filtered on the path RELATIVE to the scanned repo, not via engine globs: a glob
# would also match the absolute prefix, so scanning a fixture that itself lives
# under a `tests/` directory would silently return nothing.
_SKIP_DIRS = {"test", "tests", "spec", "__tests__", "vendor", "node_modules",
              ".venv", "dist", "build", "target", "__pycache__"}


def _is_skipped(file_path: str, repo_path: str) -> bool:
    try:
        rel = Path(file_path).resolve().relative_to(Path(repo_path).resolve())
    except ValueError:
        rel = Path(file_path)
    return any(part in _SKIP_DIRS for part in rel.parts[:-1])


def run_scan(repo_path: str, ruleset_path: str, *, engine: str = "ast-grep",
             run=_default_run) -> dict:
    out = run([engine, "scan", "-r", ruleset_path, "--include-metadata",
               "--json=compact", repo_path])
    errors = []
    try:
        data = json.loads(out) if out and out.strip() else []
    except ValueError as exc:
        # A crash mid-write, or a warning line before the JSON, must NOT read as
        # "scanned cleanly, found nothing" — that is indistinguishable from a clean
        # repo all the way through to a KNOWN verdict. Fail loud.
        data = []
        errors.append({"message": f"engine output was not valid JSON ({exc}); "
                                  "treating the scan as FAILED, not empty",
                       "path": repo_path})
    meta_by_rule = None                      # lazy: only re-read the rule file if the
    matches = []                             # engine did not echo metadata for a match
    for m in data:
        if _is_skipped(m.get("file", ""), repo_path):
            continue
        base = str(m.get("ruleId", "")).split("@")[0]
        meta = m.get("metadata")
        if meta is None:                     # engine didn't echo it (old build / test fake)
            if meta_by_rule is None:
                meta_by_rule = _rule_metadata(ruleset_path)
            meta = meta_by_rule.get(base, {})
        matches.append({
            "checkId": base,
            "vendor": meta.get("vendor", ""), "techKey": meta.get("techKey", ""),
            "kind": meta.get("kind", ""),
            "path": m.get("file", ""),
            "line": ((m.get("range") or {}).get("start") or {}).get("line", -1) + 1,
            # the FULL matched text: a multi-line string literal carries content past
            # its start line (an XML request root often sits on line 2 of the literal)
            "text": m.get("text", "") or "",
        })
    return {"matches": matches, "scanned": [], "errors": errors}
