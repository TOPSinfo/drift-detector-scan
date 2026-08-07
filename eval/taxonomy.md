# Eval failure-mode taxonomy

The closed set of reasons the scanner can miss a known integration. Mirrors
`agent/eval/corpus.TAXONOMY` (that constant is the source of truth). A corpus entry's
`known_gaps` may only use these values.

| mode | meaning |
|---|---|
| `url-split-version` | endpoint found but version is None (base URL + version on different lines) |
| `sdk-only-no-callsite` | integration is used only via its SDK package; no hard-coded URL to match |
| `uncatalogued-vendor` | the host is real but not in `agent/vendors.yaml` yet |
| `wrong-host-attribution` | a host was classified to the wrong vendor |
| `config-driven-url` | the endpoint URL is assembled from config, not a literal |
| `env-var-host` | the host comes from an environment variable, not source |
| `private-source` | dependency/source is private/unresolvable |
| `scan-error` | the repo failed to scan |
| `label-wrong` | the expectation itself is wrong (the eval can indict its own labels) |

Phase 1 uses these only as pre-declared `known_gaps`. Auto-triage of unexpected misses is Phase 2.
