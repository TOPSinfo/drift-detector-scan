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


# ── through the real parser ──────────────────────────────────────────────────────────────────
# Everything above hands _cmd_chat_summary a hand-built namespace, so a `dest` rename in the
# parser would leave these green and the actual CLI broken. These drive argparse.


def test_the_full_flag_is_wired_through_real_argparse(tmp_path, capsys):
    st = _state(tmp_path)
    assert cli.main(["chat-summary", "--state", str(st), "--full"]) == 0
    assert "more unaudited" not in capsys.readouterr().out


def test_the_default_through_real_argparse_is_brief(tmp_path, capsys):
    st = _state(tmp_path)
    assert cli.main(["chat-summary", "--state", str(st)]) == 0
    assert "more unaudited" in capsys.readouterr().out


def test_the_brief_flag_is_accepted_and_is_the_default(tmp_path, capsys):
    """The spec and the plugin both name `--brief`. It selects what you already get — but a
    documented flag that exits 2 with "unrecognized arguments" is a bug, not a no-op."""
    st = _state(tmp_path)
    assert cli.main(["chat-summary", "--state", str(st), "--brief"]) == 0
    assert "more unaudited" in capsys.readouterr().out
