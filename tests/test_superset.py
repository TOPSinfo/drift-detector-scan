from agent.lib.inventory_models import InventoryRecord
from agent.lib.superset import to_superset_repo


def _rt(product, hint, quality="unlocked"):
    return InventoryRecord(repo="r", manifest_path="composer.json", ecosystem="composer",
                           tech_key=f"runtime:{product}", name=product, kind="runtime",
                           version_hint=hint, parse_quality=quality)


def _lib(eco, name, rng, path="package.json", quality="unlocked"):
    return InventoryRecord(repo="r", manifest_path=path, ecosystem=eco,
                           tech_key=f"lib:{eco}/{name.lower()}", name=name, kind="library",
                           declared_range=rng, parse_quality=quality)


_META = {"id": 7, "path": "acme/web", "ref": "main", "ref_is_default": True,
         "last_activity_at": "2026-07-10T00:00:00Z", "head_sha": "abc123",
         "provenance": {"engine": "opengrep"}}


def test_assembles_all_buckets():
    part = {"runtimes": [_rt("php", "^8.2")],
            "frameworks": [_lib("composer", "laravel/framework", "^12.0")],
            "sdks": [_lib("npm", "axios", "^1.6", "package.json")]}
    eps = [{"vendor": "Stripe", "domain": "api.stripe.com", "version": "v1",
            "techKey": "api:stripe", "example": "...", "file_count": 1, "files": ["a.php:2"]}]
    rec = to_superset_repo(_META, part, eps)
    assert rec["id"] == 7 and rec["head_sha"] == "abc123" and rec["ref_is_default"] is True
    assert rec["runtimes"] == {"php": {"range": "^8.2", "techKey": "runtime:php", "parseQuality": "unlocked"}}
    assert rec["frameworks"]["laravel/framework"] == {"ver": "^12.0", "techKey": "lib:composer/laravel/framework", "parseQuality": "unlocked"}
    assert rec["sdks"][0] == {"eco": "npm", "pkg": "axios", "ver": "^1.6", "file": "package.json",
                              "techKey": "lib:npm/axios", "parseQuality": "unlocked"}
    assert rec["endpoints"] == eps
    assert rec["provenance"] == {"engine": "opengrep"} and rec["tree_walk_truncated"] is False


def test_runtime_dedup_keeps_best_quality(tmp_path):
    part = {"runtimes": [_rt("php", "18", "best_effort"), _rt("php", "^8.2", "exact")],
            "frameworks": [], "sdks": []}
    rec = to_superset_repo(_META, part, [])
    assert rec["runtimes"]["php"]["parseQuality"] == "exact" and rec["runtimes"]["php"]["range"] == "^8.2"
