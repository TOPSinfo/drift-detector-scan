"""Is this install current? — the ALWAYS-ON half of the freshness check.

`doctor` has been able to say "this install is BEHIND" since 1.0.0, and nothing ever runs
doctor: the guided flow does not call it, so a stale install stays invisible exactly where it
matters — inside the scan whose behaviour it shapes. The 1.1.0 leads-gate fix is the worked
example: it shipped, and every 1.0.0 install would have gone on hitting the bug it fixed while
`doctor` — had anyone run it — compared 1.0.0 against an unbumped 1.0.0 and said "up to date".

The design problem is that the scanner's contract is OFFLINE and BYTE-REPRODUCIBLE. A per-run
network call that can slow a scan, change its output or fail it trades a real guarantee for a
convenience, so this module is built to be the quietest guard in the tree:

  * it speaks ONLY when the install is behind — current, unknown and offline are all silence,
    because a line on every run is noise that trains people to ignore the one that matters;
  * it writes to STDERR only, never stdout, which carries parsed output (drift.json, the SBOM,
    chat-summary) that a consumer may be piping;
  * it caches for a day, so a 52-repo fleet scan makes at most one request, not 52;
  * it never raises and never changes an exit code — `report()` swallows everything, because a
    crash here would take down a scan that has nothing to do with versions;
  * it can be switched off with DRIFT_NO_UPDATE_CHECK=1, for air-gapped CI and for the
    byte-reproducibility harness. An always-on check with no off switch gets disabled by
    deleting the code.

Ordering lives in `freshness_check`, which stays a pure-`re` module so `doctor` can call it with
the SYSTEM python3 before the venv exists. All network and cache plumbing is deliberately here
instead, so that property is not lost.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request

from agent.lib import freshness_check

PUBLISHED_URL = ("https://raw.githubusercontent.com/TOPSinfo/drift-detector-scan/"
                 "master/.claude-plugin/marketplace.json")
PLUGIN_NAME = "drift-detector"
TTL_SECONDS = 86400          # one day: fresh enough to matter, quiet enough not to nag
_TIMEOUT = 5                 # a version check may never be the reason a scan feels slow


def disabled() -> bool:
    """Opt-out for air-gapped CI and the byte-reproducibility harness."""
    return bool(os.environ.get("DRIFT_NO_UPDATE_CHECK", "").strip())


def default_cache_path() -> str:
    from agent.lib import drift_home
    return os.path.join(drift_home.drift_root(), "update-check.json")


def installed_version() -> str | None:
    """The SHIPPED number, read from the manifest — never a constant that can drift from it."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        with open(os.path.join(root, ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
            v = json.load(fh).get("version")
        return v if isinstance(v, str) and v.strip() else None
    except (OSError, ValueError, AttributeError):
        return None


def _fetch_curl() -> str:
    out = subprocess.run(["curl", "-fsS", "--max-time", str(_TIMEOUT), PUBLISHED_URL],
                         capture_output=True, text=True, timeout=_TIMEOUT + 2)
    if out.returncode != 0:
        raise OSError(f"curl exited {out.returncode}")
    return out.stdout


def _fetch_urllib() -> str:
    with urllib.request.urlopen(PUBLISHED_URL, timeout=_TIMEOUT) as r:   # noqa: S310
        return r.read().decode("utf-8", "replace")


def _http_fetch() -> str:
    """curl first, urllib second — a finding, not a preference.

    The sandboxed and proxied environments this tool runs in routinely complete a curl request
    while Python's urllib dies in the TLS handshake. Observed on this machine while building
    the check: `URLError: _ssl.c:1064: The handshake operation timed out` against the very URL
    curl fetched with a 200 in the same second. `bin/drift-scan`'s doctor block has always used
    curl for this exact URL, so curl is already on the installer's dependency path — and having
    the two halves of the freshness check disagree about whether the network is reachable is
    its own bug. urllib stays as the fallback for a machine with no curl.
    """
    try:
        return _fetch_curl()
    except Exception:
        return _fetch_urllib()


def _parse(payload: str) -> str | None:
    """Pull our plugin's version out of a marketplace document, tolerating any shape.

    Selects the entry NAMED `drift-detector` rather than index 0, in case the marketplace ever
    lists more than one plugin — the same correction `bin/drift-scan`'s doctor block carries.
    """
    try:
        doc = json.loads(payload)
    except (ValueError, TypeError):
        return None
    if not isinstance(doc, dict):
        return None
    plugins = doc.get("plugins")
    if not isinstance(plugins, list):
        return None
    for entry in plugins:
        if isinstance(entry, dict) and entry.get("name") == PLUGIN_NAME:
            v = entry.get("version")
            return v if isinstance(v, str) and v.strip() else None
    return None


def _read_cache(path: str, ttl: int, now: float) -> str | None:
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        if not isinstance(doc, dict):
            return None
        if now - float(doc.get("fetched", 0)) >= ttl:
            return None
        v = doc.get("version")
        return v if isinstance(v, str) and v.strip() else None
    except (OSError, ValueError, TypeError):
        return None


def _write_cache(path: str, version: str, now: float) -> None:
    """Best-effort. A read-only HOME (CI, container) costs the cache, never the answer."""
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"fetched": now, "version": version}, fh)
        os.replace(tmp, path)
    except (OSError, ValueError, TypeError):
        pass


def published_version(*, fetch=None, cache_path=None, ttl: int = TTL_SECONDS,
                      now: float | None = None) -> str | None:
    """The published version, from cache when fresh, else the network. None on any failure."""
    fetch = fetch or _http_fetch
    now = time.time() if now is None else now
    path = cache_path if cache_path is not None else default_cache_path()
    cached = _read_cache(path, ttl, now)
    if cached is not None:
        return cached
    try:
        payload = fetch()
    except Exception:                                    # offline is a NON-EVENT, not a warning
        return None
    version = _parse(payload)
    if version is not None:
        _write_cache(path, version, now)
    return version


def advisory(installed, published) -> str | None:
    """The message, only when BEHIND. `could not check` and `up to date` are both silence."""
    try:
        behind, message = freshness_check.compare(installed, published)
    except Exception:
        return None
    return message if behind else None


def report(*, installed, published, stream=None) -> str | None:
    """Emit the advisory, if there is one. Never raises; never returns non-None when quiet."""
    try:
        if disabled():
            return None
        message = advisory(installed, published)
        if message:
            print(f"  {message}", file=stream if stream is not None else sys.stderr)
        return message
    except Exception:
        return None


def run(stream=None) -> str | None:
    """The wired entry point: called once per CLI invocation, before the subcommand runs."""
    try:
        if disabled():
            return None
        return report(installed=installed_version(), published=published_version(), stream=stream)
    except Exception:
        return None
