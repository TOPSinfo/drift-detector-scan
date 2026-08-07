"""Reduce a declared dependency/runtime version range to a concrete 'floor' version.

The inventory records manifest ranges (`^8.2`, `>=20`, `==1.1.0`, `^11.0|^12.0`), but
vulnerability/EOL lookups need a concrete version. We take the lower bound — exact for
pins, the smallest allowed for ranges. Conservative: may over-report (a repo could resolve
to a patched higher version), never under-reports. Returns None when there is no concrete
version to check (`*`, `dev-master`, empty).
"""
from __future__ import annotations

import re

_VER = re.compile(r"\d+(?:\.\d+)*")


def floor(spec: str | None) -> str | None:
    if not spec:
        return None
    s = str(spec).strip()
    # composite ranges: take the first alternative (`^11.0|^12.0`, `>=1,<2`)
    s = re.split(r"[|,]", s)[0].strip()
    if s.startswith("<"):
        return None                      # upper-bound only (`<2.0`) has no meaningful floor
    if "!" in s:
        s = s.split("!", 1)[1]           # PEP 440 epoch: `1!2.3.4` -> `2.3.4`
    m = _VER.search(s)
    return m.group(0) if m else None
