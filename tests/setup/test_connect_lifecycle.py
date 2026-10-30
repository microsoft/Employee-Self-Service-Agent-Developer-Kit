# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""DA Workday Connect lifecycle boundaries and guarded action contracts."""

from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_CONNECT = _ROOT / "solutions" / "ess-maker-skills" / "src" / "skills" / "connect"


def test_cea_state_cannot_mark_a_da_agent_connected() -> None:
    connected = (_CONNECT / "workday" / "status.md").read_text(encoding="utf-8")

    assert ".local/connect/workday-da/config.json" in connected
    assert "Do not read\n`.local/connect/workday/agents/`" in connected
    assert (
        "identity whose agent slug and BotId exactly match the active native DA agent."
        in " ".join(connected.split())
    )
    assert "Saved CEA lifecycle state" in connected
    assert "must not make an agent appear connected" in " ".join(connected.split())
    assert "not a fresh live validation" in " ".join(connected.split())


def test_workday_wiring_uses_installed_identity_and_explicit_result() -> None:
    action = (
        _CONNECT / "workday" / "actions" / "wire-user-context-redirect.md"
    ).read_text(encoding="utf-8")
    runtime_action = (
        _CONNECT / "workday" / "actions" / "wire-runtime-template-config.md"
    ).read_text(encoding="utf-8")

    assert "workspace/agents/{AGENT_SLUG}/.component-map.json" in action
    assert "workspace/agents/{AGENT_SLUG}/{USER_CONTEXT_TOPIC_PATH}" in action
    assert 'ACTION_RESULT = "applied"' in action
    assert "without asking for a separate publish confirmation" in " ".join(
        action.split()
    )
    assert 'dialog: "{USER_CONTEXT_DIALOG}"' in action
    assert 'dialog: "{WORKDAY_RUNTIME_TEMPLATE_DIALOG}"' in runtime_action
    assert "install-workday-extension-pack.md" not in action


def test_redirect_has_a_da_restore_point_and_returns_to_controller() -> None:
    action = (
        _CONNECT / "workday" / "actions" / "wire-user-context-redirect.md"
    ).read_text(encoding="utf-8")
    caller = (_CONNECT / "workday" / "configure-power-platform.md").read_text(
        encoding="utf-8"
    )

    assert "connect/workday/configure-power-platform.md" in action
    assert "lifecycle-runner.md" not in action
    assert action.index('checkpoint.py "pre-workday-user-context-redirect"') < (
        action.index("## A.3")
    )
    assert '--revert-reason "pre-workday-user-context-redirect"' in action
    assert '--only "{USER_CONTEXT_TOPIC_PATH}"' in action
    assert '--preferred-username "{POWER_PLATFORM_MAKER}"' in action
    assert "record-agent-binding" in action
    assert "Do not run a separate readiness checkpoint" in action
    assert 'redirect action returns `ACTION_RESULT = "applied"`' in caller
