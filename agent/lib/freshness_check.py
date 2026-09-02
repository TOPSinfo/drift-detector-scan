"""Is this install behind its published version? A plugin can sit versions behind indefinitely
with nothing saying so. The session that prompted this ran 0.15.1-beta against a source at
1.0.0 and spent an afternoon designing around behaviour already fixed upstream. Never guesses:
an unparseable version reports "could not check", never "you are behind" — a false staleness
warning is worse than none, because it trains people to ignore the real one.
"""
from __future__ import annotations

import re

_CORE = re.compile(r"^\s*v?(\d+(?:\.\d+)*)")


def _parts(v: str):
    """Return `(release_core, had_suffix)` — or `(None, False)` when nothing parses.

    Only the leading dotted-numeric release core (optionally "v"-prefixed) orders the
    comparison, so 0.9.0 < 0.10.0 compares numerically rather than lexically. Everything from
    the first character that isn't a digit or a dot onward — a pre-release suffix like "-rc.1"
    or "-hotfix.5" — is dropped whole, including any digits inside it; it never contributes
    components to the ordering. An earlier approach harvested every digit run in the string, so
    a numeric suffix on one side silently grew that side's version and could report an
    up-to-date install as behind a same-numbered pre-release/hotfix tag.

    The suffix is not thrown away entirely, though: whether one was PRESENT is reported back,
    because at equal cores it is the only thing that separates 1.0.0-beta from the released
    1.0.0 that supersedes it.
    """
    s = "" if v is None else str(v).strip()
    m = _CORE.match(s)
    if not m:
        return None, False
    return [int(n) for n in m.group(1).split(".")], bool(s[m.end():].strip())


def compare(installed: str, published: str) -> tuple[bool, str]:
    a, a_pre = _parts(installed)
    b, b_pre = _parts(published)
    if a is None or b is None:
        return False, ("drift-detector: could not check whether this install is current "
                       f"(installed {installed!r}, published {published!r})")
    width = max(len(a), len(b))
    a = a + [0] * (width - len(a))
    b = b + [0] * (width - len(b))
    # Equal cores, and only the INSTALLED side carries a pre-release suffix: the published
    # release supersedes the pre-release that preceded it, so 1.0.0-beta IS behind 1.0.0.
    # Only this direction. The mirror (installed 1.2.0, published 1.2.0-rc.1) is an ordinary
    # npm-style tag on an install that is already current, and must never raise a false alarm;
    # two suffixes at equal cores are unorderable here, so neither is called behind.
    if a == b and a_pre and not b_pre:
        return True, _behind(installed, published)
    if a >= b:
        return False, f"drift-detector: up to date ({installed})"
    return True, _behind(installed, published)


def _behind(installed: str, published: str) -> str:
    return (f"drift-detector: installed {installed}, published {published} — this install "
            f"is BEHIND. Several fixes may already exist upstream. Update with "
            f"`claude plugin update drift-detector`.")
