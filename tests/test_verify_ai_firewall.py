import pytest
from agent.lib import verify


def _clean():
    return {"counts": {"fixes": 0, "sunsets": 0}, "endpoints": [], "findings": [], "catalog": []}


def test_a_clean_payload_passes():
    verify.check_ai_firewall(_clean())


@pytest.mark.parametrize("payload", [
    {"counts": {}, "endpoints": [{"domain": "a.com", "origin": "ai"}], "findings": [], "catalog": []},
    {"counts": {}, "endpoints": [], "findings": [{"vendor": "X", "origin": "lead"}], "catalog": []},
    {"counts": {}, "endpoints": [], "findings": [], "catalog": [{"vendor": "X", "by": "lead"}]},
    {"counts": {}, "endpoints": [{"domain": "a.com", "tier": "ai-shaped"}], "findings": [],
     "catalog": []},
])
def test_an_ai_record_in_the_certified_payload_is_a_violation(payload):
    """Until now the firewall between certified findings and AI output WAS file separation: the AI
    lived in a different HTML file and verify only covered the certified ones. Once they share a
    document that structural guarantee is gone, so it has to become an executable check —
    otherwise 'merge the AI tab into the dashboard' silently weakens the tool's central claim."""
    with pytest.raises(verify.Violation) as exc:
        verify.check_ai_firewall(payload)
    assert exc.value.check == "ai-firewall"


def test_the_firewall_runs_as_part_of_verify_payload():
    # "actions": [] is required here even though this test targets the AI firewall: earlier
    # checks in verify_payload's tuple (check_tile_counts, check_row_labels_distinct) index
    # payload["actions"] directly and would raise an unrelated KeyError before check_ai_firewall
    # ever runs on a payload that omits it.
    dirty = {"counts": {}, "actions": [], "endpoints": [{"domain": "a.com", "origin": "ai"}],
             "findings": [], "catalog": []}
    names = [v.check for v in verify.verify_payload(dirty, [])]
    assert "ai-firewall" in names


def test_ai_provenance_on_an_ATTESTATION_is_still_allowed():
    """`by: ai-research` on a catalog attestation is a LEGITIMATE, gate-validated provenance marker
    (it already ships on ~40 vendors). The firewall targets AI-shaped FINDINGS and ENDPOINTS, not
    the honest labelling of who checked a vendor's page."""
    ok = _clean()
    ok["catalog"] = [{"vendor": "Mailgun", "verdict": "CURRENT", "by": "ai-research"}]
    verify.check_ai_firewall(ok)


def test_an_ai_marker_in_actions_is_a_violation():
    """PROVE THE BUG (Critical finding, fix round 1): the firewall walked a hardcoded
    ("endpoints", "findings", "catalog") section list. A real drift.json has NO "findings" key —
    build_payload never emits one, only these test fixtures invented it — while "actions" is the
    array that actually carries the per-repo remediation records build_payload does emit. Injecting
    an AI marker into actions[0] of a real drift.json and running `bin/drift-scan verify` did NOT
    fire ai-firewall: a false green on the exact invariant this check exists to guarantee."""
    dirty = _clean()
    dirty["actions"] = [{"repo": "r", "ref": "eBay", "kind": "sunset", "origin": "ai"}]
    with pytest.raises(verify.Violation) as exc:
        verify.check_ai_firewall(dirty)
    assert exc.value.check == "ai-firewall"


def _rich_real_payload():
    """A REAL build_payload() output with every top-level section populated with at least one
    dict record — endpoints, private, coveredDeps, sdkMediated, catalog, coverageGrades, shapes
    and residueSamples all non-empty, not just actions (which _real_payload() in test_verify.py
    leaves empty). Used to prove the firewall covers every section build_payload can actually
    produce, not a hand-picked subset of them."""
    from agent.lib.actions import build_actions
    from agent.lib.dashboard_render import build_payload
    from tests.test_verify import TWELVE

    actions = build_actions(TWELVE)
    inventory = {
        "repos": [{
            "path": "ebayapi",
            "endpoints": [{"domain": "api.ebay.com", "vendor": "eBay", "version": "1.0",
                          "classified": True, "hostClass": "api", "file_count": 1,
                          "files": ["a.py:1"]}],
        }],
        "scope": {"reposScanned": 1},
        "coverage": {
            "residue": {
                "byRepo": [{"repo": "ebayapi", "grade": "A", "attributed": 1,
                           "unattributedPaths": [], "unresolvedSinks": []}],
                "pathLiterals": [{"repo": "ebayapi", "loc": "a.py:2", "sample": "x"}],
            },
            "privateSources": [{"repo": "ebayapi",
                                "packages": [{"pkg": "priv-pkg", "via": "requirements.txt"}],
                                "repositories": ["https://example.com/priv.git"],
                                "covered": ["https://example.com/covered.git"]}],
            "sdkMediated": [{"repo": "ebayapi", "sdkCount": 1, "endpointCount": 1}],
            "shapes": [{"repo": "ebayapi", "languages": ["python"], "verdict": "ok",
                       "attributed": 1, "unattributedPaths": [], "unresolvedSinks": [],
                       "reasons": [], "residueFingerprint": "x", "unmodeledFiles": []}],
            "rootsUnscannable": [{"root": "https://bad.example", "reason": "404"}],
        },
    }
    audit = {
        "generated": "2026-08-12", "findings": TWELVE, "actions": actions,
        "counts": {"reposAffected": 1},
        "coverage": {
            "catalog": [{"vendor": "eBay", "verdict": "CURRENT", "by": "human",
                        "callSites": 1, "catalogEntries": 1, "reasons": [],
                        "checked": "2026-08-12", "source": "https://example.com"}],
            "notes": ["a coverage note"],
        },
    }
    from agent.lib.dashboard_render import build_payload as _bp
    return _bp(inventory, audit)


def test_every_list_of_dicts_section_in_a_real_payload_is_covered():
    """The guard that would have caught the original bug: not a fixture that GUESSES which
    sections matter, but every top-level key of a REAL build_payload() output whose value is a
    non-empty list of dicts, checked behaviourally — inject an AI marker into the first record of
    EACH such section (one at a time) and assert the firewall fires for it. A hardcoded section
    list can drift out of sync with build_payload silently (that is precisely what happened:
    "findings" was checked and doesn't exist, "actions" exists and wasn't checked); this test
    fails the moment a real, populated section stops being walked, without anyone having to
    remember to add its name to a list by hand."""
    payload = _rich_real_payload()
    list_of_dict_sections = [
        key for key, val in payload.items()
        if isinstance(val, list) and val and all(isinstance(rec, dict) for rec in val)
    ]
    # sanity: this fixture must actually exercise more than the three originally-hardcoded names
    assert set(list_of_dict_sections) >= {
        "actions", "endpoints", "private", "coveredDeps", "sdkMediated",
        "catalog", "coverageGrades", "shapes", "residueSamples", "rootsUnscannable",
    }
    import copy
    for section in list_of_dict_sections:
        dirty = copy.deepcopy(payload)
        dirty[section][0]["origin"] = "ai"
        with pytest.raises(verify.Violation) as exc:
            verify.check_ai_firewall(dirty)
        assert exc.value.check == "ai-firewall", f"section {section!r} was not covered"
