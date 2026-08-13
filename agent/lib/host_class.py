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

from agent.lib import own_infra

# The closed vocabulary — one shared set across endpoints.py (write), dashboard_render.py
# (project+count), verify.py (check) and the cockpit (group). No name drift.
VOCAB = {"api", "api-lead", "social-widget", "asset-cdn", "analytics",
         "vendored-lib", "boilerplate", "own-infra", "unclassified"}

# The API-integration audit backlog is api / api-lead / unclassified — the real services whose
# retirements you track. Everything else is SHOWN in the inventory (typed by kindOf) but is not part
# of that backlog: social-widget + analytics are third-party WIDGETS (a share embed / a tracker pixel,
# not an API you version-track), and asset-cdn / vendored-lib / boilerplate / own-infra aren't
# third-party services at all. So "integrations" == tracked + untracked, a clean partition.
_NON_INTEGRATION = {"social-widget", "analytics", "asset-cdn", "vendored-lib", "boilerplate", "own-infra"}

# Account-specific cloud endpoints — always the deployer's OWN infra, never a third party you
# integrate WITH (the random subdomain is assigned to your cloud account). Serverless/PaaS hosts too.
_OWN_CLOUD = re.compile(
    r"(execute-api\.[a-z0-9-]+\.amazonaws\.com|amazoncognito\.com|appsync-api\.[a-z0-9-]+\.amazonaws\.com"
    r"|cloudfunctions\.net|\.run\.app|workers\.dev|azurewebsites\.net|herokuapp\.com|vercel\.app"
    r"|netlify\.app|pages\.dev"
    # dynamic-DNS providers — a host here is almost always a SELF-HOSTED box, not a third party you
    # integrate with (generic rule, so a client's own dyn-dns host is caught without naming it).
    r"|mooo\.com|no-ip\.(com|org|biz|info)|duckdns\.org|dyndns\.org|hopto\.org|ddns\.net|freedns\.org)$", re.I)

_REPUTATION_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "host_reputation.yaml")
_CACHE = None

# share/messaging URL grammars (host-INDEPENDENT): these paths ARE the button, not an API call
_SHARE_PATHS = re.compile(r"/(intent[/?]|share[/?]|pin/create|sharer|dialog/|tweet)", re.I)
_API_LABEL = re.compile(r"(^|\.|-)api(\.|-|$)", re.I)   # api. / .api. / -api. / api- host label
_API_PATH = re.compile(r"/(v[0-9]+|rest|graphql|oauth|api)(/|$|\?)", re.I)
_ASSET_EXT = re.compile(r"\.(png|jpe?g|gif|svg|webp|woff2?|ttf|eot|css|js|ico|mp4|pdf)(\?|$)", re.I)
_ASSET_FILE_EXTS = {".css", ".scss", ".less"}


def is_integration(host_class: str, own_infra_reason: str | None = None) -> bool:
    """A found third-party integration worth surfacing (vs. a bundled asset/library/schema host).

    `own_infra_reason` — the endpoint's `ownInfraReason` (own_infra.reason()'s output), if any.
    M1: an own-infra host claimed only by the WEAK repo-name-token signal (own_infra.is_token_claim)
    is not certain enough to drop out of the audit backlog — dashboard_render._coverage already
    keeps it `queued` for that exact reason, so the headline counters must count it too, or the
    tile and the research work-list disagree about the same host. A domain-claimed own-infra host,
    or one with no reason at all (the unrelated _tag_own_infra multi-host heuristic), keeps the
    original behaviour: excluded. Callers that don't pass a reason keep the original class-only
    result, so pre-existing call sites are unaffected.
    """
    if host_class not in VOCAB:
        return False
    if host_class not in _NON_INTEGRATION:
        return True
    return host_class == "own-infra" and own_infra.is_token_claim(own_infra_reason)


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
             file_ext: str | None = None, own: dict | None = None) -> str:
    """Return the hostClass for an UNCATALOGUED host (always a member of VOCAB).

    `in_call` — the URL was matched inside an HTTP-client call (vs. an href/src/CSS url()).
    `file_ext` — the source file's extension (a `.css`/`.scss` origin biases toward a static asset).
    `own` — this repo's own-infrastructure signals (agent.lib.own_infra.signals). Optional; absent
    means no host is claimed as own-infra, which is exactly the pre-existing behaviour.
    """
    host = host or ""
    if _OWN_CLOUD.search(host):
        return "own-infra"                 # your own cloud backend (Cognito, API GW, serverless…)
    # BEFORE the api-label rule on purpose: `api.<client>.com` is the client's OWN API, not a
    # third-party lead. A catalogued vendor never reaches here (endpoints.py sets `api` upstream),
    # so a client whose name collides with a vendor cannot suppress that vendor.
    if own and own_infra.is_own(host, own):
        return "own-infra"
    # an api. / -api. / api- host is a real API even UNDER a reputationed parent domain — so
    # business-api.tiktok.com is the TikTok API, not "social"; api.cloudflare.com is a lead, not a CDN.
    # (This also enforces the no-pre-bury rule: an api. tracker never sinks into the analytics panel.)
    if _API_LABEL.search(host):
        return "api-lead"
    rep = _reputation(host)
    if rep:
        return rep
    u = url or ""
    if _SHARE_PATHS.search(u):
        return "social-widget"
    if (file_ext or "").lower() in _ASSET_FILE_EXTS or _ASSET_EXT.search(u):
        return "asset-cdn"
    if in_call and _API_PATH.search(u):    # a versioned/REST path in a real client call is a lead
        return "api-lead"
    # an unknown host is still a third-party the code reaches — SHOW it as found/pending-audit
    return "unclassified"
