import os
import sys
import shutil
import pytest

from agent.lib.vendors import Vendor
from agent.lib.vendor_rules import write_ruleset
from agent.lib.engine import run_scan
from agent.lib.endpoints import build_endpoints


def _find_engine():
    from agent.lib.scan_util import resolve_engine
    try:
        return resolve_engine()          # prefers ast-grep, falls back to opengrep/semgrep
    except RuntimeError:
        return None


_ENGINE = _find_engine()


@pytest.mark.skipif(_ENGINE is None, reason="no scan engine installed")
def test_live_endpoint_extraction_skips_comments(tmp_path):
    (tmp_path / "pay.php").write_text(
        '<?php\n'
        '// legacy: https://api.stripe.com/v9/dead\n'         # comment -> MUST be skipped
        '$u = "https://api.stripe.com/v1/charges";\n')
    (tmp_path / "app.js").write_text(
        'const u = "https://sellingpartnerapi-na.amazon.com/orders/v0/orders";\n')

    vendors = [Vendor("Stripe", "api:stripe", ("api.stripe.com",),
                      r'/(v\d+)'),
               Vendor("Amazon SP-API", "api:amazon-sp-api", ("sellingpartnerapi",),
                      r'/(v[0-9][0-9.]*|[0-9]{4}-[0-9]{2}-[0-9]{2})')]
    rules = tmp_path / "rules.yaml"
    write_ruleset(vendors, str(rules))

    res = run_scan(str(tmp_path), str(rules), engine=_ENGINE)
    eps = build_endpoints(res["matches"], str(tmp_path), vendors)

    by_key = {e["techKey"]: e for e in eps}
    assert by_key["api:stripe"]["version"] == "v1"          # the live code line, NOT the comment's v9
    assert all("v9" not in (e.get("version") or "") for e in eps)   # comment endpoint skipped
    assert by_key["api:amazon-sp-api"]["version"] == "v0"


def test_astgrep_output_is_normalized_to_the_match_shape(tmp_path):
    """ast-grep reports 0-indexed lines and no metadata; both must be recovered."""
    import json, yaml
    from agent.lib.engine import run_scan
    rules = tmp_path / "r.yaml"
    rules.write_text(yaml.safe_dump({"id": "stripe-endpoint@php", "language": "php",
                                     "metadata": {"vendor": "Stripe", "techKey": "api:stripe",
                                                  "kind": "endpoint"},
                                     "rule": {"kind": "string", "regex": "stripe"}}))
    canned = json.dumps([{"ruleId": "stripe-endpoint@php", "file": "a.php",
                          "range": {"start": {"line": 41}}}])          # 0-indexed
    out = run_scan("/repo", str(rules), engine="/venv/bin/ast-grep", run=lambda a: canned)
    m = out["matches"][0]
    assert m["line"] == 42                                             # -> 1-indexed
    assert m["checkId"] == "stripe-endpoint"                           # @lang stripped
    assert m["vendor"] == "Stripe" and m["techKey"] == "api:stripe" and m["kind"] == "endpoint"
