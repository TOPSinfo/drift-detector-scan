# Tech debt & banked ideas

Deferred work that is understood but deliberately not built yet. Each entry says what it is,
why it's deferred, and where it would plug in — so picking it up later doesn't start cold.

---

## Pluggable source-resolver drivers (GitHub / GitLab / filesystem / public URL)

**Status:** idea, banked for the polished product. Not scheduled.

**Today.** A single resolver, `agent/lib/source_resolver.py::resolve_sources(roots, …)`, turns
each `fleet:` entry into scannable project dirs. It already handles four input *shapes* — a git
checkout, a plain folder, a git/GitLab URL (cloned into `<state>/sources/`), and a GitLab
*group* URL (expanded to its member repos via `agent/lib/gitlab.py`). Auth is whatever the
machine's own git can do, plus a `GITLAB_TOKEN` used as a transient clone credential. The fleet
is validated in `agent/lib/ops_config.py` to a **single https host** (so a GitLab group can be
expanded and the delivery host derived unambiguously).

**The limitation.** The resolver is effectively hardwired to *git-clone + GitLab-group* semantics
on one host. There's no first-class notion of a **source driver**, so:
- GitHub is only reachable as "a git URL to clone" — no GitHub-API group/org expansion, no
  GitHub-native archived/visibility filtering, no per-host token.
- A mixed fleet (some repos on GitLab, some on GitHub, some a local vendored drop) is impossible
  — `ops_config` rejects mixed hosts, and delivery assumes one GitLab host.
- "Scan this public URL / this tarball / this path on disk" is supported only incidentally (the
  plain-folder path), with no config knobs.

**The idea.** Formalize the seam into a small set of **drivers**, each selected per source and
carrying its own config block:

    fleet:
      - driver: gitlab
        host: git.example.com
        group: example-org            # API-expanded to member repos
        auth: GITLAB_TOKEN       # env-var name (matches config-v2 auth style)
      - driver: github
        org: acme-inc
        auth: GITHUB_TOKEN
      - driver: fs
        path: /mnt/client-drop/acme-src   # a vendored source folder, no history
      - driver: url
        url: https://example.com/src.tar.gz

Each driver implements one interface — roughly `expand() -> [source]` and
`materialize(source, state) -> (abs_dir, identity, kind)` — mirroring the injectable
`clone=` / `expand_group=` seams `resolve_sources` already exposes. `kind`
(`remote | local-git | local-plain`) is already carried into the report, so honest-coverage
messaging still works per driver.

**What this unblocks:** a genuinely multi-forge fleet, GitHub-org / GitLab-group expansion
through each forge's own API, per-host credentials, and scanning non-git sources (a client's
zipped drop, a public URL) as first-class config rather than a happy accident.

**Coupled changes when it's built:**
- `ops_config`'s single-host invariant relaxes to per-driver validation (the "one host" rule
  exists so group-expansion + delivery-host derivation are unambiguous — a driver model has to
  answer both per-entry instead).
- Delivery currently assumes one GitLab host; a multi-forge fleet means delivery routing
  becomes per-source too (a GitHub repo's findings can't be filed as GitLab issues).
- The config-v2 `auth:` block (env-var *names*) already fits — each driver names its own token
  var, no schema fight.

**Why deferred:** the current single-GitLab-host model covers the near-term deployments, and a
multi-forge resolver drags delivery routing along with it (above). Bank it until a real fleet
spans more than one forge, or a client needs GitHub-org / non-git sources.

---

## Public-lane freshness research as a Workflow (parallel fan-out)

**Status:** banked 2026-07-29. Today the freshness agent (`/drift-refresh`, the Curator) is a
**promptfile** — one Claude session working vendors sequentially. That is correct for the
current scale (a handful of unaudited vendors) and for the **portal lane** (human-in-the-loop
seller logins — you cannot parallelize a person).

**The upgrade, when it's worth it:** the **public lane** — vendors whose deprecation docs are
public (AWS, Google, Kogan, Mailgun, …) — is compute-bound and independent. Each vendor's
changelog is its own web-research task, so it fans out cleanly: a Workflow script spawns one
`agent()` per vendor via `parallel()`, each returns a candidate sunset (schema-validated), then
ONE `absorb` pass sweeps them all. Wall-clock collapses from Σ(vendors) to the slowest single
vendor (~12 min → ~3 min for 6, in the sketch).

**What must NOT change:** every candidate still funnels through the deterministic `absorb` gate
(no `source` + parseable date → refused), and a human still merges the catalog MR. The workflow
parallelizes only the *research*, never the firewall. The portal/HIL lane stays a promptfile.

**Why deferred:** at today's vendor count the promptfile handles both lanes fine; parallelism
buys nothing until the unaudited-**public**-vendor list grows to ~a dozen+. Build the Workflow
for the public lane only when that list is long enough that sequential research is the
bottleneck. Not a rewrite — a second entry point beside the promptfile.

---

## Vendor-scoped idioms (multi-vendor repos can't absorb via idioms)

**Status:** banked 2026-07-29. Referenced elsewhere in this file as "itself banked" — this is
the entry that was missing.

**Today.** The concat/url-assembly idiom attribution (`agent/lib/endpoints.py`, the
single-classified-vendor guard) only auto-attributes host-less path literals when the repo has
EXACTLY ONE classified vendor — the guard exists so an idiom never attributes a call to the
wrong API. Consequence: a multi-vendor client app (marketplacehub is 9-vendor) can never absorb via
idioms; its assembled-URL calls stay in residue. The obvious upgrade is idioms scoped to a
vendor (this `$client->getHost()` pattern is the *Shopify* wrapper's) so the guard can attribute
per-idiom instead of per-repo. `pathSignature` (host-independent, vendor-declared,
`agent/vendors.yaml`) is the natural seam — it is already a vendor-scoped attribution mechanism;
a vendor-scoped idiom is the same idea applied to assembly patterns instead of paths.

**Why deferred — fleet access beats teaching the scanner.** The probe's own EDGES output shows
the residue-producing calls in multi-vendor apps route through in-house wrapper repos
(example-org/shopify-api, example-org/koganapi, example-org/mydeal, … — one vendor each). Scan the
wrappers as fleet members and the existing single-vendor idiom attribution works inside each of
them unchanged — no new mechanism, and the client app's calls are seen where they actually live.
That is an *access ask* (add the repos to the fleet), not an engineering project, and it also
composes with banked concern #5 below (PR the wrappers toward detectable shapes). Build
vendor-scoped idioms only if a real multi-vendor repo's calls demonstrably do NOT route through
scannable wrappers — until then it's a permanent detection special-case bought where a fleet
edit would do.

---

# Banked concerns — 2026-07-29 (runtime signal + detectability feedback loop)

Five ideas raised together. The first two are one axis (a **dynamic/runtime** egress signal to
complement today's **static** analysis); the middle two are one axis (a **feedback loop** that
makes the codebase easier to scan over time); the last is a minor note.

## 1 · Runtime egress from access logs (dynamic detection)

**Idea:** identify the actual network calls from **access logs** (not necessarily live) rather
than only from source. Especially for languages we read poorly (the 7-of-8 egress-rule gap —
Kotlin/Go/etc.), a log line `GET https://api.x/v2/orders` is **language-agnostic ground truth**:
it sidesteps "every language abstracts egress differently."

**Honest assessment.** High-value as a SECOND signal that *augments* static (confirms calls,
adds hosts/versions static missed), never replaces it. But it breaks three things static gives:
(a) **determinism** — logs vary run to run; (b) **exhaustiveness** — a log only shows code paths
that actually EXECUTED, so absence in logs ≠ absence in code (the opposite failure mode from
static); (c) **access/PII** — needs staging/prod egress logs, which carry privacy + credential
exposure. The user's "not live, a batch of historical logs" framing is the right one — a day of
egress as a corpus, less friction than live tapping. Would feed the SAME endpoint/attribution
model (host → vendor, path → version), tagged `attribution: observed-runtime` so a reader can
tell a real hit from a static match. **Deferred:** it's a whole new ingestion path + a
determinism carve-out; bank until a client has weak-static-language repos AND accessible logs.

## 2 · Async local observer / middleware (embedded runtime signal)

**Idea:** a middleware / log hook that runs **async** (never blocks the main thread) alongside
the project locally and observes its outbound calls — the embedded, dev-time version of #1.

**Honest assessment.** This is exactly what **OpenTelemetry / APM HTTP-client instrumentation**
already produces (outbound HTTP spans: method, host, path, status). The honest move is to
**consume OTel/APM egress spans** rather than build a bespoke per-framework observer — otherwise
it's a Laravel middleware + a Guzzle interceptor + a Node hook + … forever. Same value and
caveats as #1 (ground truth, but execution-coverage-bound, non-deterministic). It's also a
different PRODUCT surface (an agent/sidecar, not a static scanner) — a bigger commitment than a
CI job. **Deferred:** revisit if a client already runs OTel and wants drift fed from real
traffic; then it's "read their existing spans," not "build an observer."

## 3 · Flag confusing net-call code for standardization (detectability linter)

**Idea:** when someone writes confusing/non-standard network-call code the scanner can't follow,
**flag it for simplification/standardization** — so next scan it's an easy catch, making the net
we cast more robust (we stop missing obvious strings).

**Honest assessment.** The tool ALREADY localizes exactly this: `residue.sinks` +
`config-driven-url` path literals ARE the "confusing code" signals, at `file:line`. So this is
mostly a RENDERING + a suggested-pattern library on top of data we compute: turn a residue entry
into an actionable "this call assembles its URL in a way we can't trace — here's the standard
shape." Creates a virtuous loop: as devs standardize, detection improves for free. Fits the
Developer/Maintainer streams as a low-severity "detectability" suggestion. **Guardrail:** only
flag where it actually caused a MISS (residue), never stylistic nagging — a preachy linter gets
muted. **Deferred:** additive and low-risk; do it when someone wants the loop, after the higher-
value access work.

## 4 · URLs in `.env` (minor)

**Concern:** base URLs may live in `.env` (unreadable — gitignored/secret), so a host set only
there is invisible. **Assessment — mostly a non-issue, as the user reasoned:** `.env` typically
holds the HOST + credentials; the PATH + VERSION (what retirement detection needs) is written at
the call site, so the version is usually still visible in code. And a host-less versioned path is
NOT a silent miss — it lands in `config-driven-url` residue, honestly flagged. Cheap future win:
read `.env.example` (often committed) for the host when present. Low priority.

## 5 · PR in-house libraries to improve their detectable shape

**Idea:** the wrapper libs (`tops/*`) are in-house — we can modify them — so the tool should be
able to open PRs against THEM to make their integration calls easier to detect (explicit URL
assembly, operation markers, standard patterns).

**Honest assessment.** Strong, and it's the counterpart to absorption: instead of teaching the
SCANNER a confusing shape (a vendor-scoped idiom — itself banked), **fix the CODE to a standard
shape** so no idiom is needed and every future scan catches it plainly. Fits the Developer/
Maintainer MR stream, scoped to in-house repos: scan the wrapper as a fleet repo → its residue
localizes the un-scannable calls → generate a suggested-refactor MR. **Blast radius:** a shared
library's code change affects every consumer, so these MRs are proposals a human weighs, not
auto-applied. **Relationship:** often *cheaper and more durable* than the vendor-scoped-idiom
enhancement — a one-time code cleanup vs. a permanent detection special-case. Bank alongside
vendor-scoped idioms; when both are on the table, prefer fixing in-house code over teaching the
scanner a workaround.

---

## A published lifecycle source for human-signed dispositions

**Status:** concept, parked 2026-08-24. Not scheduled. Raised by the PM; deliberately left
unresolved rather than guessed at.

**Today.** `INTERNAL` and `ACCEPTED` (see `agent/lib/catalog_coverage.py`) let a named person
settle a vendor that no vendor page can settle — a library built in-house, or a vendor that
publishes nothing findable. The record carries an approver name, role, basis and a mandatory
expiry, and the gate (`check_dispositions`) refuses anything missing them.

**The limitation, and it is a real one.** These are the ONLY records in this tool that assert
something with no fetchable `source:`. Every other record traces to a URL that was fetched that
session — CLAUDE.md principle 2, enforced by the absorb gate. An approver name is *attribution*
(who said it), not *evidence* (what they read).

The sharper consequence: a disposition cannot be **re-checked**, only **re-signed**.
`catalog_check.stale_attestations` can re-fetch a real vendor's page and diff it; there is
nothing to re-fetch here, so the expiry prompts a human to re-assert from memory rather than to
re-verify against anything. That is weaker than the expiry makes it look, and it sits in the
failure class the roadmap names as the one to fear — the tool sounding more confident than its
evidence supports.

**The idea.** Publish in-house component lifecycles in the same shape a real vendor does, so an
in-house component stops being a special case: it gets a genuine `source:` URL and joins the
existing auto lane. The machinery is already here — `agent/lib/catalog_sources.py` parses
eBay's RSS deprecation feed and `agent/catalog_check.py::CHECKS` fetches and diffs it on a
schedule. An internal feed in that shape would reuse both, with no new parsing.

**Where it would plug in.** A lifecycle file in the private `drift-ops` repo, served as
RSS/JSON via GitLab Pages (see "Go GitLab-native" above, which already contemplates GitLab
Pages from `drift-ops`), registered in `CHECKS`, with `check_dispositions` extended to require
the `source:` URL alongside the approver block.

**Two constraints that decided nothing yet, and must be settled first.**

1. **It cannot be public by default.** An in-house component name is a client identifier, and
   `CONTEXT.md` plus `tests/test_no_internal_identifiers.py` forbid those in a public tree.
   "This org runs an internal billing service, v1 sunsets on date X" is an infrastructure
   disclosure on a permanent, indexable URL. Published yes; public only for components the
   owner explicitly wants named.
2. **Self-citation.** If the team that signs the disposition also owns the feed, the source is
   the same party as the claim. Still a real gain — dated, versioned, diffable, re-fetchable by
   machine rather than by memory — but it is provenance, not independent corroboration, and it
   should never be presented to a reader as the latter.

**Open questions the concept was parked on:** whether the audience is our own scanner
re-fetching it or any external reader citing it; whether "in-house" means client-owned services
(client identifiers, private) or Tops' own libraries (nameable, possibly public); and whether
this is one Tops-published catalog or one feed per client fleet.

---

## Go GitLab-native (move the CI runner from GitHub Actions to GitLab CI)

**Status:** decided in principle (Fable-5 reviewed), **deferred pending a Tops-provided GitLab
runner.** If a runner is available → do it; if not, the current GitHub-Actions + two-repo setup
is the accepted fallback.

**Why.** The tool code runs on GitHub Actions only because it gave a free runner; the fleet,
config, and state all live on GitLab (`git.example.com`). Once the repo is private the free-runner
argument weakens (metered), and a self-hosted GitLab runner has no minute quota. Moving the runner
to GitLab CI would: kill the cross-host `GITLAB_TOKEN` PAT, remove the GitHub→GitLab egress /
reachability dependency, and make the private Cockpit **free** on GitLab Pages (satisfies the
"cockpit → GitLab Pages" decision natively).

**Do NOT merge the two repos.** The Fable-5 review was explicit: keeping `drift-ops` (state/config)
separate from the tool code is load-bearing — ephemeral compute still needs a durable state store;
merging regresses the scan job to `contents: write` (it could rewrite the scanner), mirrors the
`file:line` vuln index to GitHub SaaS, worsens the state-push race (two writers), and couples the
portable tool to this deployment's private state (which a future reimplementation would want kept
separate). The genuine simplification is **one host (GitLab), two repos** — not one repo.

**Where it plugs in.** A no-AI container image once carried this (`Dockerfile`, `docs/CONTAINER.md`,
`.github/workflows/container.yml`, `tests/test_container.py`) — **removed in v0.15.1-beta** when the
tool went plugin-only, but **recoverable from git** (revert commit removing GHCR) if this GitLab-runner
path is revived; it was pinned to `bin/drift-scan`'s engine version and would need a re-pin on revival.
Port `.github/workflows/scan.yml` → a GitLab `.gitlab-ci.yml` scheduled job; publish the
Cockpit via GitLab Pages from `drift-ops`; set `PUBLISH_PAGES=false` and retire the GitHub Pages job.
Cheap tightening while there: gitignore `audit.json` / `chart.html` / `rules.generated.yaml` in
`drift-ops` (derived artifacts, ~30% of per-run state churn).

**Fallback (no runner):** stay on GitHub Actions, keep two repos, just publish the Cockpit to GitLab
Pages from the persist step — a ~2-line change, strictly better than merging.

---

## Banked from the AI-surface + queue branch (0.19.0-beta, 2026-08-13)

Three items the merge-gate review recorded as follow-up rather than blockers. Each is a real
gap, verified end-to-end, and each fails in a *safe* direction today — which is why they were
banked instead of rushed.

**1 · The lead date-gate still admits two date shapes.** `agent/cli.py` `_DATEISH` refuses
`YYYY-MM-DD`, `YYYY/MM/DD`, month-name forms and `DD/MM/YYYY`, but `note: "Sunset in March 2026"`
(month + year, no day) and `note: "sunset 01.03.2026"` (dotted European) both still pass and land
in the dashboard's Evidence column as ungated WHEN claims — the harm principle 2 exists to prevent,
one shape narrower. **This needs a product call, not a reflex widening:** the obvious fix
(`_MONTHISH\s+\d{4}`) would also refuse honest evidence like *"the May 2026 release notes mention
it"*. An over-eager gate is worse than the hole, because users route around a gate that rejects
true statements. Decide deliberately, and pin the decision with a false-refusal test.

**2 · `_tag_own_infra` is the same bug class the branch just fixed, one layer down.**
`agent/lib/endpoints.py` retags any registrable domain with ≥2 *unclassified* hosts as own-infra —
with no `ownInfraReason`, so `_coverage` drops it to `na` and it leaves the audit backlog unnamed.
A repo calling `graph.somevendor.com` and `files.somevendor.com` (neither `api.`-labelled) loses a
real third party silently. This predates the branch. The fix is the one already proven on the
repo-token signal: give it a reason string and keep it `queued`, or scope it to hosts that already
share the repo's own token/domain.

**3 · The `isIntegration` mirror in `dashboard.app.js` disagrees with the server for an
out-of-vocab `hostClass`** — the JS returns true where `host_class.is_integration` returns False.
Unreachable today (the schema enum and `host_class.VOCAB` both close the vocabulary), but it is the
last place the client and server can disagree about what counts as an integration, and the branch
already shipped one bug of exactly that shape.
