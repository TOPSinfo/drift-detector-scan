import json
from pathlib import Path
from agent.lib.vendors import Vendor
from agent.lib.repo_scan import scan_repo
from agent.lib.vendor_rules import write_ruleset
from tests import astgrep_fake
from tests import gitleaks_fake


def _w(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


_VENDORS = [Vendor("Stripe", "api:stripe", ("stripe.com",), r'/(v\d+)')]


def _fake_opengrep(canned):
    return lambda args: canned


def test_scan_repo_assembles_manifests_and_endpoints(tmp_path):
    _w(tmp_path, "composer.json", '{"require": {"php": "^8.2", "laravel/framework": "^12.0"}}')
    _w(tmp_path, "pay.php", '$u = "https://api.stripe.com/v1/charges";\n')
    rules = tmp_path / "rules.yaml"
    write_ruleset(_VENDORS, str(rules))            # real ruleset: run_scan reads kind/vendor from it
    canned = astgrep_fake.canned(astgrep_fake.hit("url-literal", "pay.php", 1))
    git = lambda args: {"rev-parse HEAD": "sha1", "rev-parse --abbrev-ref HEAD": "main",
                        "log -1 --format=%cI": "2026-07-10",
                        "remote get-url origin": "https://github.com/acme/web.git",
                        }.get(" ".join(args[2:]), "")   # .get -> tolerant of new git_meta calls

    record, note = scan_repo(str(tmp_path), "acme/web", 1, _VENDORS, str(rules),
                             engine="semgrep", run=_fake_opengrep(canned), git=git)
    assert record["id"] == 1 and record["path"] == "acme/web" and record["head_sha"] == "sha1"
    assert record["runtimes"]["php"]["range"] == "^8.2"
    assert "laravel/framework" in record["frameworks"]
    assert record["endpoints"][0]["techKey"] == "api:stripe" and record["endpoints"][0]["version"] == "v1"
    assert note["engineErrors"] == []


def test_scan_repo_surfaces_boilerplate_as_bucketed_not_dropped(tmp_path):
    _w(tmp_path, "x.php", '"http://www.w3.org/2001/XMLSchema"; // no real endpoint here\n')
    rules = tmp_path / "rules.yaml"
    write_ruleset(_VENDORS, str(rules))
    canned = astgrep_fake.canned(astgrep_fake.hit("url-literal", "x.php", 1))
    record, _ = scan_repo(str(tmp_path), "r", 1, _VENDORS, str(rules), engine="semgrep",
                          run=_fake_opengrep(canned), git=lambda a: "")
    eps = record["endpoints"]                                  # a schema host is now SHOWN, bucketed
    assert [e["domain"] for e in eps] == ["www.w3.org"]
    assert eps[0]["hostClass"] == "boilerplate" and not eps[0]["classified"]


def test_scan_repo_attaches_secrets_findings(tmp_path):
    _w(tmp_path, "config/feedvisor.php", "<?php return ['client_secret' => 'REDACTED'];\n")
    rules = tmp_path / "rules.yaml"
    write_ruleset(_VENDORS, str(rules))
    canned_endpoints = astgrep_fake.EMPTY
    canned_secrets = gitleaks_fake.canned(
        gitleaks_fake.hit("generic-api-key", "config/feedvisor.php", 1))
    git = lambda args: {"rev-parse HEAD": "sha1", "rev-parse --abbrev-ref HEAD": "main",
                        "log -1 --format=%cI": "2026-07-10",
                        "remote get-url origin": "https://git.example/acme/web.git",
                        }.get(" ".join(args[2:]), "")

    record, note = scan_repo(str(tmp_path), "acme/web", 1, _VENDORS, str(rules),
                             engine="semgrep", run=lambda args: canned_endpoints, git=git,
                             secrets_run=lambda args: canned_secrets)

    assert record["secrets"] == [{
        "ruleId": "generic-api-key", "path": "config/feedvisor.php", "line": 1,
        "commit": "deadbeef", "fingerprint": "deadbeef:config/feedvisor.php:generic-api-key:1",
    }]


def test_scan_repo_with_no_secrets_found_attaches_an_empty_list(tmp_path):
    _w(tmp_path, "pay.php", '$u = "https://api.stripe.com/v1/charges";\n')
    rules = tmp_path / "rules.yaml"
    write_ruleset(_VENDORS, str(rules))
    canned = astgrep_fake.canned(astgrep_fake.hit("url-literal", "pay.php", 1))
    git = lambda args: {"rev-parse HEAD": "sha1", "rev-parse --abbrev-ref HEAD": "main",
                        "log -1 --format=%cI": "2026-07-10",
                        "remote get-url origin": "https://git.example/acme/web.git",
                        }.get(" ".join(args[2:]), "")

    record, note = scan_repo(str(tmp_path), "acme/web", 1, _VENDORS, str(rules),
                             engine="semgrep", run=lambda args: canned, git=git,
                             secrets_run=lambda args: gitleaks_fake.EMPTY)

    assert record["secrets"] == []
