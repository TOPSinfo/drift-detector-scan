"""drift.json is a published spec — the real payload must conform to it.

The schema is the STRUCTURAL half of the contract (keys, types, enums); the SEMANTIC half
(a tile equals the rows it counts, no two rows identical) lives in verify.py, because JSON
Schema cannot express it. Both together are what let an agent — or an outside tool — trust
drift.json without reading the code that produced it.

jsonschema is a TEST-only dependency; the runtime stays stdlib + pyyaml, so this skips
rather than fails when it is absent.
"""
import json
import os

import pytest

_SCHEMA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "docs", "schema", "drift-v1.schema.json")


def _load_schema():
    with open(_SCHEMA, encoding="utf-8") as fh:
        return json.load(fh)


def test_schema_file_is_valid_json_and_versioned():
    s = _load_schema()
    assert s["properties"]["schemaVersion"]["const"] == "drift/v1"
    assert "$id" in s and s["$schema"].startswith("https://json-schema.org/")


def test_payload_carries_the_schema_version():
    from tests.test_verify import _real_payload
    payload, _ = _real_payload()
    assert payload["schemaVersion"] == "drift/v1"


def test_real_payload_conforms_to_the_published_schema():
    jsonschema = pytest.importorskip("jsonschema")
    from tests.test_verify import _real_payload
    payload, _ = _real_payload()
    # a full real payload from build_payload must validate against docs/schema
    jsonschema.validate(instance=payload, schema=_load_schema())


def test_schema_documents_own_infra_reason():
    """M4: ownInfraReason is a real drift.json field (agent/lib/endpoints.py,
    agent/lib/dashboard_render.py) with no runtime enforcement of its own — this is the only
    place it is described, so 'the one contract' stays true even without jsonschema installed."""
    s = _load_schema()
    prop = s["properties"]["endpoints"]["items"]["properties"]["ownInfraReason"]
    assert "repo token" in prop["description"] and "git remote org domain" in prop["description"]


def test_an_endpoint_carrying_own_infra_reason_conforms_to_the_schema():
    jsonschema = pytest.importorskip("jsonschema")
    payload = {"schemaVersion": "drift/v1", "generated": "2026-08-13",
               "counts": {"fixes": 0, "sunsets": 0, "eol": 0, "critical": 0, "unaudited": 0,
                         "reposScanned": 1, "reposAffected": 0},
               "actions": [],
               "endpoints": [{"repo": "rev-hubspot-connector", "domain": "api.hubspot.com",
                              "vendor": "Unknown", "version": None, "classified": False,
                              "hostClass": "own-infra", "coverage": "queued",
                              "ownInfraReason": "repo token 'hubspot'",
                              "file_count": 1, "files": ["a.php:1"]}]}
    jsonschema.validate(instance=payload, schema=_load_schema())


def test_a_secret_action_conforms_to_the_schema():
    """kind: "secret" (Task 3, gitleaks-detected credentials, agent/audit.py's
    _secret_findings) is a real action kind audit_inventory can now produce. drift.json is
    'the ONE contract' per this repo's CLAUDE.md, so a kind the code produces that the
    published schema's `actions[].kind` enum does not list would be a real defect, not a
    cosmetic gap — this proves the schema actually names it."""
    jsonschema = pytest.importorskip("jsonschema")
    payload = {"schemaVersion": "drift/v1", "generated": "2026-09-04",
               "counts": {"fixes": 0, "sunsets": 0, "eol": 0, "critical": 0, "unaudited": 0,
                         "reposScanned": 1, "reposAffected": 1},
               "actions": [{"repo": "acme-supplier-tools", "ref": "generic-api-key",
                            "kind": "secret", "status": "DEPRECATED"}]}
    jsonschema.validate(instance=payload, schema=_load_schema())


def test_schema_admits_the_exposed_action_status():
    """Structural half, asserted without jsonschema so it runs even where that test-only
    dependency is absent: the status enum is CLOSED, and "EXPOSED" is what a secret action
    actually carries."""
    s = _load_schema()
    assert "EXPOSED" in s["properties"]["actions"]["items"]["properties"]["status"]["enum"]


def test_a_secret_actions_real_status_conforms_to_the_schema():
    """The status a secret action ACTUALLY carries is "EXPOSED" (agent/audit.py sets it,
    actions.build_actions now preserves it through the rollup instead of flattening it to
    REVIEW). A status the code emits that the closed enum does not list makes every real
    drift.json with a leaked credential in it fail validation."""
    jsonschema = pytest.importorskip("jsonschema")
    payload = {"schemaVersion": "drift/v1", "generated": "2026-09-04",
               "counts": {"fixes": 0, "sunsets": 0, "eol": 0, "critical": 0, "unaudited": 0,
                          "secrets": 1, "reposScanned": 1, "reposAffected": 1},
               "actions": [{"repo": "acme-supplier-tools", "ref": "generic-api-key",
                            "kind": "secret", "status": "EXPOSED"}]}
    jsonschema.validate(instance=payload, schema=_load_schema())


def test_schema_declares_the_secrets_tile_count():
    """`counts.secrets` is written by dashboard_render and checked by verify's tile-vs-table
    invariant, but the published contract listed every OTHER count individually and not this
    one — the same gap the `kind` enum had, one object over."""
    s = _load_schema()
    prop = s["properties"]["counts"]["properties"]["secrets"]
    assert prop["type"] == "integer" and prop["minimum"] == 0
    assert "credential" in prop["description"].lower()


def test_schema_rejects_a_negative_secrets_count():
    jsonschema = pytest.importorskip("jsonschema")
    bad = {"schemaVersion": "drift/v1", "generated": "2026-09-04",
           "counts": {"fixes": 0, "sunsets": 0, "eol": 0, "critical": 0, "unaudited": 0,
                      "secrets": -1, "reposScanned": 1, "reposAffected": 0},
           "actions": []}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad, schema=_load_schema())


def test_schema_rejects_a_bad_status_enum():
    """Proof the schema actually constrains — an action with an invalid status fails."""
    jsonschema = pytest.importorskip("jsonschema")
    bad = {"schemaVersion": "drift/v1", "generated": "2026-07-21",
           "counts": {"fixes": 0, "sunsets": 0, "eol": 0, "critical": 0, "unaudited": 0,
                      "reposScanned": 1, "reposAffected": 0},
           "actions": [{"repo": "r", "ref": "eBay", "kind": "sunset", "status": "MADE-UP"}]}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad, schema=_load_schema())


def test_the_schema_admits_the_two_human_signed_verdicts():
    """The verdict enum is CLOSED, so a verdict the schema does not list makes the whole report
    invalid — a scan that produced one would fail validation with the catalog entry, not the
    code, blamed. INTERNAL and ACCEPTED are produced by catalog_coverage, so the published
    contract has to name them."""
    jsonschema = pytest.importorskip("jsonschema")
    from agent.lib import catalog_coverage as cc

    schema = _load_schema()
    item = schema["properties"]["catalog"]["items"]
    for verdict in (cc.INTERNAL, cc.ACCEPTED):
        jsonschema.validate({"vendor": "AcmeBilling", "verdict": verdict,
                             "callSites": 3, "catalogEntries": 0,
                             "checked": "2026-08-24", "source": ""}, item)


def test_the_absorption_scoreboard_is_part_of_the_contract():
    """The digest is a PROJECTION of drift.json, so any number absent from the contract is a
    number no report may state. Pinning catalogSummary/catalogDelta is what stops the digest
    quietly recomputing them from somewhere else."""
    schema = _load_schema()
    assert "catalogSummary" in schema["properties"]
    assert "catalogDelta" in schema["properties"]
