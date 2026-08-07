"""Family-level unit tests for agent/lib/idioms.py — the closed set of teachable shapes.

The `path-constant` family is the config-injected-wrapper case: a repo whose host is injected
at runtime (no URL literal to classify) but whose operations are path constants
(`protected $API_URL = "/api/orders"`). Unlike the url-* families it is repo-scoped and
vendor-bound, because there is no host literal from which to infer the repo's sole vendor.
"""
import pytest

from agent.lib import idioms


def _literal_rule(base_id, regex, lang, metadata):
    """Stand-in for vendor_rules._ast_literal_rule, so to_rules is tested in isolation."""
    return {"id": f"{base_id}@{lang}", "language": lang, "metadata": dict(metadata),
            "rule": {"any": [{"kind": "string", "regex": regex}]}}


def test_path_constant_is_a_known_family():
    assert "path-constant" in idioms.FAMILIES
    assert idioms.KIND_BY_FAMILY["path-constant"] == "path-constant"


def test_to_rules_compiles_path_constant_to_a_vendor_bound_literal_rule():
    inst = {"id": "catch-api-paths", "family": "path-constant",
            "repo": "example-org/catchapi", "vendor": "Catch", "pathRegex": r"^/api/",
            "evidence": "src/CatchApi/GetOrders.php:9"}
    docs = idioms.to_rules(inst, _literal_rule, ["php", "js"])
    assert [d["id"] for d in docs] == ["catch-api-paths@php", "catch-api-paths@js"]
    php = docs[0]
    # the rule matches the instance's path regex, and carries the bound vendor + kind so the
    # engine hands endpoints.py a match that already knows which vendor to attribute to
    assert php["metadata"] == {"kind": "path-constant", "vendor": "Catch"}
    # the leading ^ is stripped for the ast-grep rule: the node text is quote-prefixed
    # ("/api/orders"), so ^ would anchor before the quote. endpoints.py re-anchors on the
    # unquoted content, so the instance's `^/api/` semantics are preserved.
    assert php["rule"]["any"][0]["regex"] == r"/api/"


def test_validate_requires_repo_vendor_and_pathregex():
    base = {"id": "x", "family": "path-constant", "evidence": "a.php:1"}
    for missing in ("repo", "vendor", "pathRegex"):
        inst = {**base, "repo": "r", "vendor": "V", "pathRegex": "^/a"}
        del inst[missing]
        with pytest.raises(idioms.IdiomError, match=missing):
            idioms._validate(inst, "test")
    # a complete one validates clean
    idioms._validate({**base, "repo": "r", "vendor": "V", "pathRegex": "^/a"}, "test")
