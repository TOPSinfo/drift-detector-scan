import pytest
from agent.lib.extractors import gradle, extractor_for

# A Gradle version catalog. The artifacts are Maven coordinates, so the records use
# ecosystem="maven" — `gradle` deliberately stays absent from OSV_ECOSYSTEM as the
# unsupported-ecosystem sentinel.
CATALOG = '''
[versions]
okhttp = "4.12.0"
retrofit = "2.11.0"

[libraries]
okhttp = { module = "com.squareup.okhttp3:okhttp", version = "4.12.0" }
retrofit = { group = "com.squareup.retrofit2", name = "retrofit", version.ref = "retrofit" }
coroutines = { group = "org.jetbrains.kotlinx", name = "kotlinx-coroutines-core", version.ref = "missing" }
guava = { group = "com.google.guava", name = "guava" }

[plugins]
kotlin-jvm = { id = "org.jetbrains.kotlin.jvm", version = "1.9.24" }

[bundles]
network = ["okhttp", "retrofit"]
'''


def _libs(content=CATALOG):
    return {r.name: r for r in gradle.extract("clients/a", "gradle/libs.versions.toml", content)
            if r.kind == "library"}


def test_gradle_catalog_is_registered_under_both_paths():
    """`gradle/libs.versions.toml` is the conventional location, but the root is legal too.
    extractor_for keys on the basename, so both must resolve."""
    assert extractor_for("gradle/libs.versions.toml") is gradle.extract
    assert extractor_for("libs.versions.toml") is gradle.extract


def test_module_form_yields_one_maven_coordinate():
    r = _libs()["com.squareup.okhttp3:okhttp"]
    assert r.ecosystem == "maven"          # Maven coordinates, not a `gradle` ecosystem
    assert r.declared_range == "4.12.0"
    assert r.parse_quality == "exact"


def test_group_name_form_resolves_a_version_ref_from_this_file():
    """`version.ref` resolves against THIS catalog's [versions], the same scope rule as a
    pom's ${property}. No other catalog file is read."""
    r = _libs()["com.squareup.retrofit2:retrofit"]
    assert r.declared_range == "2.11.0"
    assert r.parse_quality == "exact"


def test_an_unresolved_version_ref_is_best_effort_never_a_guess():
    """A ref with no [versions] entry usually points at a catalog we were not given.
    Recording the coordinate with no version says "we could not resolve this"; inventing
    one would state a fact about the repo that nobody established."""
    r = _libs()["org.jetbrains.kotlinx:kotlinx-coroutines-core"]
    assert r.parse_quality == "best_effort"
    assert r.declared_range in ("", "missing")
    assert r.declared_range != "2.11.0"


def test_a_library_with_no_version_at_all_is_best_effort():
    """Common when the version comes from a BOM applied in the build script — which this
    order does not read."""
    r = _libs()["com.google.guava:guava"]
    assert r.parse_quality == "best_effort"
    assert r.declared_range == ""


def test_plugins_are_not_libraries():
    """[plugins] is build tooling, not something the application ships — the same exclusion
    as Maven scope=test and npm devDependencies."""
    names = set(_libs())
    assert not any("kotlin" in n and "jvm" in n for n in names)
    assert "org.jetbrains.kotlin.jvm" not in names


def test_bundles_do_not_duplicate_their_members():
    """A bundle is an alias list; its members are already in [libraries]. Emitting records
    for it would double-count okhttp and retrofit."""
    libs = _libs()
    assert len([n for n in libs if n.endswith(":okhttp")]) == 1
    assert "network" not in libs
    assert len(libs) == 4


def test_no_java_runtime_is_invented_from_a_catalog():
    recs = gradle.extract("clients/a", "gradle/libs.versions.toml", CATALOG)
    assert not [r for r in recs if r.kind == "runtime"]


def test_string_form_is_handled():
    content = '[libraries]\nokhttp = "com.squareup.okhttp3:okhttp:4.12.0"\n'
    r = _libs(content)["com.squareup.okhttp3:okhttp"]
    assert r.declared_range == "4.12.0"


def test_purl_and_osv_are_the_maven_ones_and_the_gradle_sentinel_survives():
    """These are Maven coordinates, so they audit as Maven. `gradle` stays unmapped: it is
    the stand-in for an ecosystem we cannot audit, and mapping it would retire the guard."""
    from agent.lib.purl import osv_ecosystem, to_purl
    assert to_purl("maven", "com.squareup.okhttp3:okhttp", "4.12.0") == \
        "pkg:maven/com.squareup.okhttp3/okhttp@4.12.0"
    assert osv_ecosystem("maven") == "Maven"
    assert osv_ecosystem("gradle") is None


def test_invalid_toml_raises_valueerror():
    with pytest.raises(ValueError):
        gradle.extract("clients/a", "libs.versions.toml", "[libraries\nokhttp = ")


def test_empty_catalog_returns_empty():
    assert gradle.extract("clients/a", "libs.versions.toml", "[versions]\nx = \"1\"\n") == []
