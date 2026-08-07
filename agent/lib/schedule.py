"""Install/remove a cron job that runs the deterministic pipeline for one scanned folder.

The `crontab` command is injected so tests never touch the real crontab. Each folder gets one
crontab line tagged with a per-folder marker, so installs are idempotent and folders coexist.
Config (folder, schedule) is persisted in `<state>/agent.json`.
"""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess

CONFIG_NAME = "agent.json"
WRAPPER_NAME = "cron-run.sh"
LOG_NAME = "cron.log"
FRESHNESS_LOG = "catalog-check.log"     # latest weekly vendor-source freshness result


def _marker(state_dir: str) -> str:
    h = hashlib.sha256(os.path.abspath(state_dir).encode()).hexdigest()[:16]
    return f"# drift-detector:{h}"


def config_path(state_dir: str) -> str:
    return os.path.join(state_dir, CONFIG_NAME)


def load_config(state_dir: str) -> dict:
    try:
        with open(config_path(state_dir), encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, ValueError):
        return {}


def save_config(state_dir: str, cfg: dict) -> None:
    os.makedirs(state_dir, exist_ok=True)
    with open(config_path(state_dir), "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2, sort_keys=True)


def _default_crontab(action: str, content: str | None = None) -> str:
    if action == "read":
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        if r.returncode == 0:
            return r.stdout
        # an EMPTY crontab exits non-zero with a "no crontab for <user>" message — that's fine.
        # Any OTHER read failure must ABORT: proceeding would overwrite the real crontab with ours.
        if "no crontab" in (r.stderr or "").lower():
            return ""
        raise RuntimeError(f"cannot read crontab (won't risk overwriting it): {(r.stderr or '').strip() or r.returncode}")
    subprocess.run(["crontab", "-"], input=content or "", text=True, check=True)
    return ""


def _wrapper_script(root: str, state_dir: str, plugin_root: str,
                    pull: bool, path_env: str) -> str:
    q = shlex.quote
    # Resolve the runner at RUN TIME, not install time. Pinning plugin_root/bin/drift-scan
    # froze the cron to whatever version ran `schedule` — so after an upgrade the job kept
    # executing the OLD scanner from a stale cache dir, silently, forever. The wrapper now
    # reads installed_plugins.json (authoritative) and falls back to the newest cached
    # version by SEMVER (sort -V; a lexical sort mis-picks, "0.10.0" < "0.4.0"). The
    # version active at schedule time is only the LAST resort.
    args = f'run --root {q(root)} --state {q(state_dir)} --now "$(date +%F)"'
    if pull:
        args += " --pull"
    log = q(os.path.join(state_dir, LOG_NAME))
    fresh_log = q(os.path.join(state_dir, FRESHNESS_LOG))
    pinned = q(plugin_root + "/bin/drift-scan")
    return (
        "#!/usr/bin/env bash\n"
        "# drift-detector scheduled run — generated; remove via /drift-detector unschedule\n"
        f"export PATH={q(path_env)}\n"
        "SCAN=\"\"\n"
        # $HOME expanded at RUN time, not baked at generation time — correct even if cron
        # runs as another user or in a different environment.
        "REG=\"$HOME/.claude/plugins/installed_plugins.json\"\n"
        "if [ -f \"$REG\" ] && command -v python3 >/dev/null 2>&1; then\n"
        "  P=\"$(python3 -c \"import json,sys;"
        "d=json.load(open(sys.argv[1]));"
        "e=d.get('plugins',{}).get('drift-detector@tops-tools') or [];"
        "print(e[0]['installPath'] if e else '')\" \"$REG\" 2>/dev/null)\"\n"
        "  [ -n \"$P\" ] && [ -x \"$P/bin/drift-scan\" ] && SCAN=\"$P/bin/drift-scan\"\n"
        "fi\n"
        "[ -z \"$SCAN\" ] && SCAN=\"$(find \"$HOME/.claude/plugins\" -type f -name drift-scan "
        "-path '*drift-detector*' 2>/dev/null | sort -V | tail -1)\"\n"
        f"[ -z \"$SCAN\" ] && [ -x {pinned} ] && SCAN={pinned}\n"
        "[ -z \"$SCAN\" ] && { echo \"drift-detector: runner not found\" >&2; exit 4; }\n"
        f"\"$SCAN\" {args} >> {log} 2>&1\n"
        "# weekly freshness: re-check vendor sources against the catalog. Its own log, and\n"
        "# non-fatal — a new/moved vendor retirement (exit 3) or an unreachable source\n"
        "# (exit 4) is a heads-up for a human, never a reason to fail the scan job.\n"
        f"\"$SCAN\" catalog-check --now \"$(date +%F)\" > {fresh_log} 2>&1 || true\n")


def install_cron(root: str, state_dir: str, when: str, *, plugin_root: str,
                 pull: bool = False,
                 path_env: str | None = None, crontab_run=_default_crontab) -> str:
    """Write the wrapper + install one crontab line. Returns the crontab line for display."""
    root, state_dir = os.path.abspath(root), os.path.abspath(state_dir)
    os.makedirs(state_dir, exist_ok=True)
    path_env = path_env if path_env is not None else os.environ.get("PATH", "/usr/bin:/bin")

    wrapper = os.path.join(state_dir, WRAPPER_NAME)
    with open(wrapper, "w", encoding="utf-8") as fh:
        fh.write(_wrapper_script(root, state_dir, plugin_root, pull, path_env))
    os.chmod(wrapper, 0o755)

    marker = _marker(state_dir)
    line = f'{when} "{wrapper}"  {marker}'
    existing = [ln for ln in crontab_run("read").splitlines() if marker not in ln and ln.strip()]
    crontab_run("write", "\n".join(existing + [line]) + "\n")

    cfg = load_config(state_dir)
    cfg.update({"root": root, "schedule": when, "pull": pull})
    save_config(state_dir, cfg)
    return line


def remove_cron(state_dir: str, *, crontab_run=_default_crontab) -> bool:
    """Drop this folder's crontab line. Returns True if a line was removed."""
    marker = _marker(os.path.abspath(state_dir))
    lines = crontab_run("read").splitlines()
    kept = [ln for ln in lines if marker not in ln and ln.strip()]
    crontab_run("write", ("\n".join(kept) + "\n") if kept else "")
    return len(kept) != len([ln for ln in lines if ln.strip()])
