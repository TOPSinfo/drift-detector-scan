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
