# Drift Detector

**Know before it breaks.**

Drift Detector finds dying third-party API integrations — retiring vendor APIs, plus package
CVEs and runtime EOL — down to `file:line`, and says plainly where it is blind.

It runs as a [Claude Code](https://docs.anthropic.com/en/docs/claude-code) plugin:

```
/plugin marketplace add TOPSinfo/drift-detector-scan
/plugin install drift-detector@tops-tools
/drift-detector /path/to/a/folder
```

## What makes it different

**It never invents a retirement date.** Every date carries the vendor's own source URL and the
day it was checked. A gate refuses any date without a fetched source, so a plausible-but-wrong
date cannot enter the catalog.

**"Cannot see" is never "clean".** A repo the scanner could not fully read is reported as
`UNKNOWN` with a reason — never as a green checkmark. "0 findings" for an unaudited vendor is
not evidence of health.

**One report, three trust tiers.** Certified findings, gate-validated shapes, and unverified AI
leads stay separated. The AI tier may never propose a date — only `yes`/`no`/`unknown` — and a
`verify` invariant proves no lead ever reaches the certified data.

**Deterministic and reproducible.** The scan path is stdlib + PyYAML, zero LLM tokens, with the
parsing engine pinned by version and checksum. The same inputs produce byte-identical output.

## Where to go next

- **[Claude Code plugin](PLUGIN.md)** — installing it and what each command does.
- **[Teaching it a new shape](drift-absorb.md)** — how a repo the scanner cannot read gets
  absorbed, and the gate that verifies the result.
- **[Evaluating the scanner](EVAL.md)** — the corpus and recall gate used to measure it.
- **[Roadmap](ROADMAP.md)** — what is planned next.

The canonical data contract is
[`drift-v1.schema.json`](https://github.com/TOPSinfo/drift-detector-scan/blob/master/docs/schema/drift-v1.schema.json):
every other surface — the Markdown report, the dashboard, SARIF, SBOM — is a verified projection
of it, and `drift-scan verify` fails if any of them disagree.
