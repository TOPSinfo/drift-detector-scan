from agent.lib.inventory_models import InventoryRecord
from agent.lib.record_routing import partition_records


def _lib(eco, name):
    return InventoryRecord(repo="r", manifest_path="m", ecosystem=eco,
                           tech_key=f"lib:{eco}/{name.lower()}", name=name, kind="library",
                           declared_range="^1.0")


def _rt(product, hint):
    return InventoryRecord(repo="r", manifest_path="m", ecosystem="composer",
                           tech_key=f"runtime:{product}", name=product, kind="runtime",
                           version_hint=hint)


def test_partitions_into_runtimes_frameworks_sdks():
    records = [
        _rt("php", "^8.2"),
        _lib("composer", "laravel/framework"),   # framework
        _lib("composer", "guzzlehttp/guzzle"),   # sdk
        _lib("npm", "react"),                     # framework
        _lib("npm", "axios"),                     # sdk
    ]
    part = partition_records(records)
    assert [r.name for r in part["runtimes"]] == ["php"]
    assert {r.name for r in part["frameworks"]} == {"laravel/framework", "react"}
    assert {r.name for r in part["sdks"]} == {"guzzlehttp/guzzle", "axios"}


def test_empty_and_unknown_kinds():
    assert partition_records([]) == {"runtimes": [], "frameworks": [], "sdks": []}
    weird = InventoryRecord(repo="r", manifest_path="m", ecosystem="npm",
                            tech_key="x", name="x", kind="mystery")
    assert partition_records([weird]) == {"runtimes": [], "frameworks": [], "sdks": []}


def test_order_preserved_within_bucket():
    records = [_lib("npm", "axios"), _lib("npm", "lodash"), _lib("npm", "moment")]
    assert [r.name for r in partition_records(records)["sdks"]] == ["axios", "lodash", "moment"]
