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
- **AI — undecided.** An opt-in probabilistic cross-check exists, but whether AI becomes a
  first-class feature (leads shown *beside* certified findings, behind a strict
  certified/unverified firewall) is an open question. The deterministic core is the product; AI
  stays an experiment until it earns its keep.
