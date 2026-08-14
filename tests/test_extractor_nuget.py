import pytest
from agent.lib.extractors import nuget, extractor_for

# SDK-style csproj. Most have no xmlns at all; the parser must cope either way.
CSPROJ = '''<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <Nullable>enable</Nullable>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Newtonsoft.Json" Version="13.0.3" />
    <PackageReference Include="Moq" Version="4.20.70" />
    <ProjectReference Include="..\\Lib\\Lib.csproj" />
  </ItemGroup>
</Project>
'''


def test_nuget_registered_by_suffix_not_exact_basename():
    """The registry matched the exact basename, so `Shop.csproj` could never resolve the
    way `pom.xml` does — the extractor would exist and never run in production."""
    assert extractor_for("src/Shop.csproj") is nuget.extract
    assert extractor_for("Other.Project.csproj") is nuget.extract


def test_the_suffix_registry_does_not_break_exact_matches():
    """Existing exact-basename lookups must be untouched."""
    from agent.lib.extractors import npm, go, maven
    assert extractor_for("a/package.json") is npm.extract
    assert extractor_for("a/go.mod") is go.extract
    assert extractor_for("a/pom.xml") is maven.extract
    assert extractor_for("a/README.md") is None


def test_nuget_extracts_packagereferences():
    by_name = {r.name: r for r in nuget.extract("clients/a", "Shop.csproj", CSPROJ)
               if r.kind == "library"}
    assert "Newtonsoft.Json" in by_name and "Moq" in by_name
    assert by_name["Newtonsoft.Json"].declared_range == "13.0.3"
    assert by_name["Newtonsoft.Json"].ecosystem == "nuget"


def test_nuget_skips_project_references():
    """A ProjectReference is another project in the same solution — source we scan
    directly, not a NuGet package to audit."""
    names = {r.name for r in nuget.extract("clients/a", "Shop.csproj", CSPROJ)}
    assert not any("Lib.csproj" in n for n in names)
    assert not any(n.endswith(".csproj") for n in names)


def test_nuget_target_framework_becomes_the_runtime():
    by_key = {r.tech_key: r for r in nuget.extract("clients/a", "Shop.csproj", CSPROJ)}
    rt = by_key["runtime:dotnet"]
    assert rt.kind == "runtime" and rt.version_hint == "net8.0"


def test_nuget_wires_into_osv_and_purl():
    from agent.lib.purl import osv_ecosystem, to_purl
    assert osv_ecosystem("nuget") == "NuGet"
    # No slash rewrite here — unlike maven, the NuGet id IS the whole name.
    assert to_purl("nuget", "Newtonsoft.Json", "13.0.3") == "pkg:nuget/Newtonsoft.Json@13.0.3"


def test_nuget_invalid_xml_raises_valueerror():
    with pytest.raises(ValueError):
        nuget.extract("clients/a", "Shop.csproj", "<Project><unclosed>")


def test_a_repo_containing_only_a_csproj_is_picked_up_end_to_end(tmp_path):
    """The unit call is not the contract — production reaches the extractor through
    extract_manifest_records walking the tree. A registry that cannot match `Shop.csproj`
    leaves a .NET repo's Supply Chain plane silently empty."""
    from agent.lib.manifest_scan import extract_manifest_records
    (tmp_path / "Shop.csproj").write_text(CSPROJ)
    records, unparsed = extract_manifest_records(str(tmp_path), "clients/a")
    names = {r.name for r in records if r.kind == "library"}
    assert "Newtonsoft.Json" in names, f"csproj never reached an extractor: {records}"
    assert unparsed == []


# ── packages.config: the legacy .NET manifest ────────────────────────────────────

PKGCONFIG = '''<?xml version="1.0" encoding="utf-8"?>
<packages>
  <package id="Newtonsoft.Json" version="13.0.3" targetFramework="net472" />
  <package id="Serilog" version="2.12.0" targetFramework="net472" />
  <package id="StyleCop.Analyzers" version="1.1.118" developmentDependency="true" />
  <package id="NoVersionHere" targetFramework="net472" />
  <package version="9.9.9" />
</packages>
'''


def _pkgs(content=PKGCONFIG):
    from agent.lib.extractors import nuget as _n
    return {r.name: r for r in _n.extract_packages_config("clients/a", "packages.config", content)}


def test_packages_config_is_registered_and_csproj_still_is():
    from agent.lib.extractors import nuget as _n
    assert extractor_for("packages.config") is _n.extract_packages_config
    assert extractor_for("src/packages.config") is _n.extract_packages_config
    assert extractor_for("src/Shop.csproj") is _n.extract          # suffix rule untouched


def test_packages_config_extracts_id_and_version():
    r = _pkgs()["Newtonsoft.Json"]
    assert r.ecosystem == "nuget" and r.kind == "library"
    assert r.declared_range == "13.0.3" and r.parse_quality == "exact"
    assert "Serilog" in _pkgs()


def test_development_dependencies_are_omitted():
    """`developmentDependency="true"` is the legacy marker for build-only packages — the
    same exclusion as Maven scope=test and npm devDependencies."""
    assert "StyleCop.Analyzers" not in _pkgs()


def test_a_package_with_no_version_is_listed_as_best_effort():
    """Still listed: dropping it would hide a dependency entirely. Recorded with no version
    rather than a guessed one."""
    r = _pkgs()["NoVersionHere"]
    assert r.declared_range == "" and r.parse_quality == "best_effort"


def test_an_entry_with_no_id_is_skipped():
    assert not any(n in ("", None) for n in _pkgs())
    assert len(_pkgs()) == 3          # Newtonsoft, Serilog, NoVersionHere


def test_no_dotnet_runtime_is_invented_from_targetframework():
    """`targetFramework` on a <package> says what that PACKAGE was built against, not the
    project's TFM. Taking the first one would state a runtime the file never asserts."""
    from agent.lib.extractors import nuget as _n
    recs = _n.extract_packages_config("clients/a", "packages.config", PKGCONFIG)
    assert not [r for r in recs if r.kind == "runtime"]


def test_a_version_range_is_unlocked():
    content = ('<packages><package id="A" version="[13.0,14.0)" />'
               '<package id="B" version="*" /></packages>')
    p = _pkgs(content)
    assert p["A"].parse_quality == "unlocked" and p["B"].parse_quality == "unlocked"


def test_packages_config_invalid_xml_raises_valueerror():
    from agent.lib.extractors import nuget as _n
    with pytest.raises(ValueError):
        _n.extract_packages_config("clients/a", "packages.config", "<packages><unclosed>")


def test_purl_and_osv_are_unchanged_and_the_gradle_sentinel_survives():
    from agent.lib.purl import osv_ecosystem, to_purl
    assert to_purl("nuget", "Newtonsoft.Json", "13.0.3") == "pkg:nuget/Newtonsoft.Json@13.0.3"
    assert osv_ecosystem("nuget") == "NuGet"
    assert osv_ecosystem("gradle") is None


def test_a_repo_containing_only_packages_config_is_picked_up_end_to_end(tmp_path):
    """The unit call is not the contract — production reaches the extractor through
    extract_manifest_records walking the tree."""
    from agent.lib.manifest_scan import extract_manifest_records
    (tmp_path / "packages.config").write_text(PKGCONFIG)
    records, unparsed = extract_manifest_records(str(tmp_path), "clients/a")
    names = {r.name for r in records if r.kind == "library"}
    assert "Newtonsoft.Json" in names, f"packages.config never reached an extractor: {records}"
    assert "StyleCop.Analyzers" not in names
    assert unparsed == []


# ── PrivateAssets="all": assets that never reach the project output ───────────────

PRIVATE_ASSETS_CSPROJ = '''<Project Sdk="Microsoft.NET.Sdk">
  <ItemGroup>
    <PackageReference Include="Newtonsoft.Json" Version="13.0.3" />
    <PackageReference Include="StyleCop.Analyzers" Version="1.1.118" PrivateAssets="all" />
    <PackageReference Include="Foo" Version="1.0">
      <PrivateAssets>all</PrivateAssets>
    </PackageReference>
    <PackageReference Include="Bar" Version="1.0" PrivateAssets="runtime" />
  </ItemGroup>
</Project>
'''


def _pa(content=PRIVATE_ASSETS_CSPROJ):
    return {r.name for r in nuget.extract("clients/a", "Shop.csproj", content)
            if r.kind == "library"}


def test_private_assets_all_is_omitted_attribute_form():
    """PrivateAssets="all" means the package's assets never reach the project output —
    analyzers and build-only tooling. The same exclusion as Maven scope=test, npm
    devDependencies, and packages.config developmentDependency="true"."""
    assert "StyleCop.Analyzers" not in _pa()


def test_private_assets_all_is_omitted_child_element_form():
    """PrivateAssets lives in the same two places Version does: an attribute or a child.
    Reading only the attribute would miss the form MSBuild templates generate."""
    assert "Foo" not in _pa()


def test_a_package_with_no_private_assets_is_kept():
    assert "Newtonsoft.Json" in _pa()


def test_private_assets_runtime_is_not_all_and_is_kept():
    """Only `all` severs the package from the output. `runtime`, `compile`, `analyzers`
    and their combinations still ship or compile against the app — skipping those would
    hide real dependencies."""
    assert "Bar" in _pa()


def test_private_assets_is_matched_case_insensitively():
    content = PRIVATE_ASSETS_CSPROJ.replace('PrivateAssets="all"', 'PrivateAssets="All"')
    assert "StyleCop.Analyzers" not in _pa(content)


def test_no_package_is_skipped_by_its_name():
    """Moq is a test library, but nothing in the FILE says so. Inferring "test" from a
    package name would drop real dependencies from any repo that happens to name one
    like a test tool."""
    assert "Moq" in {r.name for r in nuget.extract("clients/a", "Shop.csproj", CSPROJ)}


def test_private_assets_all_is_omitted_end_to_end(tmp_path):
    from agent.lib.manifest_scan import extract_manifest_records
    (tmp_path / "Shop.csproj").write_text(PRIVATE_ASSETS_CSPROJ)
    records, unparsed = extract_manifest_records(str(tmp_path), "clients/a")
    names = {r.name for r in records if r.kind == "library"}
    assert "Newtonsoft.Json" in names and "Bar" in names
    assert "StyleCop.Analyzers" not in names and "Foo" not in names
    assert unparsed == []
