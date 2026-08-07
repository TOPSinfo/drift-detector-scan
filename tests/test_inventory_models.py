from agent.lib.inventory_models import InventoryRecord, UsedTech, library_techkey
from agent.lib import extractors

def test_library_techkey_normalizes():
    assert library_techkey("npm", "AWS-SDK") == "lib:npm/aws-sdk"

def test_inventory_record_to_dict():
    r = InventoryRecord(repo="clients/a", manifest_path="package.json", ecosystem="npm",
                        tech_key="lib:npm/aws-sdk", name="aws-sdk", kind="library",
                        declared_range="^2.1.0", parse_quality="unlocked")
    d = r.to_dict()
    assert d["tech_key"] == "lib:npm/aws-sdk" and d["kind"] == "library"

def test_used_tech_to_dict():
    u = UsedTech(repo="clients/a", tech_key="api:amazon-sp-api", evidence="src/x.php: sellingpartnerapi")
    assert u.to_dict()["tech_key"] == "api:amazon-sp-api"

def test_registry_matches_by_basename():
    saved = dict(extractors._BY_NAME)
    try:
        @extractors.register("frobfile.json")
        def fake(repo, path, content):
            return []
        assert extractors.extractor_for("a/b/frobfile.json") is fake
        assert extractors.extractor_for("a/b/other.json") is None
        assert "frobfile.json" in extractors.registered_basenames()
    finally:
        extractors._BY_NAME.clear()
        extractors._BY_NAME.update(saved)
