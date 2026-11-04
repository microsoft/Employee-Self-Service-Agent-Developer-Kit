# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

import json
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_SOLUTION = _ROOT / "solutions" / "ess-maker-skills"


def test_test_and_prod_realm_surface_is_not_advertised() -> None:
    chooser = (
        _SOLUTION
        / "src"
        / "skills"
        / "connect"
        / "servicenow-da"
        / "SKILL.md"
    ).read_text(encoding="utf-8")
    for parked_command in (
        "validation-realm-handoff",
        "validate-realm",
        "record-realm-deployment",
        "record-realm-runtime-plan",
        "record-realm-binding",
        "record-realm-test",
    ):
        assert parked_command not in chooser


def test_connect_reuses_setup_python_launcher_without_creating_environment() -> None:
    prompt = " ".join(
        (_SOLUTION / ".github" / "prompts" / "connect.prompt.md")
        .read_text(encoding="utf-8")
        .split()
    )
    runner = " ".join(
        (
            _SOLUTION
            / "src"
            / "skills"
            / "connect"
            / "shared"
            / "lifecycle-runner.md"
        )
        .read_text(encoding="utf-8")
        .split()
    )

    assert "**Python runtime.**" in prompt
    assert "`configurePythonEnvironment`" in prompt
    assert "reuse that exact launcher" in prompt
    assert prompt.index("**Python runtime.**") < prompt.index("python scripts/")
    assert "**Python runtime:**" in runner
    assert "never create an environment" in runner


def test_servicenow_connect_entry_files_gate_progress_rendering() -> None:
    skills = _SOLUTION / "src" / "skills" / "connect"
    gated_files = (
        _SOLUTION / ".github" / "prompts" / "connect.prompt.md",
        skills / "servicenow" / "entry.md",
        skills / "servicenow-da-hrsd" / "SKILL.md",
        skills / "servicenow-da-itsm" / "SKILL.md",
        skills / "shared" / "lifecycle-runner.md",
    )
    for path in gated_files:
        text = " ".join(path.read_text(encoding="utf-8").split())
        assert "**STOP — render before acting.**" in text, path.name
        assert (
            "your very next assistant message — before any other tool call — "
            "must contain `renderBlock.text` verbatim"
        ) in text, path.name
        assert "`resume-handoff` or `record-checkpoint-results`" in text, (
            path.name
        )
        assert "the only renderable field" in text, path.name
        assert "never add a Check/Status table" in text, path.name
        assert "`progress.checklistText`" not in text, path.name
        assert "`progress.currentPhase.startText`" not in text, path.name
        assert 'write "render the plan" instead' in text, path.name


def test_servicenow_connect_docs_suppress_flightcheck_health_table() -> None:
    skills = _SOLUTION / "src" / "skills" / "connect"
    runner = " ".join(
        (skills / "shared" / "lifecycle-runner.md")
        .read_text(encoding="utf-8")
        .split()
    )
    updater = " ".join(
        (skills / "shared" / "checklist-updater.md")
        .read_text(encoding="utf-8")
        .replace("> ", "")
        .split()
    )
    prompt = " ".join(
        (_SOLUTION / ".github" / "prompts" / "connect.prompt.md")
        .read_text(encoding="utf-8")
        .split()
    )

    assert "**ServiceNow exception — no FlightCheck health display.**" in runner
    assert "never render a `| Check | Status |` table" in runner
    assert "Other providers keep U.0/U.0a unchanged." in runner
    assert "**ServiceNow exception.**" in updater
    assert "never render the U.0 table" in updater
    assert "never render a FlightCheck-style `| Check | Status |` table" in prompt

    skills = _SOLUTION / "src" / "skills" / "connect"
    entry_files = (
        _SOLUTION / ".github" / "prompts" / "connect.prompt.md",
        skills / "servicenow" / "entry.md",
        skills / "servicenow-da-hrsd" / "SKILL.md",
        skills / "servicenow-da-itsm" / "SKILL.md",
    )
    for path in entry_files:
        text = " ".join(path.read_text(encoding="utf-8").split())
        assert "**Hard rules.** Read `src/skills/connect/shared/lifecycle-runner.md` before the first action." in text, path.name
        assert "emit `renderBlock.text` verbatim as an assistant message" in text, path.name
        assert "Never edit `lifecycle.json` by hand" in text, path.name
        assert "`record-checkpoint-results`" in text, path.name
        assert (
            "launcher resolved by `/setup` (`py -3`, `python3`, then `python`), "
            "never assuming bare `python`"
        ) in text, path.name

    runner = " ".join(
        (skills / "shared" / "lifecycle-runner.md")
        .read_text(encoding="utf-8")
        .split()
    )
    assert "emit `renderBlock.text` verbatim" in runner
    assert "never assuming bare `python`" in runner
    assert "**Provider-recorded results.**" in runner
    assert "- `stop-tampered` —" in runner
    assert "`agentRules` array" in runner
    assert "record-checkpoint-results --phase {PHASE_ID}" in runner
    for provider in ("servicenow-da-hrsd", "servicenow-da-itsm"):
        contract = json.loads(
            (skills / provider / "contract.json").read_text(encoding="utf-8")
        )
        assert contract["checkpointRecording"] == "provider-command-v1"


def test_da_servicenow_connect_routes_to_agent_chooser() -> None:
    prompt = (
        _SOLUTION / ".github" / "prompts" / "connect.prompt.md"
    ).read_text(encoding="utf-8")
    router = (
        _SOLUTION / "src" / "skills" / "connect" / "SKILL.md"
    ).read_text(encoding="utf-8")
    runner = (
        _SOLUTION
        / "src"
        / "skills"
        / "connect"
        / "shared"
        / "lifecycle-runner.md"
    ).read_text(encoding="utf-8")

    assert "src/skills/connect/SKILL.md" in prompt
    assert "Extension setup is not yet available" not in prompt
    normalized_prompt = " ".join(prompt.split())
    assert "`authoring_ready: true`" in prompt
    assert "ignores `connect_ready`" in normalized_prompt
    assert (
        "do not gate ServiceNow on `.local/config.json.activeAgent`"
        in normalized_prompt
    )
    assert "sync-authoring-readiness" in prompt
    assert "agent-chooser" in prompt
    assert "Waiting for maker input" in prompt
    assert "never require the maker to invoke" in prompt
    assert "Fresh ServiceNow execution boundary" in prompt
    assert "resume-handoff" in prompt
    assert "mandatory on every `/connect servicenow` invocation" in prompt
    assert "before any FlightCheck/checkpoint command" in prompt
    assert "validate-realm" not in prompt
    assert '`planReason: "revision-reapproval"`' in prompt
    assert "stateInitializationRequired" in prompt
    assert "must never run\n    first-run initialization" in prompt
    assert '`status: "existing-compatible-state"`' in prompt
    assert "Do not\nreuse previously read lifecycle instructions" in prompt
    assert "question-required" in prompt
    assert "Never fall back to a validate-only sequence" in prompt
    assert "L.2 live re-verification" in prompt
    assert "L.4a role and\nrollback gates" in prompt
    assert "--verified-phase" in prompt
    assert "--executed-action" in prompt
    assert 'checkpoints.decision: "run-exact-commands"' in prompt
    assert "execute each returned\n  `argv` verbatim" in prompt
    assert "never reconstruct the command" in prompt
    assert "do not call the handoff again or ask twice" in prompt
    assert "verified no-op still requires the phase checkpoint" in prompt
    assert "Never report connected from cached state alone" in prompt
    assert "servicenow.phase-progress.v1" in prompt
    assert "renderBlock.text" in prompt
    for removed in (
        "progress.currentPhase.startText",
        "progress.currentPhase.waitingChecklistText",
        "progress.currentPhase.errorChecklistText",
        "transport.ordinaryReply.text",
        "progress.finalText",
    ):
        assert removed not in prompt
    assert "transport.businessGroupAvailability.question" in prompt
    assert "adapt-question" in prompt
    assert "servicenow.ask-user-arguments.v1" in prompt
    assert "askUserArguments" in prompt
    assert "{message, requestedSchema}" in prompt
    assert "`questions: [...]` is internal host output" in prompt
    assert "HR's four or IT's three collaboration groups" in prompt
    assert "Preflight and instance input never ask availability" in prompt
    assert "with `--roles-available yes`" in prompt
    assert "`--business-group-id`" in prompt
    assert "`--availability-context-sha256`" in prompt
    initial_boundary = prompt.split(
        "Parse the returned `servicenow.resume-handoff.v1` object:",
        1,
    )[0]
    assert "--roles-available" not in initial_boundary
    assert "the error `renderBlock.text`" in " ".join(prompt.split())
    assert "Always emit the freshly returned" in " ".join(prompt.split())
    assert "an action receipt" in prompt
    assert "Show a phase as complete only after" in prompt
    assert "ServiceNow phase-progress strings returned" in prompt
    assert "**ServiceNow phase-progress extension:**" in runner
    assert "adapt-question" in runner
    assert "servicenow.ask-user-arguments.v1" in runner
    assert "askUserArguments" in runner
    assert "property `description`" in runner
    assert "`questions: [...]` is internal Agent Host output" in runner
    assert "known defect that exposes" in runner
    assert "Other providers retain this runner's existing output" in runner
    assert "cached `done` phase\ndisplays **Rechecking**" in runner
    assert "Do not inspect `.local/connect/steps.md` before" in prompt
    assert "a DA ServiceNow route starts\nwith its provider lifecycle" in prompt
    chooser = (
        _SOLUTION / "src" / "skills" / "connect" / "servicenow-da" / "SKILL.md"
    ).read_text(encoding="utf-8")
    entry = (
        _SOLUTION / "src" / "skills" / "connect" / "servicenow" / "entry.md"
    ).read_text(encoding="utf-8")
    registration = json.loads(
        (
            _SOLUTION
            / "src"
            / "skills"
            / "connect"
            / "servicenow"
            / "integration.json"
        ).read_text(encoding="utf-8")
    )

    assert registration["availability"] == "available"
    assert registration["entryDoc"] == "entry.md"
    assert "unavailableMessage" not in registration
    assert "snow" in registration["aliases"]
    assert "src/skills/connect/servicenow-da/SKILL.md" in entry
    normalized_entry = " ".join(entry.split())
    assert "does not depend on `.local/config.json.activeAgent`" in (
        normalized_entry
    )
    assert "sync-authoring-readiness" in entry
    assert "do not emit it again here" in normalized_entry
    assert "emit_capability.py" not in entry
    assert "src/skills/connect/servicenow-da-hrsd/SKILL.md" in chooser
    assert "src/skills/connect/servicenow-da-itsm/SKILL.md" in chooser
    assert "Never persist the choice to `.local/config.json`" in chooser

    router = (
        _SOLUTION / "src" / "skills" / "connect" / "SKILL.md"
    ).read_text(encoding="utf-8")
    interactive_router = (
        _SOLUTION / "src" / "skills" / "connect" / "step1.md"
    ).read_text(encoding="utf-8")
    for neutral in (router, interactive_router):
        assert "servicenow" not in neutral.casefold()
    assert "entryDoc" in interactive_router
    assert "{INTEGRATION_ID}" in interactive_router


def test_global_gate_allows_connection_blocked_foundation() -> None:
    instructions = (
        _SOLUTION / ".github" / "copilot-instructions.md"
    ).read_text(encoding="utf-8")

    normalized = " ".join(instructions.split())
    assert "`/connect servicenow` is available" in normalized
    assert "`connect_ready` equal to `true`" in normalized


def test_servicenow_dev_phase_order_and_binding_intros_are_explicit() -> None:
    expected_order_hr = [
        "preflight",
        "plugin-prerequisites",
        "entra-registration",
        "servicenow-oidc",
        "credential",
        "agent-connection",
        "topics",
        "portal-url",
        "test",
    ]
    expected_order_it = [
        phase for phase in expected_order_hr if phase != "plugin-prerequisites"
    ]
    for provider, expected_order in (
        ("servicenow-da-hrsd", expected_order_hr),
        ("servicenow-da-itsm", expected_order_it),
    ):
        root = _SOLUTION / "src" / "skills" / "connect" / provider
        contract = json.loads(
            (root / "contract.json").read_text(encoding="utf-8")
        )
        skill = (root / "SKILL.md").read_text(encoding="utf-8")
        credential = (root / "actions" / "prepare-credential.md").read_text(
            encoding="utf-8"
        )
        normalized_credential = " ".join(credential.split())
        assert [phase["id"] for phase in contract["phases"]] == expected_order
        assert "Connect does not enable ServiceNow topics" in skill
        assert "After binding is confirmed, Connect reads the topic" in skill
        assert "After topic and portal configuration is complete" in skill
        field_table = credential.split(
            "Show the exact field table from the output:",
            1,
        )[1]
        assert field_table.index("**Display name (optional):**") < (
            field_table.index("**Authentication Type:**")
        )
        assert field_table.index("**Authentication Type:**") < (
            field_table.index("**Resource URI:**")
        )
        assert field_table.index("**Resource URI:**") < (
            field_table.index("**Instance Name:**")
        )
        visible_question = credential.split(
            "<!-- visible-handoff-question:v1 -->",
            1,
        )[1]
        auth_index = visible_question.index(
            "Authentication Type: Microsoft Entra ID User Login"
        )
        resource_index = visible_question.index(
            "Resource URI: `{APP_CLIENT_ID}`"
        )
        instance_index = visible_question.index(
            "Instance Name: `{INSTANCE_NAME}`"
        )
        decision_index = visible_question.index(
            "Does the exact ServiceNow connection now show Connected",
        )
        assert auth_index < resource_index < instance_index < decision_index
        required_section = visible_question[:decision_index]
        assert "Display name" not in required_section
        assert "optional guidance and is not a readiness gate" in (
            visible_question
        )
        assert "direct connector-form or connection-detail URL" in credential
        assert "conditional remediation, not an observed current error" in (
            normalized_credential
        )


def test_da_servicenow_skill_uses_shared_lifecycle_and_maker_actions() -> None:
    skill = (
        _SOLUTION
        / "src"
        / "skills"
        / "connect"
        / "servicenow-da-hrsd"
        / "SKILL.md"
    ).read_text(encoding="utf-8")

    assert "connect/shared/lifecycle-runner.md" in skill
    assert 'PROVIDER = "servicenow-da-hrsd"' in skill
    assert "topic mutation requires explicit confirmation" in skill
    assert "Publishing is outside ServiceNow Connect" in skill
    assert "source-of-truth for admin" in skill
    assert "Microsoft Learn is a\nsecondary reference" in skill
    assert "it never overrides PR #217 by itself" in skill
    assert "old PR behavior, current evidence, proposed deviation" in skill
    assert "do not assume UPN or email" in skill
    assert (
        "Connect does not enable ServiceNow topics\nbefore binding is "
        "confirmed."
    ) in skill
    assert (
        "After binding is confirmed, Connect reads the topic\nstates for "
        "Maker review"
    ) in skill
    assert (
        "After topic and portal configuration is complete, the Maker runs"
        in skill
    )
    assert "matching `sys_user` field" in skill
    assert "`aud` may be\nconfigured for audience validation" in skill
    assert "Portal Base URI is now in scope" in skill
    assert "current active\nHR agent/profile only" in skill
    assert "ITSM remains a separate provider/PR layer" in skill

    actions = (
        _SOLUTION
        / "src"
        / "skills"
        / "connect"
        / "servicenow-da-hrsd"
        / "actions"
    )
    agent = (actions / "connect-agent.md").read_text(encoding="utf-8")
    test = (actions / "test-connection.md").read_text(encoding="utf-8")
    topics = (actions / "prepare-topics.md").read_text(encoding="utf-8")
    publish = (actions / "publish-agent.md").read_text(encoding="utf-8")
    preflight = (actions / "admin-preflight.md").read_text(encoding="utf-8")
    plugins = (actions / "verify-plugin-prerequisites.md").read_text(
        encoding="utf-8"
    )
    entra = (actions / "guide-entra-registration.md").read_text(
        encoding="utf-8"
    )
    entra_normalized = " ".join(entra.split())
    oidc = (actions / "guide-servicenow-oidc.md").read_text(
        encoding="utf-8"
    )
    oidc_normalized = " ".join(oidc.split())
    credential = (actions / "prepare-credential.md").read_text(
        encoding="utf-8"
    )
    portal = (actions / "configure-portal-url.md").read_text(
        encoding="utf-8"
    )
    portal_normalized = " ".join(portal.split())
    credential_normalized = " ".join(credential.split())
    topics_normalized = " ".join(topics.split())
    assert "record-agent-connection" in agent
    assert "ACTION_RESULT = \"cancelled\"" in agent
    assert not (actions / "configure-parameter-sharing.md").exists()
    assert 'ACTION_RESULT = "recorded"' in test
    assert "List my open HR cases" in test
    assert "--prompt-category list-my-open-hr-cases" in test
    assert "--failure-category" not in test
    assert "Never store response text, case/ticket data, URLs" in test
    assert "--prompt " not in test
    assert "--details" not in test
    assert "save the current authored draft" in test
    assert "selected ServiceNow connection" in test
    assert (
        '"label": "Pass, the ServiceNow HRSD capability worked correctly"'
        in test
    )
    assert (
        '"label": "Not pass, it failed or could not be verified"' in test
    )
    assert '"recommended": true' not in test
    assert "Do not require a non-empty case result" in test
    assert 'ACTION_RESULT = "waiting"' in test
    assert "Do not ask a second failure-classification question" in (
        " ".join(test.split())
    )
    assert (
        "safely rolled-back update is still a failed action"
        in topics_normalized
    )
    assert "committed" in topics
    assert "already-active" in topics
    assert "unattributedPostimageTopics" in topics
    assert "service normalization or a concurrent edit" in topics
    assert "do not attribute it to either source" in topics_normalized
    assert "claim full postimage ownership" in topics_normalized
    assert "an exception or unknown response" in topics
    assert "missing target topic" in topics
    assert "must not repeat the confirmed update" in topics
    assert "adapt-question" in topics
    assert "while the\n  question is pending" in topics
    assert "Absence of\n  an answer is not cancellation" in topics
    assert "Maker-selected public ServiceNow instance" in preflight
    assert "does not ask the Maker to classify setup\nprogress" in preflight
    assert "which situation matches" not in preflight
    assert "--scenario" not in preflight
    assert "instanceInputRequired" in preflight
    assert "[Open this ServiceNow instance]" not in preflight
    assert "A newly visible connection\nnever changes" in preflight
    assert "Connected physical connection does not prove" in preflight
    assert "top-level `pendingInput` is authoritative" in preflight
    assert "stop without running a checkpoint" in preflight
    assert 'ACTION_RESULT = "waiting"' in preflight
    assert "Local state absence is not evidence" in preflight
    preflight_normalized = " ".join(preflight.split())
    assert "two separate terminal invocations" in preflight_normalized
    assert "60-second HTTP connect/read timeout" in preflight_normalized
    assert "not a 60-second limit for the whole invocation" in (
        preflight_normalized
    )
    assert "continues returning bytes may keep a read active" in (
        preflight_normalized
    )
    assert "Do not describe authorization waiting as API processing" in (
        preflight_normalized
    )
    assert "DA_ADMIN_PREFLIGHT_PROGRESS_JSON:" in preflight
    assert "stage: authentication" in preflight
    assert "stage: connection-inventory" in preflight
    assert "category: timeout" in preflight
    assert "category: throttled" in preflight
    assert "do not automatically retry" in preflight_normalized
    assert "does not authorize continuing with cached connection evidence" in (
        preflight_normalized
    )
    assert "com.sn_hr_core" in plugins
    assert (
        '"label": "Yes, all listed installed-and-ready evidence is present"'
        in plugins
    )
    assert (
        '"label": "No, one or more required items are missing"' in plugins
    )
    assert (
        '"label": "Not sure, the administrator still needs to check"'
        in plugins
    )
    assert "[Open HR Service Delivery Core]({HR_CORE_PLUGIN_URL})" in plugins
    assert "OIDC capability belongs to the later ServiceNow OIDC phase" in (
        plugins
    )
    assert "Multi-Provider SSO" not in plugins
    assert "ITSM must not inherit" in plugins
    assert "Never run `az ad app create`" in entra
    assert "c26b24aa-7874-4e06-ad55-7d06b1f79b63" not in entra
    assert "Application Administrator" in entra_normalized
    assert "Cloud Application Administrator" in entra_normalized
    assert "Privileged Role Administrator" not in entra
    assert "application owner may collaborate" in entra_normalized
    assert "`SN-DA-HRSD-ENTRA-SETUP-001`" in entra
    assert "historical\nstate/audit keys only" in entra
    assert "python scripts/flightcheck/cli.py" not in entra
    for suffix in ("APP", "CLAIMS", "SCOPE", "PREAUTH"):
        assert f"--checkpoint SN-DA-HRSD-ENTRA-{suffix}-001" not in entra
    assert "completes the Manual Entra identity phase" in entra
    assert "--stage entra" in entra
    assert "--yes" in entra
    assert "`Expected result`" not in entra
    assert "reconcile any older derived reused handoff" in entra
    assert "Require\n`decision: no-action`; do not ask again" in entra
    assert "<!-- visible-handoff-question:v1-confirm-setup -->" not in entra
    assert '"header": "Confirm Entra setup evidence"' not in entra
    assert "there is no separate Entra completion question" in " ".join(
        entra.split()
    )
    assert "--claim" not in oidc
    runtime_instructions = (
        _SOLUTION / "src" / "skills" / "connect" / "shared" / "runtime-instructions"
    )
    entra_admin = (runtime_instructions / "entra-administrator.md").read_text(
        encoding="utf-8"
    )
    snow_admin = (runtime_instructions / "servicenow-administrator.md").read_text(
        encoding="utf-8"
    )
    assert "runtime-instructions/entra-administrator.md" in entra
    assert "runtime-instructions/servicenow-administrator.md" in oidc
    assert "identity-direct-handoff --stage entra" in entra
    assert "identity-direct-handoff --stage servicenow" in oidc
    assert "record-identity-direct --stage entra" in entra
    assert "record-identity-direct --stage servicenow" in oidc
    assert "a blank or malformed claim, `aud`," in entra_normalized
    assert "Return `ACTION_RESULT = \"recorded\"` immediately" in oidc
    elevate = snow_admin.index("select **Elevate role**")
    application_registry = snow_admin.index("**System OAuth** > **Application Registry**")
    configure_oidc = snow_admin.index(
        "**Configure an OIDC provider to verify ID tokens**"
    )
    assert elevate < application_registry < configure_oidc
    assert "c26b24aa-7874-4e06-ad55-7d06b1f79b63" in entra_admin
    assert "`acceptMappedClaims`" in entra_admin
    assert "Don't send any secret" in entra_admin
    assert "Enable JTI claim verification:** off" in snow_admin
    assert "`/v2.0` URL" in snow_admin
    assert "Send back to the maker" in snow_admin
    assert "--stage servicenow" in oidc
    assert "`Expected result`" not in oidc
    assert "choose `Not yet`" not in oidc
    assert "Maker must say `Not yet`" not in oidc
    assert "reconcile any older derived reused handoff" in oidc
    assert "Require\n`decision: no-action`; do not ask again" in oidc
    assert "<!-- visible-handoff-question:v1-confirm-setup -->" not in oidc
    assert '"header": "Confirm ServiceNow OIDC evidence"' not in oidc
    assert "{TOKEN_CLAIM_NAME}" not in oidc
    assert '"label": "Completed"' not in oidc
    assert "enable the tenant-supported" not in oidc
    assert "plugin must be enabled" not in oidc.casefold()
    assert "client IDs, metadata" not in oidc
    assert "Resource URI" in credential
    assert "verified App A Application client ID" in credential
    assert "api://<client-id>" in credential
    assert "opens the exact returned `manualInstanceQuestion`" in (
        preflight_normalized
    )
    assert "shared-reuse-handoff" not in preflight
    assert "pass the returned `question` object unchanged" in entra_normalized
    assert "its `options` are label-only" in entra_normalized
    assert "Translate the selected label through `reuseDecisionChoices`" in (
        entra_normalized
    )
    assert "physical connections" in entra_normalized
    assert "It makes no API call" in entra_normalized
    assert "**Reuse shared identity**" in entra
    assert "If it returns `decision: no-action`, immediately return" in entra
    assert "Do not render instructions, call the question tool" in (
        entra_normalized
    )
    assert "rerun `record-identity-direct`" in entra_normalized
    assert "replace the reused admin\nhandoff with `record-admin-phase`" in entra
    assert "runner-owned Entra checkpoints still\nrun next" in entra
    assert "Only `decision: question-required` enters" in entra
    assert "Reuse listed shared configuration" not in entra
    assert "record-reuse-decision" not in preflight
    assert "reuse-discovered" not in preflight
    assert "configure-missing" not in preflight
    assert "automatically reuse one exact healthy Connected" in (
        " ".join(credential.split())
    )
    assert "wrong auth mode, Resource URI, or Instance Name" in credential
    assert "use its `Repair`, `Fix connection`, or sign-in action" in (
        credential
    )
    assert "Only when no exact candidate exists" in credential
    assert (
        '"label": "Completed, the exact ServiceNow connection is Connected"'
        in credential
    )
    assert (
        '"label": "Not yet, the ServiceNow connection is not ready"'
        in credential
    )
    assert "Do not ask the Maker for a connection display name" in (
        credential_normalized
    )
    assert "This is the only question for that path" in credential_normalized
    assert "must never run for the multiple-healthy-candidate path" in (
        credential_normalized
    )
    assert "resolve-credential" in credential
    assert "--selection-key" in credential
    assert "inspect-portal-url" in portal
    assert "portal-reuse-handoff" in portal
    assert "record-portal-reuse" in portal
    assert "`portalSourceChoices`" in portal
    assert "`portalDecisionChoices`" in portal
    assert "**Reuse saved portal URL**" in portal
    assert "Never ask the Maker to type it" in portal
    assert "make no update call" in portal
    assert "do not complete the phase or copy" in portal_normalized
    assert "--expected-portal-url <full-url>" in portal
    assert "Use the instance root only when the administrator explicitly" in (
        portal
    )
    assert "different same-instance HTTPS portal path is not sufficient" in (
        portal_normalized
    )
    assert "set-portal-url" in portal
    assert "Never infer `/sp`, `/esc`" in portal
    assert "Set ServiceNow Portal BaseURI" in portal
    assert "Do not publish the agent in this phase" in portal
    assert (
        "[Open connections for this environment]"
        "({POWER_AUTOMATE_CONNECTIONS_URL})"
    ) in credential
    assert "[Open Power Apps]({POWER_APPS_URL})" in credential
    expected_index = credential.index("**Authentication Type:**")
    resource_index = credential.index("**Resource URI:**")
    instance_index = credential.index("**Instance Name:**")
    assert expected_index < resource_index < instance_index
    assert "no verified direct connector-form or connection-detail URL" in (
        credential
    )
    assert "This action is retired" in publish
    assert "Do not invoke `publish`" in publish
    assert "historical evidence" in publish
    assert 'ACTION_RESULT = "recorded"' in publish
    agent_link = (
        "[Open Employee Self-Service (HR) in Copilot Studio]"
        "({COPILOT_STUDIO_AGENT_URL})"
    )
    for action in (topics, agent, test):
        assert action.count(agent_link) == 1
        assert "tab-specific URL" in action
    assert "ask exactly one question" in plugins
    assert "Do not add a separate\nEmail/UPN/Pay ID routing question" in entra
    assert "or pauses between Create App" in entra_normalized
    assert "or pause between role elevation" in oidc_normalized
    assert "record-admin-phase --phase plugin-prerequisites" in plugins
    assert "record-identity-direct --stage servicenow" in oidc
    assert "--confirm-saved-mapping" not in oidc
    assert "--reject-saved-mapping" not in oidc
    assert "record-admin-phase --phase servicenow-oidc" not in oidc
    assert "record-admin-operation" not in plugins + entra + oidc
    assert "one complete high-level step" in credential
    assert "one completion question" in credential
    assert "Invalid_redirect_uri" in credential
    for action in (preflight, plugins, entra, oidc, credential):
        assert "do not ask again" in action
        assert "completionStatuses" in action

    combined = (
        skill
        + preflight
        + plugins
        + entra
        + oidc
        + credential
        + topics
        + agent
        + publish
        + test
    )
    assert "portal /sp" not in combined
    assert "/api/now/table/" not in combined
    assert "app registrations/" not in combined.casefold()
    assert "/connections/" not in credential.replace(
        "{POWER_AUTOMATE_CONNECTIONS_URL}",
        "",
    )

    assert (
        "Microsoft Learn: ServiceNow for Employee Self-Service" in skill
    )
    assert "ServiceNow connector actions" in skill
    assert "ServiceNow connector known issues" in skill


def test_da_servicenow_itsm_skill_uses_isolated_shared_lifecycle() -> None:
    chooser = (
        _SOLUTION
        / "src"
        / "skills"
        / "connect"
        / "servicenow-da"
        / "SKILL.md"
    ).read_text(encoding="utf-8")
    skill = (
        _SOLUTION
        / "src"
        / "skills"
        / "connect"
        / "servicenow-da-itsm"
        / "SKILL.md"
    ).read_text(encoding="utf-8")
    actions = (
        _SOLUTION
        / "src"
        / "skills"
        / "connect"
        / "servicenow-da-itsm"
        / "actions"
    )

    assert "agent-chooser" in chooser
    assert "must not run a remote collection listing" in chooser
    assert "Use another agent (paste link)" in chooser
    assert "focused freeform question" in chooser
    assert "pastes the full\nCopilot Studio link" in chooser
    assert "Never persist the choice to `.local/config.json`" in chooser
    assert "servicenow-da-hrsd" in chooser
    assert "servicenow-da-itsm" in chooser
    assert 'PROVIDER = "servicenow-da-itsm"' in skill
    assert "AGENT_SLUG = SELECTED_AGENT_SLUG" in skill
    assert "maker-confirmed compatible shared-configuration discovery" in skill
    assert "never migrates,\nmerges, or copies the HRSD lifecycle" in skill
    assert "all eight\nITSM phases" in skill
    assert (
        "Connect does not enable ServiceNow topics\nbefore binding is "
        "confirmed."
    ) in skill
    assert (
        "After binding is confirmed, Connect reads the topic\nstates for "
        "Maker review"
    ) in skill
    assert (
        "After topic and portal configuration is complete, the Maker runs"
        in skill
    )
    assert not (actions / "verify-plugin-prerequisites.md").exists()

    topics = (actions / "prepare-topics.md").read_text(encoding="utf-8")
    preflight = (actions / "admin-preflight.md").read_text(encoding="utf-8")
    portal = (actions / "configure-portal-url.md").read_text(encoding="utf-8")
    test = (actions / "test-connection.md").read_text(encoding="utf-8")
    for text in (topics, portal, test):
        assert "--provider servicenow-da-itsm" in text
        assert "--agent-slug {SELECTED_AGENT_SLUG}" in text
    assert "Only ServiceNow ITSM topics in this inventory" in topics
    assert "Set ServiceNow Portal Base URI" in portal
    assert "Global.ServiceNowITSMPortalBaseURI" in portal
    assert "List my open IT tickets" in test
    assert (
        '"label": "Pass, the ServiceNow ITSM capability worked correctly"'
        in test
    )
    assert (
        '"label": "Not pass, it failed or could not be verified"' in test
    )
    assert '"recommended": true' not in test
    assert "--failure-category" not in test
    assert "Do not require a non-empty ticket result" in test
    assert "Do not ask a second failure-classification question" in (
        " ".join(test.split())
    )
    normalized_preflight = " ".join(preflight.split())
    assert "60-second HTTP connect/read timeout" in normalized_preflight
    assert "stage: authentication" in preflight
    assert "stage: connection-inventory" in preflight
    assert "category: throttled" in preflight
    assert "does not authorize continuing with cached connection evidence" in (
        normalized_preflight
    )
    assert "migrate-state" not in preflight


def test_entra_guides_use_direct_two_field_handoff() -> None:
    for provider in ("servicenow-da-hrsd", "servicenow-da-itsm"):
        guide = (
            _SOLUTION
            / "src"
            / "skills"
            / "connect"
            / provider
            / "actions"
            / "guide-entra-registration.md"
        ).read_text(encoding="utf-8")

        assert "--agent-slug {SELECTED_AGENT_SLUG}" in guide
        assert "Do not add a separate\nEmail/UPN/Pay ID routing question" in guide
        assert "identity-direct-handoff --stage entra" in guide
        assert "record-identity-direct --stage entra" in guide
        assert "Client ID and User Claim prompts" in " ".join(guide.split())
        assert "--directory-tenant-id" not in guide
        assert "record-identity-requirement --choice" not in guide
        assert "`identityRequirementChoices`" not in guide
        assert "there is no separate Entra completion question" in " ".join(
            guide.split()
        )
        assert "record-admin-phase --phase entra-registration" not in guide


def test_entra_guides_use_one_current_setup_checkpoint() -> None:
    for profile in ("HRSD", "ITSM"):
        provider = f"servicenow-da-{profile.lower()}"
        guide = (
            _SOLUTION
            / "src"
            / "skills"
            / "connect"
            / provider
            / "actions"
            / "guide-entra-registration.md"
        ).read_text(encoding="utf-8")

        assert f"`SN-DA-{profile}-ENTRA-SETUP-001`" in guide
        assert "historical\nstate/audit keys only" in guide
        assert "all four requirements" not in guide
        assert "Application client ID" in guide
        assert "one safe User Claim name" in " ".join(guide.split())
        assert "does not prove app configuration" in guide


def test_hr_it_admin_guides_complete_from_mapping_receipt() -> None:
    for provider in ("servicenow-da-hrsd", "servicenow-da-itsm"):
        actions = _SOLUTION / "src" / "skills" / "connect" / provider / "actions"
        entra = (actions / "guide-entra-registration.md").read_text(
            encoding="utf-8"
        )
        oidc = (actions / "guide-servicenow-oidc.md").read_text(
            encoding="utf-8"
        )

        assert "<!-- visible-handoff-question:v1-confirm-setup -->" not in entra
        assert '"header": "Confirm Entra setup evidence"' not in entra
        assert "there is no separate Entra completion question" in " ".join(
            entra.split()
        )

        assert "<!-- visible-handoff-question:v1-confirm-setup -->" not in oidc
        assert '"header": "Confirm ServiceNow OIDC evidence"' not in oidc
        assert "record-identity-direct --stage servicenow" in oidc
        assert "atomically persists the mapping receipt" in oidc
        assert "--confirm-saved-mapping" not in oidc
        assert "--reject-saved-mapping" not in oidc
        assert "record-admin-phase --phase servicenow-oidc" not in oidc


def test_servicenow_oidc_guides_match_canonical_admin_instructions() -> None:
    canonical = (
        _SOLUTION
        / "src"
        / "skills"
        / "connect"
        / "shared"
        / "runtime-instructions"
        / "servicenow-administrator.md"
    ).read_text(encoding="utf-8")
    canonical_normalized = " ".join(canonical.split())
    assert "select **Elevate role**" in canonical
    assert "select `security_admin`, and select **Update**" in canonical
    assert "Configure an OIDC provider to verify ID tokens" in canonical
    assert "Client ID `<client ID>`" in canonical
    assert "User Claim" in canonical
    assert "User Field" in canonical
    assert "configuration is saved" in canonical_normalized

    for provider in ("servicenow-da-hrsd", "servicenow-da-itsm"):
        guide = (
            _SOLUTION
            / "src"
            / "skills"
            / "connect"
            / provider
            / "actions"
            / "guide-servicenow-oidc.md"
        ).read_text(encoding="utf-8")
        normalized = " ".join(guide.split())

        assert "../../shared/runtime-instructions/servicenow-administrator.md" in (
            guide
        )
        assert "record-identity-direct --stage servicenow" in guide
        assert "--confirm-saved-mapping" not in guide
        assert "--reject-saved-mapping" not in guide
        assert "record-admin-phase --phase servicenow-oidc" not in guide
        assert "atomically persists the mapping receipt and owning Manual" in (
            normalized
        )


def test_connect_completion_uses_human_verified_wording_without_realm_text() -> None:
    import re

    skills = _SOLUTION / "src" / "skills" / "connect"
    docs = {
        "router": skills / "SKILL.md",
        "runner": skills / "shared" / "lifecycle-runner.md",
        "chooser": skills / "servicenow-da" / "SKILL.md",
        "hrsd": skills / "servicenow-da-hrsd" / "SKILL.md",
        "itsm": skills / "servicenow-da-itsm" / "SKILL.md",
        "controller": _SOLUTION / "scripts" / "connect_servicenow_da.py",
    }
    forbidden = re.compile(
        r"automatically verified|already promoted|promoted (?:to|content)|"
        r"Test (?:or|and|/) ?Prod|realm-validation|realm path|"
        r"Production (?:validation|verification)",
        re.IGNORECASE,
    )
    text = {name: path.read_text(encoding="utf-8") for name, path in docs.items()}
    for name, content in text.items():
        assert forbidden.search(content) is None, name

    readme = (_SOLUTION / "README.md").read_text(encoding="utf-8")
    assert "automatically verified" not in readme.lower()

    completion = " ".join(text["runner"].split("## L.5 — Completion", 1)[1].split())
    for phrase in (
        "Verified by Connect checks",
        "Confirmed by the administrator",
        "Confirmed by the Maker",
        "Maker-reported Test pane result",
    ):
        assert phrase in completion
    for name in ("hrsd", "itsm"):
        flat = " ".join(text[name].split())
        assert "Maker-reported Test pane result" in flat
        assert "human-verified" in flat
