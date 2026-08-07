"""Roll findings up into ACTIONS and rank them.

A finding is an advisory. An action is a job: "in this repo, upgrade this one thing." The
30 CVEs against torch 1.1.0 are not 30 jobs — they are one `pip install 'torch>=2.8.0'`.
Measured on a real 60-repo run: 320 findings -> 90 actions, 50 of them action-required.

Pure and deterministic: same input -> identical output, including order.
"""
from __future__ import annotations

from collections import OrderedDict

from agent.lib import owners
from agent.lib.ranking import severity_rank, semver_key, is_version

_MAX_FILES = 6

# Only `cve` actions get a command: an EOL means upgrading a language runtime or framework
# major, and a SUNSET means migrating to a different vendor API. Neither is a one-liner.
_COMMANDS = {
    "npm": lambda pkg, ver: f"npm install {pkg}@^{ver}",
    "composer": lambda pkg, ver: f"composer require {pkg}:^{ver}",
    "python": lambda pkg, ver: f"pip install '{pkg}>={ver}'",
}


def _split_ref(ref):
    """'composer/aws/aws-sdk-php' -> ('composer', 'aws/aws-sdk-php'). A ref with no '/' —
    every sunset finding, whose ref is a bare vendor name like 'eBay' — -> (None, ref)."""
    ref = str(ref or "")
    if "/" not in ref:
        return None, ref
    eco, pkg = ref.split("/", 1)
    return eco, pkg


def _command(kind, eco, pkg, fix_version):
    if kind != "cve" or not fix_version or eco not in _COMMANDS:
        return None
    return _COMMANDS[eco](pkg, fix_version)


def _rank_key(action):
    """Total order: action-required first, then worst severity, then blast radius, then a
    stable alphabetical tie-break so output is byte-identical across runs."""
    return (
        0 if action["status"] == "DEPRECATED" else 1,
        -severity_rank(action["worst"], action["status"]),
        -action["finding_count"],
        action["repo"],
        action["ref"],
        action.get("unit") or "",      # sunsets share a ref; the unit keeps order total
    )


def _sunset_unit(f) -> str:
    """The thing being retired: an operation, else the host, else the API version."""
    return f.get("operation") or f.get("path") or f.get("domain") or f.get("version") or ""


def _group_key(f):
    """A group is ONE JOB.

    For a CVE that is (repo, package) — 30 CVEs against torch really are one
    `pip install`. For a SUNSET it is (repo, vendor, thing-being-retired), because a
    vendor is not a job: eBay retiring GetCategoryFeatures (-> Metadata API, 2026-06-04)
    and AddDispute (-> Post-Order API, 2023-01-27) are two migrations with two deadlines
    and two owners. Keying sunsets on the vendor collapsed twelve dead eBay calls into a
    tile reading `Sunsets 1` — the operation axis was in the data and thrown away at the
    last step, which is precisely the "it skipped my call" complaint this release exists
    to answer.
    """
    if f.get("kind") == "sunset":
        return (f["repo"], f["ref"], _sunset_unit(f))
    return (f["repo"], f["ref"])


def build_actions(findings: list) -> list:
    """Group findings into jobs (see _group_key) and rank them. Returns action dicts."""
    groups: "OrderedDict[tuple, list]" = OrderedDict()
    for f in findings:
        groups.setdefault(_group_key(f), []).append(f)

    actions = []
    for group in groups.values():
        repo, ref = group[0]["repo"], group[0]["ref"]
        # the worst finding drives severity AND supplies the prose fallback
        worst_f = max(group, key=lambda f: severity_rank(f.get("severity"), f.get("status")))
        status = "DEPRECATED" if any(f.get("status") == "DEPRECATED" for f in group) else "REVIEW"
        kind = worst_f.get("kind") if len({f.get("kind") for f in group}) == 1 else "cve"

        # recommendation must come from whichever finding actually supplied fix_version, so the
        # prose and the version can never disagree (fall back to worst_f when nothing has a fix).
        fixed_findings = [f for f in group if f.get("fixed") and is_version(f["fixed"])]
        fix_f = max(fixed_findings, key=lambda f: semver_key(f["fixed"])) if fixed_findings else None
        fix_version = fix_f["fixed"] if fix_f else None

        eco, pkg = _split_ref(ref)
        actions.append({
            "repo": repo,
            "ref": ref,
            "eco": eco,
            "pkg": pkg,
            "kind": kind,
            # refKind (runtime|framework|None) splits the eol stream; owner is the derived
            # delivery stream, recomputed from (kind, refKind) so verify can re-check it.
            "refKind": worst_f.get("refKind"),
            "owner": owners.owner({"kind": kind, "refKind": worst_f.get("refKind")}),
            # what is actually retiring — the row label is "eBay GetCategoryFeatures",
            # not a bare "eBay" repeated down twelve identical-looking rows.
            "unit": _sunset_unit(worst_f) if kind == "sunset" else None,
            # the retirement/EOL date, as its own field so a table can show a clean date
            # column instead of parsing it back out of the recommendation prose
            "date": worst_f.get("date"),
            "current_version": worst_f.get("version"),
            "fix_version": fix_version,
            "command": _command(kind, eco, pkg, fix_version),
            "recommendation": (fix_f or worst_f).get("recommendation"),
            "worst": worst_f.get("severity"),
            "status": status,
            "finding_count": len(group),
            "critical_count": sum(1 for f in group if str(f.get("severity", "")).upper() == "CRITICAL"),
            "first_seen": min((f["first_seen"] for f in group if f.get("first_seen")), default=None),
            "files": list(OrderedDict.fromkeys(
                p for f in group for p in (f.get("files") or [])))[:_MAX_FILES],
            "fixes": group,
            "sources": [u for u in OrderedDict.fromkeys(
                f.get("source_url") for f in group) if u],
        })

    actions.sort(key=_rank_key)
    return actions
