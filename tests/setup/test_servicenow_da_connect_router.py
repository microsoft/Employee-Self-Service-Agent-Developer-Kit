# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_SOLUTION = _ROOT / "solutions" / "ess-maker-skills"


def test_realm_deployment_guidance_is_conditional_and_read_only() -> None:
    chooser = (
        _SOLUTION
        / "src"
        / "skills"
        / "connect"
        / "servicenow-da"
        / "SKILL.md"
    ).read_text(encoding="utf-8")
    normalized = " ".join(chooser.split())

    assert "record-realm-deployment --realm <test|prod>" in chooser
    assert "--status not-deployed" in chooser
    assert "--status deployment-completed" in chooser
    assert "upper-right **Deploy to" in chooser
    assert "lower-left **Save**" in chooser
    assert "**Deploy**, wait, then **Open Agent**" in chooser
    assert "404, unreadable environment" in chooser
    assert "not proof of missing deployment" in chooser
    assert "do not pass validation" in chooser
    assert "does not deploy, promote, import" in chooser
    assert "Not automatically verified" in chooser
    assert "never present `Manual` alone" in chooser
    assert "`List my open HR cases` or `List my open IT tickets`" in chooser
    assert "empty list is not an automatic failure" in normalized
    assert "generic answer is not an automatic pass" in normalized
    assert "without requiring a failure category" in normalized
    assert (
        "Not pass recorded; return to the Dev agent and rerun /connect "
        "servicenow to recheck the connection setup step by step."
        in normalized
    )
    assert "Do not ask a second failure-category question" in normalized


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
    assert "`authoring_ready: true`" in prompt
    assert "Ignore" in prompt
    assert "`connect_ready`" in prompt
    assert "`activeAgent` slug" in prompt
    assert "`botId`" in prompt
    assert "Skip completed steps" in prompt
    assert "Waiting for maker input" in prompt
    assert "never require the maker to invoke" in prompt
    assert "Fresh ServiceNow execution boundary" in prompt
    assert "resume-handoff" in prompt
    assert "mandatory on every `/connect servicenow` invocation" in prompt
    assert "before any FlightCheck/checkpoint command" in prompt
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
    assert "progress.currentPhase.startText" in prompt
    assert "progress.currentPhase.questionText" in prompt
    assert "progress.currentPhase.errorChecklistText" in prompt
    assert "Re-emit the freshly returned" in prompt
    assert "an action receipt" in prompt
    assert "Show a phase as complete only after" in prompt
    assert "ServiceNow phase-progress strings returned" in prompt
    assert "**ServiceNow phase-progress extension:**" in runner
    assert "Other providers retain this runner's existing output" in runner
    assert "cached `done` phase displays **Rechecking**" in runner
    assert "Do not inspect `.local/connect/steps.md` before" in prompt
    assert "a DA ServiceNow route starts\nwith its provider lifecycle" in prompt
    assert "src/skills/connect/servicenow-da/SKILL.md" in router
    assert "servicenow-da-hrsd/agents/<agent-slug>/lifecycle.json" in router
    assert "servicenow-da-itsm/agents/<agent-slug>/lifecycle.json" in router
    assert "Never changes `.local/config.json.activeAgent`" in router
    assert "`schema_version: 4` with an environment binding" in router
    assert "emit_capability.py connect --connector servicenow" in router

    interactive_router = (
        _SOLUTION / "src" / "skills" / "connect" / "step1.md"
    ).read_text(encoding="utf-8")
    dispatch = interactive_router.index(
        "src/skills/connect/servicenow-da/SKILL.md"
    )
    legacy_read = interactive_router.index(
        "Check if `.local/connect/servicenow/steps.md` exists."
    )
    assert dispatch < legacy_read
    assert 'releaseLine: "da"' in interactive_router
    assert "do not inspect or create `.local/connect/servicenow/` state" in (
        interactive_router
    )


def test_global_gate_allows_connection_blocked_foundation() -> None:
    instructions = (
        _SOLUTION / ".github" / "copilot-instructions.md"
    ).read_text(encoding="utf-8")

    assert "`authoring_ready` equal to `true`" in instructions
    assert "This is the only readiness marker" in instructions
    assert "Ignore `connect_ready`" in instructions
    assert "let the invoked command resolve" in instructions
    assert "`/connect servicenow` is available" in instructions


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
    assert "protected XLSX workbook" in skill
    assert "matching `sys_user` field" in skill
    assert "`aud` is a built-in" in skill
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
    assert '"label": "Pass"' in test
    assert '"label": "Not pass"' in test
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
    assert "vscode_askQuestions" in topics
    assert "while the\n  question is pending" in topics
    assert "Absence of\n  an answer is not cancellation" in topics
    assert "explicitly selects\n  **Not now**" in topics
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
    assert "Does the page show the listed installed-and-ready evidence" in plugins
    assert '"label": "Yes"' in plugins
    assert '"label": "No"' in plugins
    assert '"label": "Not sure"' in plugins
    assert "[Open HR Service Delivery Core]({HR_CORE_PLUGIN_URL})" in plugins
    assert "OIDC capability belongs to the later ServiceNow OIDC phase" in (
        plugins
    )
    assert "Multi-Provider SSO" not in plugins
    assert "ITSM must not inherit" in plugins
    assert "Never run `az ad app create`" in entra
    assert "https://entra.microsoft.com/" in entra
    assert "c26b24aa-7874-4e06-ad55-7d06b1f79b63" not in entra
    assert "A display name is a clue, not unique identity" in entra
    assert "If one exact app exists, reuse it." in entra
    assert "Do not add an intermediate\n     selection pause" in entra
    assert "Only when no correct app exists" in entra
    assert "Application Administrator" in entra_normalized
    assert "Cloud Application Administrator" in entra_normalized
    assert "Privileged Role Administrator" not in entra
    assert "application owner may collaborate" in entra_normalized
    assert "`Failed` or `Error`" in entra
    assert "cannot be overridden" in entra
    assert "Runner-owned checkpoint\ntarget: `SN-DA-HRSD-ENTRA-*`" in entra
    assert "python scripts/flightcheck/cli.py" not in entra
    for suffix in (
        "APP",
        "CLAIMS",
        "SCOPE",
        "PREAUTH",
    ):
        assert f"--checkpoint SN-DA-HRSD-ENTRA-{suffix}-001" not in entra
    assert "one category evaluation" in entra
    assert "Do not decide checkpoint success in this action" in entra
    assert "never enter `aud`" in entra
    assert "employee-identity candidate claim per yellow" in entra
    assert "never enter `aud`" in entra
    assert "confirm every returned candidate name is actually issued" in entra
    assert "Optional claims screen alone does not prove emission" in entra
    assert "do not add employee values" in entra
    assert "record-identity-mapping" in entra
    assert "--workbook-file" in entra
    assert "--stage entra" in entra
    assert "--yes" in entra
    assert "instructionTitle`, `instruction`, and one short" in entra
    assert "send the returned `question` object unchanged" in entra
    assert (
        "`Please enter the returned Entra admin handoff workbook URL.`"
        in entra
    )
    assert "`Purpose`, `Owner`,\n`Known target`, and `Action`" in entra
    assert "`Expected result`" not in entra
    assert "dynamic workbook link" in entra
    assert "plain absolute path" in entra_normalized
    assert "editable\nToken Claim Name cells are yellow" in entra
    assert "ServiceNow User Field cells are\ngray" in entra
    assert "no ownership legend is needed" in entra
    assert "`missingItems` may\ncontrol workbook fields and branch guidance" in entra
    assert "must never modify the returned\nshort `question` object" in entra
    assert "add an identifier question" in entra
    assert "The fixed workbook flow is" in entra
    assert "blank-label quickstart link row" in entra
    assert "Step 2 goes directly to Step 7" in entra
    assert "only the required claim is missing" in entra
    assert "Only no-app + yellow-ID flows go to Step 3" in entra
    assert "`6A.1-6A.5`" in entra
    assert "`6B.1-6B.9`" in entra
    assert "Step 7 is the single final actual-issuance verification" in entra
    assert "This Task 1 workbook does not configure them" in entra_normalized
    assert "API URI" in entra
    assert "checkpoint results and remediation independent" in entra
    assert "admin phase's only visible high-level pause" in entra_normalized
    assert "reconcile any older derived reused handoff" in entra
    assert "Require\n`decision: no-action`; do not ask again" in entra
    assert "`allowFreeformInput: true`" in entra
    assert "approved Maker-facing term" in entra
    assert "actual local path" in entra
    assert "HTTP/SharePoint/OneDrive URL" in entra_normalized
    assert "Use the exact local path returned by the question" in entra
    assert "There is no separate client-ID question" in entra
    assert "<!-- visible-handoff-question:" not in entra
    assert "acceptMappedClaims" in entra
    assert "custom signing-key route" in entra
    assert "freezes the exact Entra-confirmed candidate claim names" in (
        oidc_normalized
    )
    assert "returns to the OIDC configuration tab, then sets OIDC" in oidc
    assert "Configure an OIDC provider to verify ID tokens" in oidc
    assert "multi-provider sso" in " ".join(oidc.split()).casefold()
    assert "fills the ServiceNow User Field cell on exactly one yellow row" in (
        oidc
    )
    assert "stage-specific `Steps`" in oidc
    assert "two-column `Worksheet`" in oidc
    assert "hidden locked\n   `_metadata`" in oidc
    assert "--claim" not in oidc
    assert "--user-field" not in oidc
    assert "[this ServiceNow instance]({SERVICENOW_INSTANCE_URL})" in oidc
    elevate = oidc.index("select `Elevate roles`")
    application_registry = oidc.index(
        "`All`, search for `OAuth`, then open `System OAuth` →"
    )
    configure_oidc = oidc.index(
        "`Configure an OIDC provider to verify ID tokens`"
    )
    assert elevate < application_registry < configure_oidc
    assert "whose Client ID is the exact\n   Task 1 Application client ID" in (
        oidc
    )
    assert "Select `New`\n   only when no exact entry exists" in oidc
    assert "Name = `Microsoft Entra ID - ESS Copilot`" in oidc
    assert "Client ID = verified App A Application client ID" in oidc
    assert "Entity state = `Active`" in oidc
    assert "Scope Restriction = `Broadly scoped`" in oidc
    assert "tenant-approved non-empty\n     non-secret unused placeholder" in (
        oidc
    )
    assert "cache lifespan = `120`" in oidc
    assert "Application = `Global`" in oidc
    assert "JTI verification = disabled" in oidc
    assert "stop and\n     tell the ServiceNow Admin" in oidc
    assert "Do not continue, guess a specific plugin" in oidc
    assert "does not prove authorization" in oidc_normalized
    assert "identity-mapping-handoff" in oidc
    assert "--stage servicenow" in oidc
    assert "No answer or cancellation returns" in oidc
    assert "Render the exact returned `instructionTitle` and `instruction`" in (
        oidc
    )
    assert (
        "`Please enter the returned ServiceNow admin handoff workbook URL.`"
        in oidc
    )
    assert "`Purpose`, `Owner`, `Known target`, and\n`Action`" in oidc
    assert "`Expected result`" not in oidc
    assert "generated protected workbook URI and plain absolute path" in (
        oidc_normalized
    )
    assert "`allowFreeformInput: true`" in oidc
    assert "approved Maker-facing term" in oidc
    assert "choose `Not yet`" not in oidc
    assert "Maker must say `Not yet`" not in oidc
    assert "keep the handoff waiting" in oidc
    assert "reconcile any older derived reused handoff" in oidc
    assert "Require\n`decision: no-action`; do not ask again" in oidc
    assert "<!-- visible-handoff-question:" not in oidc
    assert "{TOKEN_CLAIM_NAME}" not in oidc
    assert '"label": "Completed"' not in oidc
    assert "PR #217 S4.3/S4.4 is authoritative" in oidc
    assert "enable the tenant-supported" not in oidc
    assert "plugin must be enabled" not in oidc.casefold()
    assert "matching Active" in oidc
    assert "Do not return the employee's" in oidc
    assert "Do not create a test user" in oidc
    assert "Dictionary or Configure Dictionary" in oidc
    assert "not a display label or dotted `table.field` name" in (
        oidc_normalized
    )
    assert "exact locked claim name" in oidc
    assert "approved custom employee claim instead of guessing" in (
        oidc_normalized
    )
    assert "c26b24aa-7874-4e06-ad55-7d06b1f79b63" in oidc
    assert "an Entra Task 1 action" in oidc_normalized
    assert "Graph Connector app-only provider" in oidc
    assert "metadata URL is already used" in oidc
    assert "do not claim a universal one-provider limit" in oidc_normalized
    assert "Do not duplicate the same tenant metadata" in oidc
    assert "Do not record completion evidence until" in oidc_normalized
    assert "evaluate metadata URL reuse or uniqueness separately" in (
        oidc_normalized
    )
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
    assert "Do not render or generate a workbook" in entra
    assert "rerun `record-identity-mapping`" in entra
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
    assert "wrong Instance Name, Resource URI, or auth mode" in credential
    assert "use its `Repair`, `Fix connection`, or sign-in action" in (
        credential
    )
    assert "Only when no exact candidate exists" in credential
    assert '"label": "Completed"' in credential
    assert '"label": "Not yet"' in credential
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
    assert "Topics -> ServiceNow HRSD Setup Configurations" in portal
    assert "Set ServiceNow Portal BaseURI" in portal
    assert "Do not publish the agent in this phase" in portal
    assert (
        "[Open connections for this environment]"
        "({POWER_AUTOMATE_CONNECTIONS_URL})"
    ) in credential
    assert "[Open Power Apps]({POWER_APPS_URL})" in credential
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
    assert "admin phase's only visible high-level pause" in entra_normalized
    assert "pause exactly once" in oidc
    assert "or pauses between Create App" in entra_normalized
    assert "or pause between role elevation" in oidc_normalized
    assert "record-admin-phase --phase plugin-prerequisites" in plugins
    assert "record-admin-phase --phase entra-registration" in entra
    assert "record-admin-phase --phase servicenow-oidc" in oidc
    assert "record-admin-operation" not in plugins + entra + oidc
    assert "one complete high-level step" in credential
    assert "one completion question" in credential
    assert "not shareable" in credential
    assert "Invalid redirect_uri" in credential
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
    assert '"label": "Pass"' in test
    assert '"label": "Not pass"' in test
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


def test_entra_guides_use_one_workbook_for_client_id_and_claims() -> None:
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

        assert "There is no separate client-ID question" in guide
        assert "--agent-slug {SELECTED_AGENT_SLUG}" in guide
        assert "Do not add a separate\nEmail/UPN/Pay ID routing question" in guide
        assert "`allowFreeformInput: true`" in guide
        assert (
            "`Please enter the returned Entra admin handoff workbook URL.`"
            in guide
        )
        assert "generated workbook link" in guide
        assert "not the returned answer" in " ".join(guide.split())
        assert "successful validation and import are still\nrequired" in guide
        assert "record-identity-requirement --choice" not in guide
        assert "`identityRequirementChoices`" not in guide
        assert "plan-cloud-hr-provision" in guide
        assert "reference-connect-sync-attributes-synchronized" in guide
        assert "jwt-claims-customization" in guide
        assert "Do not require both methods" in guide
        assert "task-1-register-an-application-in-microsoft-entra-id" in guide
        assert "yellow Application Client ID cell" in guide
        assert "one or more yellow Token Claim Name rows" in " ".join(
            guide.split()
        )
        assert "record-identity-mapping --stage entra" in guide
        assert "--client-id <application-client-id>" not in guide
        assert "record-admin-phase --phase entra-registration" in guide


def test_servicenow_oidc_guides_match_complete_stage2_workbook() -> None:
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

        assert "select `Elevate roles`" in guide
        assert "select `security_admin`, and select `Update`" in normalized
        assert "do not bypass permissions, create a role" in normalized
        assert "search for `OAuth`" in guide
        assert "whose Client ID is the exact\n   Task 1 Application client ID" in (
            guide
        )
        assert "Select `New`\n   only when no exact entry exists" in guide
        assert "Configure an OIDC provider to verify ID tokens" in guide
        assert "open its existing form instead of selecting the new-entry" in (
            guide
        )
        assert "Client ID = verified App A Application client ID" in guide
        assert "Scope Restriction = `Broadly scoped`" in guide
        assert "non-secret unused placeholder" in guide
        assert (
            "https://login.microsoftonline.com/<tenant-id>/"
            ".well-known/openid-configuration"
        ) in guide
        assert "cache lifespan = `120`" in guide
        assert "Application = `Global`" in guide
        assert "JTI verification = disabled" in guide
        assert "OIDC Provider / Provider Name" in guide
        assert "inspect existing provider configurations" in guide
        assert "Select `New` only when no suitable configuration exists" in (
            guide
        )
        assert "Do not duplicate or\n   modify another integration" in guide
        assert "in a separate browser tab" in guide
        assert "in that same lookup tab" in guide
        assert "Dictionary or Configure Dictionary" in guide
        assert "not a display label or dotted `table.field` name" in normalized
        assert "exact locked claim name" in guide
        assert "returns to the OIDC configuration tab" in guide
        assert "approved custom employee claim instead of guessing" in (
            normalized
        )
        assert "Do not create a test user" in guide
        assert "c26b24aa-7874-4e06-ad55-7d06b1f79b63" in guide
        assert "an Entra Task 1 action" in normalized
        assert "task-2-register-oidc-provider-in-servicenow" in guide
        assert "custom/non-email" in guide
        assert "metadata/JWKS route" in guide
        assert "`appid`" in guide
        assert "Do not assume the default tenant metadata is compatible" in (
            guide
        )
        assert "record-identity-mapping --stage servicenow" in guide
        assert "record-admin-phase --phase servicenow-oidc" in guide
        assert "`allowFreeformInput: true`" in guide
        assert (
            "`Please enter the returned ServiceNow admin handoff workbook "
            "URL.`" in guide
        )
        assert "Import only the exact local path returned by the question" in (
            guide
        )
