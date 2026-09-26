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
    assert '"schemaVersion": 3' in schema
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


def test_manual_handoff_is_one_packet_not_row_attestations() -> None:
    tenant = (_WORKDAY_DA / "configure-tenant.md").read_text(
        encoding="utf-8"
    )

    assert "one administrator handoff" in tenant
    assert "one response form" in tenant
    assert "repeated confirmations" in tenant
    assert "CHECKPOINT_RESULT" not in tenant
    assert "ACK=true" not in tenant
