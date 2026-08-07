import yaml

from agent.lib.vendor_rules import build_astgrep_ruleset, write_ruleset, DEFAULT_LANGUAGES
from agent.lib.vendors import Vendor

_VS = [Vendor("Stripe", "api:stripe", ("stripe.com",), r"/(v\d+)"),
       Vendor("Mailgun", "api:mailgun", ("mailgun.net", "mailgun.com"), r"/(v\d+)")]


def _by_kind(docs):
    """kind -> the PHP rule of that kind (one rule per language, PHP is the reference)."""
    return {d["metadata"]["kind"]: d for d in docs
            if d["id"].endswith("@php") and "kind" in (d.get("metadata") or {})}


def test_ruleset_has_path_literal_sink_and_assembly_rules():
    kinds = _by_kind(build_astgrep_ruleset(vendors=[]))
    # path-literal: string-literal regex matching a version segment
    pl = kinds["path-literal"]
    rx = " ".join(c["regex"] for c in pl["rule"]["any"])
    assert "v[0-9]" in rx and "[0-9]{4}-[0-9]{2}-[0-9]{2}" in rx
    # sink: PHP-only, curl_exec + CURLOPT_URL + Guzzle client
    sk = kinds["sink"]
    assert sk["language"] == "php"
    pats = " ".join(p["pattern"] for p in sk["rule"]["any"])
    assert "curl_exec" in pats and "CURLOPT_URL" in pats and "GuzzleHttp\\Client" in pats
    # path-assembly: one rule per url-assembly idiom instance (not a single hardcoded one)
    docs = build_astgrep_ruleset(vendors=[])
    asm = [d for d in docs if (d.get("metadata") or {}).get("kind") == "path-assembly"]
    # url-assembly compiles to `base . $B`; url-append to `$target .= $B`
    assert asm and all(d["rule"]["pattern"].endswith(("$B",)) for d in asm)
    pats = " ".join(d["rule"]["pattern"] for d in asm)
    assert "getHost()" in pats and "serviceUrl" in pats
    assert ".= $B" in pats          # the assemble-then-append shape


def test_ruleset_has_broad_url_rule_plus_one_per_vendor_per_language():
    docs = build_astgrep_ruleset(_VS)
    langs = [d for d in docs if d["id"].startswith("url-literal@")]
    assert len(langs) == len(DEFAULT_LANGUAGES)          # one url rule per language
    mg = next(d for d in docs if d["id"] == "mailgun-endpoint@php")
    assert mg["metadata"] == {"vendor": "Mailgun", "techKey": "api:mailgun", "kind": "endpoint"}
    assert "mailgun\\.net|mailgun\\.com" in mg["rule"]["any"][0]["regex"]   # both domains, escaped
    # every vendor gets a rule in every language
    for v in _VS:
        slug = v.vendor.lower()
        assert sum(1 for d in docs if d["id"].startswith(f"{slug}-endpoint@")) == len(DEFAULT_LANGUAGES)


def test_ruleset_without_vendors_is_just_the_shape_rules():
    bases = {d["id"].split("@")[0] for d in build_astgrep_ruleset()}
    # the shape rules, plus whatever idiom instances agent/idioms.yaml declares
    assert {"url-literal", "path-literal", "php-http-sink"} <= bases
    from agent.lib import idioms
    assert {i["id"] for i in idioms.load_idioms()} <= bases


def test_write_ruleset_is_valid_multidoc_yaml(tmp_path):
    p = tmp_path / "rules.yaml"
    write_ruleset(_VS, str(p))
    docs = [d for d in yaml.safe_load_all(p.read_text()) if d]
    assert docs and all("language" in d and "rule" in d and "id" in d for d in docs)
    assert any(d["id"] == "stripe-endpoint@php" for d in docs)


# --- ast-grep dialect ---------------------------------------------------------

def test_astgrep_ruleset_uses_verified_string_kinds_per_language():
    from agent.lib.vendor_rules import build_astgrep_ruleset, AST_STRING_KINDS
    docs = build_astgrep_ruleset(vendors=[])
    by_id = {d["id"]: d for d in docs}
    # PHP double-quoted strings are `encapsed_string`; missing it silently loses call-sites
    php = by_id["url-literal@php"]
    kinds = [c["kind"] for c in php["rule"]["any"]]
    assert kinds == AST_STRING_KINDS["php"] == ["string", "encapsed_string", "heredoc"]
    # Go has no bare `string` kind at all
    assert AST_STRING_KINDS["go"] == ["interpreted_string_literal", "raw_string_literal"]
    # inner-content kinds must NOT appear anywhere (they double-count)
    all_kinds = {c.get("kind") for d in docs for c in d["rule"].get("any", []) if "kind" in c}
    assert not (all_kinds & {"string_fragment", "string_content", "heredoc_body"})


def test_astgrep_rule_ids_carry_language_and_metadata():
    from agent.lib.vendor_rules import build_astgrep_ruleset
    from agent.lib.vendors import Vendor
    v = Vendor("Stripe", "api:stripe", ("stripe.com",), r"/(v[0-9]+)")
    docs = build_astgrep_ruleset([v], languages=["php"])
    ids = {d["id"] for d in docs}
    assert "stripe-endpoint@php" in ids
    assert any(d["id"].startswith("php-gethost-method@") for d in docs)   # from idioms.yaml
    sd = next(d for d in docs if d["id"] == "stripe-endpoint@php")
    assert sd["metadata"] == {"vendor": "Stripe", "techKey": "api:stripe", "kind": "endpoint"}


def test_domainless_vendor_gets_no_endpoint_rule():
    """A vendor with no domains (self-hosted, e.g. Magento — identified by a path-constant
    idiom, not a host) must NOT get an endpoint rule: `"|".join([])` is the empty regex, which
    matches EVERY string literal and would attribute the whole codebase to that vendor."""
    from agent.lib.vendors import Vendor
    docs = build_astgrep_ruleset([Vendor("Magento", "api:magento", (), "")])
    assert not [d for d in docs if d["id"].startswith("magento-endpoint@")]
    # a domained vendor is unaffected
    docs2 = build_astgrep_ruleset([Vendor("Stripe", "api:stripe", ("stripe.com",), r"/(v\d+)")])
    assert [d for d in docs2 if d["id"].startswith("stripe-endpoint@")]
