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
