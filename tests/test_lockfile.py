import json

from agent.lib import lockfile
from agent.audit import audit_inventory


def test_composer_lock():
    content = json.dumps({"packages": [{"name": "Laravel/Framework", "version": "v12.3.1"}],
                          "packages-dev": [{"name": "phpunit/phpunit", "version": "11.0.0"}]})
    out = lockfile.parse_lockfiles({"composer.lock": content})
    assert out[("composer", "laravel/framework")] == "12.3.1"      # lowercased, v stripped
    assert out[("composer", "phpunit/phpunit")] == "11.0.0"


def test_package_lock_v3_and_v1():
    v3 = json.dumps({"packages": {
        "": {"name": "root"},
        "node_modules/axios": {"version": "1.7.4"},
        "node_modules/@headlessui/react": {"version": "2.2.0"},
        "node_modules/axios/node_modules/follow-redirects": {"version": "1.15.0"}}})   # nested -> ignored
    out = lockfile.parse_lockfiles({"package-lock.json": v3})
    assert out[("npm", "axios")] == "1.7.4" and out[("npm", "@headlessui/react")] == "2.2.0"
    assert ("npm", "follow-redirects") not in out

    v1 = json.dumps({"dependencies": {"axios": {"version": "0.21.4"}}})
    assert lockfile.parse_lockfiles({"package-lock.json": v1})[("npm", "axios")] == "0.21.4"


def test_yarn_lock():
    content = (
        '"axios@^0.21.1", axios@~0.21.0:\n'
        '  version "0.21.4"\n'
        '  resolved "https://…"\n\n'
        '"@babel/core@^7.0.0":\n'
        '  version "7.24.0"\n')
    out = lockfile.parse_lockfiles({"yarn.lock": content})
    assert out[("npm", "axios")] == "0.21.4" and out[("npm", "@babel/core")] == "7.24.0"


def test_poetry_and_pipfile_and_requirements():
    poetry = '[[package]]\nname = "Requests"\nversion = "2.32.0"\n\n[[package]]\nname = "torch"\nversion = "2.1.0"\n'
    out = lockfile.parse_lockfiles({"poetry.lock": poetry})
    assert out[("python", "requests")] == "2.32.0" and out[("python", "torch")] == "2.1.0"

    pip = json.dumps({"default": {"Django": {"version": "==4.2.0"}}, "develop": {"pytest": {"version": "==8.0"}}})
    assert lockfile.parse_lockfiles({"Pipfile.lock": pip})[("python", "django")] == "4.2.0"

    req = "torch==1.1.0\nnumpy>=1.17  # not pinned -> skipped\nOpenCV_Python==4.1.0\n"
    out = lockfile.parse_lockfiles({"requirements.txt": req})
    assert out[("python", "torch")] == "1.1.0" and out[("python", "opencv-python")] == "4.1.0"
    assert ("python", "numpy") not in out


def test_malformed_lockfile_skipped():
    assert lockfile.parse_lockfiles({"composer.lock": "{not json"}) == {}
    assert lockfile.parse_lockfiles({"unknown.file": "x"}) == {}


def test_audit_uses_resolved_version_over_manifest_floor():
    # sdk declares ^0.21.1 but the lockfile resolved to a patched 1.7.4 -> query the patched version
    doc = {"repos": [{"path": "web", "sdks": [
        {"eco": "npm", "pkg": "axios", "ver": "^0.21.1", "resolved": "1.7.4", "versionSource": "lockfile"}]}]}
    seen = {}

    def fake_osv(eco, name, version, *, http=None):
        seen["version"] = version
        return []

    out = audit_inventory(doc, "2026-07-15", http=lambda *a, **k: {},
                          osv_query=fake_osv, eol_check=lambda *a, **k: None)
    assert seen["version"] == "1.7.4"                              # not "0.21.1" (the floor)


# ── NuGet: packages.lock.json supplies the resolved version for the csproj sdk row ──

NUGET_LOCK = json.dumps({
    "version": 1,
    "dependencies": {
        ".NETCoreApp,Version=v8.0": {
            "Newtonsoft.Json": {"type": "Direct", "requested": "[13.0.1, )", "resolved": "13.0.3"},
            "SomeTransitive": {"type": "Transitive", "resolved": "1.2.3"},
        },
        ".NETStandard,Version=v2.0": {
            "Newtonsoft.Json": {"type": "Direct", "requested": "[12.0.0, )", "resolved": "12.0.9"},
        },
    },
})


def test_nuget_lockfile_resolves_a_direct_package():
    out = lockfile.parse_lockfiles({"packages.lock.json": NUGET_LOCK})
    assert out[("nuget", "Newtonsoft.Json")] == "13.0.3"


def test_nuget_transitives_are_not_in_the_map():
    """A transitive is not one of THIS repo's declared sdks — the same line cargo draws.
    Putting it in the map would let it join onto nothing, or worse, onto a same-named
    direct dependency somewhere else."""
    out = lockfile.parse_lockfiles({"packages.lock.json": NUGET_LOCK})
    assert ("nuget", "SomeTransitive") not in out


def test_the_first_target_framework_wins_when_a_package_spans_several():
    """The same package resolves separately per TFM. First-wins matches npm v1's
    setdefault; picking the max would state a version no single build produced."""
    out = lockfile.parse_lockfiles({"packages.lock.json": NUGET_LOCK})
    assert out[("nuget", "Newtonsoft.Json")] == "13.0.3"


def test_nuget_ids_keep_their_case():
    """InventoryRecord.name is `Newtonsoft.Json` verbatim from the csproj, and the join
    keys on norm(eco, pkg). Lowercasing nuget the way npm-style ecosystems do would make
    every nuget join miss silently — the sdk would fall back to the manifest floor and
    look like a repo with no lockfile."""
    assert lockfile.norm("nuget", "Newtonsoft.Json") == "Newtonsoft.Json"


def test_malformed_nuget_lockfile_is_skipped():
    assert lockfile.parse_lockfiles({"packages.lock.json": "{not json"}) == {}


def test_the_nuget_join_key_matches_what_annotate_resolved_looks_up():
    """The map is only useful if repo_scan._annotate_resolved can find it. That function
    does `resolved.get((s["eco"], lockfile.norm(s["eco"], s["pkg"])))` — this reproduces
    that exact lookup against a csproj-shaped sdk row declaring the 13.0.1 floor."""
    resolved = lockfile.parse_lockfiles({"packages.lock.json": NUGET_LOCK})
    sdk = {"eco": "nuget", "pkg": "Newtonsoft.Json", "ver": "13.0.1"}
    exact = resolved.get((sdk["eco"], lockfile.norm(sdk["eco"], sdk["pkg"])))
    assert exact == "13.0.3", "the csproj sdk row would stay on the manifest floor"
