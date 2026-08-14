"""Python url-assembly: the same `+` change JS got, one language later.

A Python url-assembly instance used to compile to NOTHING — `_CONCAT_OP` knew php,
javascript and typescript only, and `to_rules` skips a language it has no operator for.
Emitting nothing is indistinguishable from a repo with nothing to find, which is the
failure mode this project exists to refuse.

f-strings ARE covered, by a second rule from the same instance — the JS template change,
one language later. Python stays out of `_TEMPLATE_LANGS` regardless: that tuple means
"emit a JS backtick template", which on Python could never match. It has its own branch.

Still missed, deliberately: f'...' (single quotes), rf"..."/F"..." prefixes, and
triple-quoted f-strings. Four more patterns to chase quote styles is not worth it.
"""
import os
import subprocess

import pytest

from agent.lib import idioms


def _literal_rule(base_id, regex, lang, metadata):
    return {"id": f"{base_id}@{lang}", "language": lang, "metadata": dict(metadata),
            "rule": {"any": [{"kind": "string", "regex": regex}]}}


def _patterns(docs):
    return [d["rule"]["pattern"] for d in docs]


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FIXTURES = os.path.join(_ROOT, "tests", "fixtures", "idioms")
_ENGINE = os.path.join(_ROOT, ".venv", "bin", "ast-grep")
_needs_engine = pytest.mark.skipif(not os.path.exists(_ENGINE), reason="ast-grep not built")


def _matches(pattern: str, filename: str) -> int:
    out = subprocess.run([_ENGINE, "run", "--lang", "python", "--pattern", pattern,
                          os.path.join(_FIXTURES, filename)],
                         capture_output=True, text=True)
    return sum(1 for l in out.stdout.splitlines() if ".py:" in l)


def test_python_url_assembly_compiles_to_plus():
    inst = {"id": "py-base", "family": "url-assembly",
            "language": "python", "base": "$A.base_url"}
    pats = _patterns(idioms.to_rules(inst, _literal_rule, ["python"]))
    assert "$A.base_url + $B" in pats
    assert not any(" . $B" in p for p in pats), "python compiled to the PHP concat operator"


def test_php_still_compiles_to_dot_concat():
    inst = {"id": "php-gethost", "family": "url-assembly",
            "language": "php", "base": "$A->getHost()"}
    assert _patterns(idioms.to_rules(inst, _literal_rule, ["php"])) == ["$A->getHost() . $B"]


def test_a_language_still_absent_from_the_operator_map_emits_nothing():
    """The invariant survives the language moving: go has no known concat spelling, so it
    emits no rule at all rather than a PHP `.` that could never match."""
    assert "go" not in idioms._CONCAT_OP
    inst = {"id": "go-base", "family": "url-assembly",
            "language": "go", "base": "$A.BaseURL"}
    assert idioms.to_rules(inst, _literal_rule, ["go"]) == []


def test_python_gets_an_fstring_rule_and_never_a_backtick_one():
    """Python gets a SECOND rule, but it is an f-string — not the JS backtick template.
    Copying `` `${base}$$$B` `` onto Python would ship a rule that can never match, which is
    why python stays out of _TEMPLATE_LANGS even though it now has two rules."""
    assert "python" not in idioms._TEMPLATE_LANGS
    inst = {"id": "py-base", "family": "url-assembly",
            "language": "python", "base": "$A.base_url"}
    pats = _patterns(idioms.to_rules(inst, _literal_rule, ["python"]))
    assert not any("`" in p for p in pats), "JS backtick template copied onto python"
    assert 'f"{$A.base_url}$$$B"' in pats


def test_python_url_assembly_emits_both_shapes_with_unique_ids():
    inst = {"id": "py-base", "family": "url-assembly",
            "language": "python", "base": "$A.base_url"}
    docs = idioms.to_rules(inst, _literal_rule, ["python"])
    assert _patterns(docs) == ["$A.base_url + $B", 'f"{$A.base_url}$$$B"']
    assert len({d["id"] for d in docs}) == len(docs) == 2
    assert {d["metadata"]["kind"] for d in docs} == {"path-assembly"}


def test_php_gets_neither_an_fstring_nor_a_backtick_rule():
    inst = {"id": "php-gethost", "family": "url-assembly",
            "language": "php", "base": "$A->getHost()"}
    pats = _patterns(idioms.to_rules(inst, _literal_rule, ["php"]))
    assert pats == ["$A->getHost() . $B"]
    assert not any("`" in p or p.startswith("f\"") for p in pats)


def test_the_shipped_instance_and_its_evidence_line():
    by_id = {i["id"]: i for i in idioms.load_idioms()}
    inst = by_id.get("py-base-url-concat")
    assert inst is not None, f"py-base-url-concat missing; have: {sorted(by_id)}"
    assert inst["family"] == "url-assembly" and inst["language"] == "python"
    path, _, num = inst["evidence"].rpartition(":")
    full = os.path.join(_ROOT, path)
    assert os.path.isfile(full), f"evidence file missing: {path}"
    with open(full, encoding="utf-8") as fh:
        line = fh.read().splitlines()[int(num) - 1]
    assert "base_url +" in line, f"evidence line {num} is not the concat: {line!r}"


@_needs_engine
def test_the_shipped_pattern_hits_the_concat_fixture():
    by_id = {i["id"]: i for i in idioms.load_idioms()}
    pat = _patterns(idioms.to_rules(by_id["py-base-url-concat"], _literal_rule, ["python"]))[0]
    assert _matches(pat, "py-base-url-concat.py") == 1


@_needs_engine
def test_the_shipped_pattern_matches_none_of_the_negative_controls():
    """`"hello " + name`, `self.api_key + suffix`, an f-string, and an httpx client already
    covered by another family. Widening to `$A + $B` would catch every concatenation in the
    repo and mark unrelated files as assembling."""
    by_id = {i["id"]: i for i in idioms.load_idioms()}
    pat = _patterns(idioms.to_rules(by_id["py-base-url-concat"], _literal_rule, ["python"]))[0]
    assert _matches(pat, "py-base-url-concat-noise.py") == 0


@_needs_engine
def test_concat_is_blind_to_f_strings_which_is_why_the_second_rule_exists():
    """The gap the f-string rule closes. If `+` ever matches this fixture, the second rule
    is redundant and should be removed rather than kept for tidiness."""
    by_id = {i["id"]: i for i in idioms.load_idioms()}
    pats = _patterns(idioms.to_rules(by_id["py-base-url-concat"], _literal_rule, ["python"]))
    assert _matches(pats[0], "py-base-url-fstring.py") == 0


@_needs_engine
def test_the_fstring_rule_covers_both_interpolation_shapes():
    """2 = `f"{base}/v1/charges"` and `f"{base}/v1/refunds/{id}"`. The single-`$B` form
    matched only the first, which is why the pattern uses `$$$B`."""
    by_id = {i["id"]: i for i in idioms.load_idioms()}
    pats = _patterns(idioms.to_rules(by_id["py-base-url-concat"], _literal_rule, ["python"]))
    assert _matches(pats[1], "py-base-url-fstring.py") == 2


@_needs_engine
def test_the_fstring_rule_matches_none_of_the_negative_controls():
    """`f"hello {name}"`, `f"{count} items"`, `f"{self.api_key}/v1/x"`, and an httpx client
    covered by another family. Widening to `f"$A"` would catch every f-string in the repo."""
    by_id = {i["id"]: i for i in idioms.load_idioms()}
    pats = _patterns(idioms.to_rules(by_id["py-base-url-concat"], _literal_rule, ["python"]))
    assert _matches(pats[1], "py-base-url-fstring-noise.py") == 0
    assert _matches(pats[1], "py-base-url-concat.py") == 0


@_needs_engine
def test_the_fstring_fixture_survives_without_being_cited_as_evidence():
    """No instance names this file in `evidence:` — it is the only proof the second rule is
    needed, so a `+` creeping into it would silently destroy that proof."""
    path = os.path.join(_FIXTURES, "py-base-url-fstring.py")
    assert os.path.isfile(path)
    with open(path, encoding="utf-8") as fh:
        body = fh.read()
    assert "base_url + " not in body, "the f-string fixture is no longer concat-free"


def test_python_is_in_the_operator_map_but_not_the_template_map():
    """_TEMPLATE_LANGS means "emit a JS backtick template". Python's second rule is an
    f-string emitted by its own branch, so python having two rules must NOT be spelled by
    joining that tuple."""
    assert idioms._CONCAT_OP["python"] == "+"
    assert "python" not in idioms._TEMPLATE_LANGS
    inst = {"id": "py-base", "family": "url-assembly",
            "language": "python", "base": "$A.base_url"}
    assert 'f"{$A.base_url}$$$B"' in _patterns(idioms.to_rules(inst, _literal_rule, ["python"]))
