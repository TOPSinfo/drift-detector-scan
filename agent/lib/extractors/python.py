"""Python extractor: requirements.txt + pyproject.toml (project or poetry)."""
from __future__ import annotations

import re
import tomllib

from agent.lib.inventory_models import InventoryRecord, library_techkey
from agent.lib.extractors import register

_OPS = ["==", ">=", "<=", "~=", "!=", ">", "<"]
_NAME = re.compile(r"^[A-Za-z0-9._-]+")


def _split_req(line: str):
    """('name', 'declared_range') from a PEP 508-ish string; range '' if bare."""
    core = line.split(";", 1)[0].split("#", 1)[0].strip()
    core = core.split("[", 1)[0].strip()          # drop extras: name[extra]
    for op in _OPS:
        i = core.find(op)
        if i != -1:
            return core[:i].strip(), core[i:].strip()
    m = _NAME.match(core)
    return (m.group(0) if m else core.strip()), ""


def _lib(repo, path, name, rng):
    return InventoryRecord(
        repo=repo, manifest_path=path, ecosystem="python",
        tech_key=library_techkey("python", name), name=name, kind="library",
        declared_range=rng, parse_quality=("exact" if rng.startswith("==") else "unlocked"),
    )


def _from_requirements(repo, path, content):
    out = []
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        name, rng = _split_req(line)
        if name:
            out.append(_lib(repo, path, name, rng))
    return out


def _from_pyproject(repo, path, content):
    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid pyproject.toml: {exc}") from exc
    out = []
    project = data.get("project") or {}
    if project:
        for dep in project.get("dependencies") or []:
            name, rng = _split_req(dep)
            if name:
                out.append(_lib(repo, path, name, rng))
        rp = project.get("requires-python")
        if rp:
            out.append(InventoryRecord(repo=repo, manifest_path=path, ecosystem="python",
                       tech_key="runtime:python", name="python", kind="runtime",
                       version_hint=str(rp), parse_quality="unlocked"))
        return out
    poetry = ((data.get("tool") or {}).get("poetry") or {}).get("dependencies") or {}
    for name, spec in poetry.items():
        if name.lower() == "python":
            out.append(InventoryRecord(repo=repo, manifest_path=path, ecosystem="python",
                       tech_key="runtime:python", name="python", kind="runtime",
                       version_hint=str(spec), parse_quality="unlocked"))
        else:
            out.append(_lib(repo, path, name, str(spec) if isinstance(spec, str) else ""))
    return out


@register("requirements.txt", "pyproject.toml")
def extract(repo: str, path: str, content: str) -> list:
    base = path.split("/")[-1]
    if base == "pyproject.toml":
        return _from_pyproject(repo, path, content)
    return _from_requirements(repo, path, content)
