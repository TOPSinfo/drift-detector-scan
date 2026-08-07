"""SDK profiles — read a wrapper's pinned version from its own source → synthetic endpoints
the audit dates. Pure, deterministic, no I/O beyond the reviewed YAML."""
import pytest

from agent.lib import sdk_profiles


_PROFILE = [{
    "repo": "example-org/shopify-api", "vendor": "Shopify",
    "versions": [{"version": "2025-01", "evidence": "src/GraphQL.php:19"},
                 {"version": "2023-04", "evidence": "src/Shopify/Admin2023_04/ShopifyApi.php:28"}],
    "source": "wrapper source, read 2026-07-30",
}]


def test_load_rejects_a_version_without_evidence(tmp_path):
    p = tmp_path / "sdk.yaml"
    p.write_text("- {repo: a/b, vendor: Shopify, source: x, versions: [{version: '2024-01'}]}\n")
    with pytest.raises(sdk_profiles.ProfileError):
        sdk_profiles.load(str(p))            # a profile is a read FACT — no evidence, no entry


def test_load_rejects_missing_source(tmp_path):
    p = tmp_path / "sdk.yaml"
    p.write_text("- {repo: a/b, vendor: Shopify, versions: [{version: '2024-01', evidence: 'x.php:1'}]}\n")
    with pytest.raises(sdk_profiles.ProfileError):
        sdk_profiles.load(str(p))


def test_endpoints_for_matches_repo_by_remote_identity_and_emits_per_version():
    repo = {"path": "example-org-shopify-api-abc",
            "remote_url": "https://git.example.com/example-org/shopify-api.git", "endpoints": []}
    eps = sdk_profiles.endpoints_for(repo, _PROFILE)
    assert {e["version"] for e in eps} == {"2025-01", "2023-04"}
    e = next(e for e in eps if e["version"] == "2025-01")
    assert e["vendor"] == "Shopify" and e["classified"] is True
    assert e["attribution"] == "sdk-profile"                 # never mistaken for a call-site match
    assert e["files"] == ["src/GraphQL.php:19"]              # evidence = the const line


def test_no_match_emits_nothing():
    repo = {"path": "other", "remote_url": "https://git.x/some/other.git", "endpoints": []}
    assert sdk_profiles.endpoints_for(repo, _PROFILE) == []


def test_synthetic_endpoint_feeds_the_audit_lifecycle_join_into_retired_findings():
    """End to end: a profiled Shopify wrapper's synthetic endpoints become retired-version
    sunset findings via the SAME lifecycle join a scanned endpoint uses — at the const's line."""
    from agent.audit import _lifecycle_findings
    repo = {"path": "example-org/shopify-api",
            "remote_url": "https://git.example.com/example-org/shopify-api.git",
            "endpoints": []}
    repo["endpoints"] = sdk_profiles.endpoints_for(repo, _PROFILE)
    findings = _lifecycle_findings(repo, "2026-07-30")        # Shopify computed-lifecycle branch
    shop = [f for f in findings if f.get("ref") == "Shopify"]
    by_ver = {f["version"]: f for f in shop}
    assert set(by_ver) == {"2025-01", "2023-04"}
    assert by_ver["2025-01"]["date"] == "2026-01-16"          # Shopify lifecycle, retired
    assert by_ver["2023-04"]["date"] == "2024-04-16"
    assert by_ver["2023-04"]["files"] == ["src/Shopify/Admin2023_04/ShopifyApi.php:28"]


def test_package_ships_no_client_profiles_they_live_in_the_overlay():
    # client SDK profiles carry private repo identities, so the PUBLIC package ships NONE — they
    # live in the drift-ops overlay (proven in test_catalog_overlay). The file stays a valid empty
    # list, and the loader still layers whatever the overlay holds on top.
    assert sdk_profiles.load() == []


def test_matches_is_case_insensitive_for_mixed_case_orgs():
    """scope_edges.identity() lowercases the path, so a mixed-case org (example-org/foo-sdk) must
    still match its profile repo. Same latent bug fixed in endpoints._repo_in_scope — the one
    shipped profile (example-org, already lowercase) had masked it."""
    from agent.lib.sdk_profiles import _matches
    rec = {"remote_url": "https://git.example.com/example-org/foo-sdk.git", "path": "x"}
    assert _matches(rec, "example-org/foo-sdk")
    # a different repo must NOT match
    assert not _matches({"remote_url": "https://git.example.com/example-org/bar-sdk.git"},
                        "example-org/foo-sdk")
    # local-checkout fallback (clone folder {org}-{repo}-{hash}) also case-insensitive
    assert _matches({"path": "example-org-foo-sdk"}, "example-org/foo-sdk")
