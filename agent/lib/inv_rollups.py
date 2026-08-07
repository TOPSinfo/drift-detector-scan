"""Top-level rollups: dedup APIs / API versions / packages / package versions / runtimes across repos."""
from __future__ import annotations


def _eco_from_techkey(tk: str) -> str:
    # "lib:composer/laravel/framework" -> "composer"
    return tk.split(":", 1)[1].split("/", 1)[0] if tk.startswith("lib:") else ""


def build_rollups(repos: list) -> dict:
    apis: set = set()
    api_versions: set = set()
    packages: set = set()
    package_versions: set = set()
    runtimes: dict = {}

    for repo in repos:
        for ep in repo.get("endpoints", []):
            v = ep.get("vendor", "")
            if v:
                apis.add(v)
            if ep.get("version"):
                api_versions.add((v, ep["version"]))
        for pkg in repo.get("sdks", []):
            packages.add((pkg["eco"], pkg["pkg"]))
            package_versions.add((pkg["eco"], pkg["pkg"], pkg.get("ver", "")))
        for name, fw in repo.get("frameworks", {}).items():
            eco = _eco_from_techkey(fw.get("techKey", ""))
            packages.add((eco, name))
            package_versions.add((eco, name, fw.get("ver", "")))
        for product, rt in repo.get("runtimes", {}).items():
            if rt.get("range"):
                runtimes.setdefault(product, set()).add(rt["range"])

    return {
        "unique_apis": sorted(apis),
        "unique_api_versions": [{"vendor": v, "version": ver} for v, ver in sorted(api_versions)],
        "unique_packages": [{"eco": e, "pkg": p} for e, p in sorted(packages)],
        "unique_package_versions": [{"eco": e, "pkg": p, "ver": vr} for e, p, vr in sorted(package_versions)],
        "runtimes": {p: sorted(cs) for p, cs in sorted(runtimes.items())},
    }
