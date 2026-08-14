"""The Python client-base instance: `httpx.Client(base_url=...)`.

Same shape as js-axios-create, different language: the host goes to a client factory once
and later calls pass only a path. No new family — client-base already does this job.

One instance covers both factories. That was decided from engine output, not preference:
`httpx.$M(base_url=$B)` matches Client AND AsyncClient (2 hits) and matches zero of the
negative controls, because requiring the `base_url=` keyword is what excludes
`httpx.get(...)` and a bare `httpx.Client()`.
"""
import os
import subprocess

import pytest

from agent.lib import idioms


def _literal_rule(base_id, regex, lang, metadata):
    return {"id": f"{base_id}@{lang}", "language": lang, "metadata": dict(metadata),
            "rule": {"any": [{"kind": "string", "regex": regex}]}}


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FIXTURES = os.path.join(_ROOT, "tests", "fixtures", "idioms")
_ENGINE = os.path.join(_ROOT, ".venv", "bin", "ast-grep")
_needs_engine = pytest.mark.skipif(not os.path.exists(_ENGINE), reason="ast-grep not built")


def _matches(pattern: str, filename: str) -> int:
    out = subprocess.run([_ENGINE, "run", "--lang", "python", "--pattern", pattern,
                          os.path.join(_FIXTURES, filename)],
                         capture_output=True, text=True)
    return sum(1 for l in out.stdout.splitlines() if ".py:" in l)


def _inst():
    return {i["id"]: i for i in idioms.load_idioms()}.get("py-httpx-client")


def test_the_shipped_instance_is_loadable_with_its_evidence_line():
    inst = _inst()
    assert inst is not None, "py-httpx-client missing"
    assert inst["family"] == "client-base" and inst["language"] == "python"
    path, _, num = inst["evidence"].rpartition(":")
    full = os.path.join(_ROOT, path)
    assert os.path.isfile(full), f"evidence file missing: {path}"
    with open(full, encoding="utf-8") as fh:
        line = fh.read().splitlines()[int(num) - 1]
    assert "httpx.Client(" in line, f"evidence line {num} is not the Client call: {line!r}"


def test_to_rules_emits_one_python_path_assembly_rule():
    """`language` is required for client-base, and the pattern is emitted verbatim — so
    Python needs no to_rules change and no entry in _CONCAT_OP."""
    docs = idioms.to_rules(_inst(), _literal_rule, ["python"])
    assert len(docs) == 1
    assert docs[0]["language"] == "python"
    assert docs[0]["metadata"]["kind"] == "path-assembly"
    assert docs[0]["rule"]["pattern"] == _inst()["pattern"]


@_needs_engine
def test_no_concat_rule_reaches_the_httpx_shape():
    """The gap this instance exists for, and it survives python gaining `+`: the httpx
    fixture contains no concatenation at all, so the python url-assembly rule matches it
    zero times. The two families cover genuinely different shapes rather than overlapping."""
    assert _matches("$A.baseURL + $B", "py-httpx-client.py") == 0
    assert _matches("$A.base_url + $B", "py-httpx-client.py") == 0


@_needs_engine
def test_the_shipped_pattern_covers_both_client_and_async_client():
    assert _matches(_inst()["pattern"], "py-httpx-client.py") == 2, (
        "expected Client and AsyncClient; if this changed, the one-instance decision "
        "needs re-deriving from the engine")


@_needs_engine
def test_the_shipped_pattern_matches_none_of_the_negative_controls():
    """requests.Session (no base_url at all), module-level httpx.get, a local class named
    Client, and httpx.Client() with no base_url. Matching any of these would mark an
    unrelated file as assembling and manufacture attributions for its bare paths."""
    assert _matches(_inst()["pattern"], "py-httpx-client-noise.py") == 0


@_needs_engine
def test_extra_kwargs_are_a_known_miss_not_a_silent_one():
    """`httpx.Client(base_url=..., timeout=10.0)` is not reached. Widening to
    `httpx.$M($$$)` would reach it but drops the base_url requirement, so a client holding
    no host would mark its file as assembling. Same ruling as the axios instance."""
    assert _matches(_inst()["pattern"], "py-httpx-client.py") == 2, (
        "if this is 3, extra-kwargs coverage changed — update the idiom note"
    )
    assert "known miss" in _inst()["note"].lower()


def test_the_httpx_instance_is_client_base_not_url_assembly():
    """This guarded that the httpx order did not sneak Python concat in. Python concat
    later shipped deliberately as its own change, so the assertion is now about the
    SEPARATION rather than about python's absence: httpx is a client factory, not a
    concatenation, and must stay in client-base. Folding it into url-assembly would make it
    compile to `$A.base_url + $B` and stop matching the factory call entirely."""
    inst = _inst()
    assert inst["family"] == "client-base"
    assert "base" not in inst, "client-base carries `pattern`, not url-assembly's `base`"
    assert "create" not in inst["pattern"] and "+" not in inst["pattern"]


def test_the_httpx_pattern_reaches_the_compiled_ruleset():
    from agent.lib.vendor_rules import build_astgrep_ruleset
    asm = [d for d in build_astgrep_ruleset(vendors=[])
           if (d.get("metadata") or {}).get("kind") == "path-assembly"]
    pats = [d["rule"]["pattern"] for d in asm]
    assert _inst()["pattern"] in pats, f"httpx rule never compiled: {pats}"
    assert any(d["language"] == "python" for d in asm)
