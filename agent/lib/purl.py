"""Map our (ecosystem, package, version) tuples to OSV ecosystem names and Package URLs (PURLs).

PURLs are the standard component identifier used by CycloneDX and most SCA tooling.
"""
from __future__ import annotations

# our inventory ecosystem -> OSV.dev ecosystem name
OSV_ECOSYSTEM = {"npm": "npm", "composer": "Packagist", "python": "PyPI", "go": "Go", "maven": "Maven", "nuget": "NuGet", "bundler": "RubyGems", "cargo": "crates.io"}
# our inventory ecosystem -> PURL type
_PURL_TYPE = {"npm": "npm", "composer": "composer", "python": "pypi", "go": "golang", "maven": "maven", "nuget": "nuget", "bundler": "gem", "cargo": "cargo"}


def osv_ecosystem(eco: str) -> str | None:
    return OSV_ECOSYSTEM.get(eco)


def to_purl(eco: str, name: str, version: str | None) -> str | None:
    """`pkg:npm/axios@0.21.1`, `pkg:composer/laravel/framework@12.0`, `pkg:pypi/torch@1.1.0`."""
    ptype = _PURL_TYPE.get(eco)
    if not ptype or not name:
        return None
    n = name
    if ptype == "pypi":                       # PyPI normalizes: lowercase, _ -> -
        n = n.lower().replace("_", "-")
    if ptype == "npm" and n.startswith("@"):  # scoped npm: encode the leading @
        n = "%40" + n[1:]
    if ptype == "maven":
        # Our inventory name is `groupId:artifactId`; the PURL spec separates them with a
        # SLASH (pkg:maven/org.foo/bar@1). The colon form does not match in OSV, so a
        # record would look audited while never being looked up.
        n = n.replace(":", "/", 1)
    purl = f"pkg:{ptype}/{n}"
    if version:
        purl += f"@{version}"
    return purl
