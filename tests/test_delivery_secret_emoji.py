from agent.lib.delivery import _emoji, _emoji_worst


def test_secret_kind_gets_its_own_urgency_glyph():
    assert _emoji({"kind": "secret", "severity": "CRITICAL"}) == "\U0001F511"   # 🔑


def test_a_secret_outranks_a_sunset_in_a_mixed_group():
    acts = [
        {"kind": "sunset", "status": "DEPRECATED", "date": "2027-01-01"},
        {"kind": "secret", "severity": "CRITICAL"},
    ]
    assert _emoji_worst(acts) == "\U0001F511"
