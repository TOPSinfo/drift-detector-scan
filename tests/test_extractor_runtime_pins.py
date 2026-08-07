# tests/test_extractor_runtime_pins.py
from agent.lib.extractors import runtime_pins as rp, extractor_for

DOCKER = """FROM node:18-alpine AS build
RUN npm ci
FROM nginx:1.25
FROM mcr.microsoft.com/dotnet/sdk:8.0
"""

def test_dockerfile_from_lines():
    recs = rp.extract("clients/a", "Dockerfile", DOCKER)
    by = {r.tech_key: r for r in recs}
    assert by["runtime:node"].version_hint == "18"        # 18-alpine -> 18
    assert by["runtime:dotnet"].version_hint == "8.0"
    assert "runtime:nginx" not in by                       # unknown image skipped

def test_nvmrc():
    recs = rp.extract("clients/a", ".nvmrc", "v20.11.0\n")
    assert recs[0].tech_key == "runtime:node" and recs[0].version_hint == "20.11.0"

def test_python_version():
    recs = rp.extract("clients/a", ".python-version", "3.11.6\n")
    assert recs[0].tech_key == "runtime:python" and recs[0].version_hint == "3.11.6"

def test_tool_versions():
    recs = rp.extract("clients/a", ".tool-versions", "nodejs 18.19.0\npython 3.11.6\nterraform 1.5\n")
    keys = {r.tech_key: r.version_hint for r in recs}
    assert keys.get("runtime:node") == "18.19.0" and keys.get("runtime:python") == "3.11.6"
    assert "runtime:terraform" not in keys

def test_registered():
    for f in ("Dockerfile", ".nvmrc", ".python-version", ".tool-versions"):
        assert extractor_for("a/" + f) is rp.extract
