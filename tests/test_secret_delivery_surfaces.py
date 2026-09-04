"""Where a leaked credential SHOWS UP, and who is asked to fix it.

`kind: "secret"` was added to the audit and to the tiles, but nothing downstream was told
about it, so it fell through every seam by omission rather than by decision:

  - md_render's two queues match on kind (cve / eol+runtime / sunset / eol+non-runtime).
    A secret action matched NO predicate, so a CRITICAL leaked credential rendered in NO
    table at all in drift.md — the tool's primary view.
  - owners.owner() had no `secret` case; it landed on "developer" by fall-through.
  - the delivery body then described it with the wrong stream's prose.
  - _rank_key's "action-required first" boost keys on status == "DEPRECATED"; a secret's
    status is "EXPOSED", so the most urgent finding the tool can produce sorted below a
    low-severity retiring API.
"""
from agent.lib import md_render as md, owners
from agent.lib.actions import build_actions
from agent.lib.delivery import devops_repo_body


def _secret_action(repo="web", rule="generic-api-key", loc="config/keys.php:5",
                   status="EXPOSED"):
    return {"kind": "secret", "repo": repo, "ref": rule, "unit": loc, "owner": "devops",
            "status": status, "date": None, "fix_version": None, "worst": "CRITICAL",
            "finding_count": 1, "file_count": 1, "files": [{"loc": loc}],
            "recommendation": "Rotate the credential with its vendor, then remove it from "
                              "source and read it from the environment instead."}


def _payload(actions, **over):
    base = {"generated": "2026-09-04", "actions": actions,
            "counts": {"fixes": 0, "sunsets": 0, "eol": 0, "critical": 0, "unaudited": 0,
                       "secrets": len([a for a in actions if a["kind"] == "secret"]),
                       "reposAffected": 1, "reposScanned": 1}}
    base.update(over)
    return base


# ── Fix 6: ownership is a decision, not a fall-through ────────────────────────────

def test_a_secret_is_explicitly_owned_by_devops():
    """Rotating and revoking the credential with its vendor is the only step that actually
    ends the exposure, and it happens in the secret store / vendor console, not in the repo."""
    assert owners.owner({"kind": "secret", "refKind": None}) == owners.DEVOPS


def test_the_owner_of_a_secret_survives_the_action_rollup():
    a = build_actions([{"repo": "web", "ref": "generic-api-key", "kind": "secret",
                        "status": "EXPOSED", "severity": "CRITICAL",
                        "files": ["config/keys.php:5"]}])[0]
    assert a["owner"] == owners.DEVOPS


# ── Fix 5: it must actually render in drift.md ────────────────────────────────────

def test_a_secret_action_renders_in_a_table_of_its_own():
    out = md.render_markdown(_payload([_secret_action()]), "2026-09-04")
    assert "### Exposed credentials" in out, (
        "a secret action matches no queue predicate, so the most urgent thing the scanner "
        "can find renders in NO table in the primary view")
    assert "| Repo | Rule | Status | Detected | Call-sites | First call-site |" in out
    assert "| web | generic-api-key config/keys.php:5 | EXPOSED | — | 1 | config/keys.php:5 |" in out


def test_the_exposed_credentials_table_sits_in_the_devops_queue():
    out = md.render_markdown(_payload([_secret_action()]), "2026-09-04")
    assert out.index("## DevOps queue") < out.index("### Exposed credentials")


def test_two_leaks_of_one_rule_render_as_two_distinguishable_rows():
    """md-row-identity (verify.py) rejects a report where two findings rows are byte-identical;
    with per-leak grouping the call-site column keeps them apart."""
    out = md.render_markdown(_payload([
        _secret_action(loc="config/keys.php:5"),
        _secret_action(loc="app/Feed.php:88")]), "2026-09-04")
    assert "config/keys.php:5" in out and "app/Feed.php:88" in out


def test_no_exposed_credentials_section_when_there_are_no_secrets():
    out = md.render_markdown(_payload([
        {"kind": "cve", "ref": "composer/acme/x", "unit": None, "owner": "devops",
         "status": "DEPRECATED", "date": None, "fix_version": "1.2.3", "finding_count": 1,
         "files": [{"loc": "composer.json:1"}]}]), "2026-09-04")
    assert "Exposed credentials" not in out


# ── Fix 7: the delivered body must not misdescribe a leak ─────────────────────────

def test_the_delivered_body_tells_the_reader_to_rotate_not_to_bump_a_manifest():
    body = devops_repo_body("web", [_secret_action()])
    assert "Rotate" in body
    assert "config/keys.php:5" in body
    # the DevOps stream's stock framing is "bump the manifest/lockfile or base image" —
    # true of a CVE and an EOL runtime, false and misleading for a leaked credential
    assert "Exposed credential" in body


def test_a_secret_body_never_claims_the_credential_retires_on_a_date():
    body = devops_repo_body("web", [_secret_action()])
    assert "retires" not in body


def test_a_non_secret_devops_body_is_unchanged():
    cve = {"kind": "cve", "repo": "web", "ref": "composer/acme/x", "unit": None,
           "status": "DEPRECATED", "date": None, "recommendation": "upgrade to >= 1.2.3"}
    body = devops_repo_body("web", [cve])
    assert "## composer/acme/x — DEPRECATED" in body
    assert "Exposed credential" not in body
