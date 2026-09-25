# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Structural guards for the DA-GA foundation setup flow."""

from __future__ import annotations

import re
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SOLUTION = _REPO_ROOT / "solutions" / "ess-maker-skills"
_FOUNDATION = _SOLUTION / "src" / "skills" / "foundation-setup" / "SKILL.md"
_DA_EXISTING_DEV = (
    _SOLUTION / "src" / "skills" / "foundation-setup" / "da-existing-dev.md"
)
_DA_ALM_IMPORT = (
    _SOLUTION / "src" / "skills" / "foundation-setup" / "da-alm-import.md"
)
_DA_PROD_TO_DEV = (
    _SOLUTION / "src" / "skills" / "foundation-setup" / "da-prod-to-dev.md"
)
_DA_MOS_STARTER = (
    _SOLUTION / "src" / "skills" / "foundation-setup" / "da-mos-starter.md"
)
_DA_ENVIRONMENT_TARGET = (
    _SOLUTION
    / "src"
    / "skills"
    / "foundation-setup"
    / "da-environment-target.md"
)
_PRODUCT_LINE_RECONCILIATION = (
    _SOLUTION
    / "src"
    / "skills"
    / "foundation-setup"
    / "product-line-reconciliation.md"
)
_PRODUCT_LINE_RELEASES = (
    _SOLUTION / "src" / "reference" / "product-line-releases.json"
)
_NATIVE_ALM_REFERENCE = (
    _SOLUTION / "src" / "reference" / "native-alm-import.md"
)
_MOS_STARTER_REFERENCE = (
    _SOLUTION / "src" / "reference" / "mos-starter-package.md"
)
_DA_PRODUCT_REGISTRY = (
    _SOLUTION / "src" / "reference" / "da-product-setup-registry.json"
)
_UI_FORMATTING = _SOLUTION / "src" / "reference" / "ui-formatting-guidelines.md"
_PREPARE_FRESH_WORKSPACE = _SOLUTION / "scripts" / "prepare_fresh_workspace.py"
_RESET_LOCAL_WORKSPACE = _SOLUTION / "scripts" / "reset_local_workspace.py"
_WORKDAY = _SOLUTION / "src" / "skills" / "setup" / "SKILL.md"
_CONNECT_STEP1 = _SOLUTION / "src" / "skills" / "connect" / "step1.md"
_INSTRUCTIONS = _SOLUTION / ".github" / "copilot-instructions.md"
_SETUP_PROMPT = _SOLUTION / ".github" / "prompts" / "setup.prompt.md"
_PROMPTS = _SOLUTION / ".github" / "prompts"
_MAKER_PROFILE = (
    _REPO_ROOT / "tools" / "ess-maker-profile" / "extension" / "extension.js"
)
_PATH_RE = re.compile(r"`(src/skills/[^`]+?\.md)`")


def test_public_setup_routes_to_da_foundation_module() -> None:
    instructions = _INSTRUCTIONS.read_text(encoding="utf-8")
    prompt = _SETUP_PROMPT.read_text(encoding="utf-8")

    assert "src/skills/foundation-setup/SKILL.md" in instructions
    assert "Classify the supplied URL first" in instructions
    assert "before announcing a mismatch" in instructions
    assert "src/skills/foundation-setup/SKILL.md" in prompt
    assert "Do not route to Dataverse foundation or onboarding playbooks" in prompt


def test_setup_reconciles_every_selected_agent_before_da_only_work() -> None:
    foundation = _FOUNDATION.read_text(encoding="utf-8")
    normalized_foundation = " ".join(foundation.split())
    prompt = _SETUP_PROMPT.read_text(encoding="utf-8")
    normalized_prompt = " ".join(prompt.split())
    reconciliation = _PRODUCT_LINE_RECONCILIATION.read_text(encoding="utf-8")
    normalized_reconciliation = " ".join(reconciliation.split())
    existing_dev = _DA_EXISTING_DEV.read_text(encoding="utf-8")
    mos_starter = _DA_MOS_STARTER.read_text(encoding="utf-8")
    alm_import = _DA_ALM_IMPORT.read_text(encoding="utf-8")
    prod_to_dev = _DA_PROD_TO_DEV.read_text(encoding="utf-8")

    assert _PRODUCT_LINE_RECONCILIATION.is_file()
    assert _PRODUCT_LINE_RELEASES.is_file()
    assert "## Reconcile every selected agent" in foundation
    assert (
        "regardless of whether the identity came from a supplied URL, active "
        "local setup state, a configured-agent switch, environment candidate "
        "selection, MOS creation, or ALM import"
    ) in normalized_foundation
    assert foundation.index("product-line-reconciliation.md") < foundation.index(
        "setup_existing_da.py inspect-agent"
    )
    assert "product-line reconciliation before the next DA-GA-only operation" in (
        " ".join(prompt.split())
    )
    assert normalized_prompt.index(
        "product-line reconciliation now"
    ) < normalized_prompt.index(
        "check the Microsoft Object Model converter"
    )
    assert (
        "do not install or validate the Microsoft Object Model converter"
        in normalized_prompt
    )
    assert "complete its kit-switch handoff" in normalized_prompt
    assert "python scripts/reconcile_setup_agent.py" in reconciliation
    assert "--native-da-ga" in reconciliation
    assert "DA_SETUP_PRODUCT_RECONCILIATION_JSON:" in reconciliation
    assert "action: stop-and-use-cea-kit" in reconciliation
    assert "action: continue-da-ga-setup" in reconciliation
    assert "deliberately fail-open" in normalized_reconciliation
    assert "generic API failures" in normalized_reconciliation
    for mismatch_state in (
        "**Choose the starting point and target environment** as complete",
        "**Verify access and agent identity** as blocked",
        "**Establish an editable Dev agent** and "
        "**Materialize the local workspace** as pending",
        "**Review the setup handoff** as in progress",
    ):
        assert mismatch_state in normalized_reconciliation
    assert (
        "Want me to install the compatible CEA kit in a separate folder and open "
        "it now?"
    ) in normalized_reconciliation
    assert "When the maker accepts, run `recoveryCommand`" in reconciliation
    assert "When the maker declines" in reconciliation
    assert "When command execution fails" in reconciliation
    assert "Do not label the unchanged command as a retry" in reconciliation
    assert "verify that its checkout matches `releaseTag`" in reconciliation
    assert "offer to open its `solutions/ess-maker-skills` workspace directly" in (
        reconciliation
    )
    assert reconciliation.count("**Review the setup handoff** as complete") == 2
    assert reconciliation.count("**Review the setup handoff** as blocked") == 2
    assert "No Copilot Studio agent or setup state was changed" in reconciliation
    assert "installation was not changed" not in reconciliation
    assert "identity returned by this native list" in existing_dev
    assert mos_starter.count("selected-agent product-line reconciliation") >= 2
    assert alm_import.count("selected-agent product-line reconciliation") >= 2
    assert "selected-agent product-line reconciliation" in prod_to_dev


def test_foundation_defines_setup_state_sources() -> None:
    foundation = _FOUNDATION.read_text(encoding="utf-8")
    normalized = " ".join(foundation.split())

    assert "**Current setup state:** `.local/setup/config.json`" in foundation
    assert "**Active agent and workspace:** `.local/config.json`" in foundation
    assert "**Setup evidence:** `.local/setup/agents/{AGENT_ID}/`" in foundation
    assert (
        "Use the active agent's entry in `.local/setup/config.json` when "
        "determining its setup progress and readiness."
    ) in normalized
    assert "they are not a separate setup record" in normalized


def test_public_setup_resolves_python_before_bootstrap_commands() -> None:
    prompt = _SETUP_PROMPT.read_text(encoding="utf-8")
    foundation = _FOUNDATION.read_text(encoding="utf-8")
    normalized_prompt = " ".join(prompt.split())
    normalized_foundation = " ".join(foundation.split())
    runtime_message = """> **Setup command approvals**
>
> VS Code will ask you to approve commands that:
>
> - check Python and prepare the required local tools;
> - sign you in and inspect the selected environment and agent;
> - perform the setup actions you confirm and prepare the local workspace;
> - download required Microsoft components when needed.
>
> To avoid repeated prompts, open the permissions menu below the chat input and
> select **Allow all** for this chat session. This applies to every tool used in
> the session, not only setup. Provide a screenshot of your chat input if you
> need guidance finding the setting.
>
> When you're ready, choose:"""
    declined_command_message = """> **Run this command manually**
>
> Setup paused before running this command:

```{SHELL}
{COMMAND}
```

> Run it from the current workspace. When it finishes, return here with the
> result and I'll continue setup from this step."""

    assert prompt.index("Read `src/skills/foundation-setup/SKILL.md` first") < (
        prompt.index("{PYTHON} -m pip install")
    )
    assert runtime_message in foundation
    assert foundation.index(runtime_message) < foundation.index(
        '{PYTHON} -c "import sys; print(sys.executable)"'
    )
    assert foundation.index("- **Continue setup**") < foundation.index(
        "- **Cancel setup**"
    )
    assert "Do not preselect a choice." in foundation
    assert "For **Cancel setup**, run no commands and stop." in foundation
    assert "### When command approval is declined" in foundation
    assert declined_command_message in foundation
    assert (
        "Resume from the paused operation when the maker returns."
        in normalized_foundation
    )
    object_model_check = (
        "{PYTHON} -c \"import sys; sys.path.insert(0, 'scripts'); "
        "import agentbuilder_object_model as m; "
        'm.validate_object_model_runtime()"'
    )
    assert normalized_prompt.index(
        "{PYTHON} -m pip install"
    ) < normalized_prompt.index(
        object_model_check
    )
    assert normalized_prompt.index(object_model_check) < normalized_prompt.index(
        "{PYTHON} scripts/install_agentbuilder_object_model.py"
    )
    assert "If the check fails, run:" in prompt
    assert "Then rerun the check" in prompt
    assert "without showing it to the user" not in prompt
    assert "Prepare the local setup tools" not in prompt
    assert "Prepare agent-file support" not in prompt
    assert "python -m pip install" not in prompt
    assert "python scripts/mcp_config.py" not in prompt
    assert "For any command failure" in normalized_prompt
    assert "stop only if none works" not in normalized_prompt
    assert "show the exact error and stop" not in normalized_prompt
    assert "Establish a working Python invocation" in normalized_foundation
    assert "`py -3`, `python3`, then `python` on Windows" in (
        normalized_foundation
    )
    assert "`python3`, then `python` on macOS or Linux" in normalized_foundation
    assert "check each candidate with" in normalized_foundation
    assert "one terminal command at a time" in normalized_foundation
    assert "active virtual environments, common local installation paths" in (
        normalized_foundation
    )
    assert "offer to perform it" in normalized_foundation
    assert prompt.index(
        "After reading the foundation skill, use its explicit progress render "
        "points"
    ) < prompt.index("{PYTHON} -m pip install")
    checklist = "\n".join(
        (
            "- {marker} Choose the starting point and target environment",
            "- {marker} Verify access and agent identity",
            "- {marker} Establish an editable Dev agent",
            "- {marker} Materialize the local workspace",
            "- {marker} Review the setup handoff",
        )
    )
    assert checklist in prompt
    assert checklist in foundation
    assert "not the runtime-readiness verdict" in normalized_foundation
    assert "does not roll back a completed" in normalized_foundation
    assert (
        "`SETUP-07` in state `done` completes local workspace materialization"
        in normalized_foundation
    )
    assert "At the first interactive setup surface in a turn" in normalized_prompt
    assert "Begin every snapshot with:" in prompt
    assert "Here's your ESS agent setup:" in prompt
    assert "when a marker changes" in normalized_prompt
    assert "when a blocked state requires maker action" in normalized_prompt
    assert "in the final handoff" in normalized_prompt
    assert "retains the same markers continues to its next render point" in (
        normalized_prompt
    )
    assert "After successful runtime, dependency, and converter checks" in (
        normalized_prompt
    )
    assert "one single-level bullet and one leading status emoji per stage" in (
        normalized_prompt
    )
    assert "native task list" not in normalized_prompt
    cwd_instruction = (
        "Run setup commands from the current ESS Maker Skills workspace folder"
    )
    assert cwd_instruction in normalized_prompt
    assert cwd_instruction in normalized_foundation
    assert "at these render points" in foundation
    assert "same ordinary Markdown shape" in foundation
    assert "native task list" not in foundation
    assert "Mark **Review the setup handoff** complete in the final snapshot" in foundation


def test_public_setup_does_not_configure_mcp() -> None:
    prompt = _SETUP_PROMPT.read_text(encoding="utf-8")

    assert "mcp_config.py" not in prompt
    assert "materialize-defaults" not in prompt


def test_global_and_command_gates_require_canonical_da_completion() -> None:
    instructions = _INSTRUCTIONS.read_text(encoding="utf-8")

    assert "`schema_version`" in instructions
    assert "equal to `4`" in instructions
    assert "`agents` entry matching `.local/config.json`" in instructions
    assert "`connect_ready` equal to `true`" in instructions
    assert '`status` equal to `"complete"`' not in instructions

    gated_prompts = (
        "backup-template-configs.prompt.md",
        "create.prompt.md",
        "delete.prompt.md",
        "evaluate.prompt.md",
        "push.prompt.md",
        "restore-template-configs.prompt.md",
        "review.prompt.md",
        "run.prompt.md",
        "scan.prompt.md",
        "test.prompt.md",
        "troubleshoot.prompt.md",
        "update.prompt.md",
    )
    for name in gated_prompts:
        path = _PROMPTS / name
        text = path.read_text(encoding="utf-8")
        assert ".local/setup/config.json" in text, path
        assert "schema_version: 4" in text, path
        assert "connect_ready: true" in text, path
        assert ".local/config.json" in text, path
        normalized = " ".join(text.split())
        assert 'or local config does not have `setup: "complete"`' not in normalized, (
            path
        )
        assert (
            '`.local/config.json` is missing or `setup` is not `"complete"`'
            not in normalized
        ), path

    connect_prompt = (_PROMPTS / "connect.prompt.md").read_text(encoding="utf-8")
    assert "schema_version: 4" in connect_prompt
    assert 'steps.SETUP-07.state: "done"' in connect_prompt
    assert "Do not require\n`connect_ready: true`" in connect_prompt
    assert "workspace evidence" in connect_prompt

    flightcheck_prompt = (_PROMPTS / "flightcheck.prompt.md").read_text(
        encoding="utf-8"
    )
    assert "FlightCheck entry contract" in flightcheck_prompt
    assert "Standalone FlightCheck" in flightcheck_prompt
    assert "Canonical setup ready" in flightcheck_prompt

    assert "`.local/config.json`'s" in instructions


def test_global_gate_routes_flightcheck_through_setup_evidence() -> None:
    instructions = _INSTRUCTIONS.read_text(encoding="utf-8")
    normalized = " ".join(instructions.split())
    prompt = (_PROMPTS / "flightcheck.prompt.md").read_text(encoding="utf-8")
    normalized_prompt = " ".join(prompt.split())
    skill = (
        _SOLUTION / "src" / "skills" / "flightcheck" / "SKILL.md"
    ).read_text(encoding="utf-8")
    normalized_skill = " ".join(skill.split())

    assert "typed `/flightcheck` or explicitly asked to validate setup" in normalized
    assert "FlightCheck entry contract" in instructions
    assert "`flightCheckOnly: true`" in normalized
    assert "Apply the first matching state" in normalized
    assert "**Standalone FlightCheck:**" in instructions
    assert "**Canonical setup ready:**" in instructions
    assert "**Setup readiness outstanding:**" in instructions
    assert "**Workspace preparation required:**" in instructions
    assert "exact maker-facing copy" in normalized
    assert "FlightCheck is available when setup prepares the local agent workspace" in (
        normalized
    )
    assert "Collect every non-empty `failure_causes` entry" in normalized
    assert "**Environment capacity**" in instructions
    assert "**Connections**" in instructions
    assert "**Agent content**" in instructions
    assert "keep the canonical setup IDs internal" in normalized
    assert "{READINESS_ISSUES}" in instructions
    assert "{READINESS_ITEM}" in instructions
    assert "{READINESS_DETAIL}" in instructions
    assert "Setup readiness requires attention:" in instructions
    assert "performs the next readiness run" in normalized

    assert "Follow the **FlightCheck entry contract**" in normalized_prompt
    assert "Standalone FlightCheck" in normalized_prompt
    assert "Canonical setup ready" in normalized_prompt
    assert "complete maker-facing response" in normalized_skill

    entry_contract = instructions.split("#### FlightCheck entry contract", 1)[1]
    entry_contract = entry_contract.split("### If canonical setup is ready", 1)[0]
    assert entry_contract.count("**Message:**") == 2
    assert entry_contract.count("**End message.**") == 2


def test_maker_profile_requires_only_canonical_completion() -> None:
    text = _MAKER_PROFILE.read_text(encoding="utf-8")

    assert "if (canonicalComplete) met.add('setup')" in text
    assert "json.schema_version === 4" in text
    assert "Object.values(json.agents || {}).some" in text
    assert "agentState.connect_ready === true" in text
    assert "agentState?.agent?.workspace_slug === config.activeAgent" in text
    assert "'.local/setup/config.json'" in text
    assert "workspaceComplete" not in text
    assert "json.setup === 'complete'" not in text
    assert "configPattern" not in text


def test_workday_da_setup_routes_only_supported_hr_agents() -> None:
    step1 = _CONNECT_STEP1.read_text(encoding="utf-8")
    normalized_step1 = " ".join(step1.split())
    workday = _WORKDAY.read_text(encoding="utf-8")

    assert "src/skills/setup/workday-da/SKILL.md" in step1
    assert "gptagent_copilotforemployeeselfservicehr" in step1
    assert "Workday integration with the ESS IT Agent isn't supported" in step1
    assert "or run `WD-PKG-001`" in normalized_step1
    assert "src/skills/foundation-setup/SKILL.md" not in step1
    assert _WORKDAY.is_file()
    assert "Hybrid Workday extension setup is not available" in workday
    assert "Do not run the retained Workday setup playbooks" in workday


def test_foundation_routes_supported_da_setup_paths() -> None:
    text = _FOUNDATION.read_text(encoding="utf-8")
    import_text = _DA_ALM_IMPORT.read_text(encoding="utf-8")
    normalized = " ".join(text.split())
    normalized_import = " ".join(import_text.split()).casefold()
    assert "A Prod source and its related Dev agent have different IDs by design" in normalized
    assert "Classify the supplied agent first" in normalized

    assert set(_PATH_RE.findall(text)) == {
        "src/skills/foundation-setup/da-alm-import.md",
        "src/skills/foundation-setup/da-environment-target.md",
        "src/skills/foundation-setup/da-existing-dev.md",
        "src/skills/foundation-setup/da-prod-to-dev.md",
        "src/skills/foundation-setup/da-mos-starter.md",
        "src/skills/foundation-setup/product-line-reconciliation.md",
    }
    assert "not a setup option to advertise or recommend" in normalized
    assert "src/reference/native-alm-import.md" in import_text
    assert "DA_ALM_IMPORT_JSON:" in import_text
    assert "setup_existing_da.py validate-agent" in import_text
    assert "DA_AGENT_VALIDATION_JSON:" in import_text
    assert "--setup-source alm-import" in import_text
    assert '--environment-id "{ENVIRONMENT_ID}"' in import_text
    assert '--ring "{RING}"' in import_text
    assert "--target-url" not in import_text
    assert "accept an environment url and infer its environment id" in (
        normalized_import
    )
    assert "resolve the service ring" in normalized_import
    assert "da-environment-target.md" in normalized_import
    assert "ask the maker only when" in normalized_import
    assert "`connectReady: true`" in import_text
    assert "including when `connectReady` is false" in import_text
    assert "`setupStatus`" not in import_text
    assert "`unprojectedDialogCount`" not in import_text
    assert "Never preselect or recommend **Continue replacement**" in import_text
    assert "Never remove or edit import records" in import_text
    reference = _NATIVE_ALM_REFERENCE.read_text(encoding="utf-8")
    assert "Import `kind: success` is not setup completion" in reference
    for historical_text in (
        "## open validation",
        "the current command",
        "transport fault-injection",
        "workstream",
        "experiment",
    ):
        assert historical_text not in reference.casefold()
    assert "scripts/setup_state.py" not in text
    assert "Dataverse foundation or onboarding playbooks" in text
    assert "connector authentication" in text
    assert _DA_EXISTING_DEV.is_file()
    assert _DA_ALM_IMPORT.is_file()
    assert _DA_PROD_TO_DEV.is_file()
    assert _NATIVE_ALM_REFERENCE.is_file()
    assert "setup_existing_da.py inspect-agent" in text
    assert "DA_AGENT_ROUTE_JSON:" in text
    assert "Do not infer the realm" in text
    assert "--target-url" not in text
    assert '--environment-id "{ENVIRONMENT_ID}"' in text
    assert '--agent-id "{AGENT_ID}"' in text
    assert '--ring "{RING}"' in text
    assert "resolve the service ring" in normalized.casefold()
    assert text.index("setup_existing_da.py inspect-agent") < text.index(
        "da-existing-dev.md"
    )
    assert text.index("setup_existing_da.py inspect-agent") < text.index(
        "da-prod-to-dev.md"
    )
    assert _DA_MOS_STARTER.is_file()
    assert _MOS_STARTER_REFERENCE.is_file()
    assert "explicit fresh-install intent" in normalized


def test_native_setup_skills_pass_resolved_target_fields() -> None:
    foundation = _FOUNDATION.read_text(encoding="utf-8")
    existing = _DA_EXISTING_DEV.read_text(encoding="utf-8")
    imported = _DA_ALM_IMPORT.read_text(encoding="utf-8")
    prod_to_dev = _DA_PROD_TO_DEV.read_text(encoding="utf-8")
    mos = _DA_MOS_STARTER.read_text(encoding="utf-8")
    environment_target = _DA_ENVIRONMENT_TARGET.read_text(encoding="utf-8")

    for text in (foundation, existing, imported, prod_to_dev, mos):
        assert "--target-url" not in text
        assert "--source-url" not in text

    for text in (foundation, existing, imported, mos):
        assert '--environment-id "{ENVIRONMENT_ID}"' in text
        assert '--ring "{RING}"' in text

    assert '--agent-id "{AGENT_ID}"' in foundation
    assert '--agent-id "{AGENT_ID}"' in existing
    assert '--agent-id "{INTERNAL_AGENT_ID}"' in imported
    assert '--environment-id "{SOURCE_ENVIRONMENT_ID}"' in prod_to_dev
    assert '--agent-id "{SOURCE_AGENT_ID}"' in prod_to_dev
    assert '--environment-id "{TARGET_ENVIRONMENT_ID}"' in prod_to_dev
    assert '--ring "{TARGET_RING}"' in prod_to_dev

    for text in (foundation, existing, imported, prod_to_dev, mos):
        normalized_text = " ".join(text.split()).casefold()
        assert "resolve the service ring" in normalized_text
        assert "da-environment-target.md" in normalized_text
    assert "Which Power Platform service ring should setup use?" in (
        environment_target
    )
    assert "recognized Copilot Studio hostname" in environment_target
    assert "copilotstudio.preview.microsoft.com" in environment_target
    assert "completes ring selection" in environment_target
    assert "render this exact decision surface" in environment_target
    assert "Present all three labels unchanged with no default selection" in (
        environment_target
    )


def test_empty_setup_offers_recorded_agent_without_requesting_url() -> None:
    foundation = _FOUNDATION.read_text(encoding="utf-8")
    existing = _DA_EXISTING_DEV.read_text(encoding="utf-8")
    normalized = " ".join(foundation.split())

    local_target = "When the current request supplies no agent"
    generic_question = "When the request does not identify an agent or environment"
    assert foundation.index(local_target) < foundation.index(generic_question)
    assert "read canonical setup state and `.local/config.json`" in normalized
    assert "**{agent display name}** is the active agent in this workspace" in (
        foundation
    )
    for choice in (
        "Continue with this agent",
        "Switch to another configured agent",
        "Install another product in this environment",
        "Reset and use this workspace",
        "Create and open a new workspace",
        "Cancel setup",
    ):
        assert f"**{choice}**" in foundation
    assert "Do not preselect a choice" in foundation
    assert '--environment-id "{RECORDED_ENVIRONMENT_ID}"' in foundation
    assert '--agent-id "{RECORDED_AGENT_ID}"' in foundation
    assert '--ring "{RECORDED_RING}"' in foundation
    assert "Do not ask for the agent or environment URL" in normalized
    assert "**Resume setup for this agent**" in foundation
    assert "select-agent" in foundation
    assert "changes only local active-agent selection" in normalized
    assert "no usable local target exists" in normalized
    assert "Never request a URL merely to revalidate" in " ".join(existing.split())


def test_prod_to_dev_reference_composes_durable_boundaries() -> None:
    foundation = _FOUNDATION.read_text(encoding="utf-8")
    normalized_foundation = " ".join(foundation.split())
    text = _DA_PROD_TO_DEV.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "server-backed inspection has identified its route realm" in (
        normalized_foundation
    )
    assert "When `realm` is `prod`" in normalized_foundation
    assert foundation.index("da-prod-to-dev.md") < foundation.index(
        "emit_capability.py setup"
    )
    assert "does not emit setup telemetry" in normalized_foundation
    assert "src/reference/native-alm-import.md" in text
    assert "da-existing-dev.md" in text
    assert "setup_alm_export.py inspect" in text
    assert "DA_ALM_EXPORT_INSPECTION_JSON:" in text
    assert "setup_existing_da.py validate-agent" in text
    assert "Do not offer to create a duplicate Dev agent" in normalized
    assert "same Power Platform environment as the supplied Prod agent" in normalized
    assert "explicitly requests another environment" in normalized
    assert "setup_alm_export.py export" in text
    assert "DA_ALM_EXPORT_JSON:" in text
    assert "setup_alm_import.py" in text
    assert "matching import receipt" in normalized
    assert "--resume-create-after-cleanup" in text
    assert "--expected-alm-family-id" in text
    assert "exact target and family" in normalized
    assert "importStatus: resumed" in normalized
    assert "without another export or import request" in normalized
    assert "setup_alm_export.py cleanup" in text
    assert "Immediately after the import command returns" in normalized
    assert "friendly display name" in normalized
    assert "without showing internal IDs or URLs" in normalized
    create_flow = text.split("## Export and create Dev", 1)[1]
    assert create_flow.index("Immediately before import, ask") < create_flow.index(
        "python scripts/setup_alm_import.py"
    )
    assert create_flow.index("python scripts/setup_alm_import.py") < create_flow.index(
        "python scripts/setup_alm_export.py cleanup"
    )
    conflict_flow = create_flow.split("When import returns `kind: conflict`", 1)[1]
    normalized_conflict = " ".join(conflict_flow.split())
    assert "source inspection command above" in conflict_flow
    assert "setup_existing_da.py validate-agent" in conflict_flow
    assert "same `almFamilyId`" in conflict_flow
    assert "offer to attach it" in conflict_flow
    assert "Do not recover a collision or offer replacement" in normalized_conflict
    assert "setup_existing_da.py attach" in text
    assert "--setup-source prod-to-dev" in text
    assert '--expected-schema-name "{RETURNED_SCHEMA_NAME}"' in text
    assert "without requiring published Dev configuration" in normalized
    assert "including when `connectReady` is false" in normalized
    assert "--source-url" not in text
    assert "--target-url" not in text
    assert '--environment-id "{SOURCE_ENVIRONMENT_ID}"' in text
    assert '--agent-id "{SOURCE_AGENT_ID}"' in text
    assert '--environment-id "{TARGET_ENVIRONMENT_ID}"' in text
    assert '--ring "{TARGET_RING}"' in text
    assert "Do not generate HTTP code or an end-to-end setup script" in normalized
    assert "setup_prod_to_dev.py" not in text
    assert "`setupStatus`" not in text
    assert "Do not infer an interrupted step from conversation history" in normalized
    assert "Prod agent verified. Checking for its related editable Dev agent" in normalized
    assert "No related editable Dev agent was found" in normalized
    assert "without changing Prod" in normalized
    assert "Create editable Dev agent" in text
    assert "Do not preselect **Create editable Dev agent**" in text
    assert "Use related Dev agent" in text
    assert "render the factual workspace and runtime-readiness report there" in normalized
    assert "Existing Prod agent; related Dev reused" in normalized
    assert "Existing Prod agent; new Dev created" in normalized
    for historical_text in (
        "workstream",
        "experiment",
        "script-first",
        "reference-first",
        "open validation",
    ):
        assert historical_text not in text.casefold()
    assert len(text.splitlines()) < 180


def test_mos_starter_reference_composes_durable_boundaries() -> None:
    foundation = _FOUNDATION.read_text(encoding="utf-8")
    normalized_foundation = " ".join(foundation.split())
    text = _DA_MOS_STARTER.read_text(encoding="utf-8")
    normalized = " ".join(text.split())
    environment_target = _DA_ENVIRONMENT_TARGET.read_text(encoding="utf-8")
    normalized_environment_target = " ".join(environment_target.split())
    reference = _MOS_STARTER_REFERENCE.read_text(encoding="utf-8")
    existing_dev = _DA_EXISTING_DEV.read_text(encoding="utf-8")

    assert "src/reference/mos-starter-package.md" in text
    assert "src/skills/foundation-setup/da-environment-target.md" in text
    assert "setup_existing_da.py list-environments" in environment_target
    assert "DA_ENVIRONMENT_LIST_JSON:" in environment_target
    assert "compact environment-selection result" in environment_target
    assert "Retain its `evidencePath`" in environment_target
    assert "read that file only when richer diagnostics" in environment_target
    assert "Environment discovery is separate from agent discovery" in (
        normalized_environment_target
    )
    assert "Which Power Platform service ring should setup use?" in (
        environment_target
    )
    for ring_choice in ("Production / Preview", "Pre-production", "Test"):
        assert f"**{ring_choice}**" in environment_target
    assert "Map **Production / Preview** to `prod`" in environment_target
    assert "Present all three labels unchanged with no default selection" in (
        normalized_environment_target
    )
    assert "A ring is resolved only by an explicit URL segment" in (
        normalized_environment_target
    )
    assert "Before showing the shared authorization message" in (
        normalized_environment_target
    )
    assert "do not run `list-agents`" in normalized_environment_target
    assert "Present every environment returned by the Power Platform API" in (
        normalized_environment_target
    )
    assert "without filtering by URL, Dataverse metadata, or environment type" in (
        normalized_environment_target
    )
    assert "No Power Platform environments were listed for this account" in (
        environment_target
    )
    for empty_environment_choice in (
        "Use another account",
        "Use an environment URL",
        "Create a Power Platform environment",
        "Cancel setup",
    ):
        assert f"**{empty_environment_choice}**" in environment_target
    assert "does not require a Dataverse database" in environment_target
    assert "Do not route into a Dataverse provisioning skill" in (
        normalized_environment_target
    )
    assert "authorizationFailure" in environment_target
    assert "DA_ENVIRONMENT_LIST_ERROR_JSON:" in environment_target
    assert "DA_ENVIRONMENT_LIST_ERROR_RESPONSE_JSON:" in environment_target
    assert "Do not convert an authorization failure" in (
        normalized_environment_target
    )
    assert "## Retry setup with another target" in environment_target
    assert "How would you like to continue setup?" in environment_target
    for retry_choice in (
        "Try with a different user",
        "Try a different environment",
        "Cancel setup",
    ):
        assert f"**{retry_choice}**" in environment_target
    assert "present these labels unchanged with the selection initially unset" in (
        normalized_environment_target
    )
    assert "rerun environment discovery for that account" in (
        normalized_environment_target
    )
    assert "retain the current account and ring" in normalized_environment_target
    assert "also offer **Use an agent URL**" in environment_target
    assert "setup_mos_starter.py list" in text
    assert "DA_MOS_STARTER_PACKAGES_JSON:" in text
    assert "setup_mos_starter.py inspect-connection" not in text
    assert "DA_MOS_CONNECTION_PREFLIGHT" not in text
    assert "setup_mos_starter.py create" in text
    assert "DA_MOS_STARTER_CREATE_ANNOTATIONS_JSON:" in text
    assert "DA_MOS_STARTER_CREATE_JSON:" in text
    assert "setup_mos_starter.py enable-alm" in text
    assert "DA_MOS_STARTER_ALM_ANNOTATIONS_JSON:" in text
    assert "DA_MOS_STARTER_ALM_JSON:" in text
    assert "DA_MOS_STARTER_ALM_VERIFY_ANNOTATIONS_JSON:" in text
    assert "DA_MOS_STARTER_ALM_VERIFY_JSON:" in text
    assert "setup_existing_da.py attach" in text
    assert "--setup-source mos-starter" in text
    assert '--expected-schema-name "{RETURNED_SCHEMA_NAME}"' in text
    assert "--target-url" not in text
    assert '--environment-id "{ENVIRONMENT_ID}"' in text
    assert '--ring "{RING}"' in text
    assert "--setup-prerequisite-status" not in text
    assert "--setup-prerequisite-evidence" not in text
    assert _DA_PRODUCT_REGISTRY.is_file()
    assert "src/reference/da-product-setup-registry.json" in text
    assert "evaluated after creation and attachment" in normalized
    assert "do not inspect or require a physical connection before" in normalized
    assert "outcome: created" in text
    assert "Never show the internal `packageId` to the maker" in normalized
    assert "`connectReady: true`" in existing_dev
    assert "`setupStatus`" not in text
    assert "Do not ask the maker to classify the product before loading the catalog" in normalized
    assert "infer a concise user-friendly product name" in normalized
    assert (
        "Render `Employee Self-Service` as `Employee Self-Service (Hub)`"
        in normalized
    )
    assert (
        "render `Employee Self-Service IT` or `Employee Self-Service (IT)` as "
        "`Employee Self-Service (IT)`"
        in normalized
    )
    assert (
        "render `Employee Self-Service HR` or `Employee Self-Service (HR)` as "
        "`Employee Self-Service (HR)`"
        in normalized
    )
    assert "use the exact service-provided product name unchanged" in normalized
    assert "must not change the underlying `packageId`" in normalized
    assert (
        "render the following friendly product name and supporting description "
        "exactly as written"
        in normalized
    )
    assert (
        "Do not paraphrase, shorten, or combine this copy with the "
        "service-provided description."
        in normalized
    )
    assert (
        "Use this product if you want to organize HR, IT, or other agents as "
        "connected agents behind one unified employee experience."
        in normalized
    )
    assert (
        "Create an HR agent that helps employees get HR answers and complete "
        "requests."
        in normalized
    )
    assert (
        "Create an IT agent that helps employees resolve technical issues and "
        "access support."
        in normalized
    )
    assert (
        "For every other product, use its exact service-provided name unchanged "
        "and use `shortDescription`, then `description`"
        in normalized
    )
    assert "host's interactive single-selection control" in normalized
    assert "Do not ask the maker to type a product name" in normalized
    assert "**{friendly product name} {version}**" in text
    assert "Create a new ESS agent" in normalized
    assert "**{selected product label}**" in text
    assert "Choose a different product" in text
    assert _PREPARE_FRESH_WORKSPACE.is_file()
    assert "Create and open a new workspace" in foundation
    assert "Create a new workspace without opening it" not in foundation
    assert "Use suggested location -- {suggested absolute sibling-folder path}" in foundation
    assert "Choose another location" in foundation
    assert "Do not ask the maker to type a path unless" in normalized_foundation
    assert "scripts/prepare_fresh_workspace.py" in foundation
    assert "--open-vscode" in foundation
    assert "DA_PREPARED_WORKSPACE_JSON:" in foundation
    assert (
        "Which Microsoft account should setup use to access the target "
        "Power Platform environment?"
    ) in foundation
    assert (
        "Send the complete **Message** block as its own chat message"
    ) in normalized_foundation
    assert (
        "Finish that message before opening the next question or interactive "
        "control; the next control begins with its own prompt, explanation, and choices"
    ) in normalized_foundation
    assert "Ask exactly one account question" in foundation
    assert (
        "**Skip — Use the Microsoft account picker** first, followed by every "
        "cached sign-in name"
    ) in foundation
    assert "separate from GitHub/Copilot sign-in" in foundation
    assert "Do not add a separate **Use another account** choice" in foundation
    assert "**Continue with this account**" not in foundation
    assert (
        "When the maker selects **Skip — Use the Microsoft account picker**, "
        "omit `--account`"
    ) in normalized_foundation
    assert (
        "append `--select-account` only to the first command that can authenticate"
    ) in normalized_foundation
    assert "Parse `DA_AGENTBUILDER_AUTH_JSON:`" in foundation
    assert (
        "later commands reuse its cached token and sign-in name"
        in normalized_foundation
    )
    assert "setup_existing_da.py cached-accounts` again" in foundation
    assert "Do you have a test tenant user?" not in foundation
    assert "does not prove that the maker holds a particular administrator role" in (
        normalized_foundation
    )
    assert "setup_existing_da.py cached-accounts" in foundation
    assert "DA_AGENTBUILDER_ACCOUNTS_JSON:" in foundation
    assert '--account "{SETUP_ACCOUNT}"' in foundation
    assert "reconcile_setup_agent.py" in foundation
    assert "Never infer a corp account" in normalized_foundation
    assert "Present account confirmation once" in normalized_foundation
    assert "Continue in an occupied workspace" in normalized
    assert "recorded environment is the selected target" in normalized
    assert "create a new agent, install another product, or start with a fresh agent" in (
        normalized_foundation
    )
    assert "Resolve that intent before active-agent resume handling" in (
        normalized_foundation
    )
    assert "retain every configured agent and continue directly" in (
        normalized_foundation
    )
    assert "existing-agent readiness remains unchanged" in normalized_foundation
    assert normalized_foundation.index(
        "Resolve that intent before active-agent resume handling"
    ) < normalized_foundation.index(
        "When the current request supplies no agent, environment, package, or fresh-agent intent"
    )
    assert "new absolute sibling-folder path" in normalized_foundation
    assert "Do not preselect **Create agent**" in text
    assert "After the maker explicitly selects **Create agent**" in normalized
    assert "exactly one create attempt" not in normalized
    assert "The command ends after this one attempt" not in normalized
    assert "Do not invoke create concurrently or automatically" in normalized
    assert "diagnostic evidence only" in normalized
    assert "do not explain those internal version concepts to the maker" in normalized
    assert "The agent was created. Preparing its local authoring workspace" in normalized
    assert "{PRODUCT_COUNT} entitled products are available" in text
    assert "Loading entitled products for **{environment name}**..." in text
    assert "no entitled products are currently available in the selected environment" in (
        normalized
    )
    assert normalized.count("**Retry setup with another target**") == 2
    assert "entitled products could not be loaded and nothing was changed" in (
        normalized
    )
    assert text.index("Loading entitled products for **{environment name}**...") < (
        text.index("{PRODUCT_COUNT} entitled products are available")
    )
    assert "use this fixed opening as the first product-installation surface" in (
        normalized
    )
    assert "begin the create operation immediately" in normalized
    assert "An enabled or already-enabled result proceeds directly to attachment" in (
        normalized
    )
    assert "single presentation unit defined in `da-existing-dev.md`" in normalized
    assert "Complete every check whose prerequisites remain available" in normalized
    assert "state the observed blocker and supported recovery" in normalized
    assert "application lifecycle management" not in normalized
    assert "**Prepare for local editing**" not in text
    assert "**Not now**" not in text
    assert "outcome: verification-failed" in normalized
    assert "Setup has stopped without attaching a workspace." in text
    assert "never show internal step IDs or raw technical output" in normalized
    assert "workspace is not ready to connect" in existing_dev
    assert "New entitled MOS product" in text
    assert "content was synced to your local workspace" in existing_dev
    assert "Your local workspace is ready for authoring" in existing_dev
    assert "[{USER_FRIENDLY_PRODUCT_NAME}]({ACTUAL_AGENT_URL})" in existing_dev
    assert "### Runtime readiness" in existing_dev
    assert "factual workspace and runtime-readiness report from `da-existing-dev.md`" in normalized
    assert "Do not infer persona, product, target, or progress" in normalized
    assert "Never invoke" in normalized and "/connect" in normalized
    assert "Do not publish, remove, or replace components" in normalized
    assert "Publishing is outside foundation setup and is not remediation" in normalized
    assert "including when `connectReady` is false" in normalized
    assert "setup_setup_mos_starter.py" not in text
    assert "setup_mos_starter.py resolve" not in text
    assert "setup_mos_starter.py status" not in text
    assert "DA_EXISTING_DEV_DIAGNOSTIC_JSON:" not in text
    assert len(text.splitlines()) < 200
    assert "--client-request-id" in text
    assert "one picker option per exact ID" in normalized
    assert "Do not describe products as remaining, uninstalled, or eligible" in normalized
    assert "Choose an existing agent in this environment" in text
    assert "Choose a different catalog product" in text
    assert "present the valid rows from the latest successful catalog result" in normalized
    assert "Continue through **Confirm the exact product and target**" in text
    assert "uses a new client request UUID" in normalized
    collision_choices = text[text.index("When the annotations report `outcome: collision`") :]
    collision_choices = collision_choices[: collision_choices.index("## Enable ALM")]
    assert "**Go back**" not in collision_choices
    assert "does not identify the corresponding agent" in reference

    assert "createFromStarterPackage" in reference
    assert "Live-proven" in reference
    assert "catalogPackageVersion" in reference
    assert "templateVersion" in reference
    assert "alm.isAlmEnabled" in reference
    assert "never publishes or removes components" in reference
    assert "Fuse disposition matrix" in reference
    assert "Request-scoped create evidence" in reference
    assert "PERSONA" not in reference
    assert "resolve_starter_package" not in reference
    assert "setup_mos_starter.py resolve" not in reference
    assert "setup_mos_starter.py status" not in reference


def test_foundation_offers_local_workspace_reset() -> None:
    text = _FOUNDATION.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert _RESET_LOCAL_WORKSPACE.is_file()
    assert "## Shared workspace choices" in text
    assert "Reset and use this workspace" in text
    assert "Reset workspace" in text
    assert "Go back" in text
    assert "scripts/reset_local_workspace.py --confirm-reset" in text
    assert "DA_RESET_WORKSPACE_JSON:" in text
    assert "local setup was archived to `{backupRoot}`" in normalized
    assert "report its `ERROR:` and `NOTE:` output" in normalized
    assert "will not change or delete any agent in Copilot Studio" in normalized
    assert "archive its current local agent files" in normalized


def test_foundation_exposes_multi_agent_entry_and_completion_choices() -> None:
    text = _FOUNDATION.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    for choice in (
        "Continue with this agent",
        "Switch to another configured agent",
        "Install another product in this environment",
        "Reset and use this workspace",
        "Create and open a new workspace",
        "Cancel setup",
        "Continue customizing this agent",
        "Finish for now",
    ):
        assert f"**{choice}**" in text
    assert "Create a new workspace without opening it" not in text
    assert "setup_existing_da.py select-agent" in text
    assert "one Power Platform environment" in normalized
    assert "multiple ESS Dev agents" in normalized
    assert "one active agent" in normalized


def test_foundation_resolves_python_and_announces_authorization_wait() -> None:
    text = _FOUNDATION.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "From the kit root" in normalized
    assert "`py -3`, `python3`, then `python` on Windows" in normalized
    assert "`python3`, then `python` on macOS or Linux" in normalized
    assert "check each candidate with" in normalized
    assert "one terminal command at a time" in normalized
    assert '{PYTHON} -c "import sys; print(sys.executable)"' in normalized
    assert "repository-supported repair commands" in normalized
    assert "offer to perform it" in normalized
    assert "**Waiting for authorization**" in text
    assert "Complete the Microsoft sign-in in your browser" in normalized
    assert (
        "Do not describe an authorization wait as service processing"
        in normalized
    )


def test_foundation_uses_maker_facing_progress_without_duplicate_state() -> None:
    text = _FOUNDATION.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    for stage in (
        "Choose the starting point and target environment",
        "Verify access and agent identity",
        "Establish an editable Dev agent",
        "Materialize the local workspace",
        "Review the setup handoff",
    ):
        assert stage in text
    assert "The checklist is a view, not another state model" in normalized
    assert "first interactive setup surface in a turn" in normalized
    assert "a change to any of its five markers" in normalized
    assert "a blocked state that requires maker action" in normalized
    assert "A sequence of setup operations that retains the same markers" in normalized
    assert "The final handoff is the sole completion summary" in normalized
    assert "**Finish for now** ends immediately" in normalized
    assert "first decision surface rather than rendering another completion summary" in (
        normalized
    )
    assert "After successful runtime and dependency validation" in normalized
    assert "Maker-visible setup text consists of the defined **Message** blocks" in (
        normalized
    )
    assert "Operational sequencing and response-policy prose are instruction-only" in (
        normalized
    )
    assert "Successful internal operations continue directly" in normalized
    assert "Never infer progress from conversation history" in normalized
    assert "Do not mark a stage complete from a skipped internal setup record" in (
        normalized
    )
    assert "Do you already have an ESS agent in Copilot Studio?" in text
    assert "Yes, I have an agent" in text
    assert "No, I need a fresh agent" in text


def test_environment_only_request_resolves_agent_intent_before_routing() -> None:
    text = _FOUNDATION.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert (
        "When the request identifies an environment and explicitly asks to "
        "connect to an existing agent"
    ) in normalized
    assert (
        "When the request identifies an environment but not an agent or "
        "create-versus-connect intent"
    ) in normalized
    assert (
        "What would you like to set up in "
        "`{environment name or the selected Power Platform environment}`?"
    ) in normalized
    for choice in (
        "Create a fresh agent in this environment",
        "Connect to an existing agent in this environment",
        "Cancel setup",
    ):
        assert choice in text
    assert "Require an explicit selection; all choices begin unselected" in normalized
    assert "then ask exactly" in normalized
    assert (
        "This question confirms the selected target; the access-verification "
        "stage remains current until a service operation succeeds"
    ) in normalized
    assert "retain the resolved environment ID and service ring" in normalized
    assert (
        "Send the current progress snapshot using the shared **Message** contract"
    ) in normalized
    assert (
        "continue directly through "
        "`src/skills/foundation-setup/da-mos-starter.md` with the retained "
        "environment and ring"
    ) in normalized
    assert (
        "follow its environment-candidate selection path with the retained "
        "environment and ring"
    ) in normalized
    assert (
        "When the request identifies an environment but not an agent or "
        "fresh-agent intent"
    ) not in normalized
    assert normalized.index(
        "What would you like to set up in"
    ) < normalized.index(
        "For **Connect to an existing agent in this environment**"
    )


def test_foundation_has_one_authorization_wait_contract() -> None:
    text = _FOUNDATION.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "Microsoft sign-in will open" in text
    assert text.count("Microsoft sign-in will open") == 1
    assert "The account question is the confirmation" in text
    assert "Setup will use **{SETUP_ACCOUNT}**" not in text
    assert "**Waiting for authorization**" in text
    assert text.count("**Waiting for authorization**") == 1
    assert "ask the maker to provide a token" in normalized.casefold()
    assert "Do not describe an authorization wait as service processing" in normalized


def test_alm_import_uses_shared_progress_and_completion_handoff() -> None:
    foundation = _FOUNDATION.read_text(encoding="utf-8")
    text = _DA_ALM_IMPORT.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "successful package import with direct Dev validation" in foundation
    assert "Choose the starting point and target environment" in normalized
    assert "Verify access and agent identity" in normalized
    assert "Establish an editable Dev agent" in normalized
    assert "Agent package imported and verified as an editable Dev agent" in normalized
    assert "factual workspace and runtime-readiness report from `da-existing-dev.md`" in normalized
    assert "Supplied native agent package" in text
    assert "another readiness" not in text.casefold()


def test_alm_import_collision_and_retry_require_separate_choices() -> None:
    text = _DA_ALM_IMPORT.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    for choice in (
        "Choose an existing agent in this environment",
        "Replace an existing agent with this package",
        "Cancel setup",
        "Continue replacement",
        "Retry import",
        "Stop without retrying",
    ):
        assert choice in text
    assert "Do not preselect a choice or recommend replacement" in normalized
    assert "setup_existing_da.py list-agents" in text
    assert "Never preselect or recommend **Continue replacement**" in text
    assert "could not be proven" in normalized
    assert "avoid creating or replacing the agent twice" in normalized
    assert "only after the maker selects **Retry import**" in normalized


def test_existing_da_dev_path_never_routes_through_dataverse() -> None:
    text = _DA_EXISTING_DEV.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    for command in (
        "setup_existing_da.py list-agents",
        "setup_existing_da.py inspect-agent",
        "setup_existing_da.py validate-agent",
        "setup_existing_da.py attach",
    ):
        assert command in text
    for removed_command in (
        "setup_existing_da.py status",
        "setup_existing_da.py list-environments",
        "setup_existing_da.py list-organizations",
    ):
        assert removed_command not in text
    assert "Do not run the Dataverse setup path" in text
    assert "scripts/setup_state.py" not in text
    assert "scripts/discover.py" not in text
    assert "`connectReady: true`" in text
    assert "visible Dev-realm candidates" in text
    assert "Validate only the selected candidate" in text
    assert "No visible editable Dev agents were listed in this environment" in text
    assert "A directly addressable agent may still be available" in text
    assert "including its **Use an agent URL** choice" in text
    assert "before authentication or remote agent validation" in text
    assert "Do not run `validate-agent` immediately before `attach`" in text
    assert "Your local workspace is ready for authoring." in text
    assert "The remote agent is available at" in text
    assert "[{USER_FRIENDLY_PRODUCT_NAME}]({ACTUAL_AGENT_URL})" in text
    assert "| Item" not in text
    assert "| Starting point" not in text
    assert (
        "{COPILOT_STUDIO_ORIGIN}/environments/{ENVIRONMENT_ID}/bots/"
        "{AGENT_ID}/overview"
    ) in text
    assert "Never link to the environment's agent-list page" in text
    assert "use the authoritative backend display name unchanged" in normalized
    assert "### Runtime readiness" in text
    readiness_table = "\n".join(
        (
            "| Check                | Status                          | Details                                  |",
            "| -------------------- | ------------------------------- | ---------------------------------------- |",
            "| Agent access         | {agent access status}           | {agent access evidence summary}          |",
            "| Environment capacity | {environment capacity status}   | {environment capacity evidence summary}  |",
            "| Connections          | {connections status}            | {connections evidence summary}           |",
            "| Agent content        | {agent content status}          | {agent content evidence summary}         |",
            "| **Overall**          | **{overall readiness status}**  | **{maker-facing readiness summary}**     |",
        )
    )
    assert readiness_table in text
    assert "Checkpoint and refresh" in text
    assert "Keep local files unchanged" in text
    assert "preserve the managed local files and canonical setup state" in normalized
    assert (
        "Your local files were left unchanged. Setup stopped without refreshing them."
        in text
    )
    assert "ends the current setup attempt at the refresh decision" in normalized
    assert "resume after a later unchanged attachment or successful refresh" in (
        normalized
    )
    assert "does not require published Dev configuration" in normalized
    assert "publishing is outside foundation setup" in normalized


def test_existing_dev_completion_remains_evidence_driven() -> None:
    text = _DA_EXISTING_DEV.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "`connectionStatus: workspace-ready`" in text
    assert "`connectReady: true`" in text
    assert "Canonical setup state is authoritative for each agent's setup progress and readiness" in normalized
    assert "`state`, `connectReady`, `activeStep`, and `failureCauses` are the setup-readiness verdict" in normalized
    assert "`DA-CONN-*` remains broad diagnostic evidence" in text
    assert "src/reference/da-product-setup-registry.json" in text
    assert "do not use its aggregate summary row" in normalized
    assert "current registry maps the IT product to `shared_alchemy`" in normalized
    assert (
        "Do not project `shared_service-now` or another undeclared reference"
    ) in normalized
    assert "keep canonical `connectReady` false" in normalized
    assert "keep `SETUP-05` skipped" in normalized
    assert (
        "no foundation connection requirement was applied because the "
        "product identity is not registered"
    ) in normalized
    assert (
        "do not claim that the registry declares no requirement for that "
        "product"
    ) in normalized
    assert (
        "run the three setup-readiness FlightChecks and the broad connection "
        "diagnostic"
    ) in normalized
    assert "present all four together" in normalized
    assert "attempt every available check before producing the final runtime-readiness table" in normalized
    assert "Render both even when `connectReady` is false" in normalized
    for readiness_status in (
        "**✅ Ready**",
        "**⚠️ Ready with limitation**",
        "**➖ Not required**",
        "**⛔ Action required**",
        "**⛔ Manual confirmation required**",
        "**✅ Ready — manually confirmed**",
        "**⚠️ Check unavailable**",
        "**⬜ Not checked**",
    ):
        assert readiness_status in text
    assert "### Capacity follow-up" in text
    assert (
        "We weren’t able to automatically verify capacity for this "
        "environment."
    ) in text
    assert "Your agent and local authoring workspace are already available." in text
    assert "#### Copilot Studio message capacity" in text
    assert "In the left navigation, select **Licensing**." in text
    assert "Under **Products**, select **Copilot Studio**." in text
    assert "Select **Manage Copilot Credits**." in text
    assert (
        "Confirm that the environment has more than zero allocated Copilot "
        "Credits."
    ) in normalized
    assert (
        "After checking Power Platform Admin Center, is Copilot Studio "
        "message capacity allocated to this environment?"
    ) in text
    assert "Complete this check to finish foundation readiness" not in text
    assert "https://admin.powerplatform.microsoft.com" in text
    assert "https://admin.preprod.powerplatform.microsoft.com" in text
    assert "https://admin.test.powerplatform.microsoft.com" in text
    assert (
        "Do not send a maker from a non-production setup ring to the "
        "production admin center."
    ) in normalized
    assert "using `ring_from_environment_host()`" in normalized
    assert "do not assume production" in normalized
    assert '--ring "{CONFIRMED_RING}"' in text
    assert "--manual-attested" in text
    assert "never overrides a known zero allocation" in normalized
    assert "When it is false after materialization" in normalized
    assert (
        "local authoring is ready while the setup-owned prerequisites remain"
        in normalized
    )
    assert "### Connection follow-up" in text
    assert "#### Microsoft 365 Self-Help" in text
    assert "Select **New connection**" in text
    assert "ask me to check it again" in text
    assert "Complete this connection to finish foundation readiness" in normalized
    assert "https://make.powerapps.com" in text
    assert "https://make.preprod.powerapps.com" in text
    assert "https://make.test.powerapps.com" in text
    assert "Do not send a maker from a non-production setup ring" in normalized
    assert "Do not add another completion choice" in normalized
    assert "a factual handoff, not another readiness gate" in normalized
    assert "changing canonical state conversationally" in normalized
    assert "Do not infer the realm from the URL" in normalized
    assert "from main" not in text
    assert "workstream" not in text.casefold()
    assert "later workstreams" not in text.casefold()
    assert "when the parent setup router already inspected the supplied or recorded agent" in (
        normalized
    )
    assert "canonical setup state, or conversation history" in normalized


def test_ui_guidance_keeps_ux_meta_intentions_out_of_maker_copy() -> None:
    text = _UI_FORMATTING.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "No historicity means maker-facing text describes only" in normalized
    assert "a current observed fact" in normalized
    assert "a decision the maker must make" in normalized
    assert "an action the maker must take" in normalized
    assert "a supported outcome" in normalized
    assert "Authoring rationale and UX meta-intentions remain instruction-only" in (
        normalized
    )
    assert "successful internal work continues to the next defined maker interaction" in (
        normalized
    )
    assert "a blocked operation states the observed blocker and one supported recovery" in (
        normalized
    )
    assert '"chatter," "noise," "narration," "render point," "surface,"' in text
    assert "Authoring rationale or UX-policy language presented as setup progress" in (
        normalized
    )
    assert "Send each progress snapshot as its own complete chat message" in normalized
    assert (
        "Finish that message before opening the next question or interactive control"
        in normalized
    )
    assert (
        "The next control begins with its own decision prompt, explanation, and choices"
        in normalized
    )


def test_foundation_router_paths_resolve() -> None:
    referenced = set(_PATH_RE.findall(_FOUNDATION.read_text(encoding="utf-8")))
    missing = [path for path in sorted(referenced) if not (_SOLUTION / path).is_file()]

    assert not missing


def test_non_da_ga_setup_implementation_is_absent() -> None:
    retired_paths = (
        "scripts/setup_state.py",
        "scripts/install_ess_agent.py",
        "scripts/ess_connection_binding.py",
        "scripts/preferred_solution.py",
        "src/reference/ess-agent-installation/config.json",
        "src/reference/solution-catalog.md",
        "src/skills/onboarding/SKILL.md",
        "src/skills/foundation-setup/install-starters.md",
    )

    for path in retired_paths:
        assert not (_SOLUTION / path).exists(), path


def test_da_commands_degrade_by_operation() -> None:
    expected_text = {
        "push.prompt.md": "DA-GA agent is not yet available",
        "delete.prompt.md": "DA-GA agent is not yet available",
        "troubleshoot.prompt.md": (
            "requires the corresponding product extension guidance"
        ),
    }

    for name, text in expected_text.items():
        prompt = (_PROMPTS / name).read_text(encoding="utf-8")
        assert text in prompt, name
        assert "transport" not in prompt.casefold(), name

    connect_prompt = (_PROMPTS / "connect.prompt.md").read_text(encoding="utf-8")
    assert "src/skills/connect/SKILL.md" in connect_prompt
    assert "Extension setup is not yet available" not in connect_prompt


def test_hybrid_workday_config_commands_remain_available() -> None:
    routes = {
        "backup-template-configs.prompt.md": (
            "src/skills/backup-template-configs/SKILL.md",
            "scripts/backup_template_configs.py",
        ),
        "restore-template-configs.prompt.md": (
            "src/skills/restore-template-configs/SKILL.md",
            "scripts/restore_template_configs.py",
        ),
    }

    for name, (skill_path, script_path) in routes.items():
        prompt = (_PROMPTS / name).read_text(encoding="utf-8")
        skill = (_SOLUTION / skill_path).read_text(encoding="utf-8")
        assert skill_path in prompt, name
        assert "hybrid Workday" in prompt, name
        assert "hybrid Workday" in skill, name
        assert (_SOLUTION / script_path).is_file(), name


def test_da_local_capabilities_remain_available() -> None:
    for name in ("create.prompt.md", "update.prompt.md"):
        prompt = (_PROMPTS / name).read_text(encoding="utf-8")
        normalized = " ".join(prompt.split()).casefold()
        assert "continue with local authoring" in normalized, name
        assert "skip every instruction to push, publish" in normalized, name

    evaluate = (_PROMPTS / "evaluate.prompt.md").read_text(encoding="utf-8")
    normalized_evaluate = " ".join(evaluate.split()).casefold()
    assert (
        "continue generating or editing evaluation files locally" in normalized_evaluate
    )
    assert "skip every instruction to push them" in normalized_evaluate

    test_prompt = (_PROMPTS / "test.prompt.md").read_text(encoding="utf-8")
    normalized_test = " ".join(test_prompt.split()).casefold()
    assert "retain browser-based topic driving" in normalized_test
    assert "server-side diagnostics are not yet available" in normalized_test
    assert "da-ga workflow testing is not yet available" in normalized_test

    for name in ("create.prompt.md", "update.prompt.md"):
        prompt = (_PROMPTS / name).read_text(encoding="utf-8")
        normalized = " ".join(prompt.split())
        assert "Do not offer `/test`" in normalized, name
        assert "unchanged deployed" in normalized, name


def test_flightcheck_preserves_standalone_and_configured_scope_modes() -> None:
    instructions = _INSTRUCTIONS.read_text(encoding="utf-8")
    prompt = (_PROMPTS / "flightcheck.prompt.md").read_text(encoding="utf-8")
    normalized = " ".join(prompt.split())
    skill = (
        _SOLUTION / "src" / "skills" / "flightcheck" / "SKILL.md"
    ).read_text(encoding="utf-8")

    assert "flightCheckOnly: true" in instructions
    assert "scope selection supported by the active configuration" in normalized
    assert "supported scopes are `full`, `environment`" in skill
    assert "scope fixed to `local`" not in normalized
