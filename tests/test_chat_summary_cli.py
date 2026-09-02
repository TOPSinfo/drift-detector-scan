"""The CLI surface of the closing block — the flag the plugin and CI select with."""
import json

from agent import cli


def _state(tmp_path, vendors=24):
    payload = {"generated": "2026-09-02",
               "counts": {"fixes": 1, "reposScanned": 1, "reposAffected": 1,
                          "byOwner": {"devops": {"fixes": 1, "review": 0},
                                      "developer": {"fixes": 0, "review": 0}}},
               "actions": [], "shapes": [], "rootsUnscannable": [],
               "catalog": [{"vendor": f"V{i}", "verdict": "UNAUDITED", "callSites": 30 - i}
                           for i in range(vendors)]}
    (tmp_path / "drift.json").write_text(json.dumps(payload))
    return tmp_path


def _args(state, full=False):
    return type("A", (), {"state": str(state), "full": full})()


def test_default_is_brief(tmp_path, capsys):
    assert cli._cmd_chat_summary(_args(_state(tmp_path))) == 0
    assert "more unaudited" in capsys.readouterr().out


def test_full_flag_uncaps_the_lists(tmp_path, capsys):
    assert cli._cmd_chat_summary(_args(_state(tmp_path), full=True)) == 0
    assert "more unaudited" not in capsys.readouterr().out


def test_the_flag_does_not_change_the_zero_repo_refusal(tmp_path, capsys):
    """`--full` is a verbosity, never a permission: an empty scan is refused in both."""
    st = _state(tmp_path)
    payload = json.loads((st / "drift.json").read_text())
    payload["counts"]["reposScanned"] = 0
    (st / "drift.json").write_text(json.dumps(payload))
    assert cli._cmd_chat_summary(_args(st, full=True)) == 4
    assert "NOT a clean result" in capsys.readouterr().out
