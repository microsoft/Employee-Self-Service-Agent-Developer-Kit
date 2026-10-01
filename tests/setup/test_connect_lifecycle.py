# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import json
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_SOLUTION = _ROOT / "solutions" / "ess-maker-skills"
_CONNECT = _SOLUTION / "src" / "skills" / "connect"


def test_workday_contract_uses_generic_lifecycle() -> None:
    contract = json.loads(
        (_CONNECT / "workday" / "contract.json").read_text(encoding="utf-8")
    )

    assert contract["provider"] == "workday"
    assert [phase["id"] for phase in contract["phases"]] == [
        "discovery",
        "agent-wiring",
        "validation",
    ]
    wiring = contract["phases"][1]
    assert wiring["mutates"] is True
    assert wiring["requiredRole"] == "Environment Maker"
    assert wiring["rollbackPushGlobFromAction"] is True
    assert "rollbackPushGlob" not in wiring
    assert "attestedRoleScope" not in contract

    entry = (_CONNECT / "workday" / "SKILL.md").read_text(encoding="utf-8")
    assert "connect/shared/lifecycle-runner.md" in entry
    assert "connect/workday/contract.json" in entry


def test_lifecycle_runner_requires_reverification_and_rollback() -> None:
    runner = (_CONNECT / "shared" / "lifecycle-runner.md").read_text(
        encoding="utf-8"
    )

    assert "Live re-verification on resume" in runner
    assert "permission-gate.md" in runner
    assert "--revert-reason" in runner
    assert "rollbackPushGlob" in runner
    assert 'ACTION_RESULT = "applied"' not in runner
    assert '**`"applied"`**' in runner
    assert '**`"recorded"`**' in runner
    assert '**`"cancelled"`**' in runner
    assert 'actionExecution: "every-invocation"' in runner
    assert "Non-mutating actions do not run a role" in runner
    assert "contiguous prefix" in runner
    assert (
        "clear\n   `actionApplied`/`lastActionAt`/`rollbackPushGlob`"
        in runner
    )
    assert "fresh gate\n   and fresh rollback checkpoint" in runner
    assert "must never be reused after drift" in runner
    assert "`actionApplied`/`lastActionAt`/`rollbackPushGlob`" in runner
    assert "attestedRoleScope: \"lifecycle\"" in runner
    assert "roleAttestations.{requiredRole}" in runner
    assert "Accepting the plan does not claim a\nrole" in runner
    assert "Never reuse `roleAttestations` for this mode" in runner
    assert "different provider or agent slug" in runner
    assert "missing `roleAttestations` object" in runner
    assert "Do not infer an attestation from `attested`" in runner
    assert (
        "clear its `actionApplied`, `lastActionAt`, and\n"
        "`rollbackPushGlob`"
        in runner
    )
    assert "remove `lastActionAt` and `rollbackPushGlob`" in runner
    assert "Keep valid lifecycle-scoped\nrole attestations unchanged" in runner
    assert "actual current status values" in runner
    assert "provider plan passed" not in runner
    assert 'acceptedContractRevision' in runner
    assert "Do not run a migration command on a first run" in runner
    assert '**`"waiting"`**' in runner
    assert "provider-owned question, discovery, decision" in runner
    assert "exactly one pause boundary per attempt" in runner
    assert "must not persist or ask separate questions" in runner

    recorded_section = runner.split('- **`"recorded"`**', 1)[1].split(
        '- **`"cancelled"`**',
        1,
    )[0]
    assert "actionApplied = true" in recorded_section
    assert "without creating rollback state" in recorded_section

    regression_section = runner.split(
        "4. If any checkpoint resolves to a status",
        1,
    )[1].split("## L.3", 1)[0]
    failed_branch = regression_section.split(
        "- For `Failed`/`Error`",
        1,
    )[1].split("- For every other regression", 1)[0]
    repairable_branch = regression_section.split(
        "- For every other regression",
        1,
    )[1]
    assert "set the phase to `blocked`" in failed_branch
    assert "stop for remediation" in failed_branch
    assert "set the phase to `in-progress`" in repairable_branch
    assert "continue to L.3 in this same" in repairable_branch
    assert "interactive question" in repairable_branch
    assert "do not end the turn" in repairable_branch


def test_servicenow_hrsd_contract_uses_generic_lifecycle() -> None:
    contract = json.loads(
        (_CONNECT / "servicenow-da-hrsd" / "contract.json").read_text(
            encoding="utf-8"
        )
    )

    assert contract["provider"] == "servicenow-da-hrsd"
    assert contract["attestedRoleScope"] == "lifecycle"
    assert contract["contractRevision"] == 3
    assert contract["stateMigrationCommand"].endswith("migrate-state")
    assert [phase["id"] for phase in contract["phases"]] == [
        "preflight",
        "plugin-prerequisites",
        "entra-registration",
        "servicenow-oidc",
        "credential",
        "topics",
        "agent-connection",
        "parameter-sharing",
        "publish",
        "test",
    ]
    by_id = {phase["id"]: phase for phase in contract["phases"]}
    assert by_id["preflight"]["actionExecution"] == "every-invocation"
    assert "missing or unhealthy" in by_id["preflight"]["label"]
    for phase_id in (
        "plugin-prerequisites",
        "entra-registration",
        "servicenow-oidc",
        "credential",
    ):
        assert by_id[phase_id]["actionExecution"] == "once"
    assert by_id["agent-connection"]["actionExecution"] == "every-invocation"
    assert by_id["parameter-sharing"]["actionExecution"] == "every-invocation"
    assert by_id["test"]["actionExecution"] == "every-invocation"
    assert by_id["test"]["mutates"] is False
    assert by_id["test"]["completionStatuses"] == ["Manual"]
    assert by_id["entra-registration"]["completionStatuses"] == [
        "Passed",
        "Manual",
    ]
    assert by_id["entra-registration"]["checkpoints"] == [
        "SN-DA-HRSD-ENTRA-*"
    ]
    for phase_id in (
        "plugin-prerequisites",
        "entra-registration",
        "servicenow-oidc",
    ):
        acknowledgement = by_id[phase_id]["manualAcknowledgementEvidence"]
        assert acknowledgement["path"] == (
            "adminSetup.phaseHandoffs.{phaseId}"
        )
        assert acknowledgement["acceptedRecordStatuses"] == [
            "completed",
            "reused",
        ]
        assert acknowledgement["requiredEvidenceKind"] == (
            "structured-admin-attestation"
        )
    for phase_id in (
        "preflight",
        "credential",
        "topics",
        "agent-connection",
        "parameter-sharing",
        "publish",
        "test",
    ):
        assert "manualAcknowledgementEvidence" not in by_id[phase_id]
    runner = (_CONNECT / "shared" / "lifecycle-runner.md").read_text(
        encoding="utf-8"
    )
    assert "When `TARGET` is a registered family/wildcard" in runner
    assert "Do not invoke family members again" in runner
    assert "manualAcknowledgementEvidence" in runner
    assert 'source: "matching-action-evidence"' in runner
    assert "Otherwise use the normal acknowledgement question" in runner
    assert "Matching action evidence never auto-acknowledges a warning" in (
        (_CONNECT / "shared" / "lifecycle-contract-schema.md").read_text(
            encoding="utf-8"
        )
    )

    workday = json.loads(
        (_CONNECT / "workday" / "contract.json").read_text(encoding="utf-8")
    )
    assert all("actionExecution" not in phase for phase in workday["phases"])
    assert "attestedRoleScope" not in workday
    assert all(
        "manualAcknowledgementEvidence" not in phase
        for phase in workday["phases"]
    )


def _matching_admin_evidence_acknowledges(
    phase: dict,
    checkpoint_status: str,
    provider_state: dict,
    *,
    action_succeeded_this_invocation: bool,
) -> bool:
    config = phase.get("manualAcknowledgementEvidence")
    if (
        not isinstance(config, dict)
        or checkpoint_status != "Manual"
        or not action_succeeded_this_invocation
    ):
        return False
    path = config.get("path")
    if not isinstance(path, str) or path.count("{phaseId}") != 1:
        return False
    resolved = path.replace("{phaseId}", phase["id"])
    if ".." in resolved or "[" in resolved or "]" in resolved:
        return False
    current: object = provider_state
    for part in resolved.split("."):
        if not part or not isinstance(current, dict):
            return False
        current = current.get(part)
    if not isinstance(current, dict):
        return False
    evidence = current.get("evidence")
    return bool(
        current.get("status") in config.get("acceptedRecordStatuses", [])
        and isinstance(evidence, dict)
        and evidence.get("kind") == config.get("requiredEvidenceKind")
        and evidence.get("recordedAt")
    )


def test_matching_admin_evidence_skips_only_same_phase_manual_ack() -> None:
    contract = json.loads(
        (_CONNECT / "servicenow-da-hrsd" / "contract.json").read_text(
            encoding="utf-8"
        )
    )
    phases = {phase["id"]: phase for phase in contract["phases"]}
    state = {
        "adminSetup": {
            "phaseHandoffs": {
                phase_id: {
                    "status": "completed",
                    "evidence": {
                        "kind": "structured-admin-attestation",
                        "recordedAt": "2026-10-01T00:00:00Z",
                    },
                }
                for phase_id in (
                    "plugin-prerequisites",
                    "entra-registration",
                    "servicenow-oidc",
                )
            }
        }
    }

    for phase_id in (
        "plugin-prerequisites",
        "entra-registration",
        "servicenow-oidc",
    ):
        assert _matching_admin_evidence_acknowledges(
            phases[phase_id],
            "Manual",
            state,
            action_succeeded_this_invocation=True,
        )

    assert not _matching_admin_evidence_acknowledges(
        phases["test"],
        "Manual",
        state,
        action_succeeded_this_invocation=True,
    )
    assert not _matching_admin_evidence_acknowledges(
        phases["plugin-prerequisites"],
        "Warning",
        state,
        action_succeeded_this_invocation=True,
    )
    assert not _matching_admin_evidence_acknowledges(
        phases["plugin-prerequisites"],
        "Manual",
        state,
        action_succeeded_this_invocation=False,
    )
    state["adminSetup"]["phaseHandoffs"]["plugin-prerequisites"]["evidence"][
        "kind"
    ] = "unrelated"
    assert not _matching_admin_evidence_acknowledges(
        phases["plugin-prerequisites"],
        "Manual",
        state,
        action_succeeded_this_invocation=True,
    )

    state["adminSetup"]["phaseHandoffs"]["plugin-prerequisites"]["evidence"][
        "kind"
    ] = "structured-admin-attestation"
    state["adminSetup"]["phaseHandoffs"]["plugin-prerequisites"][
        "status"
    ] = "pending"
    assert not _matching_admin_evidence_acknowledges(
        phases["plugin-prerequisites"],
        "Manual",
        state,
        action_succeeded_this_invocation=True,
    )
    state["adminSetup"]["phaseHandoffs"]["plugin-prerequisites"][
        "status"
    ] = "completed"
    state["adminSetup"]["phaseHandoffs"]["plugin-prerequisites"]["evidence"][
        "recordedAt"
    ] = ""
    assert not _matching_admin_evidence_acknowledges(
        phases["plugin-prerequisites"],
        "Manual",
        state,
        action_succeeded_this_invocation=True,
    )
    state["adminSetup"]["phaseHandoffs"]["plugin-prerequisites"]["evidence"][
        "recordedAt"
    ] = "2026-10-01T00:00:00Z"
    original = phases["plugin-prerequisites"][
        "manualAcknowledgementEvidence"
    ]["path"]
    for unsafe_path in (
        "../adminSetup.phaseHandoffs.{phaseId}",
        "adminSetup.phaseHandoffs[0].{phaseId}",
        "adminSetup/phaseHandoffs/{phaseId}",
        "adminSetup.phaseHandoffs.other",
    ):
        phases["plugin-prerequisites"][
            "manualAcknowledgementEvidence"
        ]["path"] = unsafe_path
        assert not _matching_admin_evidence_acknowledges(
            phases["plugin-prerequisites"],
            "Manual",
            state,
            action_succeeded_this_invocation=True,
        )
    phases["plugin-prerequisites"][
        "manualAcknowledgementEvidence"
    ]["path"] = original


def test_matching_action_ack_resume_requires_same_evidence_provenance() -> None:
    acknowledgement = {
        "status": "Manual",
        "source": "matching-action-evidence",
        "evidencePath": (
            "adminSetup.phaseHandoffs.plugin-prerequisites"
        ),
        "evidenceKind": "structured-admin-attestation",
        "evidenceRecordedAt": "2026-10-01T00:00:00Z",
    }
    provider_state = {
        "adminSetup": {
            "phaseHandoffs": {
                "plugin-prerequisites": {
                    "status": "completed",
                    "evidence": {
                        "kind": "structured-admin-attestation",
                        "recordedAt": "2026-10-01T00:00:00Z",
                    },
                }
            }
        }
    }

    def current() -> bool:
        record = provider_state["adminSetup"]["phaseHandoffs"][
            "plugin-prerequisites"
        ]
        evidence = record["evidence"]
        return bool(
            acknowledgement["status"] == "Manual"
            and record["status"] in {"completed", "reused"}
            and evidence["kind"] == acknowledgement["evidenceKind"]
            and evidence["recordedAt"]
            == acknowledgement["evidenceRecordedAt"]
        )

    assert current()
    provider_state["adminSetup"]["phaseHandoffs"][
        "plugin-prerequisites"
    ]["evidence"]["recordedAt"] = "2026-10-01T00:01:00Z"
    assert not current()


def test_hrsd_lifecycle_reuses_one_attested_role_per_agent() -> None:
    runner = (_CONNECT / "shared" / "lifecycle-runner.md").read_text(
        encoding="utf-8"
    )
    contract = json.loads(
        (_CONNECT / "servicenow-da-hrsd" / "contract.json").read_text(
            encoding="utf-8"
        )
    )

    mutating = [phase for phase in contract["phases"] if phase["mutates"]]
    assert {phase["gateMode"] for phase in mutating} == {"attested"}
    assert {phase["requiredRole"] for phase in mutating} == {
        "ESS Maker / Agent Developer"
    }
    assert runner.count("roleAttestations.{requiredRole}") >= 2
    assert "without asking again" in runner
    assert '`provider` exactly equals `PROVIDER`' in runner
    assert '`agentSlug` exactly equals `AGENT_SLUG`' in runner

    schema = (_CONNECT / "shared" / "lifecycle-contract-schema.md").read_text(
        encoding="utf-8"
    )
    assert "first mutating phase" in schema
    assert "Later mutating phases" in schema
    assert "later resumes" in schema
    assert "Explicit lifecycle reset/reinitialization" in schema
    assert "`gateMode: \"programmatic\"` always executes its role query" in schema


def test_cea_workday_routing_is_package_gated() -> None:
    route = (_CONNECT / "step1.md").read_text(encoding="utf-8")

    assert "--checkpoint WD-PKG-001" in route
    assert "Passed` + simplified-install result" in route
    assert "Passed` + full / legacy result" in route
    assert "Never start a lifecycle from an\n  inconclusive package check" in route
    assert "connect/workday/SKILL.md" in route
    assert ".local/connect/workday-da/config.json" in route
    assert "`scope.agent.slug` and `scope.agent.botId` exactly" in route


def test_workday_wiring_uses_installed_identity_and_explicit_result() -> None:
    action = (
        _CONNECT / "workday" / "actions" / "wire-user-context-redirect.md"
    ).read_text(encoding="utf-8")

    assert "workspace/agents/{AGENT_SLUG}/.component-map.json" in action
    assert "workspace/agents/{AGENT_SLUG}/{USER_CONTEXT_TOPIC_PATH}" in action
    assert 'ACTION_RESULT = "cancelled"' in action
    assert 'ACTION_RESULT = "applied"' in action
    assert "ACTION_ROLLBACK_PUSH_GLOB" in action
    assert "install-workday-extension-pack.md" not in action


def test_connect_contract_action_docs_and_rollback_scopes_are_valid() -> None:
    contracts = sorted(_CONNECT.glob("*/contract.json"))
    assert contracts

    for contract_path in contracts:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        for phase in contract["phases"]:
            action_doc = phase.get("actionDoc")
            if action_doc:
                assert (_SOLUTION / action_doc).is_file()

            has_static_scope = "rollbackPushGlob" in phase
            has_dynamic_scope = phase.get("rollbackPushGlobFromAction") is True
            assert not (has_static_scope and has_dynamic_scope)
            if phase.get("rollbackLabel"):
                assert has_static_scope or has_dynamic_scope


def test_dynamic_rollback_scope_is_persisted_and_reused_exactly() -> None:
    runner = (_CONNECT / "shared" / "lifecycle-runner.md").read_text(
        encoding="utf-8"
    )
    schema = (_CONNECT / "shared" / "lifecycle-contract-schema.md").read_text(
        encoding="utf-8"
    )

    assert "ACTION_ROLLBACK_PUSH_GLOB" in runner
    assert "phases.{id}.rollbackPushGlob" in runner
    assert "no wildcard characters" in runner
    assert '--only "{ROLLBACK_PUSH_GLOB}"' in runner
    assert "remove\n  `rollbackPushGlob`" in runner
    assert "rollbackPushGlobFromAction" in schema
    assert "ACTION_ROLLBACK_PUSH_GLOB" in schema


def test_declarative_agents_do_not_enter_cea_lifecycle() -> None:
    route = (_CONNECT / "step1.md").read_text(encoding="utf-8")

    assert "releaseLine: \"da\"" in route
    assert "gptagent_copilotforemployeeselfservicehr" in route
    assert "gptagent_copilotforemployeeselfserviceit" in route
    assert "WD-DA-PKG-001" in route
    assert "Do not create CEA Workday lifecycle state" in route
    assert "setup/workday-da/SKILL.md" in route
