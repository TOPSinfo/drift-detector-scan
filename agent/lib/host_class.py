"""Deterministic triage of UNCATALOGUED egress hosts into a hostClass (the M1 classifier).

Turns the "wall of unknowns" into a ranked list: real API leads on top, noise bucketed but NEVER
hidden. hostClass is orthogonal to vendor classification — nothing here sets classified/vendor/a
date; catalogued vendors are handled upstream and always get `api`, so this is only ever asked
about the *rest*.

Reviewed reputation catalog first (hand-curated; NO imported blocklist — see the plan's "Decision:
no imported blocklist"), then URL-shape + call-context heuristics. An unknown host errs toward being
SHOWN (`unclassified`), never hidden. A tracker that ships a real, versioned API (segment, mixpanel,
…) is deliberately absent from the catalog so it stays attention-worthy rather than pre-buried.
"""
from __future__ import annotations
import os
import re
import yaml

# The closed vocabulary — one shared set across endpoints.py (write), dashboard_render.py
# (project+count), verify.py (check) and the cockpit (group). No name drift.
VOCAB = {"api", "api-lead", "social-widget", "asset-cdn", "analytics",
         "vendored-lib", "boilerplate", "own-infra", "unclassified"}

# Classes that are NOT third-party service integrations — bundled assets/libs, schema/doc hosts, and
# the repo's OWN infrastructure. Everything else (api / api-lead / social-widget / analytics /
# unclassified) is a found integration the cockpit surfaces; these are shown + counted, just outside
# the integration total.
_NON_INTEGRATION = {"asset-cdn", "vendored-lib", "boilerplate", "own-infra"}

# Account-specific cloud endpoints — always the deployer's OWN infra, never a third party you
# integrate WITH (the random subdomain is assigned to your cloud account). Serverless/PaaS hosts too.
_OWN_CLOUD = re.compile(
    r"(execute-api\.[a-z0-9-]+\.amazonaws\.com|amazoncognito\.com|appsync-api\.[a-z0-9-]+\.amazonaws\.com"
    r"|cloudfunctions\.net|\.run\.app|workers\.dev|azurewebsites\.net|herokuapp\.com|vercel\.app"
    r"|netlify\.app|pages\.dev)$", re.I)

_REPUTATION_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "host_reputation.yaml")
_CACHE = None

# share/messaging URL grammars (host-INDEPENDENT): these paths ARE the button, not an API call
_SHARE_PATHS = re.compile(r"/(intent[/?]|share[/?]|pin/create|sharer|dialog/|tweet)", re.I)
_API_LABEL = re.compile(r"(^|\.|-)api(\.|-|$)", re.I)   # api. / .api. / -api. / api- host label
_API_PATH = re.compile(r"/(v[0-9]+|rest|graphql|oauth|api)(/|$|\?)", re.I)
_ASSET_EXT = re.compile(r"\.(png|jpe?g|gif|svg|webp|woff2?|ttf|eot|css|js|ico|mp4|pdf)(\?|$)", re.I)
_ASSET_FILE_EXTS = {".css", ".scss", ".less"}


def is_integration(host_class: str) -> bool:
    """A found third-party integration worth surfacing (vs. a bundled asset/library/schema host)."""
    return host_class in VOCAB and host_class not in _NON_INTEGRATION


def _load() -> dict:
    global _CACHE
    if _CACHE is None:
        with open(_REPUTATION_FILE, encoding="utf-8") as fh:
            doc = yaml.safe_load(fh) or {}
        table = {}
        for host_class, hosts in doc.items():
            if host_class == "meta" or not isinstance(hosts, list):
                continue
            for h in hosts:
                table[str(h).lower()] = host_class
        _CACHE = table
    return _CACHE


def _reputation(host: str) -> str | None:
    table = _load()
    h = (host or "").lower()
    # exact + registrable-suffix match (mirrors classify_url's suffix rule)
    while h:
        if h in table:
            return table[h]
        h = h.split(".", 1)[1] if "." in h else ""
    return None


def classify(host: str, *, url: str | None = None, in_call: bool = False,
             file_ext: str | None = None) -> str:
    """Return the hostClass for an UNCATALOGUED host (always a member of VOCAB).

    `in_call` — the URL was matched inside an HTTP-client call (vs. an href/src/CSS url()).
    `file_ext` — the source file's extension (a `.css`/`.scss` origin biases toward a static asset).
    """
    rep = _reputation(host)
    if rep:
        return rep
    u = url or ""
    host = host or ""
    if _OWN_CLOUD.search(host):
        return "own-infra"                 # your own cloud backend (Cognito, API GW, serverless…)
    if _SHARE_PATHS.search(u):
        return "social-widget"
    if (file_ext or "").lower() in _ASSET_FILE_EXTS or _ASSET_EXT.search(u):
        return "asset-cdn"
    # an api. / api- host is a strong API signal on its own (api.keepa.com, geocode-api.arcgis.com);
    # a versioned/REST path counts as a lead when it shows up in a real client call. Either way it
    # rises above the residue instead of hiding in "pending audit".
    if _API_LABEL.search(host) or (in_call and _API_PATH.search(u)):
        return "api-lead"
    # an unknown host is still a third-party the code reaches — SHOW it as found/pending-audit
    return "unclassified"
