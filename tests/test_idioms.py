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


# ── corroboration: the guard that lets a path-constant ship unbound from one repo ──
# A shipped family cannot be repo-scoped, but a generic /orders/v1 is not evidence of any
# vendor. Corroboration is the substitute: N DISTINCT path families must co-occur. Calibrated
# against 42 corpus repos — 10 genuine SP-API SDKs showed 9-16 families, the other 32 showed 0.

_CORR_INST = {"id": "spapi-operation-paths", "family": "path-constant",
              "vendor": "Amazon SP-API", "corroboration": 3,
              "families": ["catalog", "fba", "orders"],
              "pathRegex": r"^/(catalog|fba|orders)/",
              "evidence": "amzapi/selling-partner-api-sdk reports/api.gen.go:492"}


def test_validate_accepts_corroboration_instead_of_repo():
    idioms._validate(dict(_CORR_INST), "test")


def test_validate_rejects_path_constant_with_neither_repo_nor_corroboration():
    # THE BUG THIS GUARDS: an unguarded generic path family would attribute every repo's
    # /orders/ to whatever vendor the instance names. It must be impossible to author.
    inst = dict(_CORR_INST)
    del inst["corroboration"]
    del inst["families"]
    with pytest.raises(idioms.IdiomError, match="exactly one of"):
        idioms._validate(inst, "test")


def test_validate_rejects_path_constant_with_both_repo_and_corroboration():
    # Two guards on one instance means the weaker one is dead weight nobody reviews.
    inst = dict(_CORR_INST, repo="amzapi/selling-partner-api-sdk")
    with pytest.raises(idioms.IdiomError, match="exactly one of"):
        idioms._validate(inst, "test")


def test_validate_rejects_families_that_disagree_with_the_pathregex():
    # families: and pathRegex state the same set twice. Two sources of truth that CAN
    # disagree are a drift hazard; validation makes disagreement impossible.
    inst = dict(_CORR_INST, families=["catalog", "fba", "reports"])   # reports not in regex
    with pytest.raises(idioms.IdiomError, match="families"):
        idioms._validate(inst, "test")


def test_validate_rejects_a_corroboration_below_two():
    # corroboration: 1 is not corroboration — it is a single generic path, i.e. no guard.
    inst = dict(_CORR_INST, corroboration=1)
    with pytest.raises(idioms.IdiomError, match="corroboration"):
        idioms._validate(inst, "test")


def test_validate_rejects_a_corroborated_regex_without_an_alternation():
    inst = dict(_CORR_INST, pathRegex=r"^/catalog/", families=["catalog"])
    with pytest.raises(idioms.IdiomError, match="alternation"):
        idioms._validate(inst, "test")


def test_validate_rejects_a_corroborated_regex_missing_the_leading_anchor():
    # THE BUG THIS GUARDS: endpoints.py counts distinct families by reading path segment 0
    # (`path.split("/")[1]`) — it does NOT re-run pathRegex. That counting is only correct
    # if the alternation IS segment 0 by construction, which requires the regex to be
    # anchored at the start (`^/(a|b|c)/`). An unanchored `/(catalog|fba|orders)/` still
    # matches (mid-path), so validation used to accept it — but then the two mechanisms
    # disagree at scan time, in both directions:
    #   permissive: /v1/orders/x, /v2/orders/x, /api/orders/x all match the unanchored
    #   alternation on ONE family (orders), but segment-0 counts {v1, v2, api} = 3 distinct
    #   segments — clearing a corroboration threshold of 3 on the evidence of one family.
    #   restrictive: /api/orders/x, /api/catalog/y, /api/fba/z are three genuine families,
    #   but segment-0 reads `api` for all three = 1 distinct segment — a real corroborated
    #   vendor is silently refused.
    # Requiring the anchor makes segment 0 the alternation by construction, so the counter
    # in endpoints.py is provably correct instead of coincidentally correct.
    inst = dict(_CORR_INST, pathRegex=r"/(catalog|fba|orders)/")
    with pytest.raises(idioms.IdiomError, match="alternation"):
        idioms._validate(inst, "test")


def test_corroborated_instance_compiles_for_every_language():
    # No `language:` field -> to_rules falls back to the full language list. This is what
    # makes one shipped instance serve all eight languages.
    langs = ["php", "javascript", "typescript", "python", "ruby", "go", "java", "csharp"]
    docs = idioms.to_rules(dict(_CORR_INST), _literal_rule, langs)
    assert [d["language"] for d in docs] == langs
    assert all(d["metadata"] == {"kind": "path-constant", "vendor": "Amazon SP-API"}
               for d in docs)
