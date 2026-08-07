# drift-ops — the Drift Detector persistence repo

This is the GitLab repo that **stores** Drift Detector's data. The scan itself runs on
**GitHub Actions** (see `.github/workflows/scan.yml` in the plugin repo) — ephemeral compute,
no self-hosted runner — and pushes results back here.

Contents:

- **config/drift.yml** — the fleet to scan + delivery settings (one config).
- **catalog/** — the writable overlay the scanner learns into (see `catalog/README.md`).
- **state/** — the report + finding history, committed here by every run (history = git log).

## Setup

1. Copy these files into the repo and push.
2. In the **GitHub** repo (the scanner), add an Actions secret `GITLAB_TOKEN` — a GitLab PAT
   with Reporter on every scanned repo (`api` scope) and write access to this repo. Point the
   workflow's `GITLAB_HOST` / `DRIFT_OPS_PATH` at your instance + this repo.
3. Edit `config/drift.yml` with your repos.
4. Run the workflow (GitHub → Actions → drift-scan → Run workflow). It's also scheduled weekly.

The scan reads `config/drift.yml` + `catalog/`, scans the fleet, and commits `state/` back
here. A run's report is browsable at `state/drift.md`.

> An internal-GitLab-runner path (never sending code outside your network) is also possible —
> the plugin ships a `Dockerfile` + `docs/CONTAINER.md`. Use that when a client's code can't
> touch GitHub's infrastructure.
