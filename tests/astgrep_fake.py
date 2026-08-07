"""Canned ast-grep output for tests that inject the engine.

ast-grep differs from semgrep in two ways this helper encodes so tests exercise
the real normalization: results are a bare LIST (not {"results": [...]}), and
`range.start.line` is 0-INDEXED. Rule metadata is not echoed by ast-grep at all —
run_scan recovers it from the rule file — so tests that care about kind/vendor
must write a real ruleset via write_ruleset().
"""
import json


def hit(rule_id: str, path: str, line: int, lang: str = "php") -> dict:
    """One ast-grep match. `line` is the human 1-indexed line; we emit 0-indexed."""
    return {"ruleId": f"{rule_id}@{lang}", "file": path,
            "range": {"start": {"line": line - 1}, "end": {"line": line - 1}}}


def canned(*hits) -> str:
    return json.dumps(list(hits))


EMPTY = json.dumps([])
