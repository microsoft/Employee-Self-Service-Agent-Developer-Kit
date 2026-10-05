# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Contracts for the simplified Workday DA orchestration."""

import argparse
import json
from pathlib import Path
import re

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKDAY_DA = (
    _REPO_ROOT
    / "solutions"
    / "ess-maker-skills"
    / "src"
    / "skills"
    / "setup"
    / "workday-da"
)


def test_orchestrator_resumes_from_controller_status() -> None:
    text = (_WORKDAY_DA / "SKILL.md").read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "python scripts/workday_connect.py status" in text
    assert "nextPhaseId" in text
    assert "nextPhaseSummary" in text
    assert "What happens in this phase:" in text
    assert "must not be collapsed into a one-line phase list" in text
    assert "Do not\nreplace the phase explanation with only" in text
    assert "do not create, copy, update, or infer status from a Markdown" in (
        normalized
    )
    assert "resume the same blocker" in text
    assert "controller status is `ready`" in text


def test_role_availability_is_state_aware_at_phase_boundary() -> None:
    skill = (_WORKDAY_DA / "SKILL.md").read_text(encoding="utf-8")
    entra = (_WORKDAY_DA / "provision-entra-app.md").read_text(encoding="utf-8")
    tenant = (_WORKDAY_DA / "configure-tenant.md").read_text(encoding="utf-8")
    normalized_skill = " ".join(skill.split())

    briefing = skill.index("> Here's who may be needed")
    status = skill.index("python scripts/workday_connect.py status")
    attestation = skill.index('"header": "Required access"')
    dispatch = skill.index("Dispatch from `nextPhaseId`")

    assert briefing < status < attestation < dispatch
    forms = [
        json.loads(form)
        for form in re.findall(
            r"`vscode_askQuestions` form before dispatching that phase:"
            r"\s+```json\s+(.*?)\s+```",
            skill,
            re.DOTALL,
        )
    ]
    assert [
        {
            "header": "Workday administrator",
            "question": (
                "Have you looped in the Workday administrator to complete "
                "the next phase?"
            ),
            "options": [
                {"label": "Yes, the Workday administrator is engaged"},
                {
                    "label": (
                        "No, I still need to engage the Workday administrator"
                    )
                },
            ],
            "allowFreeformInput": False,
        }
    ] in forms
    assert [
        {
            "header": "Required access",
            "question": (
                "Are the people needed for the next phase available to help "
                "when that phase begins?"
            ),
            "options": [
                {"label": "Yes, required people are available"},
                {"label": "No, someone is unavailable"},
            ],
            "allowFreeformInput": False,
        }
    ] in forms
    assert "If controller status is `ready`, skip the availability question" in skill
    for phase_id in (
        "preflight",
        "entra",
        "workday-admin",
        "connections",
        "runtime",
        "employee-validation",
    ):
        assert re.search(
            rf"^\|\s*`{re.escape(phase_id)}`\s*\|",
            skill,
            re.MULTILINE,
        )
    assert "Leave the selection unset" in skill
    assert "not proof that the signed-in account has a required role" in skill
    assert (
        "phase-specific live checks or structured administrator evidence remain"
        in " ".join(skill.split())
    )
    assert "Do not include people from completed phases" in skill
    assert (
        "remediation-only roles that are not currently required"
        in normalized_skill
    )
    assert (
        "only when `nextPhaseId` is `workday-admin`" in normalized_skill
    )
    assert (
        "healthy reused tenant foundation continues at Connections"
        in normalized_skill
    )
    assert "When `nextPhaseId` is `entra`, dispatch" in skill
    assert "presents the guided handoff" in skill
    assert "stop before dispatching the next\nphase" in skill
    assert "no phase progress or target configuration was changed" in skill
    assert "do not offer to bypass the role requirement" in " ".join(skill.split())
    assert (
        "do not repeat the question while `nextPhaseId` remains unchanged"
        in " ".join(skill.split())
    )
    assert "Show the exact required Entra role" in entra
    assert "Do not silently reuse Entra configuration" in entra
    assert "must not authenticate the maker to Graph" in skill
    assert "reread Graph" not in skill
    assert "read-only discovery" not in skill
    assert '"header": "Microsoft Entra administrator"' in entra
    assert "engagement answer is not configuration evidence" in entra
    assert "Have you looped in the Microsoft Entra administrator" in entra
    assert "Information to return to the maker" in entra
    assert "Has the Microsoft Entra administrator completed" in entra
    assert (
        "Do not add a second engagement question here"
        in " ".join(tenant.split())
    )
    assert "Have you looped in the Workday administrator" in tenant


def test_entra_waiting_boundary_follows_guided_handoff() -> None:
    entra = (_WORKDAY_DA / "provision-entra-app.md").read_text(
        encoding="utf-8"
    )

    handoff = entra.index("Render one standalone section titled")
    waiting = entra.index(
        "administrator-stage --phase entra --substage awaiting-completion"
    )

    assert handoff < waiting
    assert "requiresRediscovery" not in entra
    assert "does not authenticate the maker\nto Microsoft Graph" in entra
    assert "guided handoff to\nthe Entra administrator" in entra


def test_every_controller_command_is_documented() -> None:
    import workday_connect as controller

    guide_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(_WORKDAY_DA.rglob("*.md"))
    )
    documented = set(
        re.findall(r"workday_connect\.py\s+([a-z][a-z-]*)", guide_text)
    )

    assert documented == set(controller._COMMAND_HANDLERS)


def test_workday_guides_use_file_backed_json_inputs() -> None:
    guide_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(_WORKDAY_DA.rglob("*.md"))
    )

    for unsafe_option in (
        "--discovery-json",
        "--verification-json",
        "--response-json",
        "--plan-json",
        "--evidence-json",
        "--attachment-json",
    ):
        assert unsafe_option not in guide_text


def test_workday_forms_do_not_preselect_or_recommend_answers() -> None:
    guide_paths = list(_WORKDAY_DA.rglob("*.md")) + list(
        (
            _REPO_ROOT
            / "solutions"
            / "ess-maker-skills"
            / "src"
            / "skills"
            / "connect"
            / "workday"
            / "actions"
        ).glob("*.md")
    )
    form_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(guide_paths)
    )

    assert '"recommended": true' not in form_text
    assert "(Recommended)" not in form_text
    assert (
        "Leave every field and option initially unset" in form_text
        or "Leave every worksheet answer blank" in form_text
    )
    assert "do not mark the passing outcome as recommended" in form_text


def test_employee_validation_uses_stable_remediation_contract() -> None:
    import workday_connect_contracts as contracts

    text = (_WORKDAY_DA / "verify-connection.md").read_text(
        encoding="utf-8"
    )
    normalized = " ".join(text.split())

    documented_ids = set(re.findall(r"`(WD-E2E-(?:\d{3}))`", text))
    assert documented_ids == set(contracts.EMPLOYEE_VALIDATION_REMEDIATIONS)
    documented_result_ids = dict(
        re.findall(
            r"\|\s*(Failed - [^|]+?)\s*\|\s*`(WD-E2E-\d{3})`\s*\|",
            text,
        )
    )
    assert documented_result_ids == contracts.EMPLOYEE_VALIDATION_RESULT_IDS
    documented_surfaces = {
        value
        for value in re.findall(r"`([a-z]+(?:-[a-z]+)*)`", text)
        if value in contracts.EMPLOYEE_VALIDATION_FAILURE_SURFACES
    }
    assert documented_surfaces == set(
        contracts.EMPLOYEE_VALIDATION_FAILURE_SURFACES
    )
    surface_section = text.split(
        '"header": "Failure surface"',
        maxsplit=1,
    )[1].split("Map those choices respectively to", maxsplit=1)[0]
    surface_labels = re.findall(
        r'\{ "label": "([^"]+)" \}',
        surface_section,
    )
    documented_surface_choices = dict(
        zip(
            surface_labels,
            re.findall(
                r"`([a-z]+(?:-[a-z]+)*)`",
                text.split("Map those choices respectively to", maxsplit=1)[1],
            )[: len(surface_labels)],
            strict=True,
        )
    )
    assert (
        documented_surface_choices
        == contracts.EMPLOYEE_VALIDATION_FAILURE_SURFACE_CHOICES
    )
    assert "`failureCategory`" not in text
    assert "Canonical `remediation`" not in text
    assert "Do not invent a remediation ID" in normalized
    assert "derives the safe category and canonical remediation" in normalized
    assert "migrates existing three-field failure files" in normalized
    assert "legacy free-form remediation text is discarded" in normalized
    assert "cannot publish or deploy the agent, impersonate an employee" in normalized
    assert "Maker smoke test before publishing" in text
    assert "without publishing the agent" in text
    assert '"header": "Maker smoke test"' in text
    assert "does not complete Employee validation" in normalized
    assert "Non-maker employee validation after deployment" in text
    assert "deployed ESS HR agent in Microsoft 365 Chat" in text
    assert "required employee-owned Workday connections" in text
    assert "Do not reuse the maker's connections or credentials" in text
    assert normalized.index('"header": "Maker smoke test"') < normalized.index(
        "publish the ESS HR agent"
    )
    assert normalized.index("publish the ESS HR agent") < normalized.index(
        "begin-employee-test"
    )
    assert "workday_connect.py begin-employee-test" in text
    assert text.index("begin-employee-test") < text.index(
        '"header": "Employee test result"'
    )
    assert '"header": "Tested scenario"' not in text
    assert "Which read-only Workday scenario" not in text
    assert "Do not ask a second question about which scenario was used" in normalized
    assert "Provide only `testUserCategory`, `timestamp`" in text
    assert "start a bounded test attempt" in normalized
    assert "final readiness" in text
    assert "not required to exercise both the main and REST runtime flows" in (
        normalized
    )
    assert "Do not automatically ask the employee to repeat a scenario" in (
        normalized
    )
    assert "rerun `record-validation` with the same evidence file" in normalized


def test_controller_reads_json_payload_from_file(tmp_path: Path) -> None:
    import workday_connect as controller

    payload = {
        "value": "customer text with 'quotes'; $(not-a-command)",
    }
    path = tmp_path / "payload.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert controller._json_input(
        argparse.Namespace(discovery_file=path, discovery_json=None),
        "discovery",
        "test discovery",
    ) == payload


def test_employee_validation_documents_attempt_abandonment() -> None:
    text = (_WORKDAY_DA / "verify-connection.md").read_text(
        encoding="utf-8"
    )

    assert "abandon-employee-test" in text


@pytest.mark.parametrize(
    "command,option",
    [
        ("prepare-connections-approve", "--plan-json"),
        ("record-agent-binding", "--attachment-json"),
        ("record-validation-failure", "--evidence-json"),
    ],
)
def test_new_commands_do_not_accept_inline_json(
    command: str,
    option: str,
) -> None:
    import workday_connect as controller

    with pytest.raises(SystemExit):
        controller.build_parser().parse_args([command, option, "{}"])


def test_every_phase_dispatch_target_exists_and_schema_is_reference_only() -> None:
    skill = (_WORKDAY_DA / "SKILL.md").read_text(encoding="utf-8")
    dispatch_targets = re.findall(r"-> read `([^`]+\.md)`", skill)

    assert dispatch_targets
    assert all((_WORKDAY_DA / target).is_file() for target in dispatch_targets)
    assert "Use `shared/config-schema.md` as the internal state" in skill
    assert "not a customer-executed phase" in skill


def test_customer_messages_exclude_internal_implementation_terms() -> None:
    skill = (_WORKDAY_DA / "SKILL.md").read_text(encoding="utf-8")
    activation = (
        _REPO_ROOT
        / "solutions"
        / "ess-maker-skills"
        / "src"
        / "skills"
        / "connect"
        / "workday"
        / "actions"
        / "activate-workday-topics.md"
    ).read_text(encoding="utf-8")
    redirect = (
        _REPO_ROOT
        / "solutions"
        / "ess-maker-skills"
        / "src"
        / "skills"
        / "connect"
        / "workday"
        / "actions"
        / "wire-user-context-redirect.md"
    ).read_text(encoding="utf-8")
    readiness = skill.split("> Here's who may be needed", 1)[1].split(
        "\nRun:",
        1,
    )[0]
    activation_message = activation.split("**Message:**", 1)[1].split(
        "**End message.**",
        1,
    )[0]
    redirect_message = redirect.split("**Message:**", 1)[1].split(
        "**End message.**",
        1,
    )[0]
    customer_text = readiness + activation_message + redirect_message

    for internal_term in (
        "controller",
        "component-map",
        "MinimalBot",
        "plan hash",
        "schema",
        "checkpoint",
        "CloudFlow",
        "delegatedauthorization",
    ):
        assert internal_term.casefold() not in customer_text.casefold()
    assert "Customer-facing language contract" in skill
    assert "Never show or narrate them" in skill


def test_preflight_is_read_only_and_package_install_starts_connections() -> None:
    text = (_WORKDAY_DA / "install-extension.md").read_text(encoding="utf-8")
    connections = (_WORKDAY_DA / "configure-power-platform.md").read_text(
        encoding="utf-8"
    )

    assert "workday_connect.py preflight" in text
    assert "verifies the exact Dataverse URL directly" in text
    assert "It never installs the package" in text
    assert "preflight-approve" not in text
    assert "--install-plan-hash" not in text
    assert "workday_connect.py prepare-connections" in connections
    assert "prepare-connections-approve --plan-file" in connections
    assert "--install-plan-hash" in connections
    assert "installs through PAC, and rereads Dataverse" in connections


def test_connections_are_proven_before_runtime_apply() -> None:
    text = (_WORKDAY_DA / "configure-power-platform.md").read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert text.index("## Connections") < text.index("## Runtime approval and apply")
    assert "runtime-plan" in text
    assert "record-connections" in text
    assert "record-connections --evidence-json" not in text
    assert "manual connection evidence" in text
    assert "--confirm-workday-target" in text
    assert "Do not begin with a yes/no question" in text
    assert text.count("workday_connect.py record-connections") == 2
    assert "`prod` -> `https://make.powerautomate.com`" in text
    assert "`preprod` -> `https://make.preprod.powerautomate.com`" in text
    assert "`test` -> `https://make.test.powerautomate.com`" in text
    assert "Never send a non-production environment to the production maker portal" in text
    assert (
        "{POWER_AUTOMATE_ORIGIN}/environments/{ENVIRONMENT_ID}/connections/"
        "available/shared_workdaysoap"
    ) in text
    assert (
        "{POWER_AUTOMATE_ORIGIN}/environments/{ENVIRONMENT_ID}/connections/"
        "available/shared_commondataserviceforapps"
    ) in text
    assert "Create Workday connection" in text
    assert "Create Microsoft Dataverse connection" in text
    assert text.index("Create Microsoft Dataverse connection") < text.index(
        "Create Workday connection"
    )
    assert "Treat the two physical connections as sequential gates" in text
    assert "The controller checks Microsoft Dataverse first" in text
    assert "show only the Microsoft Dataverse guidance" in text
    assert "continue\nto Workday only when Microsoft Dataverse resolves exactly" in text
    assert "Connections list fallback" in text
    assert "Power Apps maker portal" in text
    assert "Microsoft Entra ID Integrated" in text
    assert "**Display name (optional)**" in text
    assert "**Authentication type**" in text
    assert (
        "**Microsoft Entra resource URL (Application ID URI) \\***"
        in text
    )
    assert "Do not use the Entra application ID URI beginning with `api://`" in text
    assert "**Workday OAuth token URL \\***" in text
    assert "**Workday OAuth client ID \\***" in text
    assert "**SOAP base URL \\***" in text
    assert "**REST base URL**" in text
    assert "**Tenant name \\***" in text
    assert "not the Microsoft Entra application ID" in text
    assert "ESS Workday Runtime**" in text
    assert "ESS Workday Runtime REST Execution**" in text
    assert "Do not ask the maker or administrator to provide them again" in normalized
    assert "Do not request or collect a Workday password" in text
    assert "Reuse a healthy existing connection" in text
    assert "Do not open Copilot Studio Connection Settings yet" in text
    assert "Do not provide the agent Connection Settings link" in text
    assert "Do not diagnose the flow authorization script as failed" in text
    assert "keep the customer in the Power Apps **Connections** page" in text
    assert "runtime-apply" in text
    assert "applied.verified: true" in text
    assert "connection-references-bound" in text
    assert "runtime-flows-active" in text
    assert "delegated-authorization-configured" in text
    assert text.index("applied.verified: true") < text.index(
        "Only now direct the maker"
    )
    assert "CLI credential cache and the\nCopilot Studio browser session are separate" in text
    assert "show the exact recorded\nPower Platform maker account" in text
    assert "record-agent-binding" in text
    assert "--attachment-file" in text
    assert text.index("runtime-apply") < text.index("record-agent-binding")
    assert "--checkpoint WD-CONN-013" not in text
    assert "run separate readiness commands" in text
    assert "confirmation twice" in text
    assert "Do not substitute an unscoped" in normalized
    assert "one Dataverse token" in normalized
    assert "delegated" in text
    assert "User Context V2" in text
    assert "activate-workday-topics.md" in text
    assert text.index("Allow permission") < text.index("activate-workday-topics.md")
    assert text.index("activate-workday-topics.md") < text.index(
        "wire-runtime-template-config.md"
    )
    assert text.index("wire-runtime-template-config.md") < text.index(
        "wire-user-context-redirect.md"
    )


def test_workday_admin_handoff_is_provider_first_and_completion_gated() -> None:
    text = (_WORKDAY_DA / "configure-tenant.md").read_text(encoding="utf-8")

    packet = text.index("workday_connect.py workday-admin-packet")
    provider_question = text.index("`identityProviderQuestion` from the packet")
    unsupported_stop = text.index(
        "For **Okta**, **Ping Identity**, or **Another sign-in provider**"
    )
    capture_table = text.index("Before the numbered tasks")
    existing_handoff = text.index("### Existing Microsoft Entra federation handoff")
    greenfield_handoff = text.index("### New Microsoft Entra federation handoff")
    completion = text.index(
        "Has the Workday administrator completed every applicable task"
    )
    form = text.index('"header": "SAML row settings"')

    assert packet < provider_question < unsupported_stop
    assert unsupported_stop < capture_table < existing_handoff < greenfield_handoff
    assert greenfield_handoff < completion < form
    assert "This question selects a safe handoff branch" in text
    assert "Do not show the completion question\n  or response form" in text
    assert "Only after **Yes**\nmay the skill collect evidence" in text
    assert "share this whole section" in text
    assert "both the capture guide and\nthe return worksheet" in text
    assert "Leave every cell in **Your\ntenant values** blank" in text
    assert "do not repeat an **Information to return to the maker**" in text
    assert "--substage handoff-presented" in text
    assert "ending at /ccx/service, without the tenant name" in text
    assert "using steps 2 through 7" not in text
    assert '"header": "Identity provider"' not in text


def test_workday_topic_activation_uses_complete_mapped_scope() -> None:
    action = (
        _REPO_ROOT
        / "solutions"
        / "ess-maker-skills"
        / "src"
        / "skills"
        / "connect"
        / "workday"
        / "actions"
        / "activate-workday-topics.md"
    ).read_text(encoding="utf-8")
    redirect = (
        _REPO_ROOT
        / "solutions"
        / "ess-maker-skills"
        / "src"
        / "skills"
        / "connect"
        / "workday"
        / "actions"
        / "wire-user-context-redirect.md"
    ).read_text(encoding="utf-8")

    assert ".component-map.json" in action
    assert "{AGENT_SCHEMA}.topic.EmployeeUpdatePhoneNumber" in action
    assert "{AGENT_SCHEMA}.topic.GetReferenceData" in action
    assert "all 23" in " ".join(action.split())
    assert "--activate --dry-run" in action
    assert "--activate --yes" in action
    assert "state` and `status` to `Active`" in action
    assert "record-topic-activation" in action
    assert "do not treat them as an activation failure" in action
    assert "--activate" not in redirect


def test_topic_activation_precedes_runtime_template_and_user_context_wiring() -> None:
    configure = (
        _WORKDAY_DA / "configure-power-platform.md"
    ).read_text(encoding="utf-8")
    action = (
        _REPO_ROOT
        / "solutions"
        / "ess-maker-skills"
        / "src"
        / "skills"
        / "connect"
        / "workday"
        / "actions"
        / "wire-runtime-template-config.md"
    ).read_text(encoding="utf-8")

    assert configure.index("activate-workday-topics.md") < (
        configure.index("wire-runtime-template-config.md")
    )
    assert configure.index("wire-runtime-template-config.md") < (
        configure.index("wire-user-context-redirect.md")
    )
    assert "only after all reviewed Workday topics are enabled" in action
    assert "workday-topics-activated" in action
    assert "Conversation Start" in action
    assert "immediately before User Context Validate" in action
    assert "remove only that exact obsolete nested" in action
    assert "record-runtime-template-wiring" in action
    assert "runtime-template-configured" in action
    assert "continue without\nasking for a separate publish confirmation" in action
    assert "Publish this scoped Workday conversation-start change" not in action
    assert "vscode_askQuestions" not in action
    assert "re-reads the current live topics" in action
    assert "Do not ask the maker to choose an overwrite strategy" in action


def test_user_context_redirect_reconciles_without_publish_prompt() -> None:
    action = (
        _REPO_ROOT
        / "solutions"
        / "ess-maker-skills"
        / "src"
        / "skills"
        / "connect"
        / "workday"
        / "actions"
        / "wire-user-context-redirect.md"
    ).read_text(encoding="utf-8")

    assert "continue without\nasking for a separate publish confirmation" in action
    assert "Publish this scoped User Context topic change" not in action
    assert "vscode_askQuestions" not in action
    assert "re-reads the current live topic" in action
    assert "exact\nredirect is already live" in action
    assert "compatible empty scaffold" in action
    assert "Do not ask the maker to choose an overwrite\nstrategy" in action


def test_readiness_requires_real_employee_runtime_evidence() -> None:
    text = (_WORKDAY_DA / "verify-connection.md").read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "real signed-in employee scenario" in text
    assert "Copilot Studio Test pane" in text
    assert "Microsoft 365 Chat" in text
    assert "employee-owned Workday connections" in text
    assert "returns real" in text
    assert "without an unexpected repeated sign-in" in text
    assert "Never record employee data or credentials" in normalized
    assert "Do not reset completed phases" in normalized


def test_capability_claims_match_controller_surface() -> None:
    skill = (_WORKDAY_DA / "SKILL.md").read_text(encoding="utf-8")
    entra = (_WORKDAY_DA / "provision-entra-app.md").read_text(encoding="utf-8")
    tenant = (_WORKDAY_DA / "configure-tenant.md").read_text(encoding="utf-8")
    power_platform = (_WORKDAY_DA / "configure-power-platform.md").read_text(
        encoding="utf-8"
    )
    employee = (_WORKDAY_DA / "verify-connection.md").read_text(encoding="utf-8")

    normalized = {
        "skill": " ".join(skill.split()),
        "entra": " ".join(entra.split()),
        "tenant": " ".join(tenant.split()),
        "power_platform": " ".join(power_platform.split()),
        "employee": " ".join(employee.split()),
    }

    assert "## Capability contract" in skill
    assert "## Tenant foundation and deployment scope" in skill
    assert (
        "must not by itself require the Entra or Workday administrators"
        in (normalized["skill"])
    )
    assert "show this readiness briefing on every invocation" in normalized["skill"]
    for required_role in (
        "Power Platform Environment Maker",
        "Application Administrator or Cloud Application Administrator",
        "Workday Administrator",
        "Dataverse System Administrator",
        "Workday test employee",
    ):
        assert required_role in skill
    assert (
        "isn't ready until the signed-in Workday scenario succeeds"
        in (normalized["skill"])
    )
    assert "Claim an automated change only after" in normalized["skill"]
    assert "does not create or modify the Entra application" in (normalized["entra"])
    assert "record-entra" in normalized["entra"]
    assert "Do not silently reuse Entra configuration" in entra
    assert "does not authenticate the maker to Microsoft Graph" in normalized["entra"]
    assert "Role-aware execution will trigger those live API checks later" in (
        normalized["entra"]
    )
    assert "Expose an API" in entra
    assert "Sign SAML response and assertion" in entra
    assert "administrator-attestation" in entra
    assert "This phase never modifies Workday" in normalized["tenant"]
    assert "Create x509 Public Key" in tenant
    assert "Client Grant Type" in tenant
    assert "Include Workday Owned Scope" in tenant
    assert "Confirm network readiness" in tenant
    assert (
        "does not create physical connector connections"
        in (normalized["power_platform"])
    )
    assert (
        "existing Dataverse readiness coverage"
        in normalized["power_platform"]
    )
    assert "WD-REST-002" not in power_platform
    assert "WD-CONN-013" not in power_platform
    assert (
        "do not treat them alone as proof of a broken package"
        in (normalized["power_platform"])
    )
    assert (
        "signed-in employee scenario remains the functional confirmation"
        in (normalized["power_platform"])
    )
    assert "These are real automated changes" in (normalized["power_platform"])
    assert "The skill cannot publish or deploy the agent" in normalized["employee"]


def test_runtime_apply_persists_verified_stages_before_later_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import workday_connect as controller
    import workday_connect_model as model

    store = controller.WorkdayConnectStore(tmp_path)
    store.initialize()
    for phase_id in ("preflight", "entra", "workday-admin", "connections"):
        for action in model.PHASE_REQUIRED_ACTIONS[phase_id]:
            store.complete_action(
                phase_id,
                action,
                evidence={"outcome": "verified"},
            )
        store.set_phase_status(phase_id, "complete")

    def fail_after_two_stages(_state, **kwargs):
        recorder = kwargs["stage_recorder"]
        recorder(
            "connection-references-bound",
            {"outcome": "verified", "provenance": "Dataverse reread"},
        )
        recorder(
            "runtime-flows-active",
            {"outcome": "verified", "provenance": "Dataverse reread"},
        )
        raise controller.WorkdayConnectRuntimeError("authorization failed")

    monkeypatch.setattr(
        controller,
        "run_runtime_operation",
        fail_after_two_stages,
    )
    args = argparse.Namespace(
        plan_hash="approved",
        workday_connection_id=None,
        dataverse_connection_id=None,
    )

    with pytest.raises(
        controller.WorkdayConnectRuntimeError,
        match="authorization failed",
    ):
        controller._runtime_apply(args, store)

    phase = store.load()["phases"]["runtime"]
    assert phase["status"] == "active"
    assert phase["completedActions"] == [
        "connection-references-bound",
        "runtime-flows-active",
    ]
    assert {record["action"] for record in phase["evidence"]} == set(
        phase["completedActions"]
    )
