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


def test_public_setup_does_not_configure_mcp() -> None:
    prompt = _SETUP_PROMPT.read_text(encoding="utf-8")

    assert "mcp_config.py" not in prompt
    assert "materialize-defaults" not in prompt


def test_global_and_command_gates_require_canonical_da_completion() -> None:
    instructions = _INSTRUCTIONS.read_text(encoding="utf-8")

    assert "`schema_version` equal to `3`" in instructions
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
        assert "schema_version: 3" in text, path
        assert "connect_ready: true" in text, path
        normalized = " ".join(text.split())
        assert 'or local config does not have `setup: "complete"`' not in normalized, (
            path
        )
        assert (
            '`.local/config.json` is missing or `setup` is not `"complete"`'
            not in normalized
        ), path

    assert (
        "read `.local/setup/config.json` and `.local/config.json`"
        not in instructions.casefold()
    )
    assert (
        "If `.local/config.json` does not exist or its `setup` value"
        not in instructions
    )


def test_global_gate_preserves_flightcheck_only_mode() -> None:
    instructions = _INSTRUCTIONS.read_text(encoding="utf-8")
    normalized = " ".join(instructions.split())

    assert "typed `/flightcheck`" in normalized
    assert "`flightCheckOnly: true`" in normalized
    assert "This exception applies only to `/flightcheck`" in normalized


def test_maker_profile_requires_only_canonical_completion() -> None:
    text = _MAKER_PROFILE.read_text(encoding="utf-8")

    assert "if (canonicalComplete) met.add('setup')" in text
    assert "json.schema_version === 3" in text
    assert "json.connect_ready === true" in text
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
    assert "`connectReady: true`" in import_text
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
    assert text.index("setup_existing_da.py inspect-agent") < text.index(
        "da-existing-dev.md"
    )
    assert text.index("setup_existing_da.py inspect-agent") < text.index(
        "da-prod-to-dev.md"
    )
    assert _DA_MOS_STARTER.is_file()
    assert _MOS_STARTER_REFERENCE.is_file()
    assert "no existing agent and wants a fresh installation" in normalized


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
    assert "setup_alm_export.py inspect" in conflict_flow
    assert "setup_existing_da.py validate-agent" in conflict_flow
    assert "same `almFamilyId`" in conflict_flow
    assert "offer to attach it" in conflict_flow
    assert "Do not recover a collision or offer replacement" in normalized_conflict
    assert "setup_existing_da.py attach" in text
    assert "--setup-source prod-to-dev" in text
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
    assert "factual report in `da-existing-dev.md`" in normalized
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

    assert "no existing agent and wants a fresh installation" in normalized_foundation
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
    assert "outcome: created" in text
    assert "Never show the internal `packageId` to the maker" in normalized
    assert "`connectReady: true`" in text
    assert "`setupStatus`" not in text
    assert "What kind of ESS agent are you setting up?" in text
    assert "Offer exactly **HR** and **IT**" in normalized
    assert "core ESS experience" in normalized
    assert "specific connected system" in normalized
    assert "Requested setup: **{product} -- Unavailable in this environment**" in text
    assert "I have not selected a substitute." in text
    assert "explicitly select an available product" in normalized
    assert "Collapse rows with identical maker-visible fields" in text
    assert "retain the first returned row as the internal command input" in normalized
    assert "Create a new {HR or IT} ESS agent" in normalized
    assert "Choose a different product" in text
    assert "Do not preselect **Create agent**" in text
    assert "authorizes exactly one create attempt" in normalized
    assert "diagnostic evidence only" in normalized
    assert "do not explain those internal version concepts to the maker" in normalized
    assert "Prepare this agent for local editing?" in text
    assert "**Prepare for local editing**" in text
    assert "**Not now** performs no ALM operation" in normalized
    assert "outcome: verification-failed" in normalized
    assert "Setup has stopped without attaching a workspace." in text
    assert "never show internal step IDs or raw technical output" in normalized
    assert "no specific failure cause was supplied" in normalized
    assert "When a specific cause is supplied" in text
    assert "workspace is not ready to connect" in existing_dev
    assert "New entitled MOS product" in text
    assert "content was synced to the local workspace" in normalized
    assert "content was synced to your local workspace" in existing_dev
    assert "Topics synced" in existing_dev
    assert "Global variables synced" in existing_dev
    assert "factual completion report from `da-existing-dev.md`" in normalized
    assert "Do not infer persona, product, target, or progress" in normalized
    assert "Never invoke" in normalized and "/connect" in normalized
    assert "Do not publish, remove or replace components" in normalized
    assert "setup_setup_mos_starter.py" not in text
    assert "setup_mos_starter.py resolve" not in text
    assert "setup_mos_starter.py status" not in text
    assert "DA_EXISTING_DEV_DIAGNOSTIC_JSON:" not in text
    assert len(text.splitlines()) < 160

    assert "createFromStarterPackage" in reference
    assert "Live-proven" in reference
    assert "catalogPackageVersion" in reference
    assert "templateVersion" in reference
    assert "alm.isAlmEnabled" in reference
    assert "never publishes or removes components" in reference
    assert "Fuse disposition matrix" in reference
    assert "PERSONA" not in reference
    assert "resolve_starter_package" not in reference
    assert "setup_mos_starter.py resolve" not in reference
    assert "setup_mos_starter.py status" not in reference


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
    assert "factual completion report from `da-existing-dev.md`" in normalized
    assert "Supplied native agent package" in text
    assert "another readiness" not in text.casefold()


def test_alm_import_collision_and_retry_require_separate_choices() -> None:
    text = _DA_ALM_IMPORT.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    for choice in (
        "Use existing agent",
        "Replace existing agent with this package",
        "Cancel setup",
        "Continue replacement",
        "Retry import",
        "Stop without retrying",
    ):
        assert choice in text
    assert "Default to **Use existing agent**" in text
    assert "Never preselect or recommend **Continue replacement**" in text
    assert "could not be proven" in normalized
    assert "avoid creating or replacing the agent twice" in normalized
    assert "only after the maker selects **Retry import**" in normalized


def test_existing_da_dev_path_never_routes_through_dataverse() -> None:
    text = _DA_EXISTING_DEV.read_text(encoding="utf-8")

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
    assert "Your ESS agent workspace is ready." in text
    assert "| Starting point | Existing editable Dev |" in " ".join(text.split())
    assert "Not performed by foundation setup" in text
    assert "Checkpoint and refresh" in text
    assert "Keep local files unchanged" in text


def test_existing_dev_completion_remains_evidence_driven() -> None:
    text = _DA_EXISTING_DEV.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "`connectionStatus: workspace-ready`" in text
    assert "`connectReady: true`" in text
    assert "a factual handoff, not another readiness gate" in normalized
    assert "changing canonical state conversationally" in normalized
    assert "Do not infer the realm from the URL" in normalized
    assert "from main" not in text
    assert "workstream" not in text.casefold()
    assert "later workstreams" not in text.casefold()
    assert "when the parent setup router already inspected the supplied agent" in (
        normalized
    )
    assert "canonical setup state, or conversation history" in normalized


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
