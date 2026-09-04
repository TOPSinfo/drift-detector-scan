"""Canned gitleaks JSON-report output for tests that inject the secrets engine.

gitleaks' real `detect --report-format json` output is a JSON array of objects carrying
`RuleID`, `File`, `StartLine`, `Commit`, `Secret`, `Match`, `Fingerprint`, and more. Only the
fields secrets_scan.run_secrets_scan actually reads are modeled here — a fixture with every
real gitleaks field would over-specify what these tests depend on.
"""
import json


def hit(rule_id: str, path: str, line: int, *, commit: str = "deadbeef",
        fingerprint: str | None = None, secret: str = "FAKE_SECRET_VALUE") -> dict:
    """One gitleaks finding. `secret` defaults to an obviously-fake placeholder so a test
    that forgets to check redaction still can't accidentally assert on a real-looking value."""
    return {
        "RuleID": rule_id, "File": path, "StartLine": line, "Commit": commit,
        "Secret": secret, "Match": secret,
        "Fingerprint": fingerprint or f"{commit}:{path}:{rule_id}:{line}",
    }


def canned(*hits) -> str:
    return json.dumps(list(hits))


EMPTY = json.dumps([])
