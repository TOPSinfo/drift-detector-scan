"""Python url-assembly: the same `+` change JS got, one language later.

A Python url-assembly instance used to compile to NOTHING — `_CONCAT_OP` knew php,
javascript and typescript only, and `to_rules` skips a language it has no operator for.
Emitting nothing is indistinguishable from a repo with nothing to find, which is the
failure mode this project exists to refuse.

f-strings are NOT covered. `f"{self.base_url}/v1/x"` is a different AST node and Python is
deliberately absent from `_TEMPLATE_LANGS` — the JS template pattern is backtick syntax,
not an f-string. That miss is pinned below, not papered over.
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
    assert pats == ["$A.base_url + $B"]
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


def test_python_gets_no_template_rule():
    """A backticked JS template pattern on Python would be a rule that can never match. An
    f-string is a different node and would need its own pattern, which this order does not
    ship."""
    assert "python" not in idioms._TEMPLATE_LANGS
    inst = {"id": "py-base", "family": "url-assembly",
            "language": "python", "base": "$A.base_url"}
    pats = _patterns(idioms.to_rules(inst, _literal_rule, ["python"]))
    assert not any("`" in p for p in pats)


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
def test_f_strings_are_a_known_miss_not_a_silent_one():
    """The noise file contains `f"{self.base_url}/v1/charges"` and the concat rule matches
    it zero times. Recorded here so the boundary is a documented fact rather than an
    assumed capability."""
    by_id = {i["id"]: i for i in idioms.load_idioms()}
    inst = by_id["py-base-url-concat"]
    pat = _patterns(idioms.to_rules(inst, _literal_rule, ["python"]))[0]
    assert _matches(pat, "py-base-url-concat-noise.py") == 0
    assert "known miss" in inst["note"].lower()


def test_python_is_in_the_operator_map_but_not_the_template_map():
    assert idioms._CONCAT_OP["python"] == "+"
    assert "python" not in idioms._TEMPLATE_LANGS
