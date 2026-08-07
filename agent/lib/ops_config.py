"""Load the operational config — the ONE reviewed settings file (`drift.yml`), which lives in
the private drift-ops repo, not the public plugin.

Everything a deployment needs in one place: the fleet to scan (an array of repo/group URLs),
how to authenticate, how to deliver, and where to notify. The GitLab host is DERIVED from the
fleet URLs (a single https host, validated), so it can never drift from what is actually
scanned. Secrets NEVER live here — `auth` holds the env-var NAMES a token is read from, never
a token. Pure function of the file bytes: same file → same config.

    version: 1
    fleet:
      - https://git.example.com/group/repo-a
      - https://git.example.com/group/repo-b       # all must share one https host

    auth:                       # env-var NAMES (not values); each omitted one falls back to
      clone:   GITLAB_TOKEN     # GITLAB_TOKEN, so a single-token setup needs no auth block at
      persist: GITLAB_TOKEN     # all. Split them (group/project access tokens) without a code
      deliver: DELIVER_PAT      # change — this file names the vars, the CI provides them.

    delivery:
      mode: dry-run             # dry-run | live | off
      devops:    { project: group/ops }          # where DevOps issues are filed
      developer: { target: issues }              # issues | mrs (mrs needs Developer on each repo)

    notify:
      gchat: GCHAT_WEBHOOK      # env-var NAME of the webhook; omitted → no chat push

    probe:                      # acknowledged scope blind spots (from `drift-scan probe`).
      accept:                   # each needs a `reason` — a blind spot may be accepted, never
        - gap: dep:git.example.com/grp/wrapper    # silently. Paste the gap id from the probe
          reason: "access pending — TICKET-123"   # report; the gate stops failing on it but
        - gap: lang:javascript                    # still lists it (with the reason) so the
          reason: "no JS integrations"            # blindness stays visible.

The delivery block also accepts the v1 spelling (`dev_as_issues: true`, `devops_project: x`);
the two forms may not be mixed (that would say the same thing two ways). Either way `load`
returns the same normalized `delivery` dict, so existing consumers are unchanged.
"""
from __future__ import annotations

import re

import yaml

_MODES = {"dry-run", "live", "off", "create"}
_TARGETS = {"issues", "mrs"}
_TOP = {"version", "fleet", "delivery", "auth", "notify", "probe"}
_DELIVERY_V1 = {"mode", "dev_as_issues", "devops_project"}
_DELIVERY_V2 = {"mode", "devops", "developer"}
# orthogonal to the v1/v2 split — allowed in either form, never counts toward the mix check
_DELIVERY_COMMON = {"shape_stream", "freshness_stream", "granularity"}
_DELIVERY = _DELIVERY_V1 | _DELIVERY_V2 | _DELIVERY_COMMON
_AUTH = {"clone", "persist", "deliver"}
_NOTIFY = {"gchat"}
_STREAM = {"target", "project", "assignee", "fallbackAssignee"}
_GRANULARITIES = {"comprehensive", "per-vendor", "per-problem"}

# a value under `auth:`/`notify:` must be an env-var NAME, not a secret. This catches the most
# common and most dangerous mistake — pasting the actual PAT into the reviewed, git-tracked
# config. Real PATs carry known prefixes (and hyphens, which env names can't have).
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECRET_PREFIXES = ("glpat-", "glpat_", "ghp_", "gho_", "github_pat_")


class ConfigError(ValueError):
    """The config is malformed — raised, never guessed-around."""


def _host_of(url: str) -> str | None:
    m = re.match(r"^https://([^/]+)/", str(url or ""))
    return m.group(1) if m else None


def _env_name(where: str, val) -> str:
    """Validate an env-var name (used for auth + notify). Refuses anything that looks like a
    pasted secret — the config is git-tracked and reviewed, a token here is a leak."""
    s = str(val)
    if s.lower().startswith(_SECRET_PREFIXES) or len(s) > 64:
        raise ConfigError(f"{where}: expected an env-var NAME, got something that looks like a "
                          f"secret ({s[:8]}…). Put the token in that env var and name the var "
                          f"here, e.g. GITLAB_TOKEN.")
    if not _ENV_NAME.match(s):
        raise ConfigError(f"{where}: {s!r} is not a valid environment-variable name")
    return s


def _stream(where: str, block, *, default_target: str) -> dict:
    if not isinstance(block, dict):
        raise ConfigError(f"{where}: must be a mapping, e.g. {{target: issues}}")
    unknown = set(block) - _STREAM
    if unknown:
        raise ConfigError(f"{where}: unknown key(s) {sorted(unknown)} (allowed: {sorted(_STREAM)})")
    target = block.get("target", default_target)
    if target not in _TARGETS:
        raise ConfigError(f"{where}.target must be one of {sorted(_TARGETS)}, got {target!r}")
    return {"target": target, "project": block.get("project"), "assignee": block.get("assignee"),
            "fallbackAssignee": block.get("fallbackAssignee")}


def _load_auth(path: str, raw: dict) -> dict:
    block = raw.get("auth") or {}
    if not isinstance(block, dict):
        raise ConfigError(f"{path}: `auth` must be a mapping of role -> env-var name")
    unknown = set(block) - _AUTH
    if unknown:
        raise ConfigError(f"{path}: unknown auth key(s) {sorted(unknown)} (allowed: {sorted(_AUTH)})")
    # every omitted role falls back to GITLAB_TOKEN — a single-token deployment needs no block
    return {role: _env_name(f"{path}: auth.{role}", block.get(role, "GITLAB_TOKEN"))
            for role in sorted(_AUTH)}


def _load_notify(path: str, raw: dict) -> dict:
    block = raw.get("notify") or {}
    if not isinstance(block, dict):
        raise ConfigError(f"{path}: `notify` must be a mapping")
    unknown = set(block) - _NOTIFY
    if unknown:
        raise ConfigError(f"{path}: unknown notify key(s) {sorted(unknown)} (allowed: {sorted(_NOTIFY)})")
    gchat = block.get("gchat")
    return {"gchat": _env_name(f"{path}: notify.gchat", gchat) if gchat else None}


def _load_probe(path: str, raw: dict) -> dict:
    """probe.accept — the acknowledged scope blind spots. Each entry needs a `gap` id (from
    the probe report) AND a non-empty `reason`: you may accept blindness, never silently.
    Same discipline as never-invent-a-date — a bare acceptance with no stated why is refused."""
    block = raw.get("probe") or {}
    if not isinstance(block, dict):
        raise ConfigError(f"{path}: `probe` must be a mapping")
    unknown = set(block) - {"accept"}
    if unknown:
        raise ConfigError(f"{path}: unknown probe key(s) {sorted(unknown)} (allowed: ['accept'])")
    accept = block.get("accept") or []
    if not isinstance(accept, list):
        raise ConfigError(f"{path}: probe.accept must be a list")
    out = []
    for i, e in enumerate(accept):
        if not isinstance(e, dict) or not e.get("gap") or not str(e.get("reason") or "").strip():
            raise ConfigError(f"{path}: probe.accept[{i}] needs a `gap` and a non-empty `reason` "
                              "— a blind spot may be accepted, never silently")
        out.append({"gap": str(e["gap"]), "reason": str(e["reason"]).strip()})
    return {"accept": out}


def _load_delivery(path: str, raw: dict) -> dict:
    d = raw.get("delivery") or {}
    if not isinstance(d, dict):
        raise ConfigError(f"{path}: `delivery` must be a mapping")
    unknown = set(d) - _DELIVERY
    if unknown:
        raise ConfigError(f"{path}: unknown delivery key(s) {sorted(unknown)}")
    v1 = set(d) & (_DELIVERY_V1 - {"mode"})
    v2 = set(d) & (_DELIVERY_V2 - {"mode"})
    if v1 and v2:
        raise ConfigError(f"{path}: delivery mixes the v1 keys {sorted(v1)} with the v2 keys "
                          f"{sorted(v2)} — use one form, not both")

    mode = d.get("mode", "dry-run")
    if mode is False:                    # YAML 1.1 parses an unquoted `off` as the bool False
        mode = "off"
    if mode not in _MODES:
        raise ConfigError(f"{path}: delivery.mode must be one of {sorted(_MODES)}, got {mode!r}")

    if v2:                               # per-stream form
        devops = _stream(f"{path}: delivery.devops", d.get("devops", {}), default_target="issues")
        developer = _stream(f"{path}: delivery.developer", d.get("developer", {}),
                            default_target="issues")
        dev_as_issues = developer["target"] == "issues"
        devops_project = devops["project"]
        devops_assignee = devops["assignee"]
        developer_fallback = developer["fallbackAssignee"]
    else:                                # v1 form (or nothing → defaults)
        dev_as_issues = bool(d.get("dev_as_issues", True))   # default: issues (Reporter-friendly)
        devops_project = d.get("devops_project")
        devops_assignee = None
        developer_fallback = None

    if mode in ("create", "live") and not devops_assignee:
        raise ConfigError(f"{path}: delivery.devops.assignee is required when delivery.mode "
                          "files issues (create/live) — every DevOps issue is assigned to it")

    granularity = d.get("granularity", "comprehensive")
    if granularity not in _GRANULARITIES:
        raise ConfigError(f"{path}: delivery.granularity must be one of "
                          f"{sorted(_GRANULARITIES)}, got {granularity!r}")

    # the two maintainer streams, both off by default and opted into independently:
    # shape_stream files an absorption flag per UNKNOWN repo (opt in once the fleet is stable,
    # so early scans don't flag every not-yet-modeled repo); freshness_stream files THE
    # catalog-freshness work-order while any detected vendor is STALE/unaudited off the auto
    # lane (opt in once someone owns the maintainer queue — an issue nobody triages is noise).
    return {"mode": mode, "dev_as_issues": dev_as_issues, "devops_project": devops_project,
            "devopsAssignee": devops_assignee, "developerFallbackAssignee": developer_fallback,
            "shape_stream": bool(d.get("shape_stream", False)),
            "freshness_stream": bool(d.get("freshness_stream", False)),
            "granularity": granularity}


def load(path: str) -> dict:
    """Parse + validate drift.yml. Returns
        {fleet, host, delivery:{mode,dev_as_issues,devops_project,devopsAssignee,developerFallbackAssignee},
         auth:{clone,persist,deliver}, notify:{gchat}, probe:{accept:[{gap,reason}]}}.
    Raises ConfigError on anything malformed — an unknown key is an error, not ignored, so a
    typo can't silently disable delivery or drop a repo. `auth`/`notify` values are env-var
    NAMES; a pasted secret is refused."""
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: expected a YAML mapping at the top level")
    unknown = set(raw) - _TOP
    if unknown:
        raise ConfigError(f"{path}: unknown key(s) {sorted(unknown)} (allowed: {sorted(_TOP)})")

    fleet = raw.get("fleet")
    if not isinstance(fleet, list) or not fleet:
        raise ConfigError(f"{path}: `fleet` must be a non-empty list of https repo/group URLs")
    hosts = set()
    for u in fleet:
        if not str(u).startswith("https://"):
            raise ConfigError(f"{path}: fleet entry {u!r} must be an https:// URL")
        h = _host_of(u)
        if not h:
            raise ConfigError(f"{path}: cannot parse a host from {u!r}")
        hosts.add(h)
    if len(hosts) != 1:
        raise ConfigError(f"{path}: all fleet URLs must share one host, got {sorted(hosts)}")

    return {
        "fleet": [str(u) for u in fleet],
        "host": hosts.pop(),
        "delivery": _load_delivery(path, raw),
        "auth": _load_auth(path, raw),
        "notify": _load_notify(path, raw),
        "probe": _load_probe(path, raw),
    }
