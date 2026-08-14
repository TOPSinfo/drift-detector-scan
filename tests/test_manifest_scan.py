from pathlib import Path

from agent.lib.manifest_scan import extract_manifest_records


def _w(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_extracts_from_manifests_and_skips_vendor_dirs(tmp_path):
    _w(tmp_path, "composer.json", '{"require": {"php": "^8.2", "laravel/framework": "^12.0"}}')
    _w(tmp_path, "package.json", '{"dependencies": {"axios": "^1.6"}}')
    _w(tmp_path, "vendor/pkg/composer.json", '{"require": {"evil/dep": "1.0"}}')   # MUST be skipped
    _w(tmp_path, "src/app.php", 'not a manifest')
    records, unparsed = extract_manifest_records(str(tmp_path), "acme/web")
    names = {r.name for r in records}
    assert "php" in names and "laravel/framework" in names and "axios" in names
    assert "evil/dep" not in names                              # vendor/ skipped
    assert unparsed == []
    assert all(r.repo == "acme/web" for r in records)
    php = next(r for r in records if r.name == "php")
    assert php.manifest_path == "composer.json"                 # repo-relative path


def test_invalid_manifest_is_unparsed_not_crash(tmp_path):
    _w(tmp_path, "composer.json", '{invalid json')
    _w(tmp_path, "package.json", '{"dependencies": {"axios": "^1.6"}}')
    records, unparsed = extract_manifest_records(str(tmp_path), "r")
    assert {r.name for r in records} == {"axios"}               # good one still parsed
    assert len(unparsed) == 1 and unparsed[0]["path"] == "composer.json"


def test_central_package_management_versions_reach_the_records(tmp_path):
    """End-to-end: under CPM the csproj carries no version and the sibling
    Directory.Packages.props does. The unit call is not the contract — production has to
    find the catalog while walking the tree."""
    _w(tmp_path, "src/Shop.csproj", '''<Project Sdk="Microsoft.NET.Sdk"><ItemGroup>
        <PackageReference Include="Moq" />
        <PackageReference Include="StyleCop.Analyzers" PrivateAssets="all" />
      </ItemGroup></Project>''')
    _w(tmp_path, "Directory.Packages.props", '''<Project><ItemGroup>
        <PackageVersion Include="Moq" Version="4.20.72" />
        <PackageVersion Include="StyleCop.Analyzers" Version="1.1.118" />
        <PackageVersion Include="NeverReferenced" Version="9.9.9" />
      </ItemGroup></Project>''')
    records, unparsed = extract_manifest_records(str(tmp_path), "clients/a")
    by_name = {r.name: r for r in records if r.kind == "library"}
    assert by_name["Moq"].declared_range == "4.20.72", "CPM version never reached the record"
    assert "StyleCop.Analyzers" not in by_name        # PrivateAssets=all, not resurrected
    assert "NeverReferenced" not in by_name           # catalog is not a dependency list
    assert unparsed == []


def test_the_catalog_is_not_itself_a_manifest(tmp_path):
    """A repo with ONLY a Directory.Packages.props declares no dependencies — it is a
    version catalog for csproj files that are not here."""
    _w(tmp_path, "Directory.Packages.props",
       '<Project><ItemGroup><PackageVersion Include="Moq" Version="4.20.72" /></ItemGroup></Project>')
    records, unparsed = extract_manifest_records(str(tmp_path), "clients/a")
    assert [r for r in records if r.kind == "library"] == []


def test_a_broken_catalog_is_reported_and_the_rest_of_the_repo_survives(tmp_path):
    """A malformed props file must not take the whole repo's inventory down with it — the
    csproj still yields its package, and the failure is named in unparsed."""
    _w(tmp_path, "Shop.csproj", '<Project><ItemGroup>'
       '<PackageReference Include="Newtonsoft.Json" Version="13.0.3" /></ItemGroup></Project>')
    _w(tmp_path, "Directory.Packages.props", "<Project><unclosed>")
    records, unparsed = extract_manifest_records(str(tmp_path), "clients/a")
    assert "Newtonsoft.Json" in {r.name for r in records}
    assert any("Directory.Packages.props" in u["path"] for u in unparsed), unparsed
