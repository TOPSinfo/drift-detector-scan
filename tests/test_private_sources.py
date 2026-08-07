from agent.lib import private_sources as ps


def test_npm_git_and_file_deps_flagged(tmp_path):
    (tmp_path / "package.json").write_text(
        '{"dependencies": {"axios": "^1.0", "tops-ui": "git+https://git.example.com/x/ui.git",'
        ' "local-lib": "file:../local-lib", "react": "18.0"}}')
    got = ps.detect(str(tmp_path))
    flagged = {p["pkg"] for p in got["packages"]}
    assert flagged == {"tops-ui", "local-lib"}                 # semver deps (axios/react) not flagged


def test_composer_private_vcs_repo_flagged_but_not_packagist_or_path(tmp_path):
    (tmp_path / "composer.json").write_text('{"require": {"tops/ebay-wrapper": "^2.0"},'
        ' "repositories": ['
        '  {"type": "vcs", "url": "https://git.example.com/example-org/ebayapi.git"},'
        '  {"type": "composer", "url": "https://packagist.org"},'      # public -> ignored
        '  {"type": "path", "url": "../local-pkg"}]}')                 # local -> source is present
    got = ps.detect(str(tmp_path))
    assert got["repositories"] == ["https://git.example.com/example-org/ebayapi.git"]


def test_composer_repositories_as_dict(tmp_path):
    (tmp_path / "composer.json").write_text(
        '{"repositories": {"tops": {"type": "gitlab", "url": "https://git.example.com/g/p.git"}}}')
    assert ps.detect(str(tmp_path))["repositories"] == ["https://git.example.com/g/p.git"]


def test_clean_repo_has_none(tmp_path):
    (tmp_path / "composer.json").write_text('{"require": {"laravel/framework": "^12.0"}}')
    (tmp_path / "package.json").write_text('{"dependencies": {"react": "^19.0"}}')
    assert ps.detect(str(tmp_path)) == {"packages": [], "repositories": []}


def test_malformed_manifest_skipped(tmp_path):
    (tmp_path / "composer.json").write_text("{not json")
    assert ps.detect(str(tmp_path)) == {"packages": [], "repositories": []}


def test_preflight_cli_reports_private_sources(tmp_path, capsys):
    import subprocess
    (tmp_path / "EbayApi").mkdir()
    (tmp_path / "EbayApi" / "composer.json").write_text(
        '{"repositories": [{"type": "vcs", "url": "https://git.example.com/x/ebay.git"}]}')
    subprocess.run(["git", "init", "-q"], cwd=tmp_path / "EbayApi", check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
                    "--allow-empty", "-q", "-m", "i"], cwd=tmp_path / "EbayApi", check=True)
    from agent import cli
    rc = cli.main(["preflight", "--root", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0 and "private package sources needing access" in out
    assert "git.example.com" in out and "clone them locally" in out   # connector stripped on hybrid


def test_npm_bare_github_shorthand_flagged_but_not_semver_or_aliases(tmp_path):
    (tmp_path / "package.json").write_text(
        '{"dependencies": {"lib": "myorg/private-lib#v2", "axios": "^1.0",'
        ' "aliased": "npm:@scope/x@1", "ws": "workspace:*", "tag": "latest"}}')
    flagged = {p["pkg"] for p in __import__("agent.lib.private_sources", fromlist=["detect"]).detect(str(tmp_path))["packages"]}
    assert flagged == {"lib"}          # github shorthand only; semver/npm:/workspace:/dist-tag excluded
