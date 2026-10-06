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
_DA_ALM_IMPORT = _SOLUTION / "src" / "skills" / "foundation-setup" / "da-alm-import.md"
_DA_PROD_TO_DEV = (
    _SOLUTION / "src" / "skills" / "foundation-setup" / "da-prod-to-dev.md"
)
_DA_MOS_STARTER = (
    _SOLUTION / "src" / "skills" / "foundation-setup" / "da-mos-starter.md"
)
_DA_ENVIRONMENT_TARGET = (
    _SOLUTION / "src" / "skills" / "foundation-setup" / "da-environment-target.md"
)
_PRODUCT_LINE_RECONCILIATION = (
    _SOLUTION / "src" / "skills" / "foundation-setup" / "product-line-reconciliation.md"
)
_PERMISSION_GUIDANCE = (
    _SOLUTION / "src" / "skills" / "foundation-setup" / "permission-guidance.md"
)
_ALM_ENROLLMENT = (
    _SOLUTION / "src" / "skills" / "foundation-setup" / "alm-enrollment.md"
)
_PRODUCT_LINE_RELEASES = _SOLUTION / "src" / "reference" / "product-line-releases.json"
_NATIVE_ALM_REFERENCE = _SOLUTION / "src" / "reference" / "native-alm-import.md"
_MOS_STARTER_REFERENCE = _SOLUTION / "src" / "reference" / "mos-starter-package.md"
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


def test_help_me_decide_uses_chat_view_follow_up_messages() -> None:
    foundation = _FOUNDATION.read_text(encoding="utf-8")
    help_contract = foundation.split("### Help me decide", 1)[1].split(
        "### What does setup do?", 1
    )[0]
    normalized = " ".join(help_contract.split())

    assert "continue the conversation in the **Chat view**" in help_contract
    assert "Start by sending this agent response:" in help_contract
    assert (
        "Wait for the maker to enter a follow-up message in the chat input box"
        in normalized
    )
    assert (
        "one short, targeted question in each agent response followed by the "
        "maker's next follow-up message"
    ) in normalized
    assert (
        "The maker completes the decision by selecting one of those choices"
        in normalized
    )
    assert "do not" not in help_contract.lower()
    assert "never" not in help_contract.lower()
    assert "instead of" not in help_contract.lower()
    assert "disabled" not in help_contract.lower()
    assert "no default" not in help_contract.lower()


def test_first_time_orientation_explains_setup_and_preserves_direct_routes() -> None:
    foundation = _FOUNDATION.read_text(encoding="utf-8")
    normalized = " ".join(foundation.split())
    orientation = foundation.split("### What does setup do?", 1)[1].split(
        "This is the DA-GA `/setup` entry point", 1
    )[0]
    account_section = foundation.split("## Choose the sign-in account", 1)[1].split(
        "## Confirm people and role availability", 1
    )[0]

    assert "#### Why do I need this?" in orientation
    assert orientation.index("#### Why do I need this?") < orientation.index(
        "#### What you need"
    )
    assert "maintains a local copy of the agent" in orientation
    assert "ADK needs this workspace copy" in orientation
    assert "readiness requirements through Flight Checks" in orientation
    assert "Foundation" not in orientation
    assert (
        "no usable active local target and no incomplete canonical setup record"
        in normalized
    )
    assert (
        "existing agent, fresh agent, package, agent URL, environment, or resume "
        "intent, enter that route directly"
    ) in normalized
    assert (
        "render the **What does setup do?** orientation above, then ask" in normalized
    )
    assert foundation.count("- **What does setup do?**") >= 2
    assert (
        "- **What does setup do?**\n- **Help me decide**\n- **Cancel setup**"
        in foundation
    )
    assert "**What does setup do?**" not in account_section
    assert "administrator handoffs" in orientation
    assert "final\ncompletion choices" in orientation


def test_administrator_handoffs_are_forwardable_and_evidence_gated() -> None:
    permission = _PERMISSION_GUIDANCE.read_text(encoding="utf-8")
    normalized_permission = " ".join(permission.split())
    environment = _DA_ENVIRONMENT_TARGET.read_text(encoding="utf-8")
    normalized_environment = " ".join(environment.split())

    assert "## Forwardable administrator request" in permission
    for field in (
        "**Requested action:** {EXACT_ADMINISTRATOR_ACTION}",
        "**Environment:** {ENVIRONMENT_NAME}",
        "**Environment URL:** {ENVIRONMENT_URL}",
        "**Agent:** {AGENT_NAME}",
        "**User:** {SETUP_ACCOUNT}",
        "**Why this is needed:** {EVIDENCE_SUPPORTED_REASON}",
        "**When complete:** {RETURN_CONDITION}",
    ):
        assert field in permission
    assert "Omit a field when it does not apply" in normalized_permission
    assert "unsupported billing guidance" in permission
    assert "speculative role claims" in permission
    assert "rerun only the operation or Flight Check" in normalized_permission
    assert (
        "When evidence explicitly identifies missing first-party application approval"
        in permission
    )
    assert "https://entra.microsoft.com/" in permission
    assert (
        "Only when the service evidence explicitly identifies missing creation access"
        in permission
    )
    assert "**Grant agent-creation access**" in permission
    assert (
        "Assign the Environment Maker security role to {SETUP_ACCOUNT} in "
        "{ENVIRONMENT_NAME}."
    ) in normalized_permission

    assert "Retain the answer as `{REQUESTED_ENVIRONMENT_NAME}`" in (
        normalized_environment
    )
    assert "shared **Forwardable administrator request**" in environment
    assert "**Create a Power Platform environment**" in environment
    assert "This setup does not require a Dataverse database." in environment
    assert "the retained `{POWER_PLATFORM_ADMIN_ORIGIN}/`" in environment
    assert (
        "Send the requester the new environment URL" in normalized_environment
    )


def test_setup_reconciles_every_selected_agent_before_da_only_work() -> None:
    foundation = _FOUNDATION.read_text(encoding="utf-8")
    normalized_foundation = " ".join(foundation.split())
    prompt = _SETUP_PROMPT.read_text(encoding="utf-8")
    normalized_prompt = " ".join(prompt.split())
    reconciliation = _PRODUCT_LINE_RECONCILIATION.read_text(encoding="utf-8")
    normalized_reconciliation = " ".join(reconciliation.split())
    enrollment = _ALM_ENROLLMENT.read_text(encoding="utf-8")
    normalized_enrollment = " ".join(enrollment.split())
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
    ) < normalized_prompt.index("check the Microsoft Object Model converter")
    assert (
        "do not install or validate the Microsoft Object Model converter"
        in normalized_prompt
    )
    assert "complete its kit-switch handoff" in normalized_prompt
    assert "python scripts/reconcile_setup_agent.py" in reconciliation
    assert '--known-native-schema "{RETURNED_SCHEMA_NAME}"' in reconciliation
    assert "--probe dataverse" in reconciliation
    assert "--probe native" in reconciliation
    assert reconciliation.index("Run the Dataverse probe") < (
        reconciliation.index("Run the native MinimalBot probe")
    )
    assert "`agentBackend` query value is an ordering hint only" in reconciliation
    assert "`dataverse` means run the Dataverse probe first" in reconciliation
    assert "`cosmos` means run the native probe first" in reconciliation
    assert "Run the second probe even when the first probe returns `found`" in (
        reconciliation
    )
    assert "DA_SETUP_PRODUCT_RECONCILIATION_JSON:" in reconciliation
    assert "`authentication-required`" in reconciliation
    assert "`access-denied`" in reconciliation
    assert "`not-found`" in reconciliation
    assert "`uncertain`" in reconciliation
    assert (
        "Do not convert `authentication-required`, `access-denied`, or "
        "`uncertain` into `not-found`."
    ) in normalized_reconciliation
    assert "msdyn_copilotforemployeeselfservice*" in reconciliation
    assert "gptagent_copilotforemployeeselfservice*" in reconciliation
    assert "classic CA and DA-Preview variants" in reconciliation
    assert "When both probes returned `found`" in reconciliation
    assert "When both probes returned `not-found`" in reconciliation
    assert "Preserve a backend-hint mismatch as internal evidence" in reconciliation
    assert _ALM_ENROLLMENT.is_file()
    assert "## Preview optional ALM enrollment" not in reconciliation
    assert "Unresolved exact native candidate" not in enrollment
    assert "current request supplied one exact Microsoft Copilot Studio URL" not in (
        reconciliation
    )
    assert "selected-agent product reconciliation has established one exact" in (
        normalized_enrollment
    )
    assert "Continue (Recommended)" in enrollment
    assert "Skip enrollment" in enrollment
    assert (
        "Leave the selection initially unset and disable free-form input."
        in normalized_enrollment
    )
    assert "python scripts/setup_existing_da.py ensure-alm" in enrollment
    assert "DA_ALM_ENROLLMENT_JSON:" in enrollment
    assert "stop without another write or attachment" in normalized_enrollment
    assert "ALM enrollment skipped. The agent was not changed." in enrollment
    assert "Local authoring does not require ALM enrollment." in enrollment
    assert "--allow-unenrolled-authoring" in enrollment
    assert (
        "cannot prepare a local authoring workspace without an ALM authoring route"
        not in normalized_enrollment
    )
    assert "For resolved `dev`, return to the caller's exact Dev continuation" in (
        normalized_enrollment
    )
    assert "For resolved `prod`, continue through `da-prod-to-dev.md`" in enrollment
    assert "Stop without retrying enrollment, attaching, or publishing" in (
        normalized_enrollment
    )
    assert "Do not invoke `ensure-alm` after a successful import" in alm_import
    assert (
        "Do not invoke `ensure-alm` for an established Prod-to-Dev relationship "
        "or successful import"
    ) in " ".join(prod_to_dev.split())
    assert "For a native `found` DA-GA observation" in reconciliation
    assert "For a Dataverse-only `found` DA-GA observation" in reconciliation
    assert (
        "An omitted field or a null, empty, or invalid schema value is "
        "unresolved product identity"
    ) in normalized_reconciliation
    assert "not an unknown or unsupported family" in normalized_reconciliation
    assert "productIdentity.outcome: uncertain" in reconciliation
    assert "As a temporary compatibility exception" not in reconciliation
    assert (
        "Preserve the schema-identity source, observation, and error internally."
        in reconciliation
    )
    for mismatch_state in (
        "**Choose the starting point and target environment** as complete",
        "**Verify access and agent identity** as blocked",
        "**Establish an editable Dev agent** and "
        "**Materialize the local workspace** as pending",
        "**Review the setup handoff** as in progress",
    ):
        assert mismatch_state in normalized_reconciliation
    assert "How would you like to continue setup?" in reconciliation
    for recovery_choice in (
        "Install and open the compatible kit",
        "Choose a different agent",
        "Choose a different environment",
        "Go back",
    ):
        assert f"**{recovery_choice}**" in reconciliation
    assert "**Not now**" not in reconciliation
    assert "**Cancel setup**" not in reconciliation
    assert "For **Install and open the compatible kit**, run `recoveryCommand`" in (
        reconciliation
    )
    legacy_message = """**Message:**

{agent display name or Selected agent} belongs to a legacy agent family, so this Developer Kit cannot safely continue its setup.

**End message.**"""
    assert legacy_message in reconciliation
    assert "belongs to the solution-backed Employee Self-Service" not in reconciliation
    assert "classic Employee Self-Service agent product line" not in reconciliation
    compatible_handoff = reconciliation.split("When `outcome` is `available`", 1)[
        1
    ].split("## Unsupported agent", 1)[0]
    assert '"header": "Continue setup"' in compatible_handoff
    assert '"question": "How would you like to continue setup?"' in compatible_handoff
    assert '"allowFreeformInput": false' in compatible_handoff
    assert '"recommended"' not in compatible_handoff
    assert '"default"' not in compatible_handoff
    assert "Leave the selection initially unset." in compatible_handoff
    assert "Keyboard focus or a visual highlight is not a selected value" in (
        compatible_handoff
    )
    assert "wait for the maker to submit an explicit choice" in compatible_handoff
    assert "without adding Markdown emphasis" in compatible_handoff
    assert "Do not emit an operational progress line between them." in reconciliation
    assert (
        "Do not emit **Verified replacement agent identities and resolved "
        "compatible ESS kit**" in reconciliation
    )
    assert "it is not part of a supported Employee Self-Service agent family" in (
        reconciliation
    )
    assert "continue from its environment-scoped `list-agents`" in reconciliation
    assert "rerun `list-environments`" in reconciliation
    assert "Return to **Choose the sign-in account**" in reconciliation
    assert "**Go back** is the account-reset route" in reconciliation
    unavailable_recovery = reconciliation[
        reconciliation.index("When `outcome` is `unavailable`") : reconciliation.index(
            "When `outcome` is `available`"
        )
    ]
    for recovery_choice in (
        "Choose a different agent",
        "Choose a different environment",
        "Go back",
    ):
        assert f"**{recovery_choice}**" in unavailable_recovery
    assert (
        "Do not offer **Install and open the compatible kit**" in unavailable_recovery
    )
    assert (
        "Follow the shared recovery routes under **Unsupported agent**."
        in unavailable_recovery
    )
    assert "stop without guessing" not in reconciliation
    assert "When command execution fails" in reconciliation
    assert "Do not label the unchanged command as a retry" in reconciliation
    assert "verify that its checkout matches `releaseTag`" in reconciliation
    assert "offer to open its `solutions/ess-maker-skills` workspace directly" in (
        reconciliation
    )
    assert reconciliation.count("**Review the setup handoff** as complete") == 1
    assert reconciliation.count("**Review the setup handoff** as blocked") == 2
    assert "No Copilot Studio agent or setup state was changed" in reconciliation
    assert "installation was not changed" not in reconciliation
    assert "Parse `DA_AGENT_LIST_JSON:` as endpoint-labeled evidence" in existing_dev
    assert "`minimalBots.response` is the untouched array" in existing_dev
    assert "`copilotStudioAgents.response` is the untouched array" in existing_dev
    assert "correlate candidates only by exact `botId`" in existing_dev
    assert "Never correlate by display name" in existing_dev
    assert "--known-native-schema" in existing_dev
    assert mos_starter.count("selected-agent product-line reconciliation") >= 2
    assert mos_starter.count("--known-native-schema") >= 2
    assert alm_import.count("selected-agent product-line reconciliation") >= 2
    assert alm_import.count("--known-native-schema") >= 2
    assert "selected-agent product-line reconciliation" in prod_to_dev
    assert "--known-native-schema" in prod_to_dev
    assert "`agentBackend` query value as an ordering hint" in foundation
    assert "`routeStatus` is `not-established`" in foundation
    assert "`alm.isEnrolled` is `false`" in foundation
    assert "`almEnrollment`" not in foundation
    assert "alm-enrollment.md" in foundation
    assert "alm-enrollment.md" in existing_dev
    assert "does not require readable `/configure` state" in existing_dev


def test_account_picker_establishes_account_before_reconciliation() -> None:
    foundation = _FOUNDATION.read_text(encoding="utf-8")
    normalized = " ".join(foundation.split())

    assert "`reconcile_setup_agent.py` does not accept `--select-account`" in (
        normalized
    )
    assert (
        'setup_existing_da.py list-environments --ring "{RING}" --select-account'
    ) in normalized
    assert (
        "pass it to reconciliation or mutation with "
        '`--account "{SETUP_ACCOUNT}"`'
    ) in normalized
    assert (
        "Do not pass `--select-account` to `reconcile_setup_agent.py` or a "
        "mutating command."
        in normalized
    )


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
    runtime_message = """**Message:**

**Setup command approvals**

VS Code will ask you to approve commands that:

- check Python and prepare the required local tools;
- sign you in and inspect the selected environment and agent;
- perform the setup actions you confirm and prepare the local workspace;
- download required Microsoft components when needed.

These approvals let VS Code run local commands. They do not grant Power
Platform access, approve a Microsoft application, or assign administrator
roles.

To avoid repeated prompts, open the permissions menu below the chat input and
select **Allow all** for this chat session. This applies to every tool used in
the session, not only setup. Provide a screenshot of your chat input if you
need guidance finding the setting.

**End message.**"""
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
    command_runtime = foundation.split("## Command runtime", 1)[1].split(
        "## Shared workspace choices", 1
    )[0]
    assert "informational disclosure, not another setup confirmation" in (
        " ".join(command_runtime.split())
    )
    assert "**Continue setup**" not in command_runtime
    assert "**Cancel setup**" not in command_runtime
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
    assert normalized_prompt.index("{PYTHON} -m pip install") < normalized_prompt.index(
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
    assert "`py -3`, `python3`, then `python` on Windows" in (normalized_foundation)
    assert "`python3`, then `python` on macOS or Linux" in normalized_foundation
    assert "check each candidate with" in normalized_foundation
    assert "one terminal command at a time" in normalized_foundation
    assert "active virtual environments, common local installation paths" in (
        normalized_foundation
    )
    assert "offer to perform it" in normalized_foundation
    assert prompt.index(
        "After reading the foundation skill, use its explicit progress render points"
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
    assert (
        "Mark **Review the setup handoff** complete in the final snapshot" in foundation
    )


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
    normalized_flightcheck_prompt = " ".join(flightcheck_prompt.split())
    assert "FlightCheck entry contract" in flightcheck_prompt
    assert "Standalone FlightCheck" in normalized_flightcheck_prompt
    assert "Canonical setup ready" in normalized_flightcheck_prompt

    assert "`.local/config.json`'s" in instructions


def test_global_gate_routes_flightcheck_through_setup_evidence() -> None:
    instructions = _INSTRUCTIONS.read_text(encoding="utf-8")
    normalized = " ".join(instructions.split())
    prompt = (_PROMPTS / "flightcheck.prompt.md").read_text(encoding="utf-8")
    normalized_prompt = " ".join(prompt.split())
    skill = (_SOLUTION / "src" / "skills" / "flightcheck" / "SKILL.md").read_text(
        encoding="utf-8"
    )
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
    assert "Running FlightCheck requires Setup to be complete." in instructions
    assert "Some setup items still require attention:" in normalized
    assert "Setup needs to prepare the local agent workspace." in normalized
    assert "Collect every non-empty `failure_causes` entry" in normalized
    assert "**Environment capacity**" in instructions
    assert "**Connections**" in instructions
    assert "**Agent content**" in instructions
    assert "keep the canonical setup IDs internal" in normalized
    assert "{READINESS_ISSUES}" in instructions
    assert "{READINESS_ITEM}" in instructions
    assert "{READINESS_DETAIL}" in instructions
    assert '"question": "Would you like to return to Setup now?"' in instructions
    assert '"label": "Return to Setup"' in instructions
    assert '"question": "Would you like to run Setup now?"' in instructions
    assert '"label": "Run Setup"' in instructions
    assert instructions.count('"label": "Not now"') == 2
    assert instructions.count('"allowFreeformInput": false') >= 2
    assert "treat the selection as a `/setup` invocation" in normalized
    assert "src/skills/foundation-setup/SKILL.md" in instructions
    assert "selection already confirms setup intent" in normalized
    assert "Carry forward the active agent" in instructions
    assert (
        "Do not ask the maker to select **Resume setup for this agent**" in normalized
    )
    assert "first setup decision or operation not already established" in normalized
    assert "normal target-selection flow" in normalized
    assert "canonical setup state unchanged" in normalized

    assert "Follow the **FlightCheck entry contract**" in normalized_prompt
    assert "Standalone FlightCheck" in normalized_prompt
    assert "Canonical setup ready" in normalized_prompt
    assert "owns the maker interaction and next route" in normalized_skill

    entry_contract = instructions.split("#### FlightCheck entry contract", 1)[1]
    entry_contract = entry_contract.split("### If canonical setup is ready", 1)[0]
    assert entry_contract.count("**Message:**") == 2
    assert entry_contract.count("**End message.**") == 2
    assert entry_contract.count("```json") == 2


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
    assert (
        "A Prod source and its related Dev agent have different IDs by design"
        in normalized
    )
    assert "Classify the supplied agent first" in normalized

    assert set(_PATH_RE.findall(text)) == {
        "src/skills/foundation-setup/da-alm-import.md",
        "src/skills/foundation-setup/da-environment-target.md",
        "src/skills/foundation-setup/da-existing-dev.md",
        "src/skills/foundation-setup/da-prod-to-dev.md",
        "src/skills/foundation-setup/da-mos-starter.md",
        "src/skills/foundation-setup/alm-enrollment.md",
        "src/skills/foundation-setup/permission-guidance.md",
        "src/skills/foundation-setup/product-line-reconciliation.md",
    }
    assert "not a setup option to advertise or recommend" in normalized
    assert "Begin a downstream playbook only when a maker whose setup is complete" in (
        normalized
    )
    assert "**Exit setup** ends the current request" in normalized
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
    assert "Which Power Platform service ring should setup use?" in (environment_target)
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
    assert (
        "Setup is already complete for **{agent display name}**, and this "
        "workspace is ready to use."
    ) in normalized
    assert (
        "do not render a progress checklist until the maker "
        "chooses **Redo setup for this agent**"
    ) in normalized
    assert (
        "**{agent display name}** is the active agent in this workspace" in foundation
    )
    for choice in (
        "Exit setup",
        "Redo setup for this agent",
        "Switch to another configured agent",
        "Set up another agent in this environment",
    ):
        assert f"**{choice}**" in foundation
    ready_agent_choices = foundation.split(
        "Setup is already complete for **{agent display name}**", 1
    )[1].split(
        "For a usable local target whose canonical agent record is incomplete", 1
    )[0]
    normalized_ready_choices = " ".join(ready_agent_choices.split())
    assert "same ready completion choices defined above" in normalized_ready_choices
    assert (
        "inserting these choices immediately before **Exit setup**"
        in normalized_ready_choices
    )
    assert (
        "Use the same recommendation suffixes and maker-facing recommendation."
        in normalized_ready_choices
    )
    assert "**What does setup do?**" in normalized_ready_choices
    assert "**Reset and use this workspace**" not in ready_agent_choices
    assert "**Create and open a new workspace**" not in ready_agent_choices
    assert "**Continue with this agent**" not in ready_agent_choices
    assert "**Cancel setup**" not in ready_agent_choices
    incomplete_agent_choices = foundation.split(
        "**{agent display name}** is the active agent in this workspace", 1
    )[1].split("For **Redo setup for this agent**", 1)[0]
    assert "**Resume setup for this agent**" in incomplete_agent_choices
    assert "**Reset and use this workspace**" in incomplete_agent_choices
    assert "**Create and open a new workspace**" in incomplete_agent_choices
    assert (
        "For **Create and open a new workspace**, use the location-selection "
        "and worktree handoff defined under **Work with both environments side "
        "by side**"
    ) in normalized
    assert "Do not create a separate redo workflow or state model." in foundation
    assert (
        "Setup remains complete for **{agent display name}**. No checks were rerun."
    ) in normalized
    assert ("Setup has not been completed for **{agent display name}**.") in normalized
    assert "Run `/setup` when you are ready to resume." in foundation
    assert (
        "Do not advertise post-setup capabilities while canonical "
        "`connect_ready` is not `true`."
    ) in normalized
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
    initial_import = text.split(
        "Run no other operation between the maker's confirmation and the create-only import:",
        1,
    )[1].split("Do not pass replacement or retry arguments.", 1)[0]
    assert "--client-request-id" not in initial_import
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
    assert (
        "carry the unresolved cleanup warning into the detailed and durable handoffs"
        in normalized
    )
    assert "**Retry local package cleanup**" in text
    assert "canonical setup state shows that attachment started" in normalized
    assert "check whether `.local/setup/alm-export/active.json`" in normalized
    assert "every resumed detailed and durable handoff" in normalized
    assert "Parse `DA_ALM_EXPORT_CLEANUP_JSON:`" in text
    assert "status: removed" in text
    assert "status: not-found" in text
    assert "Do not repeat export, import, attachment, or FlightCheck" in normalized
    assert ".local/setup/alm-export/active.json" in text
    assert "ask whether to start a new export and create-only import" in normalized
    assert "Continue only after explicit maker approval" in normalized
    assert "ordinary create-only command without a client request UUID" in normalized
    assert "new client request UUID" in normalized
    assert len(text.splitlines()) < 180
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
    assert (
        "Prod agent verified. Checking for its related editable Dev agent" in normalized
    )
    assert "No related editable Dev agent was found" in normalized
    assert "without changing Prod" in normalized
    assert "Create editable Dev agent" in text
    assert "Do not preselect **Create editable Dev agent**" in text
    assert "Use related Dev agent" in text
    assert "**Cancel setup**" not in text
    assert "If the maker goes back after export" in normalized
    assert (
        "When the maker selected a different target environment, clear that "
        "target and return to **Choose the sign-in account**"
    ) in normalized
    assert "Never reuse the cleaned-up package" in normalized
    assert "Do not rerun export or import" in normalized
    assert (
        "render the factual workspace and runtime-readiness report there" in normalized
    )
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
    assert "Which Power Platform service ring should setup use?" in (environment_target)
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
        "Go back",
    ):
        assert f"**{empty_environment_choice}**" in environment_target
    assert "does not require a Dataverse database" in environment_target
    assert "Do not route into a Dataverse provisioning skill" in (
        normalized_environment_target
    )
    assert "authorizationFailure" in environment_target
    assert "DA_ENVIRONMENT_LIST_ERROR_JSON:" in environment_target
    assert "DA_ENVIRONMENT_LIST_ERROR_RESPONSE_JSON:" in environment_target
    for discovery_failure_choice in (
        "Retry",
        "Use another account",
        "Use an environment URL",
        "Go back",
    ):
        assert f"**{discovery_failure_choice}**" in environment_target
    assert "custom entry disabled inside the control" in normalized_environment_target
    assert "authoritative environment-scoped operation" in (
        normalized_environment_target
    )
    assert "## Retry setup with another target" in environment_target
    assert "How would you like to continue setup?" in environment_target
    for retry_choice in (
        "Try with a different user",
        "Try a different environment",
        "Go back",
    ):
        assert f"**{retry_choice}**" in environment_target
    assert "present these labels unchanged with the selection initially unset" in (
        normalized_environment_target
    )
    assert "rerun environment discovery for that account" in (
        normalized_environment_target
    )
    assert "retain the current account and ring" in normalized_environment_target
    assert "**Use another account** remains the account-switch route" in (
        normalized_environment_target
    )
    assert (
        "return to the parent skill's **What would you like to set up in this "
        "environment?** choice surface"
    ) in normalized_environment_target
    assert "also offer **Use a Microsoft Copilot Studio URL**" in environment_target
    assert "setup_mos_starter.py list" in text
    assert "DA_MOS_STARTER_PACKAGES_JSON:" in text
    assert "setup_mos_starter.py inspect-connection" not in text
    assert "DA_MOS_CONNECTION_PREFLIGHT" not in text
    assert "setup_mos_starter.py create" in text
    assert "DA_MOS_STARTER_CREATE_ANNOTATIONS_JSON:" in text
    assert "DA_MOS_STARTER_CREATE_JSON:" in text
    assert "alm-enrollment.md" in text
    assert "Continue (Recommended)" in text
    assert "Skip enrollment" in text
    assert "python scripts/setup_existing_da.py ensure-alm" not in text
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
    assert "Do not ask the maker to classify an agent template before loading the catalog" in normalized
    assert "infer a concise user-friendly agent name" in normalized
    assert (
        "Render `Employee Self-Service` as `Employee Self-Service (Hub)`" in normalized
    )
    assert (
        "render `Employee Self-Service IT` or `Employee Self-Service (IT)` as "
        "`Employee Self-Service (IT)`" in normalized
    )
    assert (
        "render `Employee Self-Service HR` or `Employee Self-Service (HR)` as "
        "`Employee Self-Service (HR)`" in normalized
    )
    assert "use the exact service-provided catalog name unchanged" in normalized
    assert "must not change the underlying `packageId`" in normalized
    assert (
        "render the following friendly agent name and default supporting description "
        "exactly as written"
        in normalized
    )
    assert (
        "Do not paraphrase, shorten, or combine this copy with the "
        "service-provided description." in normalized
    )
    assert (
        "Choose this agent if you want to organize HR, IT, or other agents "
        "behind one unified employee experience."
        in normalized
    )
    assert (
        "Create an HR agent that helps employees get HR answers and complete "
        "requests." in normalized
    )
    assert (
        "Create an IT agent that helps employees resolve technical issues and "
        "access support." in normalized
    )
    assert (
        "For every other catalog entry, use its exact service-provided name unchanged "
        "and use `shortDescription`, then `description`"
        in normalized
    )
    assert "host's interactive single-selection control" in normalized
    assert "Do not ask the maker to type an agent name" in normalized
    assert (
        "Leave the selection initially unset, and disable custom entry inside "
        "the control"
    ) in normalized
    assert "{PRODUCT_ROWS}" in text
    assert "never assume a fixed agent count" in normalized
    assert "Do not ask the maker to type an agent name or number any choice" in normalized
    assert (
        "present those agent choices followed by **Help me decide**, **Refresh list**, "
        "and **Choose a different environment**, in that order"
    ) in normalized
    assert (
        "Use **Choose an ESS agent or setup action.** as the exact question."
    ) in normalized
    assert (
        "For **Refresh list**, rerun the catalog list and agent list in their "
        "existing order"
    ) in normalized
    assert "This is a new maker-requested read, not an automatic retry" in normalized
    assert (
        "For **Choose a different environment**, retain the selected account and ring"
    ) in normalized
    assert "rerun `list-environments`" in text
    assert "selecting an installed agent creates it" in normalized
    assert "**Use {friendly agent name} — Already installed**" in text
    assert "**Create {friendly agent name} {version}**" in text
    assert "Build the agent picker as a projection of the latest successful catalog result" in normalized
    assert "render exactly one choice for every resulting catalog entry" in normalized
    assert "both endpoint-labeled list results" in normalized
    assert (
        "Only an exact candidate whose product identity and editable Dev route were established"
        in normalized
    )
    assert (
        "An older workspace observation without a currently validated exact identity is "
        "historical evidence, not a sticky installed label"
    ) in normalized
    assert (
        "When both endpoint reads fail or exact candidate reconciliation remains unresolved"
        in normalized
    )
    assert (
        "do not convert that uncertainty into either installed or uninstalled"
        in normalized
    )
    assert (
        "Rebuild this projection whenever a fresh catalog or agent-list result arrives"
        in normalized
    )
    assert "Installation status unconfirmed" in text
    assert "Installation status unavailable" in text
    assert "Previous create conflict" in text
    assert "this agent type already exists in the environment" in normalized
    assert (
        "the existing agent was not returned among the agents created by "
        "this Microsoft login"
    ) in normalized
    assert "Create anyway" in text
    assert "An existing agent may still be hidden from this account" in normalized
    assert "let Copilot Studio validate the current state" in normalized
    assert "does not claim that a matching agent is absent" in normalized
    assert "show a nonterminal progress message" in normalized
    assert (
        "I cannot confirm whether the agent was created because communication "
        "ended before a definitive result was received. Setup has stopped."
    ) not in normalized
    assert (
        "Say setup stopped only after reconciliation cannot prove an identity"
        in normalized
    )
    assert (
        "Do not add another prohibition based on the earlier observation" in normalized
    )
    assert "it is not starter-package provenance" in normalized
    assert "does not prove the installed agent's template version" in normalized
    assert "do not correlate it with agents by display name" in normalized
    assert "## Confirm the exact product and target" not in text
    assert "**Create agent**" not in text
    assert _PREPARE_FRESH_WORKSPACE.is_file()
    assert (
        "This workspace is currently set up for **{current environment}**. "
        "How would you like to set up **{new environment}**?"
    ) in normalized_foundation
    conflict_choices = foundation[
        foundation.index(
            "When an occupied workspace needs a new environment"
        ) : foundation.index(
            "For **Use the new environment in this workspace (Recommended)**"
        )
    ]
    assert "**Use the new environment in this workspace (Recommended)**" in (
        conflict_choices
    )
    assert "**Work with both environments side by side**" in conflict_choices
    assert "**Go back**" in conflict_choices
    assert "**Use suggested location" not in conflict_choices
    assert "**Choose another location**" not in conflict_choices
    assert "**Archive and reuse this workspace (Recommended)**" in foundation
    assert (
        "Reusing this workspace will archive its local setup records, agent "
        "files, and FlightCheck results for **{current environment}**."
    ) in normalized_foundation
    assert (
        "Where should setup create the workspace for **{new environment}**?"
        in foundation
    )
    assert (
        "Use suggested location -- {suggested absolute sibling-folder path}"
        in foundation
    )
    assert "Choose another location" in foundation
    assert "Do not ask the maker to type a path unless" in normalized_foundation
    workspace_location = foundation[
        foundation.index(
            "For **Work with both environments side by side**"
        ) : foundation.index("For **Reset and use this workspace**")
    ]
    assert "**Use suggested location" in workspace_location
    assert "**Choose another location**" in workspace_location
    assert "**Go back**" in workspace_location
    assert "**Cancel setup**" not in workspace_location
    assert "do not derive or create a fresh destination" in normalized_foundation
    assert (
        "return to the conflicting-environment choice surface"
    ) in normalized_foundation
    assert "scripts/prepare_fresh_workspace.py" in foundation
    assert "--open-vscode" in foundation
    assert "DA_PREPARED_WORKSPACE_JSON:" in foundation
    assert (
        "When no cached account is returned, do not ask an account question"
        in foundation
    )
    assert (
        "When exactly one cached account `{CACHED_ACCOUNT}` is returned" in foundation
    )
    assert "**Continue with {CACHED_ACCOUNT}?**" in foundation
    assert (
        "present **Continue** and **Use a different user** as the standard choices"
        in foundation
    )
    assert (
        "present **Continue**, **Use a different user**, and **Help me decide**"
        not in foundation
    )
    assert "When two or more cached accounts are returned" in foundation
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
    assert "**Use the Microsoft account picker** first" in foundation
    assert "followed by every cached sign-in name, then **Help me decide**" in foundation
    assert "For **Help me decide** on the multiple-account surface" in foundation
    assert "separate from GitHub/Copilot sign-in" in foundation
    assert "custom entry disabled inside the control" in normalized_foundation
    assert (
        "When no cached account exists, or the maker selects **Use a different "
        "user** or **Use the Microsoft account picker**, omit `--account`"
    ) in normalized_foundation
    assert (
        "append `--select-account` only to the first read-only command that can authenticate"
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
    assert "create or set up a fresh agent" in (
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
    assert "Only after the maker selects a **Create {friendly agent name} {version}**" in normalized
    assert "exactly one create attempt" not in normalized
    assert "The command ends after this one attempt" not in normalized
    assert "Do not invoke create concurrently or automatically" in normalized
    assert "diagnostic evidence only" in normalized
    assert "do not explain those internal version concepts to the maker" in normalized
    assert "The agent was created." in text
    assert "Preparing its local authoring workspace..." not in text
    assert (
        "{COPILOT_STUDIO_ORIGIN}/environments/{ENVIRONMENT_ID}/copilots/"
        "{RETURNED_AGENT_ID}/details?agentBackend=cosmos"
    ) in text
    created_agent_link = (
        "> **Open [{USER_FRIENDLY_AGENT_NAME}]({ACTUAL_AGENT_URL}) "
        "in Classic Copilot Studio.**"
    )
    assert created_agent_link in text
    assert "{PRODUCT_COUNT} agent templates are available" in text
    assert "Loading available agent templates for **{environment name}**..." in text
    assert "no agent templates are currently available in the selected environment" in (
        normalized
    )
    assert normalized.count("**Retry setup with another target**") == 2
    assert "agent templates could not be loaded and nothing was changed" in (
        normalized
    )
    assert text.index("Loading available agent templates for **{environment name}**...") < (
        text.index("{PRODUCT_COUNT} agent templates are available")
    )
    assert "use this fixed opening as the first agent-setup surface" in (
        normalized
    )
    assert "then begin **Create**" in normalized
    assert (
        "When `DA_AGENT_ROUTE_JSON:` reports `routeStatus: resolved`, "
        "`alm.isEnrolled: true`, and `realm: dev`, continue directly to **Attach** "
        "without an enrollment write."
    ) in normalized
    assert "python scripts/setup_existing_da.py inspect-agent" in text
    assert text.index("setup_existing_da.py inspect-agent") < text.index(
        "setup_existing_da.py attach"
    )
    assert ("Do not invoke `ensure-alm` directly from this file.") in normalized
    assert "single presentation unit defined in `da-existing-dev.md`" in normalized
    assert "Complete every check whose prerequisites remain available" in normalized
    assert "state the observed blocker and supported recovery" in normalized
    assert "application lifecycle management" not in normalized
    assert "**Prepare for local editing**" not in text
    assert "**Not now**" not in text
    assert text.count(created_agent_link) == 1
    assert "never show internal step IDs or raw technical output" in normalized
    assert "workspace is not ready to connect" in existing_dev
    assert "**Retry workspace materialization**" in existing_dev
    assert "Do not offer reset for an unrelated service or projection failure" in (
        " ".join(existing_dev.split())
    )
    assert "New ESS agent" in text
    assert "content was synced to your local workspace" in existing_dev
    assert "Your local workspace is ready for authoring" in existing_dev
    assert "[{USER_FRIENDLY_AGENT_NAME}]({ACTUAL_AGENT_URL})" in existing_dev
    assert (
        "> **Open [{USER_FRIENDLY_AGENT_NAME}]({ACTUAL_AGENT_URL}) "
        "in Classic Copilot Studio.**"
    ) in existing_dev
    assert (
        "For listing newer declarative agents, use the Classic experience."
        in existing_dev
    )
    assert "**Open classic experience**" in existing_dev
    assert "**Skip feedback**" in existing_dev
    assert "**Open in a new tab**" in existing_dev
    assert "### Runtime readiness" in existing_dev
    assert (
        "factual workspace and runtime-readiness report from `da-existing-dev.md`"
        in normalized
    )
    assert "Do not infer persona, product, target, or progress" in normalized
    assert "Never invoke" in normalized and "/connect" in normalized
    assert "Do not publish, remove, or replace components" in normalized
    assert "Publishing is outside foundation setup and is not remediation" in normalized
    assert "including when `connectReady` is false" in normalized
    assert "setup_setup_mos_starter.py" not in text
    assert "setup_mos_starter.py resolve" not in text
    assert "setup_mos_starter.py status" not in text
    assert "DA_EXISTING_DEV_DIAGNOSTIC_JSON:" not in text
    assert len(text.splitlines()) < 300
    assert "--client-request-id" in text
    assert "one picker option per exact ID" in normalized
    assert "Do not describe agent templates as remaining, uninstalled, or eligible" in normalized
    assert "setup_existing_da.py list-agents" in text
    assert "DA_AGENT_LIST_JSON:" in text
    assert "da_product_registry.py observe" in text
    assert "DA_PRODUCT_OBSERVATION_JSON:" in text
    assert "setup_mos_starter.py validate-agent" not in text
    assert "setup_existing_da.py validate-agent" in text
    assert "workspace-local observation becomes the preferred mapping" in normalized
    assert '--environment-id "{ENVIRONMENT_ID}"' in text
    assert '--ring "{RING}"' in text
    assert "installed: true" in text
    assert "`minimalBots.response` is the untouched MinimalBot-card array" in text
    assert "`copilotStudioAgents.response` is the untouched array" in text
    assert "Match only MinimalBot `botId` to MakerOperations `cdsBotId`" in text
    assert "**Use {friendly agent name} — Already installed**" in text
    assert (
        "Only an exact candidate whose product identity and editable Dev route were established"
        in normalized
    )
    assert "historical evidence, not a sticky installed label" in normalized
    assert "current installation could not be established" in normalized
    assert "Installation status unconfirmed" in text
    assert "Installation status unavailable" in text
    assert (
        "**Create {friendly agent name} {version} — Previous create conflict**"
        in text
    )
    assert "**How would you like to continue?**" in text
    assert (
        "**Create anyway**, **Use a Microsoft Copilot Studio URL**, "
        "**I have another login we can use to try connecting to this agent**, "
        "and **Go back**"
    ) in text
    assert (
        "**Create anyway**, **Use a Microsoft Copilot Studio URL**, "
        "**Try with a different user**, and **Go back**"
    ) in text
    assert (
        "retains the selected package facts and proceeds through **Create**"
        in normalized
    )
    assert "A selected Prod identity can still follow" in normalized
    assert "Prod-to-Dev route" in text
    assert "setup_mos_starter.py create collision" in text
    assert "Join catalog rows only to exact candidates" in normalized
    assert "Do not interpret any failed operation as an empty environment" in normalized
    assert "retain candidates from the successful endpoint" in normalized
    assert "present **Use this agent** and **Go back** as the standard choices" in text
    assert "Do not add a separate choose-from-existing step" in text
    assert "Never offer unrelated listed agents" in text
    assert "render every agent identity option as its exact service-provided display name only" in text
    assert "never display an ID, schema, product key" in text
    assert "**schema will be verified** annotation" in text
    assert "Choose an existing agent in this environment" not in text
    assert "show the returned names and schemas" not in text
    assert "Choose a different agent template" not in text
    assert "then render the complete action-oriented catalog" in normalized
    assert "uses a new client request UUID" in normalized
    collision_choices = text[
        text.index("When the annotations report `outcome: collision`") :
    ]
    collision_choices = collision_choices[
        : collision_choices.index("## Prepare the authoring route")
    ]
    assert "**Go back**" in collision_choices
    assert "**Cancel setup**" not in collision_choices
    assert "disable custom entry inside the control" in " ".join(
        collision_choices.split()
    )
    assert "never repeats the collided request" in " ".join(collision_choices.split())
    assert (
        "record that mapping and its environment-scoped installed state immediately"
        in " ".join(collision_choices.split())
    )
    assert "does not prove that a selectable agent is visible" in " ".join(
        collision_choices.split()
    )
    assert "does not identify the corresponding agent" in reference
    assert "One exact match can be offered directly as **Use this agent**" in reference
    assert "Unrelated agents are never offered" in reference
    assert (
        "no agent ID, schema, product key, or verification annotation is maker-facing"
        in reference
    )
    assert "under `minimalBots` and `copilotStudioAgents`" in reference
    assert (
        "does not merge, deduplicate, classify, enrich, or directly inspect"
        in reference
    )
    assert (
        "Endpoint errors or unresolved candidates preserve installation uncertainty"
        in reference
    )
    assert (
        "historical observations do not make **Already installed** sticky" in reference
    )
    assert "maker-confirmed create is submitted to the service" in reference
    assert "success or conflict response is authoritative" in reference

    assert "render only one picker option per exact ID" in existing_dev
    assert "continues through `da-prod-to-dev.md`" in existing_dev
    assert "do not validate or attach the Prod ID as though it were Dev" in existing_dev

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
    assert (
        "Do not say that setup will switch, reset, reuse, archive, or open a "
        "workspace before the corresponding choice and confirmation."
    ) in normalized
    assert (
        "compare it with the retained workspace environment before any ALM "
        "enrollment, import, attachment, reset, or other remote or local mutation"
    ) in normalized
    assert "Do not run attachment to discover this conflict" in normalized
    assert (
        text.index("Whenever the current request resolves a target environment")
        < text.index(
            "When the maker supplies a Microsoft Copilot Studio URL that identifies"
        )
    )
    assert (
        "For **Go back**, make no changes and return to the choice surface that "
        "offered **Reset and use this workspace**."
    ) in normalized
    reset_confirmation = text[
        text.index("For **Reset and use this workspace**") : text.index(
            "For **Switch to another configured agent**"
        )
    ]
    assert "**Cancel setup**" not in reset_confirmation


def test_foundation_separates_incomplete_and_ready_completion_choices() -> None:
    text = _FOUNDATION.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    for choice in (
        "Exit setup",
        "Redo setup for this agent",
        "Switch to another configured agent",
        "Set up another agent in this environment",
        "Reset and use this workspace",
        "Create and open a new workspace",
        "Cancel setup",
        "Add or change an integration{CONNECT_RECOMMENDATION_SUFFIX}",
    ):
        assert f"**{choice}**" in text
    assert "**Exit setup (Recommended)**" not in text
    completion_choices = text.split(
        "The final handoff is the detailed setup report", 1
    )[1].split("## Start", 1)[0]
    incomplete_choices = completion_choices.split(
        "When `connectReady` is false or absent", 1
    )[1].split("When `connectReady` is true", 1)[0]
    normalized_incomplete = " ".join(incomplete_choices.split())
    assert "setup is not complete" in normalized_incomplete
    assert (
        "append **(Recommended)** to exactly one action" in normalized_incomplete
    )
    assert (
        "render every applicable remediation, recheck, and cleanup action in one "
        "host interactive single-selection control"
        in normalized_incomplete
    )
    assert (
        "After adding every static and dynamic action, append **Exit setup** as "
        "the final secondary choice"
        in normalized_incomplete
    )
    assert "disable custom entry" in normalized_incomplete
    assert "Do not render the ready completion choices" in normalized_incomplete
    assert "durable completion snapshot" in normalized_incomplete
    assert "general post-setup capabilities" in normalized_incomplete
    assert (
        "explicit `/connect`-after-materialization exception"
        in normalized_incomplete
    )
    assert "- **Reset and use this workspace**" not in completion_choices
    assert "- **Create and open a new workspace**" not in completion_choices
    assert "- **Continue customizing this agent**" not in completion_choices
    assert "- **Finish for now**" not in completion_choices
    assert (
        "Set `{CONNECT_RECOMMENDATION_SUFFIX}` to ` (Recommended)` only when "
        "**Add or change an integration** is recommended"
    ) in normalized
    normalized_completion_choices = " ".join(completion_choices.split())
    ready_choice_list = normalized_completion_choices.split(
        "Then present these choices in one host interactive single-selection control:",
        1,
    )[1].split("Set `{CONNECT_RECOMMENDATION_SUFFIX}`", 1)[0]
    assert "- **Configure landing page" not in ready_choice_list
    assert ready_choice_list.index(
        "- **Add or change an integration{CONNECT_RECOMMENDATION_SUFFIX}**"
    ) < ready_choice_list.index("- **Switch to another configured agent**")
    assert ready_choice_list.index(
        "- **Switch to another configured agent**"
    ) < ready_choice_list.index("- **Set up another agent in this environment**")
    assert ready_choice_list.index(
        "- **Set up another agent in this environment**"
    ) < ready_choice_list.index("- **Exit setup**")
    assert (
        "always render **Exit setup** after every static and dynamic choice"
        in normalized
    )
    assert (
        "inserting these choices immediately before **Exit setup**" in normalized
    )
    assert (
        "when authoritative product-specific evidence shows that an applicable "
        "supported integration is configured, render the setup terminal choice "
        "control without a recommended action"
    ) in normalized
    assert (
        "Do not treat **Connections: Not required**, an aggregate diagnostic row, "
        "or the presence or absence of native logical connector references as "
        "authoritative evidence that an applicable integration is configured."
    ) in normalized
    assert (
        "The integration recommendation reflects the absence of completion "
        "evidence; it does not claim that an integration is missing or broken."
    ) in normalized
    assert (
        "I recommend Add or change an integration so this agent can communicate "
        "with your HR or IT systems. Setup did not find authoritative evidence "
        "that an applicable integration is configured."
    ) in normalized
    assert (
        "Setup is complete. You asked to configure the landing page next, so I'll "
        "continue there."
    ) in normalized
    assert "Do not render the setup terminal choice control." in normalized
    assert "The {agent display name} agent is now active." in completion_choices
    assert "Here's your ESS agent setup:" in completion_choices
    assert completion_choices.count(
        "> **Open [{USER_FRIENDLY_AGENT_NAME}]({ACTUAL_AGENT_URL}) "
        "in Classic Copilot Studio.**"
    ) == 1
    assert "### Runtime readiness" in completion_choices
    assert "**{overall readiness status}**" in completion_choices
    assert "Next steps:" in completion_choices
    assert (
        "Build `{POST_SETUP_COMMAND_REMINDERS}` from the same recommendation and "
        "evidence used for the ready choice control."
        in normalized
    )
    assert (
        "Render exactly one of these non-interactive command lists, with the "
        "recommended command first"
        in normalized
    )
    assert (
        "- Run `/connect` **(Recommended)** to add or change an integration so "
        "this agent can communicate with your HR or IT systems. Setup did not "
        "find authoritative evidence that an applicable integration is configured."
    ) in normalized
    assert (
        "- Run `/landing-page` **(Recommended)** to configure the branding and "
        "content employees see. An applicable integration is already configured, "
        "so this is the next useful customization step."
    ) in normalized
    assert (
        "- Run `/connect` **(Recommended)** to add or change an integration. This "
        "matches what you asked to do next, and integrations let this agent "
        "communicate with your HR or IT systems."
    ) in normalized
    assert "These reminders are text, not another choice control." in normalized
    assert "Do not render the case labels above." in normalized
    assert text.count("\n{POST_SETUP_COMMAND_REMINDERS}\n") == 2
    assert "{SUPPORTED_INTEGRATION_SHORTCUTS}" in completion_choices
    assert text.count("- Type `/menu` to see all available capabilities.") == 3
    assert "{APPLICABLE_LOCAL_CLEANUP_BLOCKS}" in completion_choices
    assert "body of every unresolved local-cleanup block" in normalized
    assert (
        "Omit each block's outer `**Message:**` and `**End message.**` markers" in text
    )
    assert "Omit the placeholder when no block applies" in normalized
    assert (
        "Build `{SUPPORTED_INTEGRATION_SHORTCUTS}` only from authoritative product identity"
        in normalized
    )
    assert "only for a supported HR architecture" in normalized
    assert "Render no shortcut lines when product identity is unresolved" in normalized
    assert "What would you like to customize?" not in completion_choices
    assert "**Create a topic**" not in completion_choices
    assert "Then end the request." in completion_choices
    assert "Create a new workspace without opening it" not in text
    assert "setup_existing_da.py select-agent" in text
    assert "one Power Platform environment" in normalized
    assert "multiple ESS Dev agents" in normalized
    assert "one active agent" in normalized
    incomplete_reentry = text.split(
        "**{agent display name}** is the active agent in this workspace", 1
    )[1].split("For **Redo setup for this agent**", 1)[0]
    normalized_incomplete_reentry = " ".join(incomplete_reentry.split())
    assert "one host interactive\nsingle-selection control" in incomplete_reentry
    for earlier, later in (
        ("- **Resume setup for this agent**", "- **Switch to another configured agent**"),
        (
            "- **Switch to another configured agent**",
            "- **Set up another agent in this environment**",
        ),
        (
            "- **Set up another agent in this environment**",
            "- **Reset and use this workspace**",
        ),
        (
            "- **Reset and use this workspace**",
            "- **Create and open a new workspace**",
        ),
        ("- **Create and open a new workspace**", "- **What does setup do?**"),
        ("- **What does setup do?**", "- **Exit setup**"),
    ):
        assert incomplete_reentry.index(earlier) < incomplete_reentry.index(later)
    assert "keep **Exit setup** as the final choice" in normalized_incomplete_reentry


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
    assert "Do not describe an authorization wait as service processing" in normalized


def test_foundation_reuses_invocation_evidence() -> None:
    text = _FOUNDATION.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert (
        "Read `.local/setup/config.json` and `.local/config.json` once per setup "
        "invocation"
    ) in normalized
    assert "reusing content already read by the parent prompt" in normalized
    assert "Reread a source only after an operation in this invocation changes" in (
        normalized
    )
    assert (
        "Do not rerun inventory, reconciliation, or inspection merely because a "
        "later branch needs a value already retained"
    ) in normalized
    assert "keep the explicit post-enrollment reinspection" in normalized


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
    assert "The final handoff is the detailed setup report" in normalized
    assert "When `connectReady` is false or absent, setup is not complete" in normalized
    assert (
        "When `connectReady` is true, setup is complete" in normalized
    )
    assert (
        "**Exit setup** acknowledges the displayed results and renders a durable "
        "completion snapshot as the final chat message"
        in normalized
    )
    assert (
        "These are the readiness results you acknowledged when you finished "
        "setup. No checks were rerun."
    ) in normalized
    assert (
        "first decision surface rather than rendering the durable completion snapshot"
        in (normalized)
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
    assert (
        "Continue when the maker selects a standard choice or supplies a clear "
        "setup intent in chat; all standard choices begin unselected"
    ) in normalized
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
    assert normalized.index("What would you like to set up in") < normalized.index(
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
    assert (
        "factual workspace and runtime-readiness report from `da-existing-dev.md`"
        in normalized
    )
    assert "Supplied native agent package" in text
    assert "another readiness" not in text.casefold()


def test_alm_import_collision_and_retry_require_separate_choices() -> None:
    text = _DA_ALM_IMPORT.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    for choice in (
        "Choose an existing agent in this environment",
        "Replace an existing agent with this package",
        "Continue replacement",
        "Go back",
        "Retry import",
        "Stop without retrying",
    ):
        assert choice in text
    assert "**Cancel setup**" not in text
    assert "Choose the existing agent without replacement" not in text
    assert "Do not preselect a choice or recommend replacement" in normalized
    assert "setup_existing_da.py list-agents" in text
    assert "Never preselect or recommend **Continue replacement**" in text
    replacement = text.split("Before replacement, validate", 1)[1].split(
        "After a successful replacement",
        1,
    )[0]
    replacement_commands = replacement.split("```text")[1:]
    assert len(replacement_commands) == 2
    for command_block in replacement_commands:
        command = command_block.split("```", 1)[0]
        assert '--account "{SETUP_ACCOUNT}"' in command
    assert (
        "For **Go back**, make no changes and return to **Handle a collision**."
        in normalized
    )
    assert (
        "Reuse the latest successful visible-agent list instead of rerunning "
        "`list-agents` solely because the maker went back."
    ) in normalized
    assert (
        "Clear the replacement intent and selected replacement candidate" in normalized
    )
    assert (
        "Clear package-import and replacement intent, but preserve the import "
        "receipt and collision evidence."
    ) in normalized
    assert "if no exact identity can be proven" in normalized
    assert "--client-request-id" in text
    assert (
        "let the service return conflict if the earlier create succeeded" in normalized
    )
    assert "only after the maker selects **Retry import**" in normalized
    initial_import = text.split("## Preflight and create", 1)[1].split(
        "## Complete workspace setup",
        1,
    )[0]
    initial_command = initial_import.split("```text", 1)[1].split("```", 1)[0]
    assert "--client-request-id" not in initial_command
    retry_section = text.split(
        "Use `--retry-safe-failure` only after the maker selects **Retry import**.",
        1,
    )[1].split("Never remove or edit import records", 1)[0]
    assert "--retry-safe-failure" in retry_section
    assert "--client-request-id" not in retry_section
    assert "reserved for the separately approved create-only recovery" in normalized


def test_foundation_typed_intent_preserves_mutation_confirmations() -> None:
    text = _FOUNDATION.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "Typed intent may select only a documented setup route" in normalized
    assert "bounded read-only recovery" in normalized
    assert "never authorizes an unlisted mutation" in normalized
    assert "replaces an explicit confirmation" in normalized
    for action in ("create", "import", "replacement", "reset", "cleanup"):
        assert action in normalized


def test_durable_snapshot_inserts_message_bodies_without_nested_markers() -> None:
    text = _FOUNDATION.read_text(encoding="utf-8")
    normalized = " ".join(text.split())
    durable_start = re.search(
        r"After the maker selects \*\*Exit\s+setup\*\*, show:",
        text,
    )
    assert durable_start is not None
    durable = text[durable_start.end() :].split(
        "Then end the request.",
        1,
    )[0]

    assert "{APPLICABLE_LOCAL_CLEANUP_BLOCKS}" in durable
    assert "body of every unresolved local-cleanup block" in normalized
    assert (
        "Omit each block's outer `**Message:**` and `**End message.**` markers" in text
    )


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
    assert "Interpret the two sources independently" in text
    assert "render only one picker option per exact ID" in text
    assert (
        "When the matching MakerOperations BotEntity has a non-empty exact `schemaName`"
        in text
    )
    assert "When no matching MakerOperations BotEntity supplies a usable schema" in text
    assert "Run both exact identity probes" in text
    assert (
        "No agents created by this Microsoft login were returned for this environment"
        in text
    )
    assert (
        "When one endpoint reports an error and the other succeeds with no identities"
        in text
    )
    assert "including its **Use a Microsoft Copilot Studio URL** choice" in text
    assert "before authentication or remote agent validation" in text
    assert "Do not run `validate-agent` immediately before `attach`" in text
    assert "Your local workspace is ready for authoring." in text
    assert (
        "> **Open [{USER_FRIENDLY_AGENT_NAME}]({ACTUAL_AGENT_URL}) "
        "in Classic Copilot Studio.**"
    ) in text
    assert "For listing newer declarative agents, use the Classic experience." in text
    assert "open the **…** menu beside your profile" in text
    assert "select **Open classic experience**" in text
    assert "select **Skip feedback** or **Open in a new tab**" in text
    assert "| Item" not in text
    assert "| Starting point" not in text
    assert (
        "{COPILOT_STUDIO_ORIGIN}/environments/{ENVIRONMENT_ID}/copilots/"
        "{AGENT_ID}/details?agentBackend=cosmos"
    ) in text
    assert "/bots/{AGENT_ID}/overview" not in text
    assert "Never link to the environment's agent-list page" in text
    assert "use the authoritative backend display name unchanged" in normalized
    assert "### Runtime readiness" in text
    assert "**Runtime readiness:**" in text
    agent_link = (
        "> **Open [{USER_FRIENDLY_AGENT_NAME}]({ACTUAL_AGENT_URL}) "
        "in Classic Copilot Studio.**"
    )
    assert text.count(agent_link) == 1
    progress_line = (
        "**Runtime readiness:** Agent access {agent access progress status} · "
        "Capacity {environment capacity progress status} · Connections "
        "{connections progress status} · Content {agent content progress status}"
    )
    assert progress_line in text
    assert (
        progress_line
        + "\n\n**{readiness progress status}: {readiness progress summary}**"
        in text
    )
    assert "compact two-line snapshot" in text
    assert "whenever one of its four check statuses changes" in normalized
    assert "**🔄 Checking** only for the operation that will run next" in text
    assert "**⬜ Pending** for an applicable check that has not run" in text
    assert "**🔄 {resolved count} of 4 resolved**" in text
    assert "**⛔ Waiting for action**" in text
    assert "Do not calculate or display the final **Overall** verdict" in text
    readiness_table = "\n".join(
        (
            "| Check                | Status                         | Details                                 |",
            "| -------------------- | ------------------------------ | --------------------------------------- |",
            "| Agent access         | {agent access status}          | {agent access evidence summary}         |",
            "| Environment capacity | {environment capacity status}  | {environment capacity evidence summary} |",
            "| Connections          | {connections status}           | {connections evidence summary}          |",
            "| Agent content        | {agent content status}         | {agent content evidence summary}        |",
            "| **Overall**          | **{overall readiness status}** | **{maker-facing readiness summary}**    |",
        )
    )
    assert readiness_table in text
    assert "**✅ Setup complete**" in text
    assert "**⚠️ Setup needs attention**" in text
    assert "Foundation ready" not in text
    assert "Foundation needs attention" not in text
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
    agent_link = (
        "> **Open [{USER_FRIENDLY_AGENT_NAME}]({ACTUAL_AGENT_URL}) "
        "in Classic Copilot Studio.**"
    )

    assert "`connectionStatus: workspace-ready`" in text
    assert "`connectReady: true`" in text
    assert (
        "Canonical setup state is authoritative for each agent's setup progress and readiness"
        in normalized
    )
    assert (
        "`state`, `connectReady`, `activeStep`, and `failureCauses` are the setup-readiness evidence"
        in normalized
    )
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
        "do not claim that the registry declares no requirement for that product"
    ) in normalized
    assert (
        "run the three setup-readiness FlightChecks and the broad connection diagnostic"
    ) in normalized
    assert "present all four together" in normalized
    assert (
        "Attempt every available check before producing the final runtime-readiness table"
        in normalized
    )
    assert "Render both even when `connectReady` is false" in normalized
    for readiness_status in (
        "**✅ Ready**",
        "**⚠️ Ready with limitation**",
        "**➖ Not required**",
        "**⛔ Action required**",
        "**⚠️ Skipped by administrator attestation**",
        "**⚠️ Check unavailable**",
        "**⬜ Not checked**",
    ):
        assert readiness_status in text
    assert "### Capacity follow-up" in text
    assert "local timezone of the machine running setup" in normalized
    assert "`YYYY-MM-DDTHH:mm:ss`" in text
    assert "`2026-10-03T01:43:19`" in text
    assert "Truncate fractional seconds; do not round" in normalized
    assert "do not rewrite persisted evidence" in normalized
    assert "omit the displayed time rather than inferring one" in normalized
    assert "Times are shown in your local timezone" not in text
    assert (
        "We weren’t able to automatically verify capacity for this environment."
    ) in text
    assert "Your agent and local authoring workspace are already available." in text
    assert "#### Copilot Studio message capacity" in text
    assert "In the left navigation, select **Licensing**." in text
    assert "Under **Products**, select **Copilot Studio**." in text
    assert "Select **Manage Copilot Credits**." in text
    capacity_section = text.split("### Capacity follow-up", 1)[1].split(
        "**End message.**",
        1,
    )[0]
    assert agent_link not in capacity_section
    assert (
        "Setup requires a nonzero allocation for an automatic pass; for initial use, we recommend "
        "allocating **500 or more Copilot Credits**."
    ) in normalized
    assert (
        "After a Power Platform administrator verifies or changes the allocation, use "
        "**Check again**"
    ) in normalized
    assert (
        "| **Power Platform administrator** | Review or change capacity, or consent to overriding this capacity check | Required for administrator-attested skip |"
        in text
    )
    assert "> ⚠️ **Administrator consent required**" in text
    assert (
        "a **Power Platform administrator is present and has consented to override this capacity check**"
        in normalized
    )
    assert "The original unavailable or denied result remains the recorded evidence." in (
        normalized
    )
    assert "Complete this check to finish foundation readiness" not in text
    assert "using `ring_from_environment_host()`" in normalized
    assert "do not assume production" in normalized
    assert '--ring "{CONFIRMED_RING}"' in text
    assert "--administrator-attested-skip" in text
    assert "--manual-attested" not in text
    assert "--manual-overridden" not in text
    assert "requires an observed allocation greater than zero" in normalized
    assert (
        "Apply the first `Warning` without a skip flag to record that zero allocation"
        in normalized
    )
    assert "the recheck still found 0 allocated credits" in normalized
    assert (
        "Never treat the maker's statement that capacity was allocated as verification"
        in normalized
    )
    assert "Continue with administrator-attested skip" in text
    assert (
        "A Power Platform administrator was present and consented to override this capacity check"
        in normalized
    )
    assert "The final readiness table remains available" in normalized
    assert (
        "`Failed` and `Error` are not eligible for administrator-attested skip"
        in normalized
    )
    assert "Agent content is present in your local workspace." in text
    assert "When it is false after materialization" in normalized
    assert (
        "local authoring is ready while the setup-owned prerequisites remain"
        in normalized
    )
    assert "### Connection follow-up" in text
    connection_section = text.split("### Connection follow-up", 1)[1].split(
        "**End message.**",
        1,
    )[0]
    assert agent_link not in connection_section
    assert "#### Microsoft 365 Self-Help" in text
    assert "Select **New connection**" in text
    assert "ask me to check it again" in text
    refresh_section = text.split("## Refresh changed content", 1)[1]
    assert agent_link not in refresh_section
    assert "Complete this connection to finish foundation readiness" in normalized
    assert "Do not add another completion choice" in normalized
    assert "a factual handoff, not another readiness gate" in normalized
    assert "changing canonical state conversationally" in normalized
    assert "Do not infer the realm from the URL" in normalized
    assert "from main" not in text
    assert "workstream" not in text.casefold()
    assert "later workstreams" not in text.casefold()
    assert (
        "when the parent setup router already inspected the supplied or recorded agent"
        in (normalized)
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
    assert (
        "successful internal work continues to the next defined maker interaction"
        in (normalized)
    )
    assert (
        "a blocked operation states the observed blocker and one supported recovery"
        in (normalized)
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


def test_da_topic_authoring_is_blocked_before_local_changes() -> None:
    instructions = _INSTRUCTIONS.read_text(encoding="utf-8")
    normalized_instructions = " ".join(instructions.split())
    create = (_PROMPTS / "create.prompt.md").read_text(encoding="utf-8")
    update = (_PROMPTS / "update.prompt.md").read_text(encoding="utf-8")
    menu = (_PROMPTS / "menu.prompt.md").read_text(encoding="utf-8")

    assert (
        "Topic creation is not yet available in this release. No local or "
        "remote files have been changed."
    ) in " ".join(create.split())
    assert (
        "Topic updates are not yet available in this release. No local or "
        "remote files have been changed."
    ) in " ".join(update.split())
    assert "Topic creation is not yet available in this release." in create
    assert "Topic updates are not yet available in this release." in update
    assert "Topic creation is not available in this release." not in create
    assert "Topic updates are not available in this release." not in update
    for prompt in (create, update):
        normalized = " ".join(prompt.split())
        assert "every explicit or implicit request" in normalized.casefold()
        assert "topic intent, whether explicit or implicit, always wins" in normalized
        assert "before reading a topic-authoring skill" in normalized
        assert "or direct file edits" in normalized
        assert "Render only that message" in normalized
        assert "do not add product-specific capability claims" in normalized
        assert "or other alternatives" in normalized
        assert "or a follow-up question" in normalized
        assert "tooling that remains visible in this repository is legacy" in normalized
        assert "It has not been cleared for use with DA" in normalized
        assert "must not be invoked for direct user requests" in normalized
    assert (
        "Create a topic | Stop: topic creation is not yet available"
        in normalized_instructions
    )
    assert (
        "Update/modify a topic | Stop: topic updates are not yet available"
        in normalized_instructions
    )
    assert "Create a workflow or evaluation test set locally" in menu
    assert "Update a workflow or evaluation test set locally" in menu
    assert "Create a topic, workflow" not in menu
    assert "Update a topic, workflow" not in menu


def test_da_workflow_local_authoring_remains_available() -> None:
    for name in ("create.prompt.md", "update.prompt.md"):
        prompt = (_PROMPTS / name).read_text(encoding="utf-8")
        normalized = " ".join(prompt.split()).casefold()
        assert "workflow" in normalized, name
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
    skill = (_SOLUTION / "src" / "skills" / "flightcheck" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "flightCheckOnly: true" in instructions
    assert "scope selection supported by the active configuration" in normalized
    assert "supported scopes are `full`, `environment`" in skill
    assert "scope fixed to `local`" not in normalized
