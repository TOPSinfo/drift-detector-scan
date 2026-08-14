import pytest
from agent.lib.extractors import bundler, extractor_for

# Canonical Gemfile.lock layout. Indentation is load-bearing: a SPEC sits at 4 spaces,
# and that gem's own transitive requirements sit at 6 UNDER it. A parser that ignores the
# indent reads `actionpack (= 7.1.3)` as a spec whose version is "= 7.1.3".
LOCK = '''GEM
  remote: https://rubygems.org/
  specs:
    rails (7.1.3)
      actionpack (= 7.1.3)
    actionpack (7.1.3)
    nokogiri (1.16.0)

PLATFORMS
  ruby

DEPENDENCIES
  rails (~> 7.1)
  nokogiri

RUBY VERSION
   ruby 3.3.0

BUNDLED WITH
   2.5.6
'''


def test_bundler_registered():
    assert extractor_for("a/Gemfile.lock") is bundler.extract


def test_bundler_extracts_direct_gems_with_resolved_versions():
    """Names come from DEPENDENCIES; versions from the GEM specs. The lock pins an exact
    version even where the Gemfile asked for a range (`~> 7.1` -> 7.1.3)."""
    by_name = {r.name: r for r in bundler.extract("clients/a", "Gemfile.lock", LOCK)
               if r.kind == "library"}
    assert set(by_name) == {"rails", "nokogiri"}
    assert by_name["rails"].declared_range == "7.1.3"
    assert by_name["nokogiri"].declared_range == "1.16.0"
    assert by_name["rails"].ecosystem == "bundler"


def test_bundler_omits_transitive_specs_not_in_dependencies():
    """actionpack is resolved into the lock but never declared — the same reason go
    `// indirect` and npm devDependencies are excluded. Reporting it would attribute
    Rails' choices to this repo."""
    names = {r.name for r in bundler.extract("clients/a", "Gemfile.lock", LOCK)}
    assert "actionpack" not in names


def test_bundler_strips_the_bang_marker_from_dependency_names():
    """`rails (~> 7.1)!` marks a gem pinned to a git/path source. The bang is a marker,
    not part of the name — keeping it would make the gem unmatchable in OSV."""
    lock = LOCK.replace("  rails (~> 7.1)\n", "  rails (~> 7.1)!\n")
    names = {r.name for r in bundler.extract("clients/a", "Gemfile.lock", lock)}
    assert "rails" in names
    assert not any(n.endswith("!") for n in names)


def test_bundler_ruby_version_becomes_the_runtime():
    by_key = {r.tech_key: r for r in bundler.extract("clients/a", "Gemfile.lock", LOCK)}
    rt = by_key["runtime:ruby"]
    assert rt.kind == "runtime"
    assert rt.version_hint == "3.3.0"          # the version, not the literal "ruby 3.3.0"


def test_bundler_does_not_mistake_bundled_with_for_the_ruby_version():
    """BUNDLED WITH is Bundler's own version. Reading it as Ruby would state a fact about
    the runtime that the file never asserts."""
    by_key = {r.tech_key: r for r in bundler.extract("clients/a", "Gemfile.lock", LOCK)}
    assert by_key["runtime:ruby"].version_hint != "2.5.6"


def test_bundler_lock_without_a_ruby_version_has_no_runtime_record():
    lock = LOCK.split("RUBY VERSION")[0]
    keys = {r.tech_key for r in bundler.extract("clients/a", "Gemfile.lock", lock)}
    assert "runtime:ruby" not in keys


def test_bundler_wires_into_osv_and_purl():
    from agent.lib.purl import osv_ecosystem, to_purl
    assert osv_ecosystem("bundler") == "RubyGems"
    # our inventory key is `bundler`; the PURL type is `gem`
    assert to_purl("bundler", "rails", "7.1.3") == "pkg:gem/rails@7.1.3"


def test_bundler_empty_lock_returns_empty():
    assert bundler.extract("clients/a", "Gemfile.lock", "") == []
