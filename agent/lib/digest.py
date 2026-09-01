"""The summary facts every surface shares — extracted from drift.json, computed nowhere else.

The chat closing block and the email are RENDERERS over this. Neither counts anything itself, so
neither can disagree with the report or with each other. That is the rule every other surface
already follows: drift.json is the one contract, everything else is a projection of it.

(`notify.chat_card` still does its own extraction and is NOT migrated here — a known deviation,
recorded in the plan's self-review. If the card and the block ever disagree, that is why.)
"""
from __future__ import annotations

_DO_FIRST = 3


def _review(counts: dict) -> int:
    by = counts.get("byOwner") or {}
    return sum((by.get(o) or {}).get("review", 0) for o in ("devops", "developer"))


def _urgent(actions: list) -> dict | None:
    """The earliest DATED retirement.

    A CVE carries no date and cannot be "most urgent" in the sense a reader means: the question
    this line answers is what dies first, not what is worst. Severity is already in the headline.
    """
    dated = [a for a in actions if a.get("date")]
    if not dated:
        return None
    a = min(dated, key=lambda x: x["date"])
    return {"ref": (a.get("ref") or "") + (f" {a['unit']}" if a.get("unit") else ""),
            "date": a["date"],
            # An EOL runtime does not "retire", it reaches end-of-life. The kind travels with the
            # fact so the renderer can name it correctly rather than guessing from the ref.
            "kind": a.get("kind"),
            "sites": a.get("file_count") or a.get("finding_count") or 0}


def summary_facts(payload: dict, *, leads: int | None = None) -> dict:
    """Everything a summary surface needs. Pure function of `payload` (+ an injected lead count)."""
    counts = payload.get("counts") or {}
    delta = payload.get("delta") or {}
    actions = payload.get("actions") or []
    return {
        "generated": payload.get("generated"),
        "fixes": counts.get("fixes", 0),
        "review": _review(counts),
        "repos_affected": counts.get("reposAffected", 0),
        "repos_scanned": counts.get("reposScanned", 0),
        "new": len(delta.get("new") or []),
        "resolved": len(delta.get("resolved") or []),
        # None means "no prior scan", which is NOT zero movement. A first run reports every
        # finding as new, and rendering that as a week's change reads as a catastrophe.
        "compared_against": delta.get("comparedAgainst"),
        "urgent": _urgent(actions),
        "do_first": actions[:_DO_FIRST],
        # Named, not merely counted: `counts.unaudited` gives a number, but only the names are
        # actionable, and this section exists to be acted on.
        # The VERDICT travels with the vendor. Collapsing BLOCKED into the word "unaudited"
        # sends a reader to research a page that cannot be read — catalog_coverage keeps the two
        # apart precisely because "a reader who cannot tell them apart will chase the wrong one".
        "unaudited": [{"vendor": c.get("vendor"), "call_sites": c.get("callSites", 0),
                       "verdict": c.get("verdict")}
                      for c in (payload.get("catalog") or [])
                      if c.get("verdict") and c["verdict"] != "CURRENT"],
        # Access CHANGES only — the standing list lives in the drift:blocked work-order.
        "newly_blocked": list((payload.get("catalogDelta") or {}).get("newlyBlocked") or []),
        "no_longer_blocked": list(
            (payload.get("catalogDelta") or {}).get("noLongerBlocked") or []),
        "unknown_repos": [s.get("repo") for s in (payload.get("shapes") or [])
                          if s.get("verdict") == "UNKNOWN"],
        # Injected, never read from disk — see the test that pins this.
        "leads": leads,
    }
