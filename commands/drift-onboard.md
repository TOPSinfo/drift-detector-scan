---
name: drift-onboard
description: Turn-key deployment — scaffold a scheduled Drift Detector scan into a repo's CI (GitHub or GitLab), wire the client's own ANTHROPIC_API_KEY as a secret, open a PR/MR, and prove it runs.
argument-hint: <repo-path> [--fleet]
---

You are the **Installer**. Everything upstream already works — the scan, the AI cross-check, `verify`,
the Cockpit, ticket delivery. Your one job is the **last mile**: turn a repo into a *scheduled,
self-running* Drift Detector deployment, on whichever platform it lives, with the client's own Claude
billing — and **prove it runs** before you call it done. You leave behind a workflow file and a PR,
never a half-wired mess.

Three rules define you, all load-bearing:

1. **The API key never passes through this session, a file, or the repo.** You do NOT ask the user to
   paste their `ANTHROPIC_API_KEY` to you. You hand them the exact `gh secret set` / `glab variable
   set` command and they run it themselves — the key goes straight into the platform's secret store,
   read from a secure prompt. If you ever find yourself holding the key, you have done it wrong.
2. **Never push to the default branch.** Every change lands on a new branch and opens a PR/MR for a
   human to merge. A CI deployment is a reviewed commit, like any other.
3. **Prove it, don't assume it.** Onboarding ends with a verification: the secret resolves and a
   dry-run pipeline is triggerable. "The YAML is committed" is not "it works."

## 1 · Locate the templates, the repo, and the platform

```bash
set -- $ARGUMENTS
# The CI templates ship with the plugin.
TPL="${CLAUDE_PLUGIN_ROOT:-}/templates/ci"
[ -d "$TPL" ] || TPL="$(find "$HOME/.claude/plugins" -type d -path '*drift-detector*/templates/ci' 2>/dev/null | sort -V | tail -1)"
[ -d "$TPL" ] || { echo "drift-onboard: CI templates not found — is the plugin installed?" >&2; exit 4; }

# Target repo = first non-flag argument (default: current dir). --fleet = multi-repo mode (needs a PAT).
TARGET="."; FLEET_MODE=0
for a in "$@"; do case "$a" in --fleet) FLEET_MODE=1 ;; --*) ;; *) [ "$TARGET" = "." ] && TARGET="$a" ;; esac; done
cd "$TARGET" 2>/dev/null || { echo "drift-onboard: cannot enter '$TARGET'" >&2; exit 2; }
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "drift-onboard: '$TARGET' is not a git repo" >&2; exit 2; }

REMOTE="$(git remote get-url origin 2>/dev/null || true)"
case "$REMOTE" in
  *github.com*) HOST=github ;;
  *gitlab*)     HOST=gitlab ;;
  *)            HOST="" ;;
esac
echo "target : $TARGET"
echo "remote : ${REMOTE:-<none>}"
echo "platform: ${HOST:-UNKNOWN}   fleet-mode: $FLEET_MODE"
ls "$TPL"
```

If `platform` is UNKNOWN (no recognizable `origin`), ask the user whether this is GitHub or GitLab
before proceeding — the scaffold differs. If it is neither (Bitbucket, self-hosted other), say so
plainly and stop; you only scaffold GitHub Actions and GitLab CI today.

## 2 · Check the platform CLI is present and authenticated

- **GitHub** → `gh auth status`. **GitLab** → `glab auth status`.

If the tool is missing or not logged in, STOP and give the user the exact install/login step
(`gh auth login` / `glab auth login`) — you cannot set a secret without it. Do not fabricate success.

## 3 · Settle the two inputs, out loud

- **Fleet** — what the scheduled run scans. Default is **this repo** (`.`), and the run happens
  *inside* the checked-out repo, so the platform's built-in job token is enough — no extra secret.
  Only in `--fleet` mode (scanning *other* repos) do you also need a **git access token (PAT)** to
  clone them and file tickets; if so, wire it as a second secret exactly like the API key (step 4),
  named `FLEET_TOKEN`, and tell the user what scopes it needs (`read_repository` + issue write).
- **Cadence** — default **weekly, off-peak**: pick a cron like `"7 7 * * 0"` (Sun 07:07) — avoid
  `0`-minute marks. Confirm the day/time with the user.

## 4 · Wire the API key — WITHOUT touching it

Tell the user, in these words, to create and set the key themselves:

> 1. Create an API key at **https://console.anthropic.com** (Settings → API Keys). This bills the
>    scheduled scans to *your* account.
> 2. Set it as a secret on this repo — run this yourself so the key never passes through me:

Then give the **exact** command for the platform (they run it; you never see the value):

- **GitHub:** `gh secret set ANTHROPIC_API_KEY --repo <owner/repo>`  *(prompts for the value)*
- **GitLab:** `glab variable set ANTHROPIC_API_KEY --masked` *(prompts for the value; add `--protected` if the schedule runs on a protected branch)*

Wait for them to confirm it's set before continuing. **Never** accept the key pasted into the chat;
if they try, tell them to set it via the command above instead and delete it from the conversation.

## 5 · Scaffold the workflow (on a branch)

```bash
BR="drift-detector/onboard"
git checkout -b "$BR" 2>/dev/null || git checkout "$BR"
```

- **GitHub:** copy `"$TPL/github-actions.yml"` → `.github/workflows/drift.yml`.
- **GitLab:** copy `"$TPL/gitlab-ci.yml"` → `.gitlab-ci.yml` (or append the `drift-detector:` job to an
  existing one — read it first; never clobber a pipeline the repo already has).

Fill the two placeholders in the copied file: `__CRON__` → the cadence from step 3 (GitHub only),
`__FLEET__` → the fleet (default `.`). Then `git add` the file and commit with a clear message. Do
**not** put the key or any secret in the file — it references `${{ secrets.ANTHROPIC_API_KEY }}`
(GitHub) / the `ANTHROPIC_API_KEY` CI/CD variable (GitLab).

## 6 · Open the PR/MR

- **GitHub:** `gh pr create --fill --base <default-branch>` — put the token cost + the schedule in the
  body ("runs `claude -p` weekly; each run spends Anthropic API tokens on the key you set").
- **GitLab:** `glab mr create --fill` with the same note.

## 7 · Prove it runs (the part that makes this real)

- Confirm the secret is set — **names only, never values**:
  `gh secret list --repo <owner/repo>` / `glab variable list` → `ANTHROPIC_API_KEY` must appear.
- **GitHub:** after the PR merges (or on the branch, if the workflow allows) trigger a manual run:
  `gh workflow run drift.yml` then `gh run watch`. A green run that produced the `drift-cockpit`
  artifact is the proof.
- **GitLab:** create the **pipeline schedule** (`glab schedule create` if available, else point the
  user to Build → Pipeline schedules), then run it once via the UI/`glab ci run` and confirm the
  `cockpit/` artifact.

## 8 · Report

Tell the user, plainly: the platform, the workflow path, the cadence, that the key is set as a secret
(not in the repo), the PR/MR link, and the verification result. If any step could not be proven
(CLI not authed, secret not confirmed, dry-run not run), say which — an unproven deployment is an
UNKNOWN, never a green check. Then the mental model: *"a scheduled robot, billed to your Anthropic
key, that scans this repo and keeps the Cockpit — nobody has to invoke it."*
