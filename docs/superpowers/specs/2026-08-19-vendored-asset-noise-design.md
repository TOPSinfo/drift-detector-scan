# Vendored-asset noise — a library mentioning a URL is not an integration

**Date:** 2026-08-19
**Status:** approved in outline, spec for review
**Origin:** a read-only scan of 19 newly-accessible fleet repos produced findings like
"this inventory system calls Dailymotion"

## The problem

A checked-in third-party UI library ships URLs in its own source. CKEditor lists the video
providers it can embed; Fancybox lists media hosts; Leaflet lists map-tile providers. The
scanner reads those files as first-party code, so every repo containing CKEditor inherits a
Dailymotion "integration" it does not have.

Measured on the 19-repo scan: **142 of 2375 classified call-sites (6%)** sit in bundled or
vendored asset paths under a broad probe (`plugins/`, `assets/`, `*.bundle.js`, `*.min.js`,
`dist/`). The rule this spec actually proposes is narrower and differently shaped, and drops 167
— the two numbers measure different things and are not meant to match. Concrete evidence:

```
Dailymotion    public/js/ckeditor/ckeditor.js:5
Vimeo Player   assets/fancybox/source/helpers/jquery.fancybox-media.js:115
Esri ArcGIS    assets/plugins/custom/leaflet/leaflet.bundle.js:23
```

The engine already holds the right principle — `agent/lib/engine.py:45` says *"vendored code
belongs to someone else — counting either as an integration is noise"* — but `_is_skipped`
inspects **directory names only** (`rel.parts[:-1]`), so it never sees `ckeditor.js` or
`*.bundle.js`, and these live under `js/`, `assets/` and `plugins/custom/`, not `vendor/`.

## What this is NOT

**Not a vendor-catalog problem.** An earlier framing proposed dropping Dailymotion, Vimeo,
OpenStreetMap and Esri ArcGIS as vendors this tool has no business tracking. The data killed it:

| vendor | catalogued sunset |
|---|---|
| Dailymotion | `www.dailymotion.com` retires **2026-02-03**, sourced from `developers.dailymotion.com/reference/sunset.md` |
| Esri ArcGIS | `arcgis.com` retires **2026-06-27**, sourced |

Dailymotion has a real, sourced retirement months away. If a client genuinely embeds a
Dailymotion player they need that date. Deleting a true capability to fix a precision bug is the
wrong trade. **The vendor is fine; the attribution is wrong.**

**Not a path-marker problem.** Adding `lib`, `libs`, `plugins` or `vendors` to `_SKIP_DIRS` was
measured and is actively dangerous: it drops **449 of 2375 call-sites (18%)**, including **219
Amazon SP-API, 33 Stripe and 20 eBay**. Those live in `application/libraries/amazon-sp-api/lib/`
because the client vendored Amazon's SDK — and **a vendored SDK is a genuine integration**, the
whole premise of the `sdk-only-no-callsite` work. Directory names cannot tell an SDK from a
widget.

## The distinction being drawn

Whether the repo **uses** the URL, or a library it happens to contain merely **mentions** it.

| file | detected | verdict |
|---|---|---|
| `libraries/amazon-sp-api/lib/Configuration.php` | Amazon SP-API | **real** — the app calls SP-API |
| `js/ckeditor/ckeditor.js:5` | Dailymotion | **noise** — CKEditor supports embedding it |
| `js/custom/pages/general/contact.js` | OpenStreetMap | **real** — a contact page with a map |

## Design

Both halves extend one function, `agent/lib/engine.py`'s `_is_skipped`, which every match already
passes through in `run_scan`. Nothing else in the pipeline changes, and the skip stays a single
choke point.

**Neither half looks at directory names.** That is the load-bearing constraint: it is what keeps
`application/libraries/amazon-sp-api/` scanned.

### Half A — generated content

`_looks_generated(path)`: read the first few KB; return true if any line exceeds 500 characters.
A file with a 60,000-character line is machine-generated, whoever wrote the generator.

This catches `ckeditor.js:5` and every unnamed bundle **with no list to maintain**, which is what
stops Half B going stale. The result is cached per file, since one file yields many matches.

It misses unminified vendored sources — `summernote.js:6384`, `fancybox.js:3477` are ordinary
readable JavaScript. Hence Half B.

### Half B — a reviewed filename list

A `_VENDORED_FILES` set beside the existing `_SKIP_DIRS`, matched against the **filename**, not
the directory:

```
ckeditor · summernote · fancybox · tinymce · leaflet · metronic
highchart · gmaps · owl.carousel · jquery.lazy
plus the *.min.* and *.bundle.* forms
```

Kept in Python next to `_SKIP_DIRS` rather than a new YAML catalog: it is the same kind of thing,
and one loader beats two. If it outgrows roughly twenty entries it should graduate to a reviewed
catalog like the vendor files.

It **fails safe**: an unlisted library stays noisy, which is a smaller harm than an over-broad
entry suppressing a real finding.

### Validated before writing this

The combined rule, run against the real 19-repo scan:

| | result |
|---|---|
| dropped | **167 of 2375 (7%)** — 121 by minified name, 46 by library name |
| removed | Vimeo 54, Mailgun 44, Dailymotion 40, ArcGIS 9, Google APIs 9, OSM 6 |
| Amazon SP-API | 929 → **929** |
| Amazon AWS | 492 → **492** |
| eBay | 190 → **190** |
| Amazon MWS | 151 → **151** |
| FedEx · Stripe · UPS | unchanged |

Zero real findings lost.

## The existing guard does not cover this

`agent/lib/engine.py:45` claims "the eval's noise metric exists to catch exactly that". It does
not. `agent/eval/score.py:84` computes `noise = count(vendor == "Unknown")` — **unclassified**
hosts. Bundle detections are classified (Dailymotion, Vimeo), so they never register as noise,
and this regression would pass the eval silently.

That comment should be corrected as part of this work rather than left overclaiming.

## Testing

Per CLAUDE.md principle 5, each guard is shown to fail on the bug it targets:

- a fixture file with a 60,000-character line containing `dailymotion.com` produces **no** match;
  shown to fail with Half A removed
- a fixture named `ckeditor.js`, unminified, containing the same host produces **no** match;
  shown to fail with Half B removed
- a hand-written `contact.js` calling the same host **still** produces a match — the guard must
  not simply suppress the vendor
- a fixture under `libraries/amazon-sp-api/lib/Configuration.php` containing an SP-API host
  **still** produces a match; this is the regression that the rejected path-marker approach
  would have caused, pinned so nobody re-introduces it
- the real 19-repo scan is re-run and compared: SP-API, AWS, eBay, MWS, FedEx, Stripe and UPS
  call-site counts must be **identical**

## Resolved during review

**Mailgun loses 44 call-sites, and four repos lose Mailgun entirely.** Checked rather than
assumed: in all four of them, the
*only* evidence is

```
resources/metronic/vendors/@form-validation/amd/plugin-mailgun/index.js:70
```

the Metronic admin theme's bundled form-validation library, which ships a plugin for Mailgun's
address-validation API. **None of the four declare Mailgun as a dependency in any manifest.**
They do not use Mailgun; a bought theme mentions it. Losing it is the correct outcome, and it is
the change working rather than a cost of it.

## Open questions

1. **The 500-character threshold is a judgement, not a measurement.** It should be checked
   against the corpus for a file that is legitimately hand-written and exceeds it; if one exists,
   the threshold moves or gains a second signal.
2. **`vendors` (plural) is absent from `_SKIP_DIRS`**, which has only the singular. The Metronic
   case sits under `resources/metronic/vendors/`, so the plural would have caught it directly.
   Adding it is tempting and probably safe — but it is a *directory* rule, the category this
   spec rejects, so it is deliberately left out and noted here rather than smuggled in.
