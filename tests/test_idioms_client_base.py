"""The `client-base` family: a client factory that stores the host.

    const api = axios.create({ baseURL: 'https://api.stripe.com' });
    api.get('/v1/charges');

The host and the path never meet in one expression, so both url-assembly rules are blind
to it — verified against the engine, they match this fixture zero times. The file DOES
carry the host as a URL literal, so a vendor is classified; what is missing is any signal
that the file assembles URLs at all, which endpoints.py requires before it will attribute
a bare path literal.

This family supplies exactly that signal and nothing more. It marks the FILE as
assembling; it does not pair `create()` with a later `.get()`, and no dataflow is claimed.
"""
import os
import shutil
import subprocess

import pytest

from agent.lib import idioms


def _literal_rule(base_id, regex, lang, metadata):
    return {"id": f"{base_id}@{lang}", "language": lang, "metadata": dict(metadata),
            "rule": {"any": [{"kind": "string", "regex": regex}]}}


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FIXTURES = os.path.join(_ROOT, "tests", "fixtures", "idioms")


def test_client_base_is_a_known_family_with_the_path_assembly_kind():
    """path-assembly is the kind endpoints.py reads to decide a file assembles URLs.
    operation-marker would be the wrong kind and would not populate assembly_files."""
    assert "client-base" in idioms.FAMILIES
    assert idioms.KIND_BY_FAMILY["client-base"] == "path-assembly"


@pytest.mark.parametrize("missing", ["pattern", "language"])
def test_client_base_requires_pattern_and_language(missing):
    inst = {"id": "x", "family": "client-base", "language": "javascript",
            "pattern": "axios.create({baseURL: $B})", "evidence": "a/b.js:1"}
    del inst[missing]
    with pytest.raises(idioms.IdiomError):
        idioms._validate(inst, "test instance")


def test_to_rules_emits_one_rule_carrying_the_instance_pattern():
    inst = {"id": "js-axios", "family": "client-base", "language": "javascript",
            "pattern": "axios.create({baseURL: $B})"}
    docs = idioms.to_rules(inst, _literal_rule, ["javascript"])
    assert len(docs) == 1
    assert docs[0]["language"] == "javascript"
    assert docs[0]["metadata"]["kind"] == "path-assembly"
    assert docs[0]["rule"]["pattern"] == "axios.create({baseURL: $B})"


def test_the_shipped_instance_and_its_evidence_line():
    by_id = {i["id"]: i for i in idioms.load_idioms()}
    inst = by_id.get("js-axios-create")
    assert inst is not None, f"js-axios-create missing; have: {sorted(by_id)}"
    assert inst["family"] == "client-base" and inst["language"] == "javascript"
    path, _, num = inst["evidence"].rpartition(":")
    full = os.path.join(_ROOT, path)
    assert os.path.isfile(full), f"evidence file missing: {path}"
    with open(full, encoding="utf-8") as fh:
        line = fh.read().splitlines()[int(num) - 1]
    assert "axios.create" in line, f"evidence line {num} is not the create call: {line!r}"


# ── Engine checks. Skipped when ast-grep is absent, as test_egress_sinks does. ──

_ENGINE = os.path.join(_ROOT, ".venv", "bin", "ast-grep")
_needs_engine = pytest.mark.skipif(not os.path.exists(_ENGINE), reason="ast-grep not built")


def _matches(pattern: str, filename: str) -> int:
    out = subprocess.run([_ENGINE, "run", "--lang", "javascript", "--pattern", pattern,
                          os.path.join(_FIXTURES, filename)],
                         capture_output=True, text=True)
    return sum(1 for l in out.stdout.splitlines() if ".js:" in l)


@_needs_engine
def test_the_existing_url_assembly_rules_are_blind_to_the_create_shape():
    """The gap this family exists for. If either of these ever matches, the family is
    redundant and should be removed rather than kept for tidiness."""
    assert _matches("$A.baseURL + $B", "js-axios-create.js") == 0
    assert _matches("`${$A.baseURL}$$$B`", "js-axios-create.js") == 0


@_needs_engine
def test_the_shipped_pattern_hits_the_create_call():
    by_id = {i["id"]: i for i in idioms.load_idioms()}
    pat = by_id["js-axios-create"]["pattern"]
    assert _matches(pat, "js-axios-create.js") >= 1


@_needs_engine
def test_the_shipped_pattern_matches_none_of_the_negative_controls():
    """Object.create, a plain config object, another library's create(), and a bare
    axios.get with no create in the file. A rule firing on any of these would mark
    unrelated files as assembling, and endpoints.py would then attribute their bare path
    literals to whatever vendor the file mentions — manufacturing attributions, which is
    worse than the gap being closed."""
    by_id = {i["id"]: i for i in idioms.load_idioms()}
    pat = by_id["js-axios-create"]["pattern"]
    assert _matches(pat, "js-axios-create-noise.js") == 0


@_needs_engine
def test_extra_option_keys_are_a_known_miss_not_a_silent_one():
    """The strict pattern does not reach `axios.create({baseURL, timeout})`. Widening to
    `axios.create($OPTS)` would reach it but drops the baseURL requirement, so a client
    created with no base would mark the file as assembling. This test pins the miss so it
    stays a documented boundary rather than an assumed capability."""
    by_id = {i["id"]: i for i in idioms.load_idioms()}
    pat = by_id["js-axios-create"]["pattern"]
    assert _matches(pat, "js-axios-create.js") == 1, (
        "if this is 2, extra-keys coverage changed — update the idiom note")
    assert "known miss" in by_id["js-axios-create"]["note"].lower()
