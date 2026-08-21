# Glossary

This tool's whole claim is that it says plainly where it is blind. That only works if the
words carrying the claim mean something specific to you. So every term below gets a
definition, **the failure it exists to prevent**, and where you actually see it.

If you read one thing here, read [Verdicts](#verdicts). They are the difference between
"we checked and it's fine" and "nobody looked" — which is the difference this tool was
built to stop people from missing.

---

## Verdicts

A verdict is a claim about *knowledge*, never about health. Each one answers "how much do we
actually know here?"

### Per repo: `KNOWN` / `UNKNOWN`

Can the scanner read this repo's outbound calls at all?

`KNOWN` requires **both**: every meaningfully-present language has egress-signal coverage,
**and** nothing was left unattributed. Anything else is `UNKNOWN`.

!!! warning "Why it exists"
    A scanner that reads nothing finds nothing, and "0 findings" looks identical to
    "healthy". `UNKNOWN` makes an unreadable repo say so out loud instead of rendering as a
    green tick. A repo made entirely of files the scanner cannot parse must never report
    `KNOWN` by virtue of being unreadable.

**Where you see it:** the coverage tree; `coverage.shapes[].verdict` in `drift.json`.

### Per vendor: `CURRENT` / `STALE` / `UNAUDITED` / `BLOCKED`

Has anyone checked *this vendor's* retirement list, and how recently?

| Verdict | Meaning |
|---|---|
| `CURRENT` | Someone read the vendor's deprecation page and recorded it, within the TTL (90 days) |
| `STALE` | It was read, but too long ago to still trust |
| `UNAUDITED` | **Nobody has ever checked.** No attestation exists |
| `BLOCKED` | Somebody checked and was **refused** — the vendor publishes retirements only behind a partner or seller login |

!!! warning "Why it exists"
    **"0 findings" for an `UNAUDITED` vendor is not evidence of health.** It means nobody
    ever looked up what that vendor is retiring. Without this distinction, a vendor nobody
    has researched is indistinguishable from one that was researched and found clean — and
    the second is the only one you can act on.

`BLOCKED` exists because `UNAUDITED` was doing two jobs. An unworked vendor needs somebody's
**time**; a blocked one needs somebody's **credentials**. A reader who cannot tell them apart
chases the wrong fix, and the freshness work-order stays permanently non-empty with a task
that can never succeed — which is how a list stops being read.

`BLOCKED` is **not** an attestation. It never ages into `CURRENT`, its call-sites keep
counting as unchecked exposure, and it must carry the gate page that was actually hit.

**Where you see it:** the per-vendor coverage table; `catalog[].verdict` in `drift.json`.

### Per finding: `CERTIFIED` / `SHAPED`

How was this number produced?

- **`CERTIFIED`** — every number came through the deterministic, machine-checked path and is
  proven to `file:line`.
- **`SHAPED`** — an AI proposed it and a gate validated it. Useful, held to a different
  standard, and **never mixed into the certified count**.

**Where you see it:** the badge on each dashboard panel.

---

## What the scanner found

### Call-site

One place in your code that calls a third-party API — a real `file:line`, not an estimate.
Call-sites are the unit of exposure: "Amazon SP-API, 191 call-sites" means 191 places to
change if it retires.

### Endpoint

A grouped API destination: vendor + host + version + operation + API family. Many call-sites
collapse into one endpoint. The API *family* (`/fba/inbound/v0`) is part of the key on
purpose — without it, one catalog entry would date 78 call-sites identically when in truth 34
of them died in 2025 and 4 live until 2027.

### Attribution: `observed` vs `inferred` vs `sdk-client`

How confidently the vendor was identified:

- **`observed`** — the vendor was *read at* this call-site. Evidence.
- **`inferred`** — assigned by a heuristic (e.g. the repo talks to exactly one vendor). A
  guess about the repo, not evidence from the line.
- **`sdk-client`** — no URL appears in the code at all; the vendor came from a dependency in
  the manifest.

!!! warning "Why it exists"
    A reader must be able to tell evidence from inference. Silently mixing them makes a
    heuristic look like a fact.

### Sink

An outbound call the scanner *can see happening* but whose URL it cannot resolve — a
`curl_exec`, an HTTP client invocation where the address is assembled at runtime. A sink is
the scanner saying: **something leaves here and I can't tell you where it goes.**

### Residue

Everything seen but not attributed: versioned path literals with no vendor, and unresolved
sinks. Residue is the honest remainder — the measure of what a scan could *not* explain.
Shrinking residue is what teaching the scanner is for.

**Where you see it:** `coverage.residue.pathLiterals[]` and `coverage.residue.sinks[]`.

---

## How it learns

### Catalog

The reviewed YAML the scanner reasons from: vendors, their retirements, idioms, attestations.
Data, not code — reviewable as a diff, with each date's provenance in a load-bearing comment.

### Attestation

A record that a human or AI **read a specific vendor's deprecation page on a specific date**,
with the URL. It is what turns `UNAUDITED` into `CURRENT`.

!!! warning "Why it exists"
    This project has been burned by plausible-but-wrong dates: a research pass once reported
    two eBay decommission dates, both wrong by days, both believable enough that nobody would
    have questioned them. **A date you did not fetch does not exist.** An attestation is the
    receipt.

### Idiom

A **taught code shape** that lets the scanner attribute calls it otherwise could not read —
typically where the host is injected at runtime, so no URL literal exists to classify.

Idioms come from a **closed set of five families**. Adding an *instance* of an existing
family is a reviewable YAML diff; adding a new *family* is a code change and a pull request.

| Family | What it recognises |
|---|---|
| `url-assembly` | a base URL held in a variable/property, concatenated with a path |
| `url-append` | a path appended to a known target |
| `operation-marker` | the operation named by a marker (an XML root, a call name) rather than a URL |
| `path-constant` | per-class path constants (`$API_URL = "/api/orders"`) with the host injected elsewhere |
| `client-base` | a client object constructed with a base URL |

Every instance carries `evidence:` — a real `file:line` somebody opened.

!!! note "Idioms are repo-scoped by design"
    An idiom generally names a *specific wrapper's* conventions, so it applies only in the
    repo it was learned from unless it is corroborated as distinctive. That scoping is why an
    idiom is rarely publishable upstream as-is.

### `pathSignature`

A vendor-declared regex that names a vendor **and version** from a distinctive URL *path*,
independent of the host. It is how a vendor with no fixed domain can be identified at all —
Salesforce Commerce Cloud's OCAPI runs on each merchant's own host, so `domains:` is empty and
`/dw/shop/v24_5` is the only identifier.

### `modelSignature`

The same idea for AI vendors, whose retirements are published per **model id** rather than per
endpoint. Corroborated against the repo's SDK dependency, so a model name in a comment cannot
attribute on its own.

### Overlay

A local catalog layered on top of the shipped one (`~/.drift/catalog` by default,
`$DRIFT_CATALOG_DIR` to move it). What *your* scans learn stays yours; the shipped catalog is
never edited in place.

### Absorb gate

The gate that new catalog knowledge must survive. It **re-scans the repo** and refuses:
attribution you did not claim, claims that do not hold, and any date without a source that was
fetched. You cannot widen a pattern to inflate your numbers — the gate rejects unclaimed
attribution by design.

!!! warning "Why it exists"
    An audit that people escalate on cannot rest on an assertion. The gate is what makes
    "we taught it something" checkable rather than asserted.

### Corroboration

Requiring a shape to appear in **more than one independent place** before it is trusted as
distinctive, rather than trusting a single sighting or a bare count.

---

## How it triages what it found

### `hostClass`

Every detected host is typed, so genuine integrations are not buried under bundled assets:

| Class | Meaning | In the audit backlog? |
|---|---|---|
| `api` | a catalogued vendor | **yes** |
| `api-lead` | looks like an API, not yet named | **yes** |
| `unclassified` | unknown, unclaimed | **yes** |
| `own-infra` | your own infrastructure | no |
| `asset-cdn` | fonts, icons, static assets | no |
| `social-widget` · `analytics` | embeds and trackers | no |
| `vendored-lib` · `boilerplate` | checked-in libraries, doc links, schema URIs | no |

!!! note "An exact host beats a parent-domain rule"
    `fonts.googleapis.com` is declared an asset CDN even though a vendor rule owns
    `googleapis.com`. Without that precedence, every page loading a Google Font counted as a
    live API integration.

### Uncatalogued vendor

A host that is plainly an API but has **no catalog entry** — its own verdict, not silence. It
becomes a vendor-resolution work-order item rather than being quietly dropped.

### Whole-API-retired

A vendor whose *entire* API is already dead (a marketplace that shut down). It comes off the
research work-list with that reason stated — asking someone to open the seller portal of a
company that no longer exists is a task that can never succeed.

---

## Words we use in two senses

**"Shape"** is overloaded, and both senses are user-visible:

1. **A repo's shape** — `coverage.shapes[]`, the per-repo readability verdict
   (`KNOWN`/`UNKNOWN`) and the reasons behind it (`config-driven-url`,
   `sdk-only-no-callsite`, `no-egress-signal`).
2. **A code shape** — the *pattern* an idiom recognises. "Teaching it a new shape" means
   writing an idiom.

They are related — you teach a **code shape** to fix a **repo shape** — but they are not the
same noun. Where it matters, this documentation says "repo verdict" or "idiom" instead.

---

## The one claim worth making

**`drift-scan verify` passing is the correctness claim.** It re-parses `drift.md` and the
rendered HTML and fails if either disagrees with `drift.json`, the single schema'd contract.
Every other surface is a *verified projection* of that file.

"It looks right" is not a claim. Rendered HTML has shipped bugs that only `verify` caught.
