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
    assert '"schemaVersion": 6' in schema
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
    assert "Never select by display name alone" in entra
    assert "Never alias" in schema or "must never be aliases" in schema
    assert "entra-handoff" in entra
    assert "workday-admin-packet" in tenant
    assert "--discovery-file" in entra
    assert "--verification-file" in entra
    assert "--discovery-json" not in entra
    assert "--verification-json" not in entra
    assert "exits with code 0" in entra
    assert "partial stdout after\na nonzero exit" in entra
    assert "legacy `src/skills/setup/workday/` procedure" in entra
    assert 'broad "everything is done" confirmation' in entra
    assert '"all good", "continue", or\n"proceed"' in entra


def test_manual_handoff_is_one_packet_not_row_attestations() -> None:
    tenant = (_WORKDAY_DA / "configure-tenant.md").read_text(
        encoding="utf-8"
    )

    assert "one administrator handoff" in tenant
    assert "one response form" in tenant
    assert "repeated confirmations" in tenant
    assert "identityProviderQuestion" in tenant
    assert "Microsoft Entra ID" in tenant
    assert "Okta" in tenant
    assert "Ping Identity" in tenant
    assert "Another sign-in provider" in tenant
    assert "No enabled SAML row" in tenant
    assert "I'm not sure" in tenant
    assert "Do not infer a match from the\n     provider choice alone" in tenant
    assert "certificateSelectionQuestion" in tenant
    assert "The new certificate created from the Entra Base64 file" in tenant
    assert "A different existing Workday certificate" in tenant
    assert "No certificate is selected" in tenant
    assert "Never suggest, prefill, or ask the administrator to confirm" in tenant
    assert "display name is optional support context" in tenant
    assert (
        "exactly one response form using one structured\n"
        "`vscode_askQuestions` call"
    ) in tenant
    assert '"header": "Identity provider"' not in tenant
    assert '"header": "Authentication policy"' in tenant
    assert '"header": "Network readiness"' in tenant
    assert "multiline text\nbox" in tenant
    assert "Do not add `recommended`" in tenant
    assert "free-text request for several numbered answers" in tenant
    assert '"all good", "continue", or "proceed"' in tenant
    assert "do not move to another field" in tenant
    assert "search workspace files" in tenant
    assert "CHECKPOINT_RESULT" not in tenant
    assert "ACK=true" not in tenant
