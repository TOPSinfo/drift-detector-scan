# How it stays honest

For the people who **own** this tool rather than run it. Everything below is a mechanism that
already exists in the tree — most of it invisible unless you go looking, which is why this page
exists.

The theme: a scanner is only worth having if you can trust a *green* result. Almost all of the
engineering here goes into making sure the tool cannot quietly say "fine" when it means "I did
not look".

## `verify` — the only correctness claim

`drift-scan verify` re-parses the rendered surfaces — `drift.md`, the dashboard, the summary
page, and `sbom.json` when one has been written — and fails if any of them disagrees with
`drift.json`. It runs about **60 named invariant checks**, including:

!!! warning "What `verify` does NOT cover"
    **SARIF is not checked.** `drift.sarif.json` is written by a separate `drift-scan sarif`
    command and no invariant re-parses it, so it carries the trust of an export, not of a
    verified projection. Saying otherwise would overstate the one claim this tool makes —
    which is precisely the failure the rest of this page exists to prevent.

| invariant | what it stops |
|---|---|
| `ai-firewall` | an unverified AI lead reaching the certified data |
| `md-row-identity`, `md-column-integrity` | a table row that says something the JSON doesn't |
| `tree-parity`, `tree-sums`, `coverage-partition` | a coverage tree whose parts don't add to its whole |
| `unknown-lt-queued` | claiming fewer unknowns than queued items — an impossible state |
| `number-format` | float notation drift (`1e+16` vs `10000000000000000`) between renderers |
| `mermaid-unescaped-label` | a diagram label that silently breaks the graph |
| `projection-parity`, `blob-parity` | two surfaces derived from one source disagreeing |

**The rule that matters:** a green `verify` is the only statement anyone may make that a report
is correct. "It looks right" is not — nobody can see rendered HTML, and that assumption has
shipped bugs before.

## The absorb gate — why a wrong date cannot get in

Every vendor retirement carries a `source:` URL fetched **that session**. The gate
(`agent/absorb.py`) refuses a date that does not appear in the document fetched from its source.
Not "should carry a source" — *refused*.

It also computes a real before/after for any proposed shape:

```
{attributedBefore, attributedAfter, residueBefore, residueAfter,
 claims: {met, missing}, invented, unclaimed, problems}
```

`problems` empty means it would pass. A proposal that invents a vendor, or attributes lines it
never claimed, is rejected — so teaching the scanner quickly cannot mean teaching it wrongly.

Undated deprecations are allowed to exist, but must say so: `status: deprecated-no-date`.

## Residue — the conscience

Every match the scanner sees but **cannot attribute** is recorded as residue: unresolved path
literals, egress sinks, operation markers, path constants. It is not swept away.

This is what makes absorption measurable. When you teach the scanner a new shape, residue must
**shrink** — that is the gate's evidence the shape did something real rather than nothing. A bug
that let attributed lines stay counted as residue made the number immovable, so a working idiom
and a no-op looked identical; that is now a regression test.

## Coverage is attested, not counted

An entry count is not coverage. `agent/lib/catalog_coverage.py` holds the distinction:

- a vendor with sunset entries but **no attestation** is `UNAUDITED` — its zero findings prove
  nothing
- an attestation records **the day a human checked** that vendor's schedule
- after `STALE_DAYS = 90` a `CURRENT` vendor flips to `STALE` on its own
- a vendor that was checked and **refused** — its retirements published only behind a partner
  login — is `BLOCKED`, not `UNAUDITED`

So "no findings for Vendor X" is always qualified by whether anyone ever looked.

`BLOCKED` is worth a note for anyone extending the catalog, because its **encoding** carries the
guarantee. A blocked entry nests its provenance under `blocked:` and has no top-level
`checked`/`source`:

```yaml
- vendor: Temu
  blocked:
    since: '2026-08-21'
    source: https://seller.temu.com/
    why: 'Seller Center requires an account …'
```

Catalog data ships independently of the code that reads it, so a scanner older than this verdict
*will* parse the entry. Encoded flat, it ignored the key it did not recognise, saw a complete
attestation, and rendered the vendor `CURRENT` — the strongest claim in the vocabulary, from
evidence saying the opposite. Nested, that older loader finds no provenance, skips the entry and
falls back to `UNAUDITED`. **An unknown verdict must fail toward under-claiming.** The flat form
is refused outright so the unsafe shape cannot be reintroduced.

## The AI plane is quarantined by construction

Not by convention:

- an AI lead may **never** carry a date — the schema makes it unrepresentable; it reports
  `yes` / `no` / `unknown`
- leads land in their own artifact, hash-bound to the scan, excluded from every count and tile
- the `ai-firewall` invariant **proves** no lead reached `drift.json`

The only route from AI to certified is the absorb gate, and it ends in a human merge.

## Determinism

Same inputs, byte-identical output. Enforced by construction rather than hoped for:

- no wall-clock in logic — `now` is passed in
- the parsing engine is pinned by version, and in CI by **sha256** as well, so two machines
  cannot scan with different engines
- output ordering is canonicalised, because the engine's match order is *not* stable run to run
  (a container double-run proved it)
- the scan path is stdlib + PyYAML only, zero LLM tokens

## Client data never enters the public tree

The tool is published; a client's repo map must not be. `tests/test_no_internal_identifiers.py`
scans the **whole tracked tree** for the internal host and client repo names on every change.

The deny-list is itself sensitive — it *names* the namespaces — so it is not hardcoded here. It
comes from `git config drift.internalIds` (or `DRIFT_INTERNAL_IDS`) per clone, and the guard
skips in any public checkout rather than shipping the list.

**It is enforced at `git push`, not in CI, and that placement is the point.** CI runs *after* a
push has landed on the public remote — by then the names are already cloneable, mirrored and
cached, and force-pushing them away does not undo it. This project has client names in its git
history from exactly that sequence. The `.githooks/pre-push` hook is the last moment where "no"
still means something. Install it with `./bin/install-hooks`.

Two honest limits: the hook is bypassable with `--no-verify`, and it only protects clones that
installed it. It is a guardrail, not a wall — on a public repo there is no unbypassable place to
put one.

Client-scoped catalog data (confirmed own-domains, unresolved hosts, repo-scoped idioms) lives in
the private overlay, never in the package.

## Delivery is idempotent

A re-scan **updates** an existing issue rather than filing a duplicate — issues carry a hidden
identity key. An issue closes itself when its finding is resolved, and an absorption flag closes
itself when its repo comes back `KNOWN`. Running the scanner more often does not mean more noise.

## Test discipline

1448 tests, and the convention is that a test **comment names the real bug it pins** — nine test
files cite a specific shipped defect. The comments are load-bearing documentation of things that
actually went wrong.

The governing rule (CLAUDE.md principle 5): **a guard must be shown to FAIL on the bug it
targets**, not merely written. Reproduce first, then fix. Several guards in this repo were
verified by temporarily reverting the fix and watching the test go red.

## Where it is deliberately blind

Stated because the alternative is implying coverage that doesn't exist:

- sink → endpoint linking needs dataflow, and is out of scope
- only directly-declared dependencies are audited, not transitive ones
- a host assembled from a constant elsewhere needs dataflow to resolve
- week-over-week history is stored but **not rendered** — the first roadmap item
