"""Render the probabilistic comparison as a SELF-CONTAINED, explicitly-UNVERIFIED artifact.
Separate from dashboard.html BY DESIGN: it is outside the `verify` contract, so it must SAY
it is unverified everywhere and never be mistaken for the certified report."""
from __future__ import annotations

import html


def _esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def render_probabilistic(comparison: dict, meta: dict) -> str:
    t = comparison.get("tallies", {})
    tokens = int(meta.get("tokens", 0) or 0)
    rows = []
    for r in comparison.get("byRepo", []):
        leads = r.get("aiOnly", [])
        if not leads and not r.get("agree") and not r.get("toolOnly"):
            continue
        lead_html = "".join(
            f'<li><b>{_esc(l.get("vendor"))}</b> <code>{_esc(l.get("endpoint"))}</code> '
            f'<span class="loc">{_esc(l.get("file"))}:{_esc(l.get("line"))}</span>'
            f'{" <span class=ret>retired?</span>" if l.get("retired")=="yes" else ""}</li>'
            for l in leads) or "<li class=none>— no AI-only leads</li>"
        rows.append(
            f'<div class="repo"><div class="rname">{_esc(r.get("repo"))}</div>'
            f'<div class="mini">agree {len(r.get("agree",[]))} · '
            f'AI-only {len(leads)} · tool-only {len(r.get("toolOnly",[]))}</div>'
            f'<ul class="leads">{lead_html}</ul></div>')
    ncc = comparison.get("notCrossChecked", [])
    ncc_html = (f'<div class="ncc"><b>Not cross-checked</b> ({len(ncc)}): '
                f'{_esc(", ".join(ncc))} — the AI could not read these; absence of a lead here '
                f'is not evidence of anything.</div>') if ncc else ""
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Probabilistic cross-check · AI · unverified</title>
<style>
:root{{color-scheme:dark light}}
body{{margin:0;font:14px/1.5 ui-sans-serif,system-ui,sans-serif;background:#0f1114;color:#e8ebf1}}
.wrap{{max-width:1000px;margin:0 auto;padding:32px 20px 64px}}
.badge{{display:inline-block;background:#4b8bff22;color:#4b8bff;font:11px ui-monospace,monospace;
letter-spacing:.08em;text-transform:uppercase;padding:4px 10px;border-radius:20px}}
h1{{font-size:26px;margin:10px 0 4px}}
.sub{{color:#98a1b1;margin:0 0 20px}}
.warn{{background:#e3b34118;border-left:3px solid #e3b341;border-radius:0 8px 8px 0;
padding:12px 15px;margin:16px 0;color:#cdd3de;font-size:13px}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin:14px 0}}
.tile{{background:#16191e;border:1px solid #2a2f38;border-radius:10px;padding:12px}}
.tile .n{{font-size:24px;font-weight:700}}.tile .l{{font:10px ui-monospace,monospace;color:#6a7180;text-transform:uppercase}}
.repo{{background:#16191e;border:1px solid #2a2f38;border-radius:10px;padding:12px 14px;margin:8px 0}}
.rname{{font:600 14px ui-monospace,monospace}}.mini{{color:#98a1b1;font-size:12px;margin:2px 0 6px}}
ul.leads{{margin:4px 0 0;padding-left:18px}}ul.leads li{{color:#cdd3de;font-size:13px}}
.loc{{font:11px ui-monospace,monospace;color:#6a7180}}.ret{{color:#e0533d;font-weight:600}}
.none{{color:#6a7180}}.ncc{{color:#cdd3de;font-size:13px;margin:14px 0}}
a{{color:#4b8bff}}
</style></head><body><div class="wrap">
<span class="badge">AI · unverified</span>
<h1>Probabilistic cross-check</h1>
<p class="sub">A second opinion from AI over {_esc(t.get('reposScanned'))} repos, {_esc(t.get('reposReadByAI'))} read · {tokens:,} tokens · {_esc(meta.get('now'))}</p>
<div class="warn"><b>These are leads, not findings.</b> Nothing here is verified, sourced, or
certified. The certified report is the deterministic scan → <a href="dashboard.html">dashboard.html</a>.
A lead becomes a finding only by passing the absorb gate.</div>
<div class="tiles">
<div class="tile"><div class="n">{_esc(t.get('agree'))}</div><div class="l">Agree (tool + AI)</div></div>
<div class="tile"><div class="n" style="color:#4b8bff">{_esc(t.get('aiOnly'))}</div><div class="l">AI-only (leads)</div></div>
<div class="tile"><div class="n" style="color:#e0533d">{_esc(t.get('toolOnly'))}</div><div class="l">Tool-only (certified)</div></div>
</div>
{ncc_html}
<h2 style="font-size:14px;color:#98a1b1;margin:22px 0 8px">Per repo</h2>
{''.join(rows)}
</div></body></html>"""
