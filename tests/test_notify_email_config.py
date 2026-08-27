"""`notify.email` — recipients in the config, the credential in an env var.

Recipients are not secrets the way the SMTP password is: they belong in review, in the MR,
versioned beside the fleet they describe. The credential keeps the `notify.gchat` pattern of
naming an env var rather than carrying a value.
"""
import pytest

from agent.lib import ops_config

# The message every malformed entry produced BEFORE this block existed. Asserted AGAINST, not for:
# a pytest.raises(match=...) silently matches the tmp_path baked into a ConfigError, and tmp_path
# contains the test's own function name. That has already produced four hollow tests in this repo.
_GENERIC = "unknown notify key"

_HEAD = "version: 1\nfleet:\n  - https://git.x/g/a\n"
_TAIL = "delivery:\n  mode: dry-run\n  dev_as_issues: true\n  devops_project: root/ops\n"


def _write(tmp_path, notify_block):
    p = tmp_path / "drift.yml"
    p.write_text(_HEAD + notify_block + _TAIL)
    return str(p)


def _refusal(tmp_path, notify_block):
    with pytest.raises(ops_config.ConfigError) as exc:
        ops_config.load(_write(tmp_path, notify_block))
    return str(exc.value)


def test_a_valid_email_block_loads(tmp_path):
    cfg = ops_config.load(_write(tmp_path, """notify:
  email:
    to: [ops@example.com, lead@example.com]
    from: drift@example.com
    smtp: DRIFT_SMTP_URL
"""))
    assert cfg["notify"]["email"] == {"to": ["ops@example.com", "lead@example.com"],
                                      "from": "drift@example.com", "smtp": "DRIFT_SMTP_URL"}


def test_no_notify_block_at_all_still_loads(tmp_path):
    """Opt-in. Every config in the wild today has no email block and must keep working."""
    cfg = ops_config.load(_write(tmp_path, ""))
    assert cfg["notify"]["email"] is None


def test_gchat_still_works_alongside(tmp_path):
    cfg = ops_config.load(_write(tmp_path, """notify:
  gchat: DRIFT_CHAT_WEBHOOK
  email:
    to: [ops@example.com]
    from: drift@example.com
    smtp: DRIFT_SMTP_URL
"""))
    assert cfg["notify"]["gchat"] == "DRIFT_CHAT_WEBHOOK"
    assert cfg["notify"]["email"]["to"] == ["ops@example.com"]


def test_missing_recipients_is_refused_by_name(tmp_path):
    msg = _refusal(tmp_path, """notify:
  email:
    from: drift@example.com
    smtp: DRIFT_SMTP_URL
""")
    assert _GENERIC not in msg
    assert "to" in msg and "recipient" in msg.lower()


def test_an_empty_recipient_list_is_refused(tmp_path):
    """`to: []` reads as configured and delivers to nobody — the exact silent failure this whole
    feature exists to avoid."""
    msg = _refusal(tmp_path, """notify:
  email:
    to: []
    from: drift@example.com
    smtp: DRIFT_SMTP_URL
""")
    assert "to" in msg and "empty" in msg.lower()


def test_a_malformed_address_is_refused_and_named(tmp_path):
    msg = _refusal(tmp_path, """notify:
  email:
    to: [not-an-address]
    from: drift@example.com
    smtp: DRIFT_SMTP_URL
""")
    assert "not-an-address" in msg


def test_a_missing_sender_or_smtp_is_refused(tmp_path):
    for block, want in (("""notify:
  email:
    to: [ops@example.com]
    smtp: DRIFT_SMTP_URL
""", "from"), ("""notify:
  email:
    to: [ops@example.com]
    from: drift@example.com
""", "smtp")):
        assert want in _refusal(tmp_path, block)


def test_an_unknown_key_inside_email_is_named(tmp_path):
    """Matching the top-level validator: a silently-ignored `cc:` would read as configured and do
    nothing."""
    msg = _refusal(tmp_path, """notify:
  email:
    to: [ops@example.com]
    from: drift@example.com
    smtp: DRIFT_SMTP_URL
    cc: [someone@example.com]
""")
    assert "cc" in msg and "unknown" in msg.lower()


def test_the_smtp_value_is_an_env_var_name_not_a_url(tmp_path):
    """Same rule as notify.gchat: the config names a variable, the secret lives in GitLab."""
    msg = _refusal(tmp_path, """notify:
  email:
    to: [ops@example.com]
    from: drift@example.com
    smtp: smtps://user:hunter2@smtp.example.com:465
""")
    assert "env" in msg.lower()
    assert "hunter2" not in msg, "the refusal echoed the credential it was rejecting"
