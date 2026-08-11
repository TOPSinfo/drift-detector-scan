"""Guards the last-mile onboarding command (`/drift-detector onboard`) and its CI templates.

Onboarding writes CI config into a client's repo and wires a billable secret — so the guardrails are
load-bearing: (1) the API key must NEVER be baked into a template (it lives only in the platform
secret store); (2) the command must handle BOTH platforms; (3) the command must never push to the
default branch. Each assertion below pins one of those, plus the plumbing that makes the deployment
actually run (plugin install + `claude -p`)."""
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_TPL = _ROOT / "templates" / "ci"


def test_both_ci_templates_ship():
    assert (_TPL / "github-actions.yml").exists()
    assert (_TPL / "gitlab-ci.yml").exists()


def test_templates_install_the_plugin_and_run_headless():
    for name in ("github-actions.yml", "gitlab-ci.yml"):
        t = (_TPL / name).read_text()
        assert "claude plugin marketplace add TOPSinfo/drift-detector-scan" in t
        assert "claude plugin install drift-detector@tops-tools" in t
        # the actual scan — headless, with the fleet placeholder onboard fills in
        assert 'claude -p "/drift-detector __FLEET__" --permission-mode bypassPermissions' in t


def test_templates_reference_the_key_as_a_secret_never_inline():
    """The billable key must be a secret reference, and NO real key may ever sit in a template."""
    for name in ("github-actions.yml", "gitlab-ci.yml"):
        t = (_TPL / name).read_text()
        assert "ANTHROPIC_API_KEY" in t                       # referenced
        assert "sk-ant-" not in t                             # but never a literal key value
    # GitHub reads it from the Actions secret store; GitLab from a CI/CD variable.
    assert "${{ secrets.ANTHROPIC_API_KEY }}" in (_TPL / "github-actions.yml").read_text()


def test_github_template_has_cron_placeholder_and_gitlab_uses_schedule_rule():
    gh = (_TPL / "github-actions.yml").read_text()
    assert "__CRON__" in gh and "workflow_dispatch" in gh     # scheduled + manual
    gl = (_TPL / "gitlab-ci.yml").read_text()
    assert '$CI_PIPELINE_SOURCE == "schedule"' in gl          # fires on the pipeline schedule


def test_onboard_command_registered_and_present():
    plugin = json.loads((_ROOT / ".claude-plugin" / "plugin.json").read_text())
    assert "./commands/drift-onboard.md" in plugin["commands"]
    assert (_ROOT / "commands" / "drift-onboard.md").exists()


def test_onboard_command_guardrails():
    """The three load-bearing rules must be stated in the command itself."""
    c = (_ROOT / "commands" / "drift-onboard.md").read_text()
    # platform-agnostic: both CLIs named
    assert "gh secret set ANTHROPIC_API_KEY" in c and "glab variable set ANTHROPIC_API_KEY" in c
    # the key never passes through the session
    assert "never passes through this session" in c
    # a PR/MR, never a push to the default branch
    assert "Never push to the default branch" in c
    # prove it, don't assume it
    assert "Prove it" in c
