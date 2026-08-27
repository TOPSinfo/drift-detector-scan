# Email summary — an independent delivery job

**Date:** 2026-08-27
**Status:** design approved, not implemented

## Problem

A fleet scan runs weekly and publishes `drift.json`, `drift.md`, the dashboards and the SARIF/SBOM
exports. Everything is **pull**: somebody has to go and look. Nobody does, reliably, and the one
group who most needs the headline — whoever owns the remediation — is the least likely to open a
JSON contract or a CI artifact page.

There is already a **push** channel for exactly this, and it has never been switched on.
`agent/lib/notify.py` builds a Google Chat card as a pure function of the payload, `_cmd_notify`
wires it to a webhook named by `notify.gchat`, and the fleet's `.gitlab-ci.yml` does not call it.
So this is not a new subsystem; it is a second renderer over the same payload, plus the delivery
job the existing one also lacks.

## Goal

When a scan completes end to end, email a short summary to addresses configured in `drift.yml`,
from an independent CI job, on GitLab.

## Non-goals

- **No SMTP in the scan path.** `CONTEXT.md` records the rule this preserves: the scanner renders,
  CI delivers, "so no SMTP credential or network dependency enters the scan path".
- **No new runtime dependency.** `smtplib` and `email.message` are stdlib; runtime stays
  stdlib + PyYAML.
- **No templating engine, no HTML framework.** The body is assembled in Python from the payload.
- **No per-recipient content, no unsubscribe, no bounce handling.** This is an internal operations
  mail to a handful of colleagues, not a mailing list. If it ever becomes one, that is a different
  design with different obligations.
- **Not a replacement for `notify.gchat`.** Both are renderers over one payload; a deployment may
  enable either, both, or neither.

## Design

### 1 · `agent/lib/mail.py` — rendering, pure

```python
def summary_mail(payload: dict, *, report_url: str | None = None,
                 run_url: str | None = None) -> tuple[str, str, str]:
    """(subject, text_body, html_body) — a pure function of drift.json."""
```

Same inputs and same figures as `notify.chat_card()`: the headline counts, the top rows to do
first, and links to the report and the run. Deliberately a sibling rather than a wrapper — the two
channels format differently — but both read the payload and neither computes a figure of its own,
so an email can never disagree with the report it summarises.

**Both parts are sent.** `multipart/alternative` with a plain-text part and an HTML part: the text
part is what survives a terminal mail client, a digest, and a forward into a ticket; the HTML part
is what makes the numbers scannable. Sending HTML alone would make the mail unreadable in exactly
the places an operations mail gets read.

The empty case is explicit: a clean fleet gets *"0 to fix"* and the coverage line, never an empty
body. A summary that renders as nothing is indistinguishable from a delivery that failed.

### 2 · Transport, injected

```python
def send(smtp_url: str, msg, *, transport=None) -> None:
```

`smtp_url` is a URL — `smtps://user:pass@host:465` for implicit TLS, `smtp://…:587` upgraded with
STARTTLS. One variable rather than four, parsed with `urllib.parse`, and it is the shape every
provider documents.

`transport` is injected exactly as `http` is throughout this codebase, so tests assert the envelope
without opening a socket. **TLS is not optional**: a `smtp://` URL that cannot negotiate STARTTLS
is an error, not a silent downgrade to cleartext, because the body names client repositories.

### 3 · `drift-scan email-summary` — one command, one job

```
drift-scan email-summary --state <dir> --config <drift.yml> \
    [--report-url URL] [--run-url URL] [--dry-run]
```

Reads `<state>/drift.json`, renders, sends. `--dry-run` prints subject and recipients and sends
nothing — the thing you run when setting it up, and in tests.

### Config

```yaml
notify:
  gchat: DRIFT_CHAT_WEBHOOK          # unchanged
  email:
    to: [ops@example.com, lead@example.com]
    from: drift-detector@example.com
    smtp: DRIFT_SMTP_URL             # env var NAME, not the URL itself
```

`_NOTIFY` becomes `{"gchat", "email"}`. The `email` block requires `to` (a non-empty list),
`from`, and `smtp`; unknown keys are refused by name, matching every other block in this file.
Addresses are validated for shape at load, so a typo fails the config gate — which CI already runs
as `config-preflight` — rather than at 17:30 on a Sunday.

Recipients sit in the config, not an env var, because they are not secrets in the way the SMTP
password is: they belong in review, in the MR, versioned beside the fleet they describe. The
credential stays an env var name, as `notify.gchat` established.

### CI

A `notify-email` job in the `deploy` stage, `needs: [drift-fleet-scan]`, opt-in behind its own
variable in the same style as the `pages` job's `$PAGES_PUBLISH` gate.

## The one deliberate divergence: this job fails loudly

`_cmd_notify` returns 0 on every failure — *"a chat outage must not fail the pipeline"*, *"notify
must never turn a failure into a second red"*. That is right for chat and wrong here, and the
reason is the trigger.

Sending on **every** completed scan makes the mail's **absence** informative: no mail means no
scan. A silent delivery failure destroys that signal, and recipients are left unable to distinguish
"nothing to report" from "delivery has been broken for a month" — the same collapse as principle 1,
arriving through the inbox.

So `email-summary` **exits non-zero when it cannot send**. This is safe precisely because it is an
independent job: by the time it runs, the scan has succeeded, `drift.json` is committed, and the
artifacts are published. Only the notify job goes red, and somebody finds out.

Two cases are *not* failures, and both are silent by design:

- **No `notify.email` configured** — opt-in, no-op, exit 0, exactly like `gchat`.
- **No `drift.json`** — the scan failed upstream and has already reported that. A second red here
  would say nothing new.

## Testing

Written test-first; each guard proved against its bug before it is accepted.

1. `summary_mail` renders the headline figures from a fixture payload — asserted against the
   payload's own counts, so a renderer that invents a number fails.
2. The clean-fleet case renders "0 to fix" and a coverage line, never an empty body.
3. Both a `text/plain` and a `text/html` part are present, and the text part is non-empty.
4. `send` gives the transport the right envelope: every recipient, the configured `from`, the
   subject.
5. A `smtp://` URL whose STARTTLS fails raises rather than sending in cleartext.
6. Missing `to`, an empty `to`, a malformed address, and an unknown key inside `notify.email` are
   each refused at config load, by name.
7. `email-summary` with no `notify.email` exits 0 and sends nothing.
8. `email-summary` with no `drift.json` exits 0 and sends nothing.
9. `email-summary` whose transport raises exits **non-zero** — the divergence above, pinned so a
   later "make it consistent with notify" edit fails here and reads why.

## Risks

| Risk | Mitigation |
|---|---|
| Credentials leak into logs | The URL is read from an env var and never printed; `--dry-run` prints recipients and subject only. A test asserts the URL never appears in stdout. |
| A red notify job trains people to ignore red | It only fires when delivery is genuinely broken, which is rare and worth knowing. The scan's own success is unaffected. |
| Client repo names travel by email | They already travel by GitLab issue and dashboard. Recipients are internal and configured in a private repo; the body names repos, never code. |
| SMTP blocked from the runner | Found immediately, because the job is red. Same egress that already resets 60% of OSV connections — see the runner discussion in `CONTEXT.md`. |

## Open question, deliberately deferred

Whether `notify.gchat` should be wired into the fleet CI at the same time. It is built, tested and
dormant, and enabling it is a two-line job addition — but it is a separate decision about a
separate channel, and bundling it would hide that choice inside an email change.
