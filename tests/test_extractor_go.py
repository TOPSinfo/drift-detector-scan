import pytest
from agent.lib.extractors import go, extractor_for

# Covers every shape the order names: block require, single-line require,
# `// indirect` (skipped, same idea as npm devDependencies), and the go directive.
GOMOD = '''module github.com/acme/shop

go 1.22

require (
	github.com/stripe/stripe-go/v76 v76.25.0
	github.com/aws/aws-sdk-go v1.50.0
	golang.org/x/text v0.14.0 // indirect
)

require github.com/redis/go-redis/v9 v9.5.1
'''


def test_go_extracts_direct_requires_and_runtime():
    recs = go.extract("clients/a", "go.mod", GOMOD)
    by_key = {r.tech_key: r for r in recs}
    assert "lib:go/github.com/stripe/stripe-go/v76" in by_key
    assert "lib:go/github.com/aws/aws-sdk-go" in by_key
    assert "lib:go/github.com/redis/go-redis/v9" in by_key   # single-line require form
    assert by_key["lib:go/github.com/stripe/stripe-go/v76"].declared_range == "v76.25.0"
    assert by_key["lib:go/github.com/stripe/stripe-go/v76"].ecosystem == "go"
    assert by_key["lib:go/github.com/stripe/stripe-go/v76"].kind == "library"
    rt = by_key["runtime:go"]
    assert rt.kind == "runtime" and rt.version_hint == "1.22"


def test_go_skips_indirect_requires():
    """`// indirect` is the transitive set the module graph pulled in, not what this repo
    declares — the same reason npm devDependencies are excluded. Auditing them would
    attribute another module's choices to this repo."""
    by_key = {r.tech_key for r in go.extract("clients/a", "go.mod", GOMOD)}
    assert "lib:go/golang.org/x/text" not in by_key


def test_go_module_with_no_requires_yields_only_the_runtime():
    recs = go.extract("clients/a", "go.mod", "module github.com/acme/x\n\ngo 1.21\n")
    assert [r.tech_key for r in recs] == ["runtime:go"]


def test_go_bare_module_line_returns_empty():
    assert go.extract("clients/a", "go.mod", "module github.com/acme/x\n") == []


def test_go_registered():
    assert extractor_for("a/go.mod") is go.extract


def test_go_wires_into_osv_and_purl():
    """A Go repo's Supply Chain plane was silently empty: no extractor, and `go` absent
    from OSV_ECOSYSTEM, so even an extracted record could not be audited."""
    from agent.lib.purl import osv_ecosystem, to_purl
    assert osv_ecosystem("go") == "Go"
    assert to_purl("go", "github.com/aws/aws-sdk-go", "v1.50.0") == \
        "pkg:golang/github.com/aws/aws-sdk-go@v1.50.0"
