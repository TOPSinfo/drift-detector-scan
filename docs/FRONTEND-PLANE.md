# Frontend plane (parked)

Parked 2026-08-14. Do not start until the extractor/honesty work order is done.
Not Astro, Gatsby, Evidence, Streamlit, or Charm-as-a-dependency.

## Decision
drift.json is the data plane. The frontend plane is Markdown + one HTML projection,
not a second Vue app and not a JS SSG.

- drift.md is the primary view (agent-readable, verify-parsed).
- summary.html is the only HTML report to grow (Python, 0 JS, data-n / data-count).
- dashboard.html (Vue cockpit) is FROZEN: no new features. Optional explorer until
  summary covers tables + timeline.
- chart.html is not a third look to invest in.
- Charm/Glow: user-side viewer of drift.md (`glow drift.md`). Do not add as a runtime dep.
- SARIF → editor for file:line. Extractors never belong in the frontend.

## Why not Astro/Gatsby
Each scan emits HTML. A Node SSG is a third toolchain; verify cannot re-parse
Astro-hydrated numbers. We already SSG in Python from drift.json.

## Target (when unparked)
One builder family (tree.py, md tables) → drift.md and report.html.
One CSS (grow summary.css; classless Pico/Simple optional).
Kill the AI Frontier plane as a tab (fold into badges). Do not fold summary into Vue.

## Out of scope until unparked
Vue restyle, Evidence/Observable, rewriting the scanner as a Charm TUI.
