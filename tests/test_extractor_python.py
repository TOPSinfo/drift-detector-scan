import pytest
from agent.lib.extractors import python as py, extractor_for

REQS = """# prod deps
boto3==1.34.0
requests>=2.31
django
-r other.txt
"""

PYPROJECT = '''
[project]
requires-python = ">=3.11"
dependencies = ["boto3>=1.34", "stripe==8.0.0"]
'''

def test_requirements_txt():
    recs = py.extract("clients/c", "requirements.txt", REQS)
    by = {r.tech_key: r for r in recs}
    assert by["lib:python/boto3"].declared_range == "==1.34.0"
    assert by["lib:python/boto3"].parse_quality == "exact"
    assert by["lib:python/requests"].declared_range == ">=2.31"
    assert by["lib:python/django"].parse_quality == "unlocked"   # bare name
    assert not any("other.txt" in k for k in by)                 # -r line skipped

def test_pyproject_project_table():
    recs = py.extract("clients/c", "pyproject.toml", PYPROJECT)
    keys = {r.tech_key for r in recs}
    assert "lib:python/boto3" in keys and "lib:python/stripe" in keys
    assert "runtime:python" in keys
    rt = next(r for r in recs if r.tech_key == "runtime:python")
    assert rt.version_hint == ">=3.11"

def test_pyproject_invalid_raises():
    with pytest.raises(ValueError):
        py.extract("clients/c", "pyproject.toml", "not = = toml")

def test_python_registered_for_both():
    assert extractor_for("x/requirements.txt") is py.extract
    assert extractor_for("x/pyproject.toml") is py.extract
