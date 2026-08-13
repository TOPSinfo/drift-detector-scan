"""summary.html — the report's DEFAULT view: the coverage tree + its glossary + the headline
numbers. Pure HTML, self-contained (CSS inlined), zero JavaScript — not even a snippet.

Why this page exists: Stage 1 injected the tree into the cockpit (dashboard.html), a heavy Vue
application, at the BOTTOM — underneath the very tile strip it was meant to replace. That
placement was a plan error, not a design choice. Asked where the tree should actually live, the
owner chose a separate bare-bones page over patching the cockpit's layout: the tree's whole
value is being readable in seconds, and loading a Vue application to read twelve numbers is at
odds with that. The owner's standing constraint — "I can afford UI basicness as long as results
are verifiable, consistent and make sense" — is exactly what this page is.

Reuses `agent/lib/tree.py`'s `build`/`html_tree`/`html_definitions`, the SAME builder drift.md
(and, until this page existed, dashboard.html) render from — so this page cannot disagree with
either. `verify`'s tree checks (tree-sums, tree-payload, tree-units, tree-parity,
tree-node-set, tree-definitions, tree-missing, tree-text-mismatch) run against this page's
markup; see `agent/cli.py`'s verify command.

Deterministic: a pure function of (payload, now). No wall-clock, no I/O beyond reading the
static CSS asset at import time (the same pattern `dashboard_render._read_asset` uses).
"""
from __future__ import annotations

import html
import os

from agent.lib import tree as _tree

_ASSETS = os.path.join(os.path.dirname(__file__), "..", "assets")


def _read_asset(name: str) -> str:
    with open(os.path.join(_ASSETS, name), encoding="utf-8") as fh:
        return fh.read()


CSS_SRC = _read_asset("summary.css")

# (counts key, display label) — the four headline numbers the owner asked for: what needs
# action (fixes), what is already broken (sunsets, past-due), and what nobody has audited yet
# (unaudited). Read from the REAL key names `dashboard_render._build_projection` writes —
# never renamed/guessed ones, so a rename over there cannot silently blank a tile here.
_HEADLINE = (("fixes", "Fixes"), ("sunsets", "Sunsets"), ("pastDue", "Past-due"),
             ("unaudited", "Unaudited"))


def _e(s) -> str:
    """HTML-text escape. Every value on this page is derived from the payload (a scanned
    repo's own strings can reach it via hostClass/domain), so nothing is trusted raw."""
    return html.escape(str(s), quote=True)


def _stat(key: str, label: str, counts: dict) -> str:
    n = counts.get(key)
    # An absent count is "not counted", never a confident 0 — the same rule tree.py enforces
    # for the tree itself (see its module docstring): "cannot see" must not render as "clean".
    shown = "—" if n is None else n
    return f'<div class="stat"><dt>{_e(label)}</dt><dd>{_e(shown)}</dd></div>'


def render_summary(payload: dict, now: str) -> str:
    """A complete, self-contained summary.html for `payload`. `now` is a fallback only —
    the meta line prefers `payload["generated"]`, the date the report itself was produced,
    kept for signature stability with the other renderers (run.py, cli.py)."""
    counts = payload.get("counts") or {}
    nodes = _tree.build(payload)
    repos = counts.get("reposScanned")
    repos_shown = "—" if repos is None else repos
    generated = payload.get("generated") or now
    tiles = "".join(_stat(key, label, counts) for key, label in _HEADLINE)
    return (
        '<!doctype html>\n'
        '<html lang="en">\n'
        '<head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<title>Drift Detector — Summary</title>\n'
        f'<style>{CSS_SRC}</style>\n'
        '</head><body>\n'
        '<header><h1>Drift Detector <span class="accent">Summary</span></h1>\n'
        f'<p class="meta">{_e(repos_shown)} repo(s) scanned &middot; generated {_e(generated)}'
        '</p></header>\n'
        f'<dl class="headline">{tiles}</dl>\n'
        f'<div id="tree">{_tree.html_tree(nodes)}{_tree.html_definitions(nodes)}</div>\n'
        '</body></html>'
    )
