from agent.lib.inv_rollups import build_rollups


def _repo(**kw):
    base = {"runtimes": {}, "frameworks": {}, "sdks": [], "endpoints": []}
    base.update(kw)
    return base


def test_rollups_dedup_and_sort():
    repos = [
        _repo(runtimes={"php": {"range": "^8.2", "techKey": "runtime:php", "parseQuality": "unlocked"}},
              frameworks={"laravel/framework": {"ver": "^12.0", "techKey": "lib:composer/laravel/framework", "parseQuality": "unlocked"}},
              sdks=[{"eco": "npm", "pkg": "axios", "ver": "^1.6", "file": "p", "techKey": "lib:npm/axios", "parseQuality": "unlocked"}],
              endpoints=[{"vendor": "Stripe", "version": "v1", "techKey": "api:stripe"}]),
        _repo(runtimes={"php": {"range": "^8.3", "techKey": "runtime:php", "parseQuality": "unlocked"}},
              sdks=[{"eco": "npm", "pkg": "axios", "ver": "^1.6", "file": "p", "techKey": "lib:npm/axios", "parseQuality": "unlocked"}],
              endpoints=[{"vendor": "Stripe", "version": "v2", "techKey": "api:stripe"},
                         {"vendor": "eBay", "version": None, "techKey": "api:ebay"}]),
    ]
    r = build_rollups(repos)
    assert r["unique_apis"] == ["Stripe", "eBay"] or r["unique_apis"] == sorted(["Stripe", "eBay"])
    assert {"vendor": "Stripe", "version": "v1"} in r["unique_api_versions"]
    assert {"vendor": "Stripe", "version": "v2"} in r["unique_api_versions"]
    assert all(v["version"] for v in r["unique_api_versions"])                # None dropped (eBay)
    assert {"eco": "npm", "pkg": "axios"} in r["unique_packages"]             # deduped across repos
    assert len([p for p in r["unique_packages"] if p["pkg"] == "axios"]) == 1
    assert {"eco": "composer", "pkg": "laravel/framework"} in r["unique_packages"]  # framework eco from techKey
    assert r["runtimes"]["php"] == ["^8.2", "^8.3"]
