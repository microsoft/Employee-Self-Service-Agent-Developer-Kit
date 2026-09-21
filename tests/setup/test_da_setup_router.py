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
_NATIVE_ALM_REFERENCE = (
    _SOLUTION / "src" / "reference" / "native-alm-import.md"
)
_MOS_STARTER_REFERENCE = (
    _SOLUTION / "src" / "reference" / "mos-starter-package.md"
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


def test_public_setup_resolves_python_before_bootstrap_commands() -> None:
    prompt = _SETUP_PROMPT.read_text(encoding="utf-8")
    foundation = _FOUNDATION.read_text(encoding="utf-8")
    normalized_prompt = " ".join(prompt.split())
    normalized_foundation = " ".join(foundation.split())

    assert prompt.index("Read `src/skills/foundation-setup/SKILL.md` first") < (
        prompt.index("{PYTHON} -m pip install")
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
    assert "If the check fails" in prompt
    assert "Then rerun the check" in prompt
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
        "connect.prompt.md",
        "create.prompt.md",
        "delete.prompt.md",
        "evaluate.prompt.md",
        "flightcheck.prompt.md",
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

    assert "`.local/config.json`'s" in instructions


def test_global_gate_preserves_flightcheck_only_mode() -> None:
    instructions = _INSTRUCTIONS.read_text(encoding="utf-8")
    normalized = " ".join(instructions.split())

    assert "typed `/flightcheck`" in normalized
    assert "`flightCheckOnly: true`" in normalized
    assert "This exception applies only to `/flightcheck`" in normalized


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


def test_workday_routing_remains_separate() -> None:
    step1 = _CONNECT_STEP1.read_text(encoding="utf-8")
    workday = _WORKDAY.read_text(encoding="utf-8")

    assert "src/skills/setup/SKILL.md" in step1
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
        "src/skills/foundation-setup/da-existing-dev.md",
        "src/skills/foundation-setup/da-prod-to-dev.md",
        "src/skills/foundation-setup/da-mos-starter.md",
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
    assert "segment denoting the service ring" in normalized_import
    assert "confirm the `prod` ring with the user" in normalized_import
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
    assert "confirm the `prod` ring with the user" in normalized.casefold()
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
        assert "confirm the `prod` ring with the user" in " ".join(
            text.split()
        ).casefold()


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
    reference = _MOS_STARTER_REFERENCE.read_text(encoding="utf-8")
    existing_dev = _DA_EXISTING_DEV.read_text(encoding="utf-8")

    assert "src/reference/mos-starter-package.md" in text
    assert "setup_mos_starter.py list" in text
    assert "DA_MOS_STARTER_PACKAGES_JSON:" in text
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
    assert "outcome: created" in text
    assert "Never show the internal `packageId` to the maker" in normalized
    assert "`connectReady: true`" in existing_dev
    assert "`setupStatus`" not in text
    assert "Do not ask the maker to classify the product before loading the catalog" in normalized
    assert "infer a concise user-friendly product name" in normalized
    assert "render `Employee Self-Service IT` as `Employee Self-Service (IT)`" in normalized
    assert "render `Employee Self-Service HR` as `Employee Self-Service (HR)`" in normalized
    assert "use the exact service-provided product name unchanged" in normalized
    assert "must not change the underlying `packageId`" in normalized
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
    assert "Do you have a test tenant user?" in foundation
    assert "setup_existing_da.py cached-accounts" in foundation
    assert "DA_AGENTBUILDER_ACCOUNTS_JSON:" in foundation
    assert "**Continue with this account**" in foundation
    assert '--account "{SETUP_ACCOUNT}"' in foundation
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
    assert "does not require published Dev configuration" in normalized
    assert "publishing is outside foundation setup" in normalized


def test_existing_dev_completion_remains_evidence_driven() -> None:
    text = _DA_EXISTING_DEV.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "`connectionStatus: workspace-ready`" in text
    assert "`connectReady: true`" in text
    assert "Canonical setup state is authoritative for each agent's setup progress and readiness" in normalized
    assert "`state`, `connectReady`, `activeStep`, and `failureCauses` are the runtime-readiness verdict" in normalized
    assert "treat all four setup-owned FlightChecks and their maintenance calls as one presentation unit" in normalized
    assert "attempt every available check before producing the final runtime-readiness table" in normalized
    assert "Render both even when `connectReady` is false" in normalized
    for readiness_status in (
        "**✅ Ready**",
        "**⚠️ Ready with limitation**",
        "**➖ Not required**",
        "**⛔ Action required**",
        "**⚠️ Check unavailable**",
        "**⬜ Not checked**",
    ):
        assert readiness_status in text
    assert "When `connectReady` is false after materialization" in normalized
    assert "local authoring is ready while the reported runtime prerequisites remain" in normalized
    assert "Present **Connection required**" in normalized
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
        "connect.prompt.md": "requires the corresponding product extension",
        "troubleshoot.prompt.md": (
            "requires the corresponding product extension guidance"
        ),
    }

    for name, text in expected_text.items():
        prompt = (_PROMPTS / name).read_text(encoding="utf-8")
        assert text in prompt, name
        assert "transport" not in prompt.casefold(), name


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


def test_flightcheck_preserves_standalone_and_local_only_modes() -> None:
    prompt = (_PROMPTS / "flightcheck.prompt.md").read_text(encoding="utf-8")
    normalized = " ".join(prompt.split())

    assert "flightCheckOnly: true" in normalized
    assert "proceed without canonical setup state" in normalized
    assert "only the local-files FlightCheck scope" in normalized
    assert "scope fixed to `local`" in normalized
