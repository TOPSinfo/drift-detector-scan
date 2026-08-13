"""A client's own hostnames can never be catalogued — agent/host_reputation.yaml ships in a PUBLIC
repo — and cannot be pattern-guessed, because a `cdn.*` rule would claim a genuine CDN vendor. They
are derived from the repo being scanned.

The signals were chosen against a real repo, after the obvious ones were measured and REJECTED:
its .env.example had APP_URL=http://localhost and its composer.json name was the framework default
`laravel/laravel`. Config-derived inference produced nothing at all.
"""
import pytest

from agent.lib import own_infra


def _sig():
    return own_infra.signals(repo_path="/srv/checkouts/promoteplus-crm",
                             repo_id="https://git.topsdemo.in/root/promoteplus-crm.git")


def test_repo_name_token_catches_the_clients_own_hosts():
    sig = _sig()
    assert sig["tokens"] == {"promoteplus"}          # `crm` is generic and too short
    for host in ("crm.promoteplus.ai", "promotepluscdn.com", "qa-promoteplus-idx.topsdemo.in"):
        assert own_infra.is_own(host, sig), host


def test_self_hosted_forge_domain_is_own_infra():
    sig = _sig()
    assert "topsdemo.in" in sig["domains"]
    assert own_infra.is_own("anything.topsdemo.in", sig)


def test_a_public_forge_is_never_treated_as_own_infra():
    """The decisive negative. A github.com remote would otherwise make the registrable domain
    `github.com` own-infra, silently suppressing every github.com host in every repo."""
    sig = own_infra.signals(repo_path="/srv/acme-shop",
                            repo_id="https://github.com/acme/acme-shop.git")
    assert sig["domains"] == set()
    assert not own_infra.is_own("api.github.com", sig)
    assert not own_infra.is_own("raw.githubusercontent.com", sig)


def test_real_vendor_hosts_are_never_claimed():
    sig = _sig()
    for host in ("api.justcall.io", "hooks.zapier.com", "api.mailgun.net",
                 "graph.microsoft.com", "api.openai.com"):
        assert not own_infra.is_own(host, sig), host


def test_descriptive_integration_words_are_generic_not_a_claim():
    """F3: `shipping-tracker-app` describes what the repo DOES ('tracker'), not who it belongs
    to, and must not claim a real vendor host that happens to share that generic word.
    Measured: shipping-tracker-app -> tracker.aftership.com was falsely own-infra."""
    sig = own_infra.signals(repo_path="/srv/shipping-tracker-app")
    assert sig["tokens"] == set()
    assert not own_infra.is_own("tracker.aftership.com", sig)


@pytest.mark.parametrize("repo_path,host", [
    ("/srv/acme-hubspot-connector", "connector.example.io"),
    ("/srv/acme-payments-gateway", "gateway.stripe.com"),
    ("/srv/acme-invoice-manager", "manager.xero.com"),
    ("/srv/order-bridge-service", "bridge.shopify.com"),
])
def test_generic_integration_nouns_never_become_a_token(repo_path, host):
    """Each of these >=6-char descriptive words (F3's stop-list additions) names the repo's
    SHAPE, never an organisation, so a host sharing the word must stay unclaimed."""
    sig = own_infra.signals(repo_path=repo_path)
    assert not own_infra.is_own(host, sig)


def test_short_and_generic_names_yield_no_token():
    """Failing toward SHOWN. A repo called `crm` or `laravel-api` produces no usable token, so its
    hosts stay queued rather than being suppressed by a 3-letter substring match."""
    assert own_infra.signals(repo_path="/srv/crm")["tokens"] == set()
    assert own_infra.signals(repo_path="/srv/laravel-api")["tokens"] == set()
    assert own_infra.signals(repo_path="/srv/web-portal")["tokens"] == set()


def test_no_signals_means_no_claims():
    sig = own_infra.signals()
    assert sig == {"tokens": set(), "domains": set()}
    assert not own_infra.is_own("crm.promoteplus.ai", sig)


def test_vendor_named_repo_does_not_suppress_that_vendors_host():
    """A repo literally named after its vendor (`acme-mailgun-sync`) must not swallow that
    vendor's host once the caller supplies the vendor-name tokens."""
    sig = own_infra.signals(repo_path="/srv/acme-mailgun-sync",
                            repo_id="https://git.topsdemo.in/root/acme-mailgun-sync.git",
                            vendor_tokens=frozenset({"mailgun"}))
    assert "mailgun" not in sig["tokens"]
    assert not own_infra.is_own("api.mailgun.net", sig)


def test_registrable_handles_multi_part_public_suffix():
    """`co.uk` (and friends) are public suffixes, not organisations — the org label sits one
    level above them, so `git.example.co.uk` must register as `example.co.uk`, not `co.uk`."""
    sig = own_infra.signals(repo_id="https://git.example.co.uk/root/example.git")
    assert sig["domains"] == {"example.co.uk"}
    assert own_infra.is_own("anything.example.co.uk", sig)
    assert not own_infra.is_own("othervendor.co.uk", sig)


def test_bare_multi_part_suffix_yields_no_domain():
    """A host that IS the public suffix, with no organisation label above it, must not become
    own-infra — a public suffix is not an organisation."""
    sig = own_infra.signals(repo_id="https://co.uk/root/example.git")
    assert sig["domains"] == set()


def test_two_label_public_suffix_general_rule_not_hardcoded():
    """Any {generic-second-level}.{cctld} pair is a public suffix (not an organisation) even
    when it isn't on an explicit list — com.cn, co.kr, gov.uk, etc. Previously only a ~20-entry
    hardcoded `_MULTI_PART_SUFFIXES` list was checked, so an unlisted suffix silently became the
    "registrable domain" and suppressed every unrelated vendor parked under it."""
    cases = {
        "https://git.example.com.cn/g/r.git": "example.com.cn",
        "https://git.example.co.kr/g/r.git": "example.co.kr",
        "https://git.example.gov.uk/g/r.git": "example.gov.uk",
    }
    for repo_id, expected_domain in cases.items():
        sig = own_infra.signals(repo_id=repo_id)
        assert sig["domains"] == {expected_domain}, (repo_id, sig)

    # the bug as verified live: an unrelated vendor parked under the same bare suffix must never
    # be claimed as this repo's own infra.
    sig = own_infra.signals(repo_id="https://git.example.com.cn/g/r.git")
    assert not own_infra.is_own("vendor.com.cn", sig)


def test_bare_two_label_public_suffix_remote_yields_no_domain():
    """A remote host that IS a general-rule public suffix (e.g. `com.cn`, `co.kr`, `gov.uk`),
    with no organisation label above it, must not become own-infra — same failure-toward-SHOWN
    as the hardcoded `co.uk` case below."""
    for host in ("com.cn", "co.kr", "gov.uk"):
        sig = own_infra.signals(repo_id=f"https://{host}/root/example.git")
        assert sig["domains"] == set(), host


def test_genuine_org_domains_still_resolve_correctly():
    """The general rule must not swallow real organisation domains — only the public-suffix
    label pair is special-cased, the label above it still comes through."""
    assert own_infra.signals(repo_id="https://git.topsdemo.in/root/x.git")["domains"] == {"topsdemo.in"}
    assert own_infra.signals(repo_id="https://git.acme.co.uk/root/x.git")["domains"] == {"acme.co.uk"}


def test_repo_token_that_contains_a_vendor_token_is_also_dropped():
    """Critical bug: the original guard only dropped a derived token on EXACT equality with a
    vendor token. A repo token that CONTAINS a vendor token (`globalpaymentsapi` contains
    `globalpayments`) never compares equal, so it survived and silently claimed the vendor's
    own host as own-infra. A repo token that contains a vendor's name is still that vendor's
    name; over-dropping is the SAFE direction, since a dropped token just leaves the host
    visible in the queue, whereas a kept one deletes a real vendor from the backlog."""
    sig = own_infra.signals(repo_path="/srv/acme-globalpaymentsapi-bridge",
                            repo_id="https://git.topsdemo.in/root/acme-globalpaymentsapi-bridge.git",
                            vendor_tokens=frozenset({"globalpayments"}))
    assert "globalpaymentsapi" not in sig["tokens"]
    assert not own_infra.is_own("api.globalpayments.com", sig)


def test_reason_names_the_signal_and_the_matched_value():
    """F1: the endpoint record must say WHY a host was claimed, not just tag it silently.
    The exact wording is a contract other modules (dashboard_render, md_render) parse via
    `is_token_claim`, so it is pinned here."""
    sig = _sig()
    assert own_infra.reason("crm.promoteplus.ai", sig) == "repo token 'promoteplus'"
    dsig = own_infra.signals(repo_id="https://git.topsdemo.in/root/promoteplus-crm.git")
    assert own_infra.reason("anything.topsdemo.in", dsig) == "git remote org domain 'topsdemo.in'"


def test_reason_is_none_when_no_signal_claims_the_host():
    sig = _sig()
    assert own_infra.reason("api.justcall.io", sig) is None


def test_is_token_claim_distinguishes_the_weak_signal():
    """The distinction F1 hinges on: a token claim is a heuristic on the repo's own name and must
    not be treated the same as the strong git-remote org-domain claim."""
    assert own_infra.is_token_claim("repo token 'promoteplus'")
    assert not own_infra.is_token_claim("git remote org domain 'topsdemo.in'")
    assert not own_infra.is_token_claim(None)
    assert not own_infra.is_token_claim("")


def test_dev_azure_com_remote_is_not_own_infra():
    """`dev.azure.com`'s registrable form (`azure.com`) is not itself in `_PUBLIC_FORGES`, so the
    full remote host must also be checked or an Azure DevOps remote makes `azure.com` — and
    hence `management.azure.com` — falsely own-infra."""
    sig = own_infra.signals(repo_path="/srv/example",
                            repo_id="https://dev.azure.com/org/example/_git/example")
    assert sig["domains"] == set()
    assert not own_infra.is_own("management.azure.com", sig)
