import pytest

from agent.lib.version_floor import floor
from agent.lib.purl import to_purl, osv_ecosystem


@pytest.mark.parametrize("spec,expected", [
    ("^8.2", "8.2"), ("~2.10.1", "2.10.1"), ("==1.1.0", "1.1.0"), (">=2.32.5", "2.32.5"),
    ("^0.21.1", "0.21.1"), (">=4.2.0.34", "4.2.0.34"), ("23", "23"), (">=20", "20"),
    ("^11.0|^12.0|^13.0", "11.0"), ("^11.0 || ^12.0", "11.0"), ("15.14.0", "15.14.0"),
    ("dev-master", None), ("*", None), ("", None), (None, None),
])
def test_floor(spec, expected):
    assert floor(spec) == expected


def test_purl_forms():
    assert to_purl("npm", "axios", "0.21.1") == "pkg:npm/axios@0.21.1"
    assert to_purl("composer", "laravel/framework", "12.0") == "pkg:composer/laravel/framework@12.0"
    assert to_purl("python", "Torch", "1.1.0") == "pkg:pypi/torch@1.1.0"          # pypi lowercases
    assert to_purl("npm", "@headlessui/react", "2.2.0") == "pkg:npm/%40headlessui/react@2.2.0"
    assert to_purl("python", "opencv_python", "4.1.0") == "pkg:pypi/opencv-python@4.1.0"  # _ -> -
    assert to_purl("unknown", "x", "1") is None


def test_osv_ecosystem_mapping():
    assert osv_ecosystem("npm") == "npm"
    assert osv_ecosystem("composer") == "Packagist"
    assert osv_ecosystem("python") == "PyPI"
    assert osv_ecosystem("go") == "Go"          # go.mod extractor shipped
    assert osv_ecosystem("maven") == "Maven"    # pom.xml extractor shipped
    assert osv_ecosystem("nuget") == "NuGet"    # *.csproj extractor shipped
    assert osv_ecosystem("bundler") == "RubyGems"  # Gemfile.lock extractor shipped
    assert osv_ecosystem("cargo") == "crates.io"   # Cargo.lock extractor shipped
    # An ecosystem we do NOT extract must still map to None, so a record we cannot audit
    # is never handed to OSV as if it could be. `gradle` stands in for the unsupported
    # set now that `cargo` has left it — this line is the guard, not the example in it.
    assert osv_ecosystem("gradle") is None


@pytest.mark.parametrize("spec,expected", [
    ("<2.0", None), ("<=3", None), (">=1,<2", "1"), ("1!2.3.4", "2.3.4"),
])
def test_floor_bounds_and_epoch(spec, expected):
    assert floor(spec) == expected
