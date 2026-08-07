"""Runtime pins: Dockerfile FROM lines + .nvmrc/.python-version/.tool-versions."""
from __future__ import annotations

import re

from agent.lib.inventory_models import InventoryRecord
from agent.lib.extractors import register

_FROM = re.compile(r"^\s*FROM\s+(\S+)", re.IGNORECASE)
_TOOLMAP = {"nodejs": "node", "node": "node", "python": "python", "php": "php"}


def _runtime(repo, path, product, hint):
    return InventoryRecord(repo=repo, manifest_path=path, ecosystem="docker",
                           tech_key=f"runtime:{product}", name=product, kind="runtime",
                           version_hint=hint, parse_quality="best_effort")


def _image_product(image: str):
    low = image.lower()
    if low.startswith("mcr.microsoft.com/dotnet"):
        return "dotnet"
    name_part = low.split(":", 1)[0]           # drop the :tag before matching
    base = name_part.rsplit("/", 1)[-1]        # strip registry/org
    for prod in ("node", "php", "python"):
        if base == prod:
            return prod
    return None


def _tag(image: str) -> str:
    if ":" not in image:
        return ""
    tag = image.rsplit(":", 1)[1]
    return tag.split("-", 1)[0]             # 18-alpine -> 18


@register("Dockerfile", ".nvmrc", ".python-version", ".tool-versions")
def extract(repo: str, path: str, content: str) -> list:
    base = path.split("/")[-1]
    out: list = []
    if base == "Dockerfile":
        for line in content.splitlines():
            m = _FROM.match(line)
            if not m:
                continue
            product = _image_product(m.group(1))
            if product:
                out.append(_runtime(repo, path, product, _tag(m.group(1))))
    elif base == ".nvmrc":
        v = content.strip().lstrip("v")
        if v:
            out.append(_runtime(repo, path, "node", v))
    elif base == ".python-version":
        v = content.strip()
        if v:
            out.append(_runtime(repo, path, "python", v))
    elif base == ".tool-versions":
        for line in content.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0].lower() in _TOOLMAP:
                out.append(_runtime(repo, path, _TOOLMAP[parts[0].lower()], parts[1]))
    return out
