# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Static DA connection-routing contracts, not live model-behavior tests."""

from pathlib import Path

import pytest


_SOLUTION = Path(__file__).resolve().parents[2] / "solutions" / "ess-maker-skills"
_CONNECT = _SOLUTION / "src" / "skills" / "connect"


def _availability() -> str:
    return (_CONNECT / "SKILL.md").read_text(encoding="utf-8").split(
        "## Availability", 1
    )[1].split("## Start", 1)[0]


def test_service_now_contract_stops_before_connect_side_effects() -> None:
    contract = " ".join(_availability().split())

    assert "**Workday only**" in contract
    assert "ServiceNow integration isn't supported in this DA release." in contract
    assert "show this Message and STOP before" in contract
    for action in (
        "reading or writing provider state",
        "asking for credentials",
        "emitting connect telemetry",
        "configuring MCP",
        "loading or executing retained provider files",
    ):
        assert action in contract
    for branch in ("topic/workflow", "reconnect", "change-auth", "resume/continue", "repair"):
        assert branch in contract
    assert "Leave existing state unchanged" in contract
    assert "Do not substitute Workday" in contract


@pytest.mark.parametrize("alias", ("servicenow", "service now", "snow", "hrsd", "itsm"))
def test_service_now_aliases_share_the_availability_contract(alias: str) -> None:
    contract = _availability()

    assert "case-insensitive" in contract
    assert f"`{alias}`" in contract
    assert "PRE_SELECTED_INTEGRATION" in contract


def test_generic_connect_excludes_service_now_discovery_and_saved_state() -> None:
    route = (_CONNECT / "step1.md").read_text(encoding="utf-8")
    discovery = route.split("## 1.1", 1)[1].split("## 1.3", 1)[0]
    contract = " ".join(_availability().split())

    assert ".local/connect/workday-da/config.json" in discovery
    assert "servicenow" not in discovery.casefold()
    assert discovery.count("1. **Workday**") == 2
    assert "complete, incomplete, stale, or absent ServiceNow state" in contract
    assert "saved state cannot enable it" in contract
    assert "generic `/connect` never reads or advertises saved ServiceNow state" in contract


def test_preselection_and_retained_route_are_guarded_before_legacy_actions() -> None:
    route = (_CONNECT / "step1.md").read_text(encoding="utf-8")
    entry = " ".join(route.split("## 1.1", 1)[0].split())
    legacy = route.split("### If the user requested ServiceNow", 1)[1].split(
        "### If the user chose Workday", 1
    )[0]

    assert "Apply **Availability** in `src/skills/connect/SKILL.md`" in entry
    assert "PRE_SELECTED_INTEGRATION" in entry
    assert "before section 1.1" in entry
    assert "every selection before section 1.3" in entry
    assert "reference-only" in legacy
    assert "show its unavailable Message and STOP" in " ".join(legacy.split())
    for action in (
        "emit_capability.py connect --connector servicenow",
        ".local/connect/servicenow/steps.md",
        "vscode_askQuestions",
        "src/skills/connect/servicenow/step1.md",
        "src/skills/connect/servicenow/step2-entra.md",
        "src/skills/connect/servicenow/step3-entra.md",
        "src/skills/connect/servicenow/step4.md",
    ):
        assert legacy.index("Message and STOP") < legacy.index(action)
    assert '### If the user chose Workday (1 or "workday")' in route


def test_command_and_global_gates_check_availability_before_setup() -> None:
    prompt = (_SOLUTION / ".github" / "prompts" / "connect.prompt.md").read_text(
        encoding="utf-8"
    )
    instructions = (_SOLUTION / ".github" / "copilot-instructions.md").read_text(
        encoding="utf-8"
    )

    assert prompt.index("**Availability check.**") < prompt.index("**Setup-state check.**")
    assert "src/skills/connect/SKILL.md" in prompt.split("**Setup-state check.**", 1)[0]
    entry = instructions.split("## MANDATORY FIRST ACTION", 1)[0]
    assert "src/skills/connect/SKILL.md" in entry
    assert "before setup gating" in entry
    for branch in ("reconnect", "change-auth", "resume", "continue", "repair", "workflow"):
        assert branch in entry
    assert "never load or execute" in entry


def test_service_now_is_not_an_advertised_connect_trigger() -> None:
    instructions = (_SOLUTION / ".github" / "copilot-instructions.md").read_text(
        encoding="utf-8"
    )
    triggers = instructions.split("**Trigger phrases for connect:**", 1)[1].split(
        "**Trigger phrases for troubleshooting:**", 1
    )[0]
    guidance = instructions.split("### ServiceNow", 1)[1].split("### Workday", 1)[0]

    assert "Workday" in triggers
    assert "servicenow" not in triggers.casefold()
    assert "src/skills/connect/SKILL.md" in guidance
    assert "informational only" in guidance
    assert "| Connect to ServiceNow/Workday |" not in instructions


def test_flightcheck_does_not_offer_or_dispatch_service_now_connection_repair() -> None:
    text = (_SOLUTION / "src" / "skills" / "flightcheck" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    fixes = text.split("### 3c", 1)[1].split("### 3d", 1)[0]
    normalized = " ".join(fixes.split())

    assert fixes.index("**Availability**") < fixes.index("**Auto-fixable**")
    assert "ServiceNow connection findings are not auto-fixable" in normalized
    assert "- Missing Workday connection" in fixes
    assert "Missing Workday/ServiceNow connection" not in fixes
    assert "- Supported Workday connection issues" in fixes
    assert "with Workday preselected" in normalized
    assert "- Connection issues" not in fixes


def test_high_level_router_retains_no_service_now_execution_pointers() -> None:
    router = (_CONNECT / "SKILL.md").read_text(encoding="utf-8")

    assert "connect/servicenow/" not in router
    assert ".local/connect/servicenow/" not in router
    assert "src/skills/setup/workday-da/SKILL.md" in router
    assert (_CONNECT / "servicenow" / "step1.md").is_file()
    assert (_CONNECT / "servicenow" / "steps.md").is_file()


def test_readme_offers_supported_workday_not_service_now_connect() -> None:
    readme = (_SOLUTION / "README.md").read_text(encoding="utf-8")
    normalized = " ".join(readme.split())

    assert "/connect servicenow" not in readme
    assert "ServiceNow connection setup is not supported in this DA release" in normalized
    assert "| `/connect` | Choose the supported Workday integration |" in readme
    assert "/connect workday" in readme
