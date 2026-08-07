"""Resolve exact installed versions from lockfiles, so the audit can check what a repo
*actually resolved to* instead of the declared manifest floor (which over-reports).

Pure deterministic parsing (stdlib only). The manifest range stays the fallback when a
repo has no lockfile. Keys are (ecosystem, normalized-name) to join against `sdks[]`.
"""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from agent.lib.manifest_scan import _walk


def norm(eco: str, name: str) -> str:
    if eco == "python":
        return (name or "").lower().replace("_", "-")
    if eco == "composer":
        return (name or "").lower()
    return name or ""


def _v(s) -> str:
    return re.sub(r"^[vV=]+", "", str(s or "").strip())


def _composer_lock(content: str) -> dict:
    data = json.loads(content)
    out = {}
    for section in ("packages", "packages-dev"):
        for p in data.get(section) or []:
            n, ver = p.get("name"), p.get("version")
            if n and ver:
                out[("composer", norm("composer", n))] = _v(ver)
    return out


def _package_lock(content: str) -> dict:
    data = json.loads(content)
    out = {}
    pkgs = data.get("packages")
    if isinstance(pkgs, dict):                       # npm lockfile v2/v3
        for path, meta in pkgs.items():
            if not path.startswith("node_modules/"):
                continue
            name = path.split("node_modules/")[-1]   # keeps @scope/name
            ver = (meta or {}).get("version")
            if name and ver and "/node_modules/" not in path:   # top-level installs only
                out[("npm", name)] = _v(ver)
    deps = data.get("dependencies")
    if isinstance(deps, dict):                       # npm lockfile v1
        for name, meta in deps.items():
            ver = (meta or {}).get("version")
            if ver:
                out.setdefault(("npm", name), _v(ver))
    return out


_YARN_HEADER = re.compile(r'^"?(@[^@\s/]+/[^@\s]+|[^@\s"][^@\s]*)@')

def _yarn_lock(content: str) -> dict:
    out, current = {}, []
    for line in content.splitlines():
        if line and not line[0].isspace() and line.rstrip().endswith(":"):
            current = []
            for spec in line.rstrip(":").split(","):
                m = _YARN_HEADER.match(spec.strip())
                if m:
                    current.append(m.group(1))
        elif current and line.strip().startswith("version"):
            m = re.search(r'version\s+"?([^"\s]+)"?', line)
            if m:
                for name in current:
                    out[("npm", name)] = _v(m.group(1))
                current = []
    return out


def _poetry_lock(content: str) -> dict:
    data = tomllib.loads(content)
    out = {}
    for p in data.get("package") or []:
        n, ver = p.get("name"), p.get("version")
        if n and ver:
            out[("python", norm("python", n))] = _v(ver)
    return out


def _pipfile_lock(content: str) -> dict:
    data = json.loads(content)
    out = {}
    for section in ("default", "develop"):
        for name, meta in (data.get(section) or {}).items():
            ver = (meta or {}).get("version")
            if ver and str(ver).startswith("=="):
                out[("python", norm("python", name))] = _v(ver)
    return out


_REQ_PIN = re.compile(r"^\s*([A-Za-z0-9._-]+)\s*==\s*([A-Za-z0-9._+!-]+)")

def _requirements(content: str) -> dict:
    out = {}
    for line in content.splitlines():
        m = _REQ_PIN.match(line.split("#")[0])
        if m:
            out[("python", norm("python", m.group(1)))] = _v(m.group(2))
    return out


_PARSERS = {
    "composer.lock": _composer_lock,
    "package-lock.json": _package_lock,
    "yarn.lock": _yarn_lock,
    "poetry.lock": _poetry_lock,
    "Pipfile.lock": _pipfile_lock,
    "requirements.txt": _requirements,
}


def parse_lockfiles(files: dict) -> dict:
    """{path_or_basename: content} -> {(eco, norm_name): exact_version}. Malformed files are skipped."""
    out: dict = {}
    for path, content in files.items():
        parser = _PARSERS.get(path.rsplit("/", 1)[-1])
        if not parser:
            continue
        try:
            for k, v in parser(content).items():
                out.setdefault(k, v)
        except Exception:
            continue
    return out


def resolve_versions(repo_abs: str) -> dict:
    files = {}
    for p in _walk(Path(repo_abs)):
        if p.name in _PARSERS:
            try:
                files[str(p)] = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                pass
    return parse_lockfiles(files)
