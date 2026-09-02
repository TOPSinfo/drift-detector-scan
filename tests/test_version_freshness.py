import pytest

from agent.lib import freshness_check


@pytest.mark.parametrize("installed,published,stale", [
    ("0.15.1-beta", "1.0.0", True),
    ("1.0.0", "1.0.0", False),
    ("1.0.1", "1.0.0", False),      # ahead of the marketplace: a dev checkout, not stale
    ("0.9.0", "0.10.0", True),      # numeric, not lexical: 9 < 10
    ("1.2.0", "1.2.0-rc.1", False),      # pre-release suffix digit must not corrupt the core
    ("1.2.0", "1.2.0-hotfix.5", False),  # same: "5" is not a fourth release component
    # The mirror case: a RELEASED 1.0.0 supersedes the 1.0.0-beta that preceded it. Reported
    # "up to date (1.0.0-beta)" until 2026-09-02 — a false "you are current" from the module
    # whose whole job is catching exactly this.
    ("1.0.0-beta", "1.0.0", True),
    ("v1.2", "1.3", True),          # the "v" prefix is accepted, and does not corrupt the core
])
def test_compare_detects_staleness(installed, published, stale):
    is_stale, _ = freshness_check.compare(installed, published)
    assert is_stale is stale


def test_the_message_names_both_versions_and_the_fix():
    _, msg = freshness_check.compare("0.15.1-beta", "1.0.0")
    assert "0.15.1-beta" in msg and "1.0.0" in msg
    assert "update" in msg.lower()


def test_an_unparseable_version_is_not_reported_as_stale():
    """Never guess. An unreadable version means "could not check", not "you are behind" — a
    false staleness warning trains people to ignore the real one."""
    is_stale, msg = freshness_check.compare("", "1.0.0")
    assert is_stale is False
    assert "could not" in msg.lower()
