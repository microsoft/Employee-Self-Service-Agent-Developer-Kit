# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_SOLUTION = _ROOT / "solutions" / "ess-maker-skills"


def test_da_servicenow_connect_routes_to_hrsd_lifecycle() -> None:
    prompt = (
        _SOLUTION / ".github" / "prompts" / "connect.prompt.md"
    ).read_text(encoding="utf-8")
    router = (
        _SOLUTION / "src" / "skills" / "connect" / "SKILL.md"
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
    assert "Do not inspect `.local/connect/steps.md` before" in prompt
    assert "a DA ServiceNow route starts\nwith its provider lifecycle" in prompt
    assert "src/skills/connect/servicenow-da-hrsd/SKILL.md" in router
    assert "servicenow-da-hrsd/agents/<agent-slug>/lifecycle.json" in router
    assert "releaseLine" in router
    assert "emit_capability.py connect --connector servicenow" in router

    interactive_router = (
        _SOLUTION / "src" / "skills" / "connect" / "step1.md"
    ).read_text(encoding="utf-8")
    dispatch = interactive_router.index(
        "src/skills/connect/servicenow-da-hrsd/SKILL.md"
    )
    legacy_read = interactive_router.index(
        "Check if `.local/connect/servicenow/steps.md` exists."
    )
    assert dispatch < legacy_read
    assert 'releaseLine: "da"' in interactive_router
    assert "gptagent_copilotforemployeeselfservicehr" in interactive_router
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
    assert "topic mutation and publish require" in skill
    assert "source-of-truth for admin" in skill
    assert "Microsoft Learn is a\nsecondary reference" in skill
    assert "it never overrides PR #217 by itself" in skill
    assert "old PR behavior, current evidence, proposed deviation" in skill
    assert "`email`/`upn` optional-claim requirement" in skill
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
    parameter = (actions / "configure-parameter-sharing.md").read_text(
        encoding="utf-8"
    )
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
    oidc = (actions / "guide-servicenow-oidc.md").read_text(
        encoding="utf-8"
    )
    credential = (actions / "prepare-credential.md").read_text(
        encoding="utf-8"
    )
    assert "record-agent-connection" in agent
    assert "ACTION_RESULT = \"cancelled\"" in agent
    assert "record-parameter-sharing --status enabled" in parameter
    assert "record-parameter-sharing --status not-exposed" in parameter
    assert 'ACTION_RESULT = "recorded"' in test
    assert "safely rolled-back update is still a failed action" in topics
    assert "committed" in topics
    assert "already-active" in topics
    assert "vscode_askQuestions" in topics
    assert "while the\n  question is pending" in topics
    assert "Absence of\n  an answer is not cancellation" in topics
    assert "explicitly selects\n  **Not now**" in topics
    assert "automatically reuse each valid" in preflight
    assert "does not ask the Maker to classify setup\nprogress" in preflight
    assert "which situation matches" not in preflight
    assert "--scenario" not in preflight
    assert "instanceInputRequired" in preflight
    assert (
        "[Open this ServiceNow instance]({SERVICENOW_INSTANCE_URL})"
        in preflight
    )
    assert preflight.count(
        "[Open this ServiceNow instance]({SERVICENOW_INSTANCE_URL})"
    ) == 2
    assert "Connected physical connection does not prove" in preflight
    assert 'ACTION_RESULT = "waiting"' in preflight
    assert "Local state absence is not evidence" in preflight
    assert "com.sn_hr_core" in plugins
    assert "Is HR Service Delivery Core installed and Active?" in plugins
    assert "Choices: **Yes**, **No**, **Not sure**" in plugins
    assert "[Open HR Service Delivery Core]({HR_CORE_PLUGIN_URL})" in plugins
    assert "OIDC capability belongs to the later ServiceNow OIDC phase" in (
        plugins
    )
    assert "Multi-Provider SSO" not in plugins
    assert "ITSM must not inherit" in plugins
    assert "Never run `az ad app create`" in entra
    assert (
        "[Open Microsoft Entra admin center](https://entra.microsoft.com/)"
        in entra
    )
    assert "c26b24aa-7874-4e06-ad55-7d06b1f79b63" in entra
    assert "ESS Copilot - ServiceNow OIDC" in entra
    assert "Application Administrator" in entra
    assert "Cloud Application Administrator" in entra
    assert "Privileged Role Administrator" in entra
    assert "application\n  owner may collaborate" in entra
    assert "`Failed` or `Error`" in entra
    assert "cannot be overridden" in entra
    assert "Runner-owned checkpoint\ntarget: `SN-DA-HRSD-ENTRA-*`" in entra
    assert "python scripts/flightcheck/cli.py" not in entra
    for suffix in (
        "APP",
        "CLAIMS",
        "SCOPE",
        "PREAUTH",
        "PERMISSIONS",
        "CONSENT",
    ):
        assert f"--checkpoint SN-DA-HRSD-ENTRA-{suffix}-001" not in entra
    assert "one category evaluation" in entra
    assert "Do not decide checkpoint success in this action" in entra
    assert "upn" in oidc
    assert "Configure an OIDC provider to verify ID tokens" in oidc
    assert "Multi-Provider SSO" in oidc
    assert "structured response such as `upn, user_name`" in oidc
    assert (
        "[Open this ServiceNow instance]({SERVICENOW_INSTANCE_URL})" in oidc
    )
    assert "matching Active" in oidc
    assert "Do not return the employee's" in oidc
    assert "Do not create a test user" in oidc
    assert "Broadly scoped" not in oidc
    assert "Resource URI" in credential
    assert "verified App A Application client ID" in credential
    assert "api://<client-id>" in credential
    assert "one standalone\n`vscode_askQuestions` free-form question" in (
        preflight
    )
    assert "record-reuse-decision" not in preflight
    assert "reuse-discovered" not in preflight
    assert "configure-missing" not in preflight
    assert "automatically\n  reuse it" in credential
    assert "wrong Instance Name, Resource URI, or auth mode" in credential
    assert (
        "[Open connections for this environment]"
        "({POWER_AUTOMATE_CONNECTIONS_URL})"
    ) in credential
    assert "[Open Power Apps]({POWER_APPS_URL})" in credential
    assert "inspect-publish" in publish
    assert "reconcile-publish-receipt" in publish
    assert "It never publishes or mutates the remote agent" in publish
    assert 'ACTION_RESULT = "recorded"' in publish
    agent_link = (
        "[Open Employee Self-Service (HR) in Copilot Studio]"
        "({COPILOT_STUDIO_AGENT_URL})"
    )
    for action in (topics, agent, parameter, publish, test):
        assert action.count(agent_link) == 1
        assert "tab-specific URL" in action
    assert "ask exactly one question" in plugins
    assert "pause exactly once" in entra
    assert "pause exactly once" in oidc
    assert "Do not pause between" in entra
    assert "Do not pause between" in oidc
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
        + parameter
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
