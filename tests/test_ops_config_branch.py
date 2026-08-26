"""`fleet` entries may name a branch. Strings must keep working untouched.

Many repos on this fleet keep a README on their default branch and the real code on `dev` or
`develop`, so the scan reads a placeholder. The config is the only place that can state which
branch is real: guessing it (most files, most recent commit) is the failure being fixed, not a fix.
"""
import pytest

from agent.lib import ops_config

# The generic message every malformed entry produced BEFORE the mapping form existed. Asserted
# against, not for: a `pytest.raises(match=...)` here silently matched the tmp_path baked into the
# message — which contains the test's own name — so four tests "passed" against this one generic
# error before a single line of the feature was written. Each test below now names the specific
# refusal it wants and rejects this one explicitly.
_GENERIC = "must be an https:// URL"


def _refusal(tmp_path, body):
    """Load and return the ConfigError message, failing loudly on the generic fallthrough."""
    with pytest.raises(ops_config.ConfigError) as exc:
        ops_config.load(_write(tmp_path, body))
    msg = str(exc.value)
    return msg


def _write(tmp_path, body):
    p = tmp_path / "drift.yml"
    p.write_text(body)
    return str(p)


_TAIL = """
delivery:
  mode: dry-run
  dev_as_issues: true
  devops_project: root/ops
"""


def test_a_plain_string_entry_still_parses(tmp_path):
    """The compatibility guarantee: every config in the wild today is a list of strings."""
    cfg = ops_config.load(_write(tmp_path, """
version: 1
fleet:
  - https://git.x/g/a
  - https://git.x/g/b
""" + _TAIL))
    assert cfg["fleet"] == [("https://git.x/g/a", None), ("https://git.x/g/b", None)]
    assert cfg["host"] == "git.x"


def test_a_mapping_entry_carries_its_branch(tmp_path):
    cfg = ops_config.load(_write(tmp_path, """
version: 1
fleet:
  - https://git.x/g/a
  - url: https://git.x/g/b
    branch: develop
""" + _TAIL))
    assert cfg["fleet"] == [("https://git.x/g/a", None), ("https://git.x/g/b", "develop")]


def test_a_mapping_without_a_url_is_refused(tmp_path):
    msg = _refusal(tmp_path, """
version: 1
fleet:
  - branch: develop
""" + _TAIL)
    assert _GENERIC not in msg, "fell through to the generic URL check instead of naming the gap"
    assert "url" in msg and "needs" in msg, msg



def test_an_unknown_key_in_the_mapping_is_named(tmp_path):
    """Consistent with the top-level validator, which refuses unknown keys rather than ignoring
    them — a silently-ignored `ref:` would read as configured and do nothing."""
    msg = _refusal(tmp_path, """
version: 1
fleet:
  - url: https://git.x/g/a
    tag: v1.0
""" + _TAIL)
    assert _GENERIC not in msg, "fell through to the generic URL check instead of naming the key"
    assert "tag" in msg and "unknown" in msg, msg



def test_an_empty_branch_is_refused(tmp_path):
    """`branch: ""` reads as configured and behaves as unconfigured — the gap this whole change
    exists to close. Omitting the key is how you ask for the default."""
    msg = _refusal(tmp_path, """
version: 1
fleet:
  - url: https://git.x/g/a
    branch: ""
""" + _TAIL)
    assert _GENERIC not in msg, "fell through to the generic URL check instead of naming branch"
    assert "branch" in msg and "omit" in msg.lower(), msg



def test_the_host_rule_still_applies_across_both_forms(tmp_path):
    """One fleet, one host — the mapping form must not become a way around it."""
    with pytest.raises(ops_config.ConfigError, match="host"):
        ops_config.load(_write(tmp_path, """
version: 1
fleet:
  - https://git.x/g/a
  - url: https://other.x/g/b
    branch: develop
""" + _TAIL))


def test_a_non_https_url_in_the_mapping_is_refused(tmp_path):
    """The mapping form is validated exactly as the string form is, not more loosely. This is the
    ONE case where the generic message is the right answer."""
    msg = _refusal(tmp_path, """
version: 1
fleet:
  - url: git@git.x:g/a.git
    branch: develop
""" + _TAIL)
    assert _GENERIC in msg, msg
    assert "git@git.x" in msg, "the offending url must be named, not just the rule"
