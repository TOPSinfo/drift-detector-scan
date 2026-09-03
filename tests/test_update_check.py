"""The every-run half of the freshness check.

`doctor` has been able to say "this install is BEHIND" since 1.0.0, and nothing ever runs
doctor: the guided flow does not call it, so a stale install stays invisible exactly where it
matters — inside the scan whose behaviour it changes. This is the always-on half.

Its whole design problem is that the scanner's contract is OFFLINE and BYTE-REPRODUCIBLE. A
per-run network call that can slow a scan, change its output, or fail it would trade a real
guarantee for a convenience. So every test here is about what the check must NOT do.
"""
import io
import json
import os
import time

import pytest

from agent.lib import update_check


def _cache(tmp_path):
    return str(tmp_path / "update-check.json")


# ---------- what it says, and when it stays quiet ----------

def test_it_speaks_only_when_the_install_is_behind(tmp_path):
    """A line on every run is noise that trains people to ignore it. Current = silence."""
    assert update_check.advisory("1.1.0", "1.1.0") is None
    assert update_check.advisory("1.2.0", "1.1.0") is None
    msg = update_check.advisory("1.0.0", "1.1.0")
    assert msg and "BEHIND" in msg and "1.1.0" in msg


def test_an_unparseable_version_is_silence_not_a_warning(tmp_path):
    """freshness_check refuses to guess; the advisory must not turn 'could not check' into a
    visible nag. A false staleness warning is worse than none."""
    assert update_check.advisory("", "1.1.0") is None
    assert update_check.advisory("1.0.0", "") is None
    assert update_check.advisory("not-a-version", "1.1.0") is None


# ---------- the cache: a fleet scan must not hammer the network ----------

def test_a_fresh_cache_is_used_without_touching_the_network(tmp_path):
    calls = []

    def fetch():
        calls.append(1)
        return json.dumps({"plugins": [{"name": "drift-detector", "version": "9.9.9"}]})

    p = _cache(tmp_path)
    assert update_check.published_version(fetch=fetch, cache_path=p, ttl=3600, now=1000) == "9.9.9"
    assert len(calls) == 1
    # Second call inside the TTL: served from disk, fetch NOT called again.
    assert update_check.published_version(fetch=fetch, cache_path=p, ttl=3600, now=2000) == "9.9.9"
    assert len(calls) == 1, "a cached answer must not re-fetch — 52 repos would mean 52 requests"


def test_the_cache_expires(tmp_path):
    calls = []

    def fetch():
        calls.append(1)
        return json.dumps({"plugins": [{"name": "drift-detector", "version": "9.9.9"}]})

    p = _cache(tmp_path)
    update_check.published_version(fetch=fetch, cache_path=p, ttl=3600, now=1000)
    update_check.published_version(fetch=fetch, cache_path=p, ttl=3600, now=1000 + 3601)
    assert len(calls) == 2


def test_a_corrupt_cache_is_a_miss_not_a_crash(tmp_path):
    p = _cache(tmp_path)
    with open(p, "w") as fh:
        fh.write("{not json at all")
    got = update_check.published_version(
        fetch=lambda: json.dumps({"plugins": [{"name": "drift-detector", "version": "2.0.0"}]}),
        cache_path=p, ttl=3600, now=1000)
    assert got == "2.0.0"


# ---------- offline is a non-event ----------

def test_offline_is_silent_and_never_raises(tmp_path):
    def fetch():
        raise OSError("network unreachable")

    assert update_check.published_version(fetch=fetch, cache_path=_cache(tmp_path),
                                          ttl=3600, now=1000) is None


def test_an_unwritable_cache_dir_does_not_break_the_check(tmp_path):
    """The answer still comes back; only the caching is lost. A read-only HOME (CI, container)
    must not turn an advisory into a failure."""
    got = update_check.published_version(
        fetch=lambda: json.dumps({"plugins": [{"name": "drift-detector", "version": "3.0.0"}]}),
        cache_path="/proc/nonexistent-dir/cache.json", ttl=3600, now=1000)
    assert got == "3.0.0"


def test_a_malformed_payload_is_silence(tmp_path):
    for payload in ("[]", "{}", '{"plugins": []}', '{"plugins": "nope"}', "null", "7"):
        assert update_check.published_version(fetch=lambda p=payload: p,
                                              cache_path=_cache(tmp_path / payload[:3]),
                                              ttl=0, now=1000) is None


def test_it_selects_the_named_plugin_not_index_zero(tmp_path):
    payload = json.dumps({"plugins": [{"name": "something-else", "version": "0.1.0"},
                                      {"name": "drift-detector", "version": "4.5.6"}]})
    assert update_check.published_version(fetch=lambda: payload, cache_path=_cache(tmp_path),
                                          ttl=3600, now=1000) == "4.5.6"


# ---------- the wiring: stderr only, opt-out, never fatal ----------

def test_the_notice_goes_to_stderr_never_stdout(tmp_path, monkeypatch):
    """stdout carries parsed output — drift.json, chat-summary, the SBOM. A version notice on
    stdout would corrupt a consumer that pipes it."""
    monkeypatch.delenv("DRIFT_NO_UPDATE_CHECK", raising=False)
    err = io.StringIO()
    update_check.report(installed="1.0.0", published="1.1.0", stream=err)
    assert "BEHIND" in err.getvalue()


def test_the_check_can_be_switched_off(tmp_path, monkeypatch):
    """Air-gapped CI and byte-reproducibility harnesses need a way to guarantee no network and
    no extra bytes. An always-on check with no off switch gets disabled by deleting the code."""
    monkeypatch.setenv("DRIFT_NO_UPDATE_CHECK", "1")
    assert update_check.disabled() is True
    err = io.StringIO()
    update_check.report(installed="1.0.0", published="1.1.0", stream=err)
    assert err.getvalue() == ""


def test_report_never_raises_whatever_it_is_given(tmp_path):
    """It runs before every subcommand. A crash here would take down a scan that has nothing to
    do with versions — the check must be strictly additive."""
    for a, b in [(None, None), ("", ""), (None, "1.0.0"), ("1.0.0", None),
                 (object(), "1.0.0"), ("1.0.0", object())]:
        update_check.report(installed=a, published=b, stream=io.StringIO())


def test_installed_version_comes_from_the_plugin_manifest():
    """The number it compares must be the shipped one, not a constant that drifts from it."""
    v = update_check.installed_version()
    assert v and v[0].isdigit(), f"expected a version from .claude-plugin/plugin.json, got {v!r}"


# ---------- the wiring: it must actually run, on EVERY subcommand ----------

def test_cli_main_runs_the_check_on_every_invocation(tmp_path, monkeypatch):
    """The whole point of 1.1.0's mechanism: `doctor` could always report a stale install and
    nothing ran doctor. If main() stops calling this, the check silently reverts to the
    doctor-only state it was built to replace, and no other test would notice."""
    from agent import cli

    monkeypatch.delenv("DRIFT_NO_UPDATE_CHECK", raising=False)
    calls = []
    monkeypatch.setattr(cli.update_check, "run", lambda *a, **k: calls.append(1))
    # `verify` on an empty state: a cheap subcommand that fails fast. We assert on the CHECK
    # having run, not on the subcommand's outcome.
    try:
        cli.main(["verify", "--state", str(tmp_path)])
    except SystemExit:
        pass
    assert calls == [1], "cli.main() must run the published-version check before dispatching"


def test_the_check_runs_before_the_subcommand_not_after(tmp_path, monkeypatch):
    """A notice printed after a long scan is a notice nobody connects to the run. It has to
    land before the work starts."""
    from agent import cli

    monkeypatch.delenv("DRIFT_NO_UPDATE_CHECK", raising=False)
    order = []
    monkeypatch.setattr(cli.update_check, "run", lambda *a, **k: order.append("check"))
    monkeypatch.setattr(cli, "_cmd_verify", lambda args: order.append("subcommand") or 0)
    cli.main(["verify", "--state", str(tmp_path)])
    assert order == ["check", "subcommand"]


# ---------- the fetcher: curl first, because urllib is not reliable where this runs ----------

def test_the_fetcher_falls_back_to_urllib_when_curl_is_unavailable(monkeypatch):
    """curl is preferred on evidence, not taste: on the machine this was built on, urllib died
    in the TLS handshake against the very URL curl fetched with a 200 in the same second. But a
    machine with no curl must still get an answer, so the fallback has to be live."""
    monkeypatch.setattr(update_check, "_fetch_curl",
                        lambda: (_ for _ in ()).throw(OSError("no curl")))
    monkeypatch.setattr(update_check, "_fetch_urllib", lambda: '{"plugins":[]}')
    assert update_check._http_fetch() == '{"plugins":[]}'


def test_both_transports_failing_is_silence_not_a_crash(monkeypatch, tmp_path):
    """Offline is a non-event. Neither transport working must look exactly like being current."""
    monkeypatch.setattr(update_check, "_fetch_curl",
                        lambda: (_ for _ in ()).throw(OSError("no curl")))
    monkeypatch.setattr(update_check, "_fetch_urllib",
                        lambda: (_ for _ in ()).throw(OSError("no net")))
    assert update_check.published_version(cache_path=str(tmp_path / "c.json"),
                                          ttl=3600, now=1000) is None
    assert update_check.run(stream=io.StringIO()) is None


def test_curl_is_tried_before_urllib(monkeypatch):
    """Order is the whole point of the finding. If urllib went first, the observed TLS timeout
    would burn the timeout budget on every check before curl ever ran."""
    order = []
    monkeypatch.setattr(update_check, "_fetch_curl",
                        lambda: order.append("curl") or '{"plugins":[]}')
    monkeypatch.setattr(update_check, "_fetch_urllib", lambda: order.append("urllib") or "{}")
    update_check._http_fetch()
    assert order == ["curl"], "urllib must not be reached when curl succeeds"
