---
name: drift-deepen
description: Deprecated alias — use /drift-absorb. Investigate and teach the scanner repos it can't fully read.
argument-hint: <folder> [repo-name]
---

**`/drift-deepen` has been renamed to `/drift-absorb`.**

The absorption flow — investigate a repo the scanner can't fully read, teach it the shape as **verified, gated YAML**, and hand back a **merge request** for a human to merge — now lives in [`drift-absorb.md`](drift-absorb.md). It adds an iteration loop (`drift-scan absorb --check`), explicit stop conditions, and the escalation paths for shapes that need a code release rather than an idiom.

**Run `/drift-absorb <folder>` instead** — read and follow `drift-absorb.md`. This alias will be removed in a later release.
