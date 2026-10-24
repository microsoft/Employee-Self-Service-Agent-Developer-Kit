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
    / "connect"
    / "workday"
)


def test_connect_prompt_allows_phase_walkthroughs_and_requires_them_before_questions():
    prompt = (
        _REPO_ROOT / "solutions" / "ess-maker-skills" / ".github" / "prompts"
        / "connect.prompt.md"
    ).read_text(encoding="utf-8")
    normalized = " ".join(prompt.split())
    assert "a Message block is not required" in normalized
    assert "walkthrough in full before its confirmation" in normalized
    assert "before showing another question" in normalized
    assert "repair guidance before **Check again**" in normalized
    assert "controller success and error JSON directly" in normalized
    assert "The ONLY text the user sees is Message blocks" not in normalized
    assert "If there is no Message block for a situation, stay silent" not in normalized


def test_portal_and_test_pane_walkthroughs_cannot_be_replaced_with_questions():
    connections = (_WORKDAY_DA / "configure-power-platform.md").read_text(encoding="utf-8")
    validation = (_WORKDAY_DA / "verify-connection.md").read_text(encoding="utf-8")
    assert connections.index("Show these instructions before offering **Check again**") < (
        connections.index("Show a **Create Microsoft Dataverse connection**")
    )
    assert connections.index("Show this complete click path before asking") < (
        connections.index("3. Select **See details**.")
    )
    assert "before showing its confirmation or **Check again** question" in (
        " ".join(connections.split())
    )
    assert validation.index("Render the following numbered walkthrough") < (
        validation.index("open a new Test pane conversation")
    ) < validation.index('"header": "Maker smoke test"')
    assert "Do not ask whether the scenario passed before explaining how to run it." in (
        " ".join(validation.split())
    )
    assert "this walkthrough again before the question" in " ".join(validation.split())


def test_orchestrator_resumes_from_controller_status() -> None:
    text = (_WORKDAY_DA / "SKILL.md").read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "python scripts/workday_connect.py status" in text
    assert "nextPhaseId" in text
    assert "nextPhaseSummary" in text
    assert "What happens in this phase:" in text
    assert "must not be collapsed into a one-line phase list" in normalized
    assert "Do not\nreplace the phase explanation with only" in text
    assert "do not create, copy, update, or infer status from a Markdown" in (
        normalized
    )
    assert "resume the same blocker" in text
    assert "controller status is `ready`" in text


def test_promotion_request_does_not_assert_completed_promotion() -> None:
    skill = " ".join((_WORKDAY_DA / "SKILL.md").read_text(encoding="utf-8").split())
    assert "is not evidence that promotion happened" in skill
    assert "does not promote or publish an agent" in skill
    assert "Yes, promotion is complete - check again" in skill
    assert "No, I need to complete promotion first" in skill
    assert "do not ask it again" in skill
    assert "same Power Platform environment as Dev" in skill
    assert "Reuse a supplied valid environment selection" in skill
    assert "Choose another environment" in skill


def test_ready_dev_reentry_resolves_realm_before_showing_any_plan() -> None:
    skill = " ".join((_WORKDAY_DA / "SKILL.md").read_text(encoding="utf-8").split())
    start = skill.split("## Start or resume", 1)[1]
    resolution = start.split("### Choose the presentation", 1)[0]

    assert "before showing any plan, role table, progress table" in resolution
    assert resolution.index("python scripts/workday_connect.py status") < (
        resolution.index("discover-realm-target --realm test")
    )
    assert resolution.index("discover-realm-target --realm prod") < (
        resolution.index("If controller status is `ready`")
    )
    assert "run `status` again and use the newly verified `activeTargetRealm`" in resolution
    assert "Do not render the previous realm's progress or completion first" in resolution
    assert "do not show a speculative Test or Production plan" in resolution
    assert "go directly to **Completion** and finish this invocation" in resolution
    assert "Do not show the opening role table, `progressText`, a phase plan, or a participant question" in resolution
    assert "A bare Connect request after Development is Ready does not restart Development" in resolution
    assert "Do not discover or activate the next realm without the maker's explicit intent" in resolution
    assert start.index("If controller status is `ready`") < (
        start.index("> Here's who may be needed")
    )


def test_promoted_realm_plan_contains_only_verified_unfinished_work() -> None:
    skill = " ".join((_WORKDAY_DA / "SKILL.md").read_text(encoding="utf-8").split())
    presentation = skill.split("### Choose the presentation", 1)[1].split(
        "### First Development start only", 1
    )[0]

    assert "**Workday connection plan - Test**" in presentation
    assert "**Workday connection plan - Production**" in presentation
    assert "only after that realm has been resolved by the controller" in presentation
    assert "including only phases whose `status` is not `complete`" in presentation
    assert "Never show the Development opening briefing, capability table, or six-row `progressText`" in presentation
    assert "even on the first invocation for that promoted target" in presentation
    assert "narrow this list to the still-unfinished work" in presentation
    assert "`foundationReused: true`" in presentation
    assert "unfinished **Connections**, **Runtime configuration**, and **Maker validation**" in presentation
    assert "Do not include completed Preflight or administrator phases" in presentation
    assert "Development's completed connection remains unchanged" in presentation
    assert "Do not claim reuse or promise the three-phase promoted plan until the controller confirms it" in presentation


def test_full_briefing_and_progress_are_limited_to_first_dev_start() -> None:
    skill = " ".join((_WORKDAY_DA / "SKILL.md").read_text(encoding="utf-8").split())
    presentation = skill.split("### Choose the presentation", 1)[1]
    continuation = skill.split("### Continue the current unfinished phase", 1)[1]

    assert "This table is an internal reference, not an opening customer plan" in skill
    assert "Only when `activeTargetRealm` is `dev`, the lifecycle is not ready, all phases are still pending" in presentation
    assert "no administrator evidence has been captured" in presentation
    assert "do not repeat the full role table, full progress table" in presentation
    assert "Only on the first Development start, render the returned `progressText`" in continuation
    assert "Omit it on every resume, ready lifecycle, and Test or Production plan" in continuation
    assert "not a recap of every completed phase" in continuation


def test_administrator_handoffs_explain_readable_files_and_all_corrections() -> None:
    for filename in ("provision-entra-app.md", "configure-tenant.md"):
        text = " ".join((_WORKDAY_DA / filename).read_text(encoding="utf-8").split())
        assert "Worksheet - Detailed" in text
        assert "exact successful answer" in text
        assert "information protection administrator" in text
        assert "Do not share passwords or bypass required protections" in text
        assert "details.fieldErrors" in text
        assert "same workbook" in text


def test_role_availability_is_state_aware_at_phase_boundary() -> None:
    from workday_connect_entra_contracts import (
        ENTRA_ADMIN_COMPLETION_QUESTION,
        ENTRA_ADMIN_ENGAGEMENT_QUESTION,
    )

    skill = (_WORKDAY_DA / "SKILL.md").read_text(encoding="utf-8")
    entra = (_WORKDAY_DA / "provision-entra-app.md").read_text(encoding="utf-8")
    tenant = (_WORKDAY_DA / "configure-tenant.md").read_text(encoding="utf-8")
    normalized_skill = " ".join(skill.split())
    normalized_entra = " ".join(entra.split())

    briefing = skill.index("> Here's who may be needed")
    status = skill.index("python scripts/workday_connect.py status")
    attestation = skill.index('"header": "Required access"')
    dispatch = skill.index("Dispatch from `nextPhaseId`")

    assert status < briefing < attestation < dispatch
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
    expected_privilege_forms = [
        (
            "Connection creation privilege",
            (
                "Do you have the Power Platform Environment Maker privilege "
                "and package installation access to create the Workday "
                "connections?"
            ),
        ),
        (
            "Maker validation privilege",
            (
                "Do you have the Environment Maker privilege to perform "
                "maker validation in the Copilot Studio Test pane?"
            ),
        ),
    ]
    for header, question in expected_privilege_forms:
        assert [
            {
                "header": header,
                "question": question,
                "options": [
                    {
                        "label": (
                            "Yes, I have the required privilege and access"
                        )
                    },
                    {
                        "label": (
                            "No, I do not have the required privilege or access"
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
    assert "When `nextPhaseId` is `preflight` or `runtime`" in skill
    ready_branch = normalized_skill.split(
        "If controller status is `ready`", 1
    )[1].split("For a non-ready lifecycle", 1)[0]
    assert "go directly to **Completion** and finish this invocation" in ready_branch
    assert "Do not show the opening role table, `progressText`, a phase plan, or a participant question" in ready_branch
    for phase_id in (
        "preflight",
        "entra",
        "workday-admin",
        "connections",
        "runtime",
        "maker-validation",
    ):
        assert re.search(
            rf"^\|\s*`{re.escape(phase_id)}`\s*\|",
            skill,
            re.MULTILINE,
        )
    assert "Leave every selection unset" in skill
    assert (
        "None is proof that the signed-in account has the required role"
        in normalized_skill
    )
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
        "healthy reused tenant foundation on a controller-verified Test or "
        "Production promotion continues at Connections"
        in normalized_skill
    )
    assert (
        "always require fresh Workday administrator confirmation and a "
        "completed Workday administrator workbook"
        in " ".join(tenant.split())
    )
    assert "tenantFoundationReused: true" not in tenant
    assert "When `nextPhaseId` is `entra`, dispatch" in skill
    assert "presents the guided handoff" in skill
    assert "stop before dispatching the next phase" in normalized_skill
    assert (
        "no phase progress or target configuration was changed"
        in normalized_skill
    )
    assert "do not offer to bypass the role requirement" in " ".join(skill.split())
    assert "rerun the skill using the authorized maker account" in normalized_skill
    assert (
        "do not repeat the question while `nextPhaseId` remains unchanged"
        in " ".join(skill.split())
    )
    assert "alternative accepted\nroles, not two required people" in entra
    assert "Do not silently reuse Entra configuration" in entra
    assert "must not authenticate the maker to Graph" in skill
    assert "reread Graph" not in skill
    assert "read-only discovery" not in skill
    assert '"header": "Microsoft Entra app administrator"' in entra
    assert "engagement answer is not configuration evidence" in entra
    assert ENTRA_ADMIN_ENGAGEMENT_QUESTION in entra
    assert "Information to return to the maker" in entra
    assert ENTRA_ADMIN_COMPLETION_QUESTION in normalized_entra
    assert "consent-capable administrator" not in (
        ENTRA_ADMIN_ENGAGEMENT_QUESTION
    )
    assert "same person does not need both" in normalized_entra
    assert 'not a general "cloud administrator."' in normalized_entra
    assert "separate consent-capable administrator only" in normalized_entra
    assert "does not need to arrange\none up front" in entra
    assert "Render `packet.consentNote` exactly here" in entra
    assert "Yes, that administrator is engaged" in entra
    assert "No, I still need to engage that administrator" in entra
    assert (
        "Do not add a second engagement question here"
        in " ".join(tenant.split())
    )
    assert "Have you looped in the Workday administrator" in tenant
    assert "## One-way administrator handoff" in skill
    assert "Microsoft Entra sign-off must finish first" in skill
    assert "Only then may the Workday administrator phase begin" in skill
    assert "must not ask the maker to\n   reopen Entra" in skill
    assert "different\npeople" in skill


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
    assert "guided handoff to\nthe Entra app administrator" in entra


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
    assert (
        "do not mark the passing option as recommended"
        in form_text.casefold()
    )


def test_maker_validation_ends_guided_lifecycle() -> None:
    text = (_WORKDAY_DA / "verify-connection.md").read_text(
        encoding="utf-8"
    )
    normalized = " ".join(text.split())

    assert "# Phase 6 - Maker validation" in text
    assert "without publishing the agent" in text
    assert '"header": "Maker smoke test"' in text
    assert '"testUserCategory": "maker"' in text
    assert '"remediationId": "WD-E2E-006"' in text
    assert "record-validation-failure --evidence-file" in text
    assert "retest that same named scenario" in text
    assert "lifecycleComplete: true" in text
    assert "begin-employee-test" not in text
    assert "abandon-employee-test" not in text
    assert (
        "do not wait for power automate run-history evidence"
        in normalized.casefold()
    )
    assert "Promote the agent from Development to Test when ready" in text
    assert "Promote the agent from Test to Production when ready" in text
    assert "Publish and deploy the Production agent when ready" in text
    assert "employee establish their own Workday connections" in normalized
    assert "Do not add Production employee-adoption steps" in text
    assert "outside this guided setup lifecycle" in normalized


def test_workday_completion_does_not_return_to_setup() -> None:
    finish = " ".join(
        (_WORKDAY_DA / "verify-connection.md").read_text(encoding="utf-8").split()
    )
    orchestrator = " ".join(
        (_WORKDAY_DA / "SKILL.md").read_text(encoding="utf-8").split()
    )
    assert "render its `completionMessage` first" in finish
    assert "all six steps and the maker Test pane validation are complete" in finish
    assert "End this Connect execution after its completion message" in finish
    assert "do not invoke `src/skills/foundation-setup/SKILL.md` here" in finish
    assert "Do not invoke Setup between phases or at completion" in orchestrator
    assert "Do not ask the maker to run Connect again for this completed realm" in orchestrator
    assert "Optional later - not part of this completed connection" in orchestrator
    assert "Do not start promotion or another realm without an explicit maker request" in orchestrator
    for text in (finish, orchestrator):
        assert "Resume after an integration completes" not in text
        assert "I'm returning to Setup" not in text

    preflight = " ".join(
        (_WORKDAY_DA / "install-extension.md").read_text(encoding="utf-8").split()
    )
    assert "Never invoke Setup automatically between Workday phases" in preflight


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


def test_maker_validation_excludes_retired_runtime_evidence_contract() -> None:
    text = (_WORKDAY_DA / "verify-connection.md").read_text(
        encoding="utf-8"
    )
    normalized = " ".join(text.split()).casefold()

    assert "begin-employee-test" not in normalized
    assert "abandon-employee-test" not in text
    assert "runtime-evidence" not in text


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
        "\n### Continue the current unfinished phase",
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
    maker_connection_steps = text.split(
        "Connect both maker-visible entries",
        1,
    )[1].split(
        "Internal execution note",
        1,
    )[0]
    assert "displayed as **Workday**" in maker_connection_steps
    assert "ESS Workday Runtime" not in maker_connection_steps
    assert "ESS Workday Runtime REST Execution" not in maker_connection_steps
    assert maker_connection_steps.index("Select **Connect**") < (
        maker_connection_steps.index(
            "Select the already-created Workday connection"
        )
    )
    assert maker_connection_steps.index(
        "Select the already-created Workday connection"
    ) < maker_connection_steps.index("Select **See details**")
    assert maker_connection_steps.index("Select **See details**") < (
        maker_connection_steps.index("Open **Connection parameters**")
    )
    assert maker_connection_steps.index("Open **Connection parameters**") < (
        maker_connection_steps.index(
            "Enable **Allow permission to share parameters**"
        )
    )
    assert "Select **Manage**" not in maker_connection_steps
    assert "enabled under See details > Connection parameters for both?" in text
    assert "enabled under Manage" not in text
    assert "both entries displayed as Workday" in text
    assert "Confirm Workday connection" in text
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
    assert "run separate readiness commands" in normalized
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
    normalized = " ".join(text.split())

    packet = text.index("workday_connect.py workday-admin-packet")
    provider_question = text.index("`identityProviderQuestion` from the packet")
    non_entra_branch = text.index(
        "For **Okta**, **Ping Identity**, or **Another sign-in provider**"
    )
    workbook = text.index("Share `workbookFile`")
    existing_handoff = text.index("### Existing Microsoft Entra federation handoff")
    coexistence_handoff = text.index(
        "### Existing non-Entra federation coexistence or transition handoff"
    )
    greenfield_handoff = text.index("### New Microsoft Entra federation handoff")
    completion = text.index(
        "Has the Workday administrator completed their task"
    )
    form = text.index('"header": "SAML row settings"')

    assert packet < provider_question < non_entra_branch
    assert non_entra_branch < workbook < existing_handoff
    assert existing_handoff < coexistence_handoff < greenfield_handoff
    assert greenfield_handoff < completion < form
    assert "This question selects a safe handoff branch" in text
    assert "Do not return to Entra or re-engage the Entra app administrator" in (
        normalized
    )
    assert "resume the same handoff after approval" in normalized
    assert "Only after **Yes**\nmay the skill collect evidence" in text
    assert "share these steps and the workbook" in text
    assert "workbook is the single capture worksheet" in normalized
    assert "fill every cell in the **Your tenant values** column" in normalized
    assert "Upload the completed Workday administrator workbook" in text
    assert (
        "do not repeat an **Information to return to the maker**"
        in normalized
    )
    assert "This phase starts only after Microsoft Entra sign-off is complete" in text
    assert "Do not direct the maker back to the Entra" in text
    assert "already delivered through the approved customer channel" in text
    assert "Do not open Entra or request another" in text
    assert "Do not return to the Entra phase" in text
    assert "In Entra, open" not in text
    assert "Workday and identity administrators" not in text
    assert "identity administrator to identify" not in text
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
    assert "Refresh the Copilot\nStudio page" in action
    assert '"header": "Confirm Workday topics"' in action
    assert "all Workday topics show as On" in action
    assert action.index("Confirm Workday topics") < action.index(
        "record-topic-activation"
    )
    assert "does not replace the\ncontroller's live reread" in action
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


def test_maker_validation_lists_non_maker_work_as_post_skill_steps() -> None:
    text = (_WORKDAY_DA / "verify-connection.md").read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "Copilot Studio Test pane" in text
    assert "Microsoft 365 Chat" in text
    assert "their own Workday connections" in text
    assert "returns real" in text
    assert "without an unexpected repeated sign-in" in text
    assert "Do not wait for those results" in text
    assert "keep the Workday skill open" in normalized


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
    assert "On the first start of a non-ready Development lifecycle" in normalized["skill"]
    assert "On resume, show the current phase and only its remaining participants" in (
        normalized["skill"]
    )
    assert "do not repeat the full role table" in normalized["skill"]
    for required_role in (
        "Power Platform Environment Maker",
        "Application Administrator or Cloud Application Administrator",
        "Workday Administrator",
        "Dataverse System Administrator",
    ):
        assert required_role in skill
    assert (
        "guided lifecycle completes after the maker's Test pane scenario succeeds"
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
    assert "Confirm network readiness" not in tenant
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
        "maker's Copilot Studio Test pane scenario remains the functional "
        "confirmation"
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
        root=tmp_path,
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
