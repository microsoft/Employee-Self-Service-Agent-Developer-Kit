# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Contracts for the resumable Workday DA setup foundation."""

from pathlib import Path
import re


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
_SHARED = _WORKDAY_DA / "shared"


def test_checklist_has_the_complete_unique_step_set() -> None:
    tasks = (_WORKDAY_DA / "tasks.md").read_text(encoding="utf-8")
    step_ids = re.findall(r"<!-- id: (DA\d+\.\d+)", tasks)

    expected = (
        {"DA1.1"}
        | {f"DA2.{index}" for index in range(1, 8)}
        | {f"DA3.{index}" for index in range(1, 5)}
        | {f"DA4.{index}" for index in range(1, 9)}
        | {"DA5.1"}
    )
    assert set(step_ids) == expected
    assert len(step_ids) == len(set(step_ids))
    assert tasks.count("| status: pending -->") == len(expected)


def test_checklist_uses_readable_titles_without_visible_internal_ids() -> None:
    tasks = (_WORKDAY_DA / "tasks.md").read_text(encoding="utf-8")
    visible_rows = [
        line for line in tasks.splitlines() if line.startswith("- [ ] **")
    ]

    assert len(visible_rows) == 21
    assert all(not re.search(r"\bDA\d", line) for line in visible_rows)
    assert all("ESS DA" not in line for line in visible_rows)
    assert any("Connect Microsoft Entra sign-in to Workday" in line for line in tasks.splitlines())
    assert any("Match the signed-in employee" in line for line in visible_rows)


def test_orchestrator_renders_canonical_titles_in_canonical_order() -> None:
    tasks = (_WORKDAY_DA / "tasks.md").read_text(encoding="utf-8")
    skill = (_WORKDAY_DA / "SKILL.md").read_text(encoding="utf-8")

    canonical_titles = re.findall(r"^- \[ \] \*\*(.+?)\*\*", tasks, re.MULTILINE)
    rendered_titles = re.findall(r"^\s+- \{m\} (.+)$", skill, re.MULTILINE)

    assert rendered_titles == canonical_titles


def test_state_contract_requires_immediate_durable_updates() -> None:
    updater = (_SHARED / "checklist-updater.md").read_text(encoding="utf-8")
    schema = (_SHARED / "config-schema.md").read_text(encoding="utf-8")

    assert "A `MANUAL` or attestation-gated row is never" in updater
    assert "**Persist immediately — never batch.**" in updater
    assert ".local/setup/workday-da/tasks.md" in updater
    assert ".local/connect/workday-da/config.json" in updater
    assert "Read" in schema and "Merge" in schema and "Write" in schema
    assert "sidecarDataverseEndpoint" in schema
    assert '"gateEvidence"' in schema
    assert '"provenance"' in schema
    assert '`reviewed`' in updater
    assert "FAILED` or `ERROR` always produces `blocked`" in updater


def test_entra_setup_pins_tenant_and_exact_app_identity() -> None:
    entra = (_WORKDAY_DA / "provision-entra-app.md").read_text(encoding="utf-8")
    gate = (_SHARED / "permission-gate.md").read_text(encoding="utf-8")

    assert "az account show --query tenantId -o tsv" in entra
    assert '--tenant "{SETUP_TENANT_ID}"' in entra
    assert "normalized **exact equality**" in entra
    assert "contains(@, 'workday.com/{tenant}')" not in entra
    assert "microsoft.graph.directoryRole" in entra
    assert "roleTemplateId" in entra
    assert "9b895d92-2cd3-44c7-9d02-a6ac2d5ea5c3" in entra
    assert "never auto-select by display name" in entra
    assert "Never downgrade a programmatic privileged-role" in gate
    assert "user_impersonation" in entra
    assert "claimsMappingPolicy" in entra


def test_workday_tenant_setup_preserves_manual_gates_and_safe_order() -> None:
    tasks = (_WORKDAY_DA / "tasks.md").read_text(encoding="utf-8")
    tenant = (_WORKDAY_DA / "configure-tenant.md").read_text(encoding="utf-8")

    register = tenant.index("## DA3.1 + DA3.2 — Register the API client")
    policy = tenant.index("## DA3.3 — Verify the signed-in employee authentication policy")

    assert register < policy
    assert "Single-tenant SAML pre-gate" in tenant
    assert "CHECKPOINT_RESULT=\"MANUAL\"" in tenant
    assert "ACK=true" in tenant
    assert "Workday cert field is not API-reachable" in tenant
    assert "checkpoints: WD-CONN-102 | gate: manual" in tasks
    assert "checkpoints: WD-API-CLIENT-001 | gate: attest" in tasks
    assert (
        "| DA3.2 | `WD-API-CLIENT-001` — Workday connection fields captured"
        in tenant
    )
    assert "There is no separate domain-to-integration-security-group" in tenant
    assert "Do not look for an OAuth-client restriction" in tenant
    assert "Existing active policy already allows employee SAML" in tenant


def test_workday_portal_tasks_start_only_after_the_admin_gate() -> None:
    entra = (_WORKDAY_DA / "provision-entra-app.md").read_text(encoding="utf-8")
    tenant = (_WORKDAY_DA / "configure-tenant.md").read_text(encoding="utf-8")
    normalized_entra = " ".join(entra.split())

    assert "Workday-side issuer, service-provider ID, and certificate" in normalized_entra
    assert (
        "happens in the next phase, after the Workday-administrator gate"
        in normalized_entra
    )
    assert "Do not ask the maker to open Workday" in entra
    assert tenant.index("## DA3.0 — Workday administrator gate") < tenant.index(
        "## DA3.0b — Single-tenant SAML pre-gate"
    )
