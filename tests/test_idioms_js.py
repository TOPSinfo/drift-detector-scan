"""JS/TS url-assembly: the concat operator is per-language.

`to_rules` emitted `{base} . $B` for every language. That is PHP. JavaScript concatenates
with `+`, so a JS instance compiled to a pattern that can never match — the family existed
for JS on paper and found nothing in practice.
"""
import os

from agent.lib import idioms


def _literal_rule(base_id, regex, lang, metadata):
    """Stand-in for vendor_rules._ast_literal_rule, so to_rules is tested in isolation."""
    return {"id": f"{base_id}@{lang}", "language": lang, "metadata": dict(metadata),
            "rule": {"any": [{"kind": "string", "regex": regex}]}}


def _pattern(docs):
    return docs[0]["rule"]["pattern"]


def test_javascript_url_assembly_compiles_to_plus_not_php_concat():
    inst = {"id": "js-baseurl", "family": "url-assembly",
            "language": "javascript", "base": "$A.baseURL"}
    docs = idioms.to_rules(inst, _literal_rule, ["javascript"])
    assert _pattern(docs) == "$A.baseURL + $B"
    assert " . $B" not in _pattern(docs), "JS compiled to the PHP concat operator"


def test_typescript_url_assembly_also_uses_plus():
    inst = {"id": "ts-baseurl", "family": "url-assembly",
            "language": "typescript", "base": "$A.baseURL"}
    docs = idioms.to_rules(inst, _literal_rule, ["typescript"])
    assert _pattern(docs) == "$A.baseURL + $B"


def test_php_url_assembly_still_compiles_to_dot_concat():
    """The existing PHP instances must be untouched — this is a per-language addition,
    not a replacement."""
    inst = {"id": "php-gethost", "family": "url-assembly",
            "language": "php", "base": "$A->getHost()"}
    docs = idioms.to_rules(inst, _literal_rule, ["php"])
    assert _pattern(docs) == "$A->getHost() . $B"


def test_a_language_with_no_known_concat_operator_emits_nothing():
    """Emitting PHP's `.` on a language that concatenates some other way would ship a rule
    that cannot match, and a rule that cannot match is indistinguishable from a repo with
    nothing to find.

    The example was python until python gained `+`; the INVARIANT is what matters, so it
    moved to go rather than being deleted with the language it happened to name."""
    assert "go" not in idioms._CONCAT_OP
    inst = {"id": "go-base", "family": "url-assembly",
            "language": "go", "base": "$A.BaseURL"}
    assert idioms.to_rules(inst, _literal_rule, ["go"]) == []


def test_the_shipped_js_instance_is_loadable_and_its_evidence_file_exists():
    """Every instance must point at real code. An idiom nobody can point at is a guess —
    so the evidence path is checked on disk, not merely present as a string."""
    by_id = {i["id"]: i for i in idioms.load_idioms()}
    inst = by_id.get("js-baseurl-concat")
    assert inst is not None, f"js-baseurl-concat missing; have: {sorted(by_id)}"
    assert inst["family"] == "url-assembly"
    assert inst["language"] in ("javascript", "typescript")
    path = inst["evidence"].split(":")[0].split(" ")[-1]
    root = os.path.dirname(os.path.dirname(os.path.abspath(idioms.__file__)))
    root = os.path.dirname(root)          # agent/lib -> agent -> repo root
    assert os.path.isfile(os.path.join(root, path)), f"evidence file missing: {path}"


def test_the_shipped_js_instance_compiles_to_a_plus_pattern():
    by_id = {i["id"]: i for i in idioms.load_idioms()}
    docs = idioms.to_rules(by_id["js-baseurl-concat"], _literal_rule, ["javascript"])
    assert docs and "+ $B" in _pattern(docs)


# ── Template literals: a different AST node, invisible to the `+` rule ──────────────

def _patterns(docs):
    return [d["rule"]["pattern"] for d in docs]


def test_javascript_url_assembly_emits_a_template_rule_as_well_as_plus():
    """`${this.baseURL}/v1/charges` is a template_string, not a binary `+` expression, so
    the concat rule cannot see it. Proven against the engine: the `+` pattern matches the
    template fixture zero times."""
    inst = {"id": "js-baseurl", "family": "url-assembly",
            "language": "javascript", "base": "$A.baseURL"}
    pats = _patterns(idioms.to_rules(inst, _literal_rule, ["javascript"]))
    assert "$A.baseURL + $B" in pats
    assert any(p.startswith("`") for p in pats), f"no template rule emitted: {pats}"
    assert "`${$A.baseURL}$$$B`" in pats


def test_typescript_gets_the_template_rule_too():
    inst = {"id": "ts-baseurl", "family": "url-assembly",
            "language": "typescript", "base": "$A.baseURL"}
    pats = _patterns(idioms.to_rules(inst, _literal_rule, ["typescript"]))
    assert "`${$A.baseURL}$$$B`" in pats


def test_php_gets_no_template_rule():
    """A backticked template pattern on PHP would be a rule that can never match — the
    same failure the per-language concat operator fixed."""
    inst = {"id": "php-gethost", "family": "url-assembly",
            "language": "php", "base": "$A->getHost()"}
    pats = _patterns(idioms.to_rules(inst, _literal_rule, ["php"]))
    assert pats == ["$A->getHost() . $B"]
    assert not any("`" in p for p in pats)


def test_the_template_rules_carry_the_same_path_assembly_kind():
    inst = {"id": "js-baseurl", "family": "url-assembly",
            "language": "javascript", "base": "$A.baseURL"}
    docs = idioms.to_rules(inst, _literal_rule, ["javascript"])
    assert {d["metadata"]["kind"] for d in docs} == {"path-assembly"}
    assert len({d["id"] for d in docs}) == len(docs), "rule ids must stay unique"


def test_one_instance_emits_both_the_plus_and_template_shapes():
    """There is deliberately ONE shipped instance for `$A.baseURL`. url-assembly emits both
    JS/TS shapes from it, so a second `js-baseurl-template` id would compile to the
    identical two patterns and buy nothing but a duplicate rule in the engine."""
    by_id = {i["id"]: i for i in idioms.load_idioms()}
    assert "js-baseurl-template" not in by_id, "the redundant second instance is back"
    inst = by_id["js-baseurl-concat"]
    pats = _patterns(idioms.to_rules(inst, _literal_rule, ["javascript"]))
    assert "$A.baseURL + $B" in pats
    assert "`${$A.baseURL}$$$B`" in pats
    assert len(pats) == len(set(pats)) == 2, f"expected exactly two distinct rules: {pats}"


def test_the_template_fixture_survives_the_instance_being_dropped():
    """The fixture is the evidence that `+` is blind to templates — the engine matches it
    zero times. Deleting it would remove the only proof that the template rule is needed
    at all, so it stays on disk even though no instance cites it as `evidence:`."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(idioms.__file__))))
    path = os.path.join(root, "tests/fixtures/idioms/js-baseurl-template.js")
    assert os.path.isfile(path), "template fixture deleted"
    with open(path, encoding="utf-8") as fh:
        line = fh.read().splitlines()[15]          # :16, 0-indexed
    assert "${" in line and "baseURL" in line and "+" not in line, (
        f"line 16 is no longer a concat-free template: {line!r}")


def test_the_surviving_instance_evidence_line_is_the_concat():
    by_id = {i["id"]: i for i in idioms.load_idioms()}
    path, _, num = by_id["js-baseurl-concat"]["evidence"].rpartition(":")
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(idioms.__file__))))
    with open(os.path.join(root, path), encoding="utf-8") as fh:
        line = fh.read().splitlines()[int(num) - 1]
    assert "baseURL +" in line, f"evidence line {num} is not the + concat: {line!r}"
