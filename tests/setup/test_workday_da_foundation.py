# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Structural guards for the simplified Workday DA lifecycle."""

from pathlib import Path


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


def test_lifecycle_has_one_json_state_authority() -> None:
    skill = (_WORKDAY_DA / "SKILL.md").read_text(encoding="utf-8")
    schema = (_WORKDAY_DA / "shared" / "config-schema.md").read_text(
        encoding="utf-8"
    )

    assert "scripts/workday_connect.py" in skill
    assert ".local/connect/workday-da/config.json" in skill
    assert "must not edit this file directly" in schema
    assert '"schemaVersion": 9' in schema
    assert '"substage": "not-started"' in schema
    assert "config.pre-v9.json" in schema
    assert '"tenantFoundation": null' in schema
    assert "Markdown state mirror" in schema
    assert not (_WORKDAY_DA / "tasks.md").exists()
    assert not (_WORKDAY_DA / "shared" / "checklist-updater.md").exists()
    assert not (_WORKDAY_DA / "shared" / "permission-gate.md").exists()


def test_orchestrator_exposes_exactly_six_customer_phases() -> None:
    skill = (_WORKDAY_DA / "SKILL.md").read_text(encoding="utf-8")

    for phase in (
        "Preflight",
        "Microsoft Entra",
        "Workday administrator",
        "Connections",
        "Runtime configuration",
        "Employee validation",
    ):
        assert phase in skill
    assert "21" not in skill
    assert "DA1.1" not in skill
    assert "setupStatus" not in skill


def test_entra_and_workday_identifiers_remain_distinct() -> None:
    entra = (_WORKDAY_DA / "provision-entra-app.md").read_text(
        encoding="utf-8"
    )
    tenant = (_WORKDAY_DA / "configure-tenant.md").read_text(
        encoding="utf-8"
    )
    schema = (_WORKDAY_DA / "shared" / "config-schema.md").read_text(
        encoding="utf-8"
    )

    for text in (entra, tenant, schema):
        assert "http://www.workday.com/{tenant}" in text or (
            "http://www.workday.com/{workdayTenant}" in text
        )
        assert "api://" in text
    assert (
        "Never select an application by display name alone"
        in " ".join(entra.split())
    )
    assert "Never alias" in schema or "must never be aliases" in schema
    assert "entra-handoff" in entra
    assert "workday-admin-packet" in tenant
    assert "--discovery-file" in entra
    assert "--verification-worksheet-file" in entra
    assert "--discovery-json" not in entra
    assert "--verification-json" not in entra
    assert "does not authenticate the maker" in " ".join(entra.split())
    assert "guided handoff to the Entra administrator" in " ".join(
        entra.split()
    )
    assert "Enter the Workday tenant name, or paste a Workday" in entra
    assert "controller safely extracts the tenant name" in entra
    assert "Do not ask the maker to paste the full signed-in URL" not in entra
    assert "legacy `src/skills/setup/workday/` procedure" in entra
    assert 'broad "everything is done" confirmation' in entra
    assert (
        '"all good", "continue", or "proceed"' in " ".join(entra.split())
    )
    assert "captureInstructions" in entra
    assert "python scripts/workday_connect.py entra-handoff" in entra
    assert "Information to capture" in entra
    assert "Where to find it" in entra
    assert "What to record" in entra
    assert "Example value" in entra
    assert "Your tenant values" in entra
    normalized_entra = " ".join(entra.split())
    assert "both the capture guide and the return worksheet" in normalized_entra
    assert (
        "Before the numbered tasks" in entra
    )
    assert "renders an array of questions as a sequential wizard" in entra
    assert "containing exactly one free-form question" in entra
    assert "Do not replay the full worksheet" in entra
    assert '"header": "Entra administrator details"' in entra
    assert "Certificate valid from" not in entra
    assert "Do not\nsay only \"paste a revised worksheet\"" in entra
    for removed_header in (
        "Directory tenant ID",
        "Enterprise app Object ID",
        "App registration Object ID",
        "Application ID URIs",
        "Reply URLs",
        "Microsoft Entra Identifier",
        "Login URL",
        "Scope ID",
    ):
        assert f'"header": "{removed_header}"' not in entra
    assert "Do not ask for a\nfield after completion unless it appeared" in entra


def test_preflight_explains_silent_auth_and_current_phase() -> None:
    skill = (_WORKDAY_DA / "SKILL.md").read_text(encoding="utf-8")
    preflight = (_WORKDAY_DA / "install-extension.md").read_text(
        encoding="utf-8"
    )

    assert "### Current phase: {title}" in skill
    assert "A browser opens only when there is no valid cached session" in preflight
    assert "silent reuse does not mean the checks were skipped" in preflight
    assert "Preflight checks completed" in preflight


def test_manual_handoff_is_one_packet_not_row_attestations() -> None:
    tenant = (_WORKDAY_DA / "configure-tenant.md").read_text(
        encoding="utf-8"
    )
    normalized = " ".join(tenant.split())

    assert "one administrator handoff" in tenant
    assert "Workday administrator details" in tenant
    assert "both the capture guide and the return worksheet" in normalized
    assert "share this whole section" in tenant
    assert "Your tenant values" in tenant
    assert "do not repeat an **Information to return to the maker**" in tenant
    assert "identityProviderQuestion" in tenant
    assert "Microsoft Entra ID" in tenant
    assert "Okta" in tenant
    assert "Ping Identity" in tenant
    assert "Another sign-in provider" in tenant
    assert "No enabled SAML row" in tenant
    assert "I'm not sure" in tenant
    assert "Do not infer a match from the provider choice alone" in normalized
    assert "certificateSelectionQuestion" in tenant
    assert (
        "The certificate transferred from the completed Entra handoff"
        in tenant
    )
    assert "A different existing Workday certificate" in tenant
    assert "No certificate is selected" in tenant
    assert "Never suggest, prefill, or ask the administrator to confirm" in tenant
    assert '"header": "Certificate name"' not in tenant
    assert "containing exactly one free-form question" in tenant
    assert '"header": "Workday administrator details"' in tenant
    assert '"header": "Identity provider"' not in tenant
    assert '"header": "Authentication policy"' in tenant
    assert '"header": "Network readiness"' in tenant
    assert "Do not add `recommended`" in tenant
    assert "one mini-worksheet containing only the missing or invalid" in tenant
    assert "Do not reopen a sequence of individual questions" in tenant
    assert "reformat a recognizable response" in tenant
    assert "rejects missing, duplicate, or unknown labels" in normalized
    assert "--response-worksheet-file" in tenant
    assert "Enter a JSON string array" not in tenant
    assert 'Enter a JSON array of {' not in tenant
    assert "Yes, all four required functional areas are present" in tenant
    assert "Domain | supported scenario" in tenant
    assert '"all good", "continue", or "proceed"' in tenant


def test_administrator_worksheets_use_controller_parsing_contract() -> None:
    skill = (_WORKDAY_DA / "SKILL.md").read_text(encoding="utf-8")
    entra = (_WORKDAY_DA / "provision-entra-app.md").read_text(
        encoding="utf-8"
    )
    tenant = (_WORKDAY_DA / "configure-tenant.md").read_text(
        encoding="utf-8"
    )
    install = (_WORKDAY_DA / "install-extension.md").read_text(
        encoding="utf-8"
    )
    matrix = (
        _REPO_ROOT
        / "solutions"
        / "ess-maker-skills"
        / "src"
        / "reference"
        / "ess-docs"
        / "flightcheck"
        / "validation-matrix.md"
    ).read_text(encoding="utf-8")
    normalized_skill = " ".join(skill.split())

    assert "only exception" in normalized_skill
    assert "controller's worksheet parser" in normalized_skill
    assert "reformat it" in normalized_skill
    assert "reformat a recognizable response" in " ".join(entra.split())
    assert "including the header and every row" not in entra
    assert "--verification-worksheet-file" in entra
    assert "entra-verification.json" not in entra
    assert "--response-worksheet-file" in tenant
    assert "workday-admin-response.json" not in tenant
    assert "environment and capacity evidence is inherited" not in matrix
    assert "environment and capacity evidence" not in install
    assert "do not move to another field" in tenant
    assert "search workspace files" in tenant
    assert "CHECKPOINT_RESULT" not in tenant
    assert "ACK=true" not in tenant
