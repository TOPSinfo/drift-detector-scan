# Drift Detector — roadmap

> Kept out of the README to keep the front page focused on *using* the tool.

## What's next

- **Trend history** — the dashboard shows the *latest* run; week-over-week burn-down needs a
  multi-run archive (a real persistence layer, not faked from one run).
- **Broader fleet access** — the scanner only covers repos its token can *read*; the rest are
  flagged blind. Giving the bot read access across the fleet unlocks full coverage.
- **More integration shapes** — each new vendor/API idiom is a reviewed catalog contribution
  through the `absorb` gate (the reviewed adaptation mechanism).
- **GitLab-native CI** — move the scheduled run from GitHub Actions to GitLab CI (kills the
  cross-host token + egress, makes the private Cockpit free on GitLab Pages). Deferred pending a
  self-hosted runner — details in [TECH_DEBT.md](TECH_DEBT.md).
- **AI-surface consolidation — done.** The three AI report surfaces (a separate
  `probabilistic.html`, a separate `adhoc.html`, and the certified dashboard) are now one
  dashboard: `dashboard.html`'s **AI Frontier** tab, with leads/shapes/research kept in their own
  blobs and badged by tier (`UNVERIFIED LEAD`, `GATE-VALIDATED`, `SOURCED`). The CLI subcommand
  that used to render the side-car page is now `leads` (writes `<state>/leads.json`, a
  `drift-leads/v1` document; it no longer renders HTML). The certified/unverified firewall is
  enforced by `verify`'s `ai-firewall` invariant, which asserts no AI-derived record reaches the
  certified payload.
