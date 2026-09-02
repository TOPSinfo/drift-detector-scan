"""Is this install behind its published version? A plugin can sit versions behind indefinitely
with nothing saying so. The session that prompted this ran 0.15.1-beta against a source at
1.0.0 and spent an afternoon designing around behaviour already fixed upstream. Never guesses:
an unparseable version reports "could not check", never "you are behind" — a false staleness
warning is worse than none, because it trains people to ignore the real one.
"""
from __future__ import annotations

import re

_NUM = re.compile(r"\d+")


def _parts(v: str):
    # Leading numeric components, so 0.9.0 < 0.10.0 compares numerically rather than lexically.
    # A pre-release suffix (-beta) is ignored for ordering: it is not what staleness turns on.
    nums = _NUM.findall(str(v or "").strip())
    return [int(n) for n in nums] if nums else None


def compare(installed: str, published: str) -> tuple[bool, str]:
    a, b = _parts(installed), _parts(published)
    if a is None or b is None:
        return False, ("drift-detector: could not check whether this install is current "
                       f"(installed {installed!r}, published {published!r})")
    width = max(len(a), len(b))
    a = a + [0] * (width - len(a))
    b = b + [0] * (width - len(b))
    if a >= b:
        return False, f"drift-detector: up to date ({installed})"
    return True, (f"drift-detector: installed {installed}, published {published} — this install "
                  f"is BEHIND. Several fixes may already exist upstream. Update with "
                  f"`claude plugin update drift-detector`.")
