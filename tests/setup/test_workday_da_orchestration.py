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
    assert "Leave every field and option initially unset" in form_text
    assert "do not mark the passing outcome as recommended" in form_text


def test_employee_validation_uses_stable_remediation_contract() -> None:
    text = (_WORKDAY_DA / "verify-connection.md").read_text(
        encoding="utf-8"
    )
    normalized = " ".join(text.split())

    for remediation_id in (
        "WD-E2E-001",
        "WD-E2E-002",
        "WD-E2E-003",
        "WD-E2E-004",
        "WD-E2E-005",
        "WD-E2E-006",
        "WD-E2E-007",
        "WD-E2E-999",
    ):
        assert remediation_id in text
    assert "Do not invent a remediation ID" in normalized
    assert "rejects arbitrary IDs, mismatched categories" in normalized
    assert "cannot publish the agent, impersonate an employee" in normalized


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


@pytest.mark.parametrize(
    "command,option",
    [
        ("preflight-approve", "--plan-json"),
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


def test_preflight_is_one_identity_aware_operation() -> None:
    text = (_WORKDAY_DA / "install-extension.md").read_text(encoding="utf-8")

    assert "workday_connect.py preflight" in text
    assert "pins and verifies the resulting PAC account" in text
    assert "verifies the exact Dataverse URL directly" in text
    assert "requiresApproval: true" in text
    assert "preflight-approve --plan-file" in text
    assert "--install-plan-hash" in text
    assert "installs it only after exact-plan approval" in text
    assert "manual-install instruction" in text


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
    assert "Connections list fallback" in text
    assert "Power Apps maker portal" in text
    assert "Microsoft Entra ID Integrated" in text
    assert "**Microsoft Entra resource URL:**" in text
    assert "Do not use the Entra application\n  ID URI beginning with `api://`" in text
    assert "**Workday OAuth token URL:**" in text
    assert "**Client ID:**" in text
    assert "not the Microsoft Entra application ID" in text
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
    assert "Do not run `WD-CONN-013` separately" in text
    assert "confirmation twice" in text
    assert "Do not substitute an unscoped" in normalized
    assert "--connect-config" in text
    assert "one Dataverse token" in normalized
    assert "delegated" in text
    assert "User Context V2" in text
    assert "activate-workday-topics.md" in text
    assert text.index("Allow permission") < text.index("activate-workday-topics.md")


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
    assert "{AGENT_SCHEMA}.topic.Workday" in action
    assert "all 21 Workday dialog topics" in " ".join(action.split())
    assert "--activate --dry-run" in action
    assert "--activate --yes" in action
    assert "state` and `status` to `Active`" in action
    assert "record-topic-activation" in action
    assert "do not treat them as an activation failure" in action
    assert "--activate" not in redirect


def test_readiness_requires_real_employee_runtime_evidence() -> None:
    text = (_WORKDAY_DA / "verify-connection.md").read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "real signed-in employee scenario" in text
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
    assert "foundationReuse.eligible" in entra
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
    assert "reruns `WD-REST-002` and `WD-CONN-013`" in (normalized["power_platform"])
    assert (
        "do not treat them alone as proof of a broken package"
        in (normalized["power_platform"])
    )
    assert (
        "signed-in employee scenario remains the functional confirmation"
        in (normalized["power_platform"])
    )
    assert "These are real automated changes" in (normalized["power_platform"])
    assert "The skill cannot publish the agent" in normalized["employee"]


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
