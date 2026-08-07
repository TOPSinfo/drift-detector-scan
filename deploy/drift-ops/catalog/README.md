# catalog/ — the writable index overlay

This directory is the **overlay** the scanner reads on top of its built-in catalogs
(`$DRIFT_CATALOG_DIR` points here). It is how the tool gets smarter without a rebuild.

Files (all optional, each a YAML list layered on the package baseline):

- `vendors.local.yaml` — extra vendors to detect (Index A: *what to look for*)
- `idioms.local.yaml` — extra URL-assembly idioms (Index A)
- `sunsets.local.yaml` — extra vendor API retirements, each with a `source:` URL (Index B: *when things die*)
- `attestations.local.yaml` — records of which vendor page was checked, when (Index B)

**Don't hand-edit these to add dates.** New entries enter through a **Learn** session
(`/drift-deepen` + `drift absorb`), which verifies every claim against the code and refuses a
retirement date with no fetched source. Absorbed entries land here as a reviewed merge
request; the next scheduled scan reads them automatically.
