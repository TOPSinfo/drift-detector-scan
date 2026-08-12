"""A client's own hostnames can never be catalogued — agent/host_reputation.yaml ships in a PUBLIC
repo — and cannot be pattern-guessed, because a `cdn.*` rule would claim a genuine CDN vendor. They
are derived from the repo being scanned.

The signals were chosen against a real repo, after the obvious ones were measured and REJECTED:
its .env.example had APP_URL=http://localhost and its composer.json name was the framework default
`laravel/laravel`. Config-derived inference produced nothing at all.
"""
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
