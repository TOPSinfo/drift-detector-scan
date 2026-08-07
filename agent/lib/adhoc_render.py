"""Render the ad-hoc / middle tier as a STANDALONE artifact (`adhoc.html`) — never folded into the
certified `dashboard.html` in the PoC (that would owe new `verify` invariants; deferred). Amber, a
persistent "not certified, not in the catalog" banner, a link back to the certified report. Self
contained, no external assets.

The label, verbatim: **"AI-shaped · gate-validated (this run)"** — a deterministic scanner attributed
these exact call-sites under a gate that proved the shape claims nothing beyond what was named; but
nobody reviewed the shape, so it is NOT certified. Absorb to make it permanent.
"""
from __future__ import annotations

import html
import json

_AMBER = "#e3b341"


def _esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def render_adhoc(doc: dict) -> str:
    meta = doc.get("meta", {})
    repos = doc.get("byRepo", [])
    tot_new = sum(int(r.get("attributedNew", 0)) for r in repos)
    tot_shaped = sum(len(r.get("shaped", [])) for r in repos)
    tot_dated = sum(int(r.get("datedCount", 0)) for r in repos)

    def tile(n, label):
        return (f'<div class="tile"><div class="n">{_esc(n)}</div>'
                f'<div class="l">{_esc(label)}</div></div>')

    rows = []
    for r in repos:
        problem = bool(r.get("problems"))
        head = (f'<h2>{_esc(r.get("repo"))}'
                + (' <span class="bad">✗ over-broad — not validated</span>' if problem else '')
                + f' <span class="sub">{r.get("attributedNew", 0)} call-site(s) shaped · '
                  f'{r.get("datedCount", 0)} dated by the catalog</span></h2>')
        idioms = "".join(
            f'<li><code>{_esc(i.get("id"))}</code> — {_esc(i.get("family"))}'
            f' · vendor <b>{_esc(i.get("vendor"))}</b>'
            f' · <code>{_esc(i.get("pathRegex") or i.get("base") or i.get("marker") or "")}</code></li>'
            for i in (r.get("idioms") or []))
        acts = "".join(
            f'<tr><td>{_esc(a.get("ref"))}</td><td><code>{_esc(a.get("operation") or a.get("pkg") or "")}</code></td>'
            f'<td>{_esc(a.get("date") or "— (attributed, not dated)")}</td>'
            f'<td class="loc">{_esc((a.get("files") or [""])[0])}</td></tr>'
            for a in (r.get("shaped") or []))
        if not acts:
            acts = ('<tr><td colspan="4" class="muted">shape attributed call-sites, but none match a '
                    'catalogued retirement — newly <b>seen</b>, not yet <b>flagged</b>.</td></tr>')
        probs = ("".join(f'<li class="bad">{_esc(p)}</li>' for p in r.get("problems", []))
                 if problem else "")
        rows.append(
            f'<section>{head}'
            f'<div class="idioms"><div class="cap">shape(s) authored this session</div><ul>{idioms}</ul></div>'
            + (f'<ul class="probs">{probs}</ul>' if probs else '')
            + f'<table><thead><tr><th>Vendor</th><th>Call</th><th>Retires</th><th>file:line</th></tr></thead>'
              f'<tbody>{acts}</tbody></table></section>')

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Drift Detector — AI-shaped (gate-validated this run)</title>
<style>
:root {{ color-scheme: dark; }}
body {{ font: 15px/1.5 system-ui, sans-serif; margin: 0; background:#0d1117; color:#c9d1d9; }}
.wrap {{ max-width: 980px; margin: 0 auto; padding: 24px; }}
.eyebrow {{ color:{_AMBER}; font-weight:700; letter-spacing:.08em; font-size:12px; text-transform:uppercase; }}
h1 {{ margin:.2em 0; font-size:26px; }}
.banner {{ border-left:4px solid {_AMBER}; background:rgba(227,179,65,.08); padding:12px 16px; border-radius:6px; margin:16px 0; }}
.banner b {{ color:{_AMBER}; }}
.tiles {{ display:flex; gap:12px; margin:18px 0; }}
.tile {{ flex:1; border:1px solid #30363d; border-radius:8px; padding:14px; }}
.tile .n {{ font-size:26px; font-weight:700; }}
.tile .l {{ font-size:11px; color:#8b949e; text-transform:uppercase; letter-spacing:.05em; }}
section {{ border:1px solid #30363d; border-radius:8px; padding:14px 16px; margin:14px 0; }}
h2 {{ font-size:17px; margin:0 0 8px; }}
h2 .sub {{ font-size:12px; color:#8b949e; font-weight:400; }}
.cap {{ font-size:11px; color:#8b949e; text-transform:uppercase; letter-spacing:.05em; margin:8px 0 2px; }}
.idioms ul {{ margin:.3em 0; padding-left:1.2em; }}
table {{ width:100%; border-collapse:collapse; margin-top:10px; }}
th, td {{ text-align:left; padding:6px 8px; border-bottom:1px solid #21262d; font-size:13px; }}
th {{ color:#8b949e; font-weight:600; }}
.loc {{ color:#8b949e; font-family:ui-monospace,monospace; font-size:12px; }}
.muted {{ color:#8b949e; }}
code {{ background:#161b22; padding:1px 5px; border-radius:4px; font-size:12px; }}
.bad {{ color:#f85149; }}
.probs {{ margin:6px 0; }}
a {{ color:{_AMBER}; }}
</style></head><body><div class="wrap">
<div class="eyebrow">AI-shaped · gate-validated (this run)</div>
<h1>Just-in-time shapes</h1>
<div class="banner"><b>These are not certified findings, and not raw guesses.</b> An idiom authored
this session attributed these exact call-sites, and the <b>absorb gate proved</b> it claims nothing
beyond what was named — but nobody reviewed the shape, and it is <b>not in the catalog</b>. Every date
still comes from the human-curated sunset catalog (the AI supplies the <i>where</i>, the catalog the
<i>when</i>). The certified report is <a href="dashboard.html">dashboard.html</a>. Re-running without
these shapes changes this page. <b>Absorb to make a shape permanent.</b></div>
<div class="tiles">{tile(tot_new, "call-sites shaped")}{tile(tot_shaped, "became findings")}{tile(tot_dated, "dated by catalog")}</div>
{''.join(rows)}
<p class="muted" style="margin-top:20px; font-size:12px;">Bound to certified scan
<code>{_esc(meta.get("driftJsonSha256", "")[:16])}…</code> · generated {_esc(meta.get("generated"))} ·
producer {_esc(meta.get("producer"))}</p>
</div></body></html>"""
