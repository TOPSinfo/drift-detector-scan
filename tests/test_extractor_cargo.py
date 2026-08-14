import pytest
from agent.lib.extractors import cargo, extractor_for

# Cargo.lock v3. The workspace member is the package with NO `source` — that is how a
# lockfile distinguishes "this repo's own crate" from "something fetched from crates.io".
LOCK = '''version = 3

[[package]]
name = "shop"
version = "0.1.0"
dependencies = [
 "rand",
 "serde",
]

[[package]]
name = "serde"
version = "1.0.210"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "aaaa"
dependencies = [
 "serde_derive",
]

[[package]]
name = "rand"
version = "0.8.5"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "bbbb"
dependencies = [
 "getrandom",
]

[[package]]
name = "getrandom"
version = "0.2.10"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "cccc"
'''


def test_cargo_registered():
    assert extractor_for("a/Cargo.lock") is cargo.extract


def test_cargo_extracts_direct_crates_with_resolved_versions():
    by_name = {r.name: r for r in cargo.extract("clients/a", "Cargo.lock", LOCK)
               if r.kind == "library"}
    assert "serde" in by_name and "rand" in by_name
    assert by_name["serde"].declared_range == "1.0.210"
    assert by_name["rand"].declared_range == "0.8.5"
    assert by_name["serde"].ecosystem == "cargo"


def test_cargo_omits_transitive_only_crates():
    """getrandom is pulled in by rand, never declared by this repo — the same exclusion as
    go `// indirect` and a Gemfile.lock spec absent from DEPENDENCIES."""
    names = {r.name for r in cargo.extract("clients/a", "Cargo.lock", LOCK)}
    assert "getrandom" not in names
    assert "serde_derive" not in names


def test_cargo_does_not_report_the_workspace_member_as_a_library():
    """`shop` is this repo's own crate, not a dependency to audit. It is identified by
    having no `source`, which is exactly what makes its dependency list authoritative."""
    names = {r.name for r in cargo.extract("clients/a", "Cargo.lock", LOCK)}
    assert "shop" not in names


def test_cargo_handles_versioned_dependency_entries():
    """Older/ambiguous locks write `serde 1.0.210` or `serde 1.0.210 (registry+...)` in a
    dependencies list. The crate name is the first token; treating the whole string as a
    name loses the crate entirely."""
    lock = LOCK.replace('"serde",', '"serde 1.0.210 (registry+https://x)",')
    names = {r.name for r in cargo.extract("clients/a", "Cargo.lock", lock)}
    assert "serde" in names


def test_cargo_wires_into_osv_and_purl():
    from agent.lib.purl import osv_ecosystem, to_purl
    assert osv_ecosystem("cargo") == "crates.io"
    assert to_purl("cargo", "serde", "1.0.210") == "pkg:cargo/serde@1.0.210"


def test_an_unsupported_ecosystem_still_maps_to_none():
    """The sentinel moves from cargo to gradle now that cargo ships. The None case itself
    must survive: a record we cannot audit must never be handed to OSV as if it could be."""
    from agent.lib.purl import osv_ecosystem
    assert osv_ecosystem("gradle") is None


def test_cargo_invalid_toml_raises_valueerror():
    with pytest.raises(ValueError):
        cargo.extract("clients/a", "Cargo.lock", "[[package]\nname = ")


def test_cargo_empty_lock_returns_empty():
    assert cargo.extract("clients/a", "Cargo.lock", "version = 3\n") == []
