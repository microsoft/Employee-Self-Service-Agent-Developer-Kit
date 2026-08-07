# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Structural guards for the isolated foundation setup flow."""

from __future__ import annotations

import re
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SOLUTION = _REPO_ROOT / "solutions" / "ess-maker-skills"
_FOUNDATION = (
    _SOLUTION / "src" / "skills" / "foundation-setup" / "SKILL.md"
)
_SCOPE = _SOLUTION / "src" / "skills" / "foundation-setup" / "scope.md"
_PREREQUISITES = (
    _SOLUTION / "src" / "skills" / "foundation-setup" / "prerequisites.md"
)
_ENVIRONMENT = (
    _SOLUTION / "src" / "skills" / "foundation-setup" / "environment.md"
)
_ONBOARDING_STEP1 = _SOLUTION / "src" / "skills" / "onboarding" / "step1.md"
_ONBOARDING_STEP1B = (
    _SOLUTION / "src" / "skills" / "onboarding" / "step1b.md"
)
_ONBOARDING_STEP2 = (
    _SOLUTION / "src" / "skills" / "onboarding" / "step2.md"
)
_ONBOARDING_TASKS = (
    _SOLUTION / "src" / "skills" / "onboarding" / "tasks.md"
)
_ONBOARDING_STEP3 = (
    _SOLUTION / "src" / "skills" / "onboarding" / "step3-flightcheck.md"
)
_ONBOARDING = _SOLUTION / "src" / "skills" / "onboarding" / "SKILL.md"
_FOUNDATION_BOOTSTRAP = (
    _SOLUTION
    / "src"
    / "skills"
    / "onboarding"
    / "foundation-bootstrap.md"
)
_INSTALL_STARTERS = (
    _SOLUTION
    / "src"
    / "skills"
    / "foundation-setup"
    / "install-starters.md"
)
_READINESS = (
    _SOLUTION / "src" / "skills" / "foundation-setup" / "readiness.md"
)
_INSTALLATION_CATALOG = (
    _SOLUTION / "src" / "reference" / "ess-agent-installation" / "config.json"
)
_UI_FORMATTING_GUIDELINES = (
    _SOLUTION / "src" / "reference" / "ui-formatting-guidelines.md"
)
_WORKDAY = _SOLUTION / "src" / "skills" / "setup" / "SKILL.md"
_CONNECT_STEP1 = _SOLUTION / "src" / "skills" / "connect" / "step1.md"
_INSTRUCTIONS = _SOLUTION / ".github" / "copilot-instructions.md"
_SETUP_PROMPT = _SOLUTION / ".github" / "prompts" / "setup.prompt.md"
_PATH_RE = re.compile(r"`(src/skills/[^`]+?\.md)`")


def test_public_setup_routes_to_foundation_module() -> None:
    instructions = _INSTRUCTIONS.read_text(encoding="utf-8")
    prompt = _SETUP_PROMPT.read_text(encoding="utf-8")

    assert "src/skills/foundation-setup/SKILL.md" in instructions
    assert "src/skills/foundation-setup/SKILL.md" in prompt
    assert "Do not route directly to `src/skills/onboarding/SKILL.md`" in prompt


def test_workday_routing_remains_unchanged() -> None:
    step1 = _CONNECT_STEP1.read_text(encoding="utf-8")

    assert "src/skills/setup/SKILL.md" in step1
    assert "src/skills/foundation-setup/SKILL.md" not in step1
    assert _WORKDAY.is_file()


def test_foundation_dispatches_all_playbooks() -> None:
    text = _FOUNDATION.read_text(encoding="utf-8")
    expected = {
        "src/skills/foundation-setup/scope.md",
        "src/skills/foundation-setup/prerequisites.md",
        "src/skills/foundation-setup/environment.md",
        "src/skills/foundation-setup/alm-baseline.md",
        "src/skills/foundation-setup/install-starters.md",
        "src/skills/foundation-setup/readiness.md",
        "src/skills/foundation-setup/handoff.md",
    }

    assert expected <= set(_PATH_RE.findall(text))
    assert ".local/connect/workday/config.json" not in text


def test_capacity_is_an_automated_blocking_gate() -> None:
    text = " ".join(_PREREQUISITES.read_text(encoding="utf-8").split())

    assert "Do not ask the maker to select or confirm a billing model" in text
    assert "Continue only when the checkpoint reports `Passed`" in text
    assert '"allowFreeformInput": false' in text
    assert '--cause "Copilot Studio message capacity is not allocated"' in text
    assert "Show this message verbatim once" in text
    assert "admin.powerplatform.microsoft.com/billing/licenses/copilotStudio/overview" in text
    assert "Open the `Manage capacity` tab" in text
    assert "Find `{ENVIRONMENT_NAME}`" in text
    assert "Render the verbatim remediation only once" in text
    assert "do not print another blocked-state summary" in text
    assert "Do not ask governance questions" in text
    assert "There is no skip, continue, defer" in text
    assert "replies with `skip`" in text
    assert "Do not accept Pay-as-you-go" in text


def test_resume_never_replays_completed_prerequisites() -> None:
    router = " ".join(_FOUNDATION.read_text(encoding="utf-8").split())
    prerequisites = " ".join(_PREREQUISITES.read_text(encoding="utf-8").split())

    assert "Never infer the active step from prior conversation" in router
    assert "do not read or execute `foundation-setup/prerequisites.md`" in router
    assert "only when the current persisted `active_step`" in prerequisites
    assert "Do not rerun Dataverse MCP, capacity, or governance" in prerequisites


def test_alm_step_reuses_env009_as_an_optional_step_checkpoint() -> None:
    alm = (
        _SOLUTION / "src" / "skills" / "foundation-setup" / "alm-baseline.md"
    ).read_text(encoding="utf-8")
    tasks = (
        _SOLUTION / "src" / "skills" / "foundation-setup" / "tasks.md"
    ).read_text(encoding="utf-8")

    assert "--checkpoint ENV-009" in alm
    assert "Skip preferred solution setup" in alm
    assert "exactly three options" in alm
    assert "checks:" not in tasks
    assert "When the maker skips, no validation is required." in alm
    assert "SETUP-ALM-" not in alm
    assert "SETUP-ALM-" not in tasks


def test_foundation_router_paths_resolve() -> None:
    referenced = set(_PATH_RE.findall(_FOUNDATION.read_text(encoding="utf-8")))
    missing = [
        path
        for path in sorted(referenced)
        if not (_SOLUTION / path).is_file()
    ]

    assert not missing


def test_foundation_does_not_prompt_for_non_decisions() -> None:
    router = _FOUNDATION.read_text(encoding="utf-8")
    scope = _SCOPE.read_text(encoding="utf-8")

    assert "ask the maker to confirm resuming" not in router
    assert "Picking up at:" not in router
    assert "Confirm that this run covers" not in scope


def test_selected_environment_requires_approved_maker_role() -> None:
    scope = _SCOPE.read_text(encoding="utf-8")
    normalized = " ".join(scope.split())

    assert "scripts/check_environment_roles.py" in scope
    assert "ENVIRONMENT_ROLE_ACCESS_JSON:" in scope
    assert "When `eligible` is true, continue immediately" in scope
    assert "do not lock the environment" in scope
    assert (
        "needs the **System Administrator** role"
        in normalized
    )
    assert "needs both the **Environment Maker**" not in normalized
    assert "directly and through team membership" in scope


def test_scope_asks_how_to_provide_environment_before_discovery() -> None:
    scope = _SCOPE.read_text(encoding="utf-8")

    prompt_index = scope.index(
        "How would you like to choose your Power Platform environment?"
    )
    list_index = scope.index("python scripts/discover.py --list-environments")

    assert prompt_index < list_index
    assert "Yes, list my environments" in scope
    assert "No, I'll enter the URL manually" in scope
    assert "Create a new environment" in scope
    assert "What's your Power Platform environment URL?" in scope
    assert "--resolve-environment-url" in scope
    assert "ENVIRONMENT_LIST_JSON:" in scope
    assert "--list-environments --select" not in scope


def test_scope_uses_discovered_environment_type_without_prompting() -> None:
    scope = _SCOPE.read_text(encoding="utf-8")
    normalized = " ".join(scope.split())

    assert "ENVIRONMENT_PLATFORM_TYPE" in scope
    assert "Do not ask the maker to classify the environment." in normalized
    assert "classify the selected target as Dev, Test, or Prod" not in scope
    assert "{Dev|Test|Prod}" not in scope


def test_install_step_selects_one_product_without_default_selection() -> None:
    scope = _SCOPE.read_text(encoding="utf-8")
    installation = _INSTALL_STARTERS.read_text(encoding="utf-8")
    normalized = " ".join(installation.split())

    assert "--inventory-only" not in scope
    assert "--product \"{PRODUCT_ID}\"" not in scope
    assert "--inventory-only" in installation
    assert "ESS_AGENT_DISCOVERY_JSON:" in installation
    assert "availableInstallations" in installation
    assert "Do not offer an installed product as an installation option." in (
        normalized
    )
    assert (
        "Installed: **{agent 1 name}**; **{agent 2 name}**"
        in installation
    )
    assert "Customize an installed agent" in installation
    assert "Allow exactly one selection." in installation
    assert "Do not mark any option as recommended in the tool metadata" in (
        normalized
    )
    assert "do not preselect an option" in normalized
    assert "select-product" in installation
    assert "--product \"{PRODUCT_ID}\"" in installation
    assert "ANOTHER_PRODUCT_ID" not in installation
    assert "--status installed" in installation
    assert "it does not reinstall it" in normalized


def test_scope_guides_and_verifies_new_environment_creation() -> None:
    scope = _SCOPE.read_text(encoding="utf-8")
    normalized = " ".join(scope.split())

    assert "Power Platform or Dynamics 365 administrator" in normalized
    assert "at least 1 GB of available database capacity" in normalized
    assert "Set `Add a Dataverse data store` to `Yes`." in scope
    assert "Keep the release cycle standard" in scope
    assert (
        "assign **System Administrator**"
        in normalized
    )
    assert "create-an-environment-with-a-database" in scope
    assert "Never assume creation succeeded" in normalized
    assert (
        scope.index("Create a new environment")
        < scope.index("scripts/check_environment_roles.py")
    )


def test_dataverse_mcp_enablement_is_checked_automatically() -> None:
    prerequisites = _PREREQUISITES.read_text(encoding="utf-8")
    onboarding = _ONBOARDING_STEP1.read_text(encoding="utf-8")

    assert "scripts/check_dataverse_mcp.py" in prerequisites
    assert "scripts/check_dataverse_mcp.py" in onboarding
    assert "without asking the maker anything" in prerequisites
    assert "Type **done**" not in onboarding


def test_readiness_records_manual_attestation_provenance() -> None:
    readiness = " ".join(_READINESS.read_text(encoding="utf-8").split())

    assert "--mode {automated|manual-attested}" in readiness
    assert "when any selected starter required manual readiness attestation" in (
        readiness
    )


def test_environment_access_does_not_require_redundant_attestation() -> None:
    prerequisites = _PREREQUISITES.read_text(encoding="utf-8")

    assert "both Power Platform and Copilot Studio" not in prerequisites
    assert "Do not ask whether the maker can" in prerequisites
    assert "Do not ask the maker to select or confirm a billing model" in prerequisites
    assert "do not replace a failed automated result" in prerequisites
    assert "discover.py --list-environments" not in prerequisites


def test_locked_environment_is_not_reconfirmed() -> None:
    environment = _ENVIRONMENT.read_text(encoding="utf-8")
    normalized = " ".join(environment.split())

    assert "Do not ask whether it is still intended" in normalized
    assert "do not show a confirmation popup" in normalized
    assert "Ask the maker to confirm" not in environment
    assert "ENVIRONMENT_DRIFT" in environment
    assert environment.count('--environment-url "{ENVIRONMENT_URL}"') == 1
    assert environment.count('--environment-id "{ENVIRONMENT_ID}"') == 1
    assert "Do not read `.local/config.json`" in environment
    assert "no more than 15 minutes old" in environment
    assert "--quiet-auth" in environment


def test_foundation_flightchecks_use_locked_environment_context() -> None:
    prerequisites = _PREREQUISITES.read_text(encoding="utf-8")

    assert prerequisites.count(
        '--environment-url "{ENVIRONMENT_URL}"'
    ) == 2
    assert prerequisites.count(
        '--environment-id "{ENVIRONMENT_ID}"'
    ) == 2
    assert prerequisites.count("--quiet-auth") == 2


def test_foundation_uses_targeted_state_views_and_compact_transitions() -> None:
    router = _FOUNDATION.read_text(encoding="utf-8")
    prerequisites = _PREREQUISITES.read_text(encoding="utf-8")
    installation = _INSTALL_STARTERS.read_text(encoding="utf-8")

    assert "show --view current" in router
    assert "Do not rerender the full checklist between steps." in router
    assert "show --view environment" in prerequisites
    assert "show --view products" in installation


def test_onboarding_reuses_locked_foundation_environment() -> None:
    onboarding = _ONBOARDING_STEP1.read_text(encoding="utf-8")

    assert "python scripts/setup_state.py show --view report" in onboarding
    assert "environment.tenant_endpoint" in onboarding
    assert "Do not list environments" in onboarding


def test_onboarding_offers_install_or_customize_for_existing_agents() -> None:
    discovery = _ONBOARDING_STEP1B.read_text(encoding="utf-8")
    normalized = " ".join(discovery.split())

    assert "install another ESS agent or customize" in discovery
    assert "Customize an installed agent" in discovery
    assert "setup_state.py add-product" in discovery
    assert "Installed: **{agent 1 name}**; **{agent 2 name}**" in discovery
    assert "Do not render installed agent names as plain text." in normalized


def test_foundation_handoff_routes_directly_to_agent_inventory() -> None:
    handoff = (
        _SOLUTION / "src" / "skills" / "foundation-setup" / "handoff.md"
    ).read_text(encoding="utf-8")
    bootstrap = _FOUNDATION_BOOTSTRAP.read_text(encoding="utf-8")
    extraction = _ONBOARDING_STEP2.read_text(encoding="utf-8")

    assert "onboarding/foundation-bootstrap.md" in handoff
    assert "onboarding/SKILL.md" not in handoff
    assert "Do not display that checklist." in bootstrap
    assert "onboarding/step1b.md" in bootstrap
    assert "FOUNDATION_REUSED" in bootstrap
    assert "| # | Task | Status |" not in extraction


def test_onboarding_does_not_offer_legacy_optional_readiness_check() -> None:
    router = _ONBOARDING.read_text(encoding="utf-8")
    normalized_router = " ".join(router.split())
    discovery = _ONBOARDING_STEP1B.read_text(encoding="utf-8")
    extraction = _ONBOARDING_STEP2.read_text(encoding="utf-8")
    tasks = _ONBOARDING_TASKS.read_text(encoding="utf-8")

    assert "delete only that row" in router
    assert (
        "legacy optional FlightCheck is no longer part"
        in normalized_router
    )
    assert "Readiness check (optional)" not in router
    assert "Readiness check (optional)" not in discovery
    assert "Readiness check (optional)" not in extraction
    assert "Readiness check" not in tasks
    assert "pre-deployment readiness check when needed" in extraction
    assert not _ONBOARDING_STEP3.exists()


def test_onboarding_guidance_uses_precise_markdown_formatting() -> None:
    router = _ONBOARDING.read_text(encoding="utf-8")
    foundation = _FOUNDATION.read_text(encoding="utf-8")
    installation = _INSTALL_STARTERS.read_text(encoding="utf-8")
    catalog = _INSTALLATION_CATALOG.read_text(encoding="utf-8")
    guidelines = _UI_FORMATTING_GUIDELINES.read_text(encoding="utf-8")

    assert "src/reference/ui-formatting-guidelines.md" in router
    assert "src/reference/ui-formatting-guidelines.md" in foundation
    assert "Use a numbered list for any sequence of UI actions." in guidelines
    assert "Do not use bold for portal controls" in guidelines
    assert "Never show unresolved placeholders" in guidelines
    assert "Do not add complete popup messages" in guidelines
    assert "Verify an installed agent connection" not in guidelines
    assert "[Power Apps](https://make.powerapps.com)" in installation
    assert "`Connections`" in installation
    assert "`New connection`" in installation
    assert "**{displayName}**" in installation
    assert "Select the `{ENVIRONMENT_NAME}` environment." in installation
    assert "connection-attestation-required" in installation
    assert "attest-product-connection" in installation
    assert "connectionSettingsUrl" in installation
    assert "There is no skip option." in installation
    assert "`Connection settings`" in installation
    assert (
        "Is **{CONNECTION_DISPLAY_NAME}** connected"
        in installation
    )
    assert r"\`{AGENT_NAME}\` agent?" in installation
    assert "In the `Manage` column, choose `See details`." in installation
    assert "Open `Connection parameters`." in installation
    assert (
        "If parameters are available, enable sharing for the parameters"
        in installation
    )
    assert "`Save`." in installation
    assert "In make.powerapps.com, select the target environment" not in catalog
