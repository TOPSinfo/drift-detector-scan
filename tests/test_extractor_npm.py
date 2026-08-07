import pytest
from agent.lib.extractors import npm, extractor_for

PKG = '''{
  "name": "shop", "engines": {"node": ">=18"},
  "dependencies": {"aws-sdk": "^2.1500.0", "stripe": "12.0.0"},
  "devDependencies": {"jest": "^29.0.0"}
}'''

def test_npm_extracts_production_deps_and_runtime():
    recs = npm.extract("clients/a", "package.json", PKG)
    by_key = {r.tech_key: r for r in recs}
    assert "lib:npm/aws-sdk" in by_key and "lib:npm/stripe" in by_key
    assert "lib:npm/jest" not in by_key                 # devDependencies excluded
    assert by_key["lib:npm/aws-sdk"].declared_range == "^2.1500.0"
    assert by_key["lib:npm/aws-sdk"].parse_quality == "unlocked"    # has ^
    assert by_key["lib:npm/stripe"].parse_quality == "exact"        # pinned
    rt = by_key["runtime:node"]
    assert rt.kind == "runtime" and rt.version_hint == ">=18"

def test_npm_no_deps_returns_empty():
    assert npm.extract("clients/a", "package.json", '{"name":"x"}') == []

def test_npm_invalid_json_raises_valueerror():
    with pytest.raises(ValueError):
        npm.extract("clients/a", "package.json", "{ not json")

def test_npm_registered():
    assert extractor_for("a/package.json") is npm.extract
