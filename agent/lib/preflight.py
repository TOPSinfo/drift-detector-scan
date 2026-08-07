"""Pre-scan preflight — a 5-second gate that fails a misconfigured deployment before the scan
runs, instead of a 403 ten minutes in (after the clone + scan + verify are wasted).

The decision is a pure function of (config, environment): which token env vars must be set,
whether a configured webhook is actually present, and whether the delivery token reaches
GitLab. The network probe is INJECTED — `check(..., probe=fn)` — so the branching is testable
without a network, matching the rest of the codebase's I/O-injection discipline.

Returns (problems, advisories): problems block the run (missing token, unreachable host);
advisories inform (an mrs target needs per-repo Developer access we can't verify pre-scan).
"""
from __future__ import annotations

_ROLES = ("clone", "persist", "deliver")


def check(cfg: dict, env: dict, *, probe=None) -> tuple[list, list]:
    """(problems, advisories). `env` is a name->value mapping (os.environ). `probe(host, token)`
    returns (ok: bool, detail: str); None skips the network check (used pre-scan when only the
    static config is available)."""
    problems: list = []
    advisories: list = []
    auth = cfg.get("auth") or {}

    # every token env var the config names must be set — grouped so one unset var reports all
    # the roles it serves (a single-token setup names GITLAB_TOKEN three times)
    by_name: dict = {}
    for role in _ROLES:
        by_name.setdefault(auth.get(role, "GITLAB_TOKEN"), []).append(role)
    for name, roles in sorted(by_name.items()):
        if not env.get(name):
            problems.append(f"auth: ${name} is unset — needed for {', '.join(roles)}")

    # a webhook that is named but unset is a silent-failure trap: the run looks fine and no
    # chat message ever arrives. Fail loudly instead (notify itself stays opt-in when unnamed).
    gchat = (cfg.get("notify") or {}).get("gchat")
    if gchat and not env.get(gchat):
        problems.append(f"notify: gchat is configured as ${gchat} but that var is unset")

    delivery = cfg.get("delivery") or {}
    if delivery.get("mode") == "live" and not delivery.get("dev_as_issues", True):
        advisories.append("developer target is `mrs` — needs Developer on each scanned repo; "
                          "repos where the token can't open an MR are reported unroutable, not "
                          "silently skipped")

    if probe is not None:
        name = auth.get("deliver", "GITLAB_TOKEN")
        tok = env.get(name)
        if tok:                              # only probe if we HAVE a token (missing is above)
            ok, detail = probe(cfg.get("host"), tok)
            if not ok:
                problems.append(f"gitlab: {cfg.get('host')} — {detail}")
    return problems, advisories
