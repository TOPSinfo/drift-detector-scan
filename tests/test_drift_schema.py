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


def test_schema_rejects_a_bad_status_enum():
    """Proof the schema actually constrains — an action with an invalid status fails."""
    jsonschema = pytest.importorskip("jsonschema")
    bad = {"schemaVersion": "drift/v1", "generated": "2026-07-21",
           "counts": {"fixes": 0, "sunsets": 0, "eol": 0, "critical": 0, "unaudited": 0,
                      "reposScanned": 1, "reposAffected": 0},
           "actions": [{"repo": "r", "ref": "eBay", "kind": "sunset", "status": "MADE-UP"}]}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad, schema=_load_schema())
