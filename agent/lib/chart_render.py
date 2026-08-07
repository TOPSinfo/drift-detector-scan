"""chart.html — the ONLINE chart view.

Deliberately NOT self-contained: it loads Chart.js from a CDN, so it needs internet
and will NOT open usefully from `file://` while offline. That is the whole reason it is
a SEPARATE file from `dashboard.html`, which stays inline-only, CDN-free and offline —
and is the artifact `verify` and the Claude Artifact renderer trust (a Claude Artifact's
CSP blocks CDN scripts, so this file is a browser-opened extra, never the artifact).

It is still a projection of the same payload: it embeds the identical `#drift-data` blob
that `dashboard.html` does, so `verify`'s blob-parity check proves the charts are drawn
from `drift.json` and nothing else. Chart.js only turns that trusted data into pixels;
if the CDN is unreachable the page says so and points at `dashboard.html`.
"""
from __future__ import annotations

from agent.lib.dashboard_render import _blob, _e

# Pinned so the page renders the same library every time. No SRI hash: it cannot be
# verified offline at build time, and this file is the explicitly-non-authoritative online
# view — dashboard.html is the trusted artifact. `onerror` degrades to a plain message.
_CHART_JS_CDN = "https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"

_CSS = """
:root{--bg:#0d1117;--panel:#161b22;--line:#30363d;--text:#c9d1d9;--muted:#8a8f98;
--crit:#c0392b;--dep:#e67e22;--moat:#8e44ad;--cve:#4a78d0;--grid:#30363d}
:root[data-theme="light"]{--bg:#fff;--panel:#f4f4f8;--line:#ddd;--text:#1a1a2e;
--muted:#5a5f68;--grid:#e2e2ea}
@media(prefers-color-scheme:light){:root:not([data-theme="dark"]){--bg:#fff;--panel:#f4f4f8;
--line:#ddd;--text:#1a1a2e;--muted:#5a5f68;--grid:#e2e2ea}}
*{box-sizing:border-box}
body{margin:0;font:14px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--text)}
header{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;
padding:16px 20px;background:var(--panel);border-bottom:1px solid var(--line)}
h1{font-size:17px;margin:0 0 4px}
.headline{font-weight:600}
.note{color:var(--muted);font-size:12px;margin-top:4px}
#theme-toggle{background:none;border:1px solid var(--line);color:var(--text);border-radius:6px;
cursor:pointer;font-size:16px;padding:2px 8px;flex:none}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:18px;padding:20px}
figure{margin:0;background:var(--panel);border:1px solid var(--line);border-radius:10px;
padding:14px 16px}
figure.wide{grid-column:1/-1}
figcaption{font-size:13px;font-weight:600;margin-bottom:10px}
.cap{color:var(--muted);font-size:11px;margin-top:8px}
.wrap{position:relative;height:300px}
figure.wide .wrap{height:min(70vh,560px)}
#offline{margin:20px;padding:16px 18px;border:1px solid var(--dep);border-radius:8px;
color:var(--text);background:var(--panel)}
#offline code{color:var(--dep)}
"""

_CLIENT_JS = r"""
(function(){
  var DATA = JSON.parse(document.getElementById("drift-data").textContent);
  var NOW  = document.body.getAttribute("data-now") || "";
  var offline = document.getElementById("offline");

  if(typeof Chart === "undefined"){ offline.hidden = false; return; }  // CDN blocked/offline

  var CRIT="#c0392b", DEP="#e67e22", MOAT="#8e44ad", CVE="#4a78d0";
  function cssvar(n){ return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }
  function label(a){ return (a.ref||"") + (a.unit ? " "+a.unit : ""); }

  var charts = [];
  function destroyAll(){ charts.forEach(function(c){ c.destroy(); }); charts = []; }

  function buildAll(){
    destroyAll();
    Chart.defaults.color = cssvar("--text") || "#c9d1d9";
    Chart.defaults.borderColor = cssvar("--grid") || "#30363d";
    Chart.defaults.font.family = "system-ui, sans-serif";

    // ---- 1. where the risk sits (doughnut) — the past-due split, front and centre ----
    var c = DATA.counts || {};
    var pastDue = c.pastDue || 0;
    var upcoming = Math.max(0, (c.sunsets || 0) - pastDue);
    var eol = c.eol || 0;
    var cve = DATA.actions.filter(function(a){ return a.kind === "cve"; }).length;
    charts.push(new Chart(document.getElementById("risk"), {
      type: "doughnut",
      data: { labels: ["Past-due (retired)", "Deadline ahead", "Runtime EOL", "Package CVEs"],
              datasets: [{ data: [pastDue, upcoming, eol, cve],
                           backgroundColor: [CRIT, DEP, MOAT, CVE], borderWidth: 0 }] },
      options: { responsive:true, maintainAspectRatio:false,
                 plugins:{ legend:{ position:"bottom" } } }
    }));

    // ---- 2. sunsets by vendor (stacked: retired vs upcoming) ----
    var byV = {};
    DATA.actions.forEach(function(a){
      if(a.kind !== "sunset") return;
      var k = a.ref || "—"; byV[k] = byV[k] || {past:0, up:0};
      if(a.status === "DEPRECATED" && a.date) byV[k].past++; else byV[k].up++;
    });
    var vendors = Object.keys(byV).sort();
    charts.push(new Chart(document.getElementById("byVendor"), {
      type: "bar",
      data: { labels: vendors,
              datasets: [{ label:"Past-due", data: vendors.map(function(v){ return byV[v].past; }),
                           backgroundColor: CRIT },
                         { label:"Upcoming", data: vendors.map(function(v){ return byV[v].up; }),
                           backgroundColor: DEP }] },
      options: { responsive:true, maintainAspectRatio:false,
                 plugins:{ legend:{ position:"bottom" } },
                 scales:{ x:{ stacked:true }, y:{ stacked:true, beginAtZero:true,
                          ticks:{ precision:0 } } } }
    }));

    // ---- 3. retirement schedule (days from now; overdue is negative + red) ----
    var DAY = 86400000, nowMs = Date.parse(NOW);
    var sched = DATA.actions.filter(function(a){ return a.kind === "sunset" && a.date; })
      .map(function(a){ return { name: label(a) + " (" + a.date + ")",
                                 days: Math.round((Date.parse(a.date) - nowMs) / DAY) }; });
    sched.sort(function(x, y){ return x.days - y.days; });
    var CAP = 30, dropped = sched.length - CAP;
    if(dropped > 0) sched = sched.slice(0, CAP);            // most-urgent first; note the rest
    document.getElementById("sched-cap").textContent = dropped > 0
      ? ("Showing the 30 most urgent of " + (sched.length + dropped) + " dated surfaces.")
      : "";
    charts.push(new Chart(document.getElementById("schedule"), {
      type: "bar",
      data: { labels: sched.map(function(s){ return s.name; }),
              datasets: [{ label:"Days from " + NOW, data: sched.map(function(s){ return s.days; }),
                           backgroundColor: sched.map(function(s){ return s.days <= 0 ? CRIT : DEP; }) }] },
      options: { indexAxis:"y", responsive:true, maintainAspectRatio:false,
                 plugins:{ legend:{ display:false },
                           tooltip:{ callbacks:{ label:function(ctx){
                             var d = ctx.parsed.x;
                             return d <= 0 ? (Math.abs(d) + " day(s) overdue") : (d + " day(s) left"); } } } },
                 scales:{ x:{ title:{ display:true, text:"← overdue   |   days   |   ahead →" },
                              grid:{ color:function(ctx){ return ctx.tick.value === 0
                                     ? (cssvar("--text") || "#c9d1d9") : (cssvar("--grid") || "#30363d"); } } } } }
    }));
  }

  buildAll();

  // theme toggle — rebuild so axis/text colours follow the theme
  var root = document.documentElement, saved = null;
  try{ saved = localStorage.getItem("drift-theme"); }catch(e){}
  if(saved){ root.setAttribute("data-theme", saved); buildAll(); }
  document.getElementById("theme-toggle").addEventListener("click", function(){
    var next = root.getAttribute("data-theme") === "light" ? "dark" : "light";
    root.setAttribute("data-theme", next);
    try{ localStorage.setItem("drift-theme", next); }catch(e){}
    buildAll();
  });
})();
"""


def render_chart(payload: dict, now: str) -> str:
    """chart.html: the same payload as dashboard.html, drawn with Chart.js from a CDN.

    Deterministic — same payload + `now` → byte-identical output (Chart.js runs in the
    reader's browser, not here). Requires internet to render; degrades to a pointer at
    dashboard.html when the CDN is unreachable.
    """
    c = payload.get("counts", {})
    headline = (f'{c.get("pastDue", 0)} past-due · {c.get("sunsets", 0)} sunsets · '
                f'{c.get("fixes", 0)} fixes across '
                f'{c.get("reposAffected", 0)} of {c.get("reposScanned", 0)} repos')
    parts = [
        "<!doctype html>",
        '<html lang="en" data-theme="dark">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>Drift Detector — charts — {_e(now)}</title>",
        f"<style>{_CSS}</style>",
        "</head>",
        f'<body data-now="{_e(now)}">',
        "<header><div>",
        "<h1>Drift Detector — charts</h1>",
        f'<div class="headline">{_e(headline)}</div>',
        '<div class="note">Online view — loads Chart.js from a CDN, so it needs internet. '
        'The same data offline: <code>dashboard.html</code>.</div>',
        '</div><button id="theme-toggle" title="Toggle light/dark">◐</button></header>',
        '<div class="grid">',
        '<figure><figcaption>Where the risk sits</figcaption>'
        '<div class="wrap"><canvas id="risk"></canvas></div></figure>',
        '<figure><figcaption>Sunsets by vendor (retired vs upcoming)</figcaption>'
        '<div class="wrap"><canvas id="byVendor"></canvas></div></figure>',
        '<figure class="wide"><figcaption>Retirement schedule</figcaption>'
        '<div class="wrap"><canvas id="schedule"></canvas></div>'
        '<div class="cap" id="sched-cap"></div></figure>',
        "</div>",
        '<p id="offline" hidden>Chart.js could not be loaded (no internet, or the CDN is '
        'blocked). The same report renders offline in <code>dashboard.html</code>.</p>',
        '<script id="drift-data" type="application/json">' + _blob(payload) + "</script>",
        f'<script src="{_CHART_JS_CDN}" crossorigin="anonymous" '
        "onerror=\"document.getElementById('offline').hidden=false\"></script>",
        "<script>" + _CLIENT_JS + "</script>",
        "</body></html>",
    ]
    return "\n".join(parts)
