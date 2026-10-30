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
    schema = (
        _CONNECT / "shared" / "lifecycle-contract-schema.md"
    ).read_text(encoding="utf-8")
    assert "`stateInitializationCommand`" in schema
    assert "provider command must create its complete canonical state" in schema

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
    runner_normalized = " ".join(runner.split())

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
    assert "stateInitializationCommand" in runner
    assert "**Visible ServiceNow handoff style:**" in runner
    assert "separate sections with two newlines" in runner
    assert "Use numbered or bulleted lines under Action" in runner
    assert "Prefer buttons with no recommended" in runner
    assert "Freeform is allowed only for one genuinely unknown value" in runner
    assert "**ServiceNow phase-progress extension:**" in runner
    assert "Other providers retain this runner's existing output" in runner
    assert "show its short headline once" in runner
    assert "Re-emit the freshly returned checklist" in runner
    assert "phase checklist once" not in runner
    assert "cached `done` phase displays **Rechecking**" in runner
    assert "**Complete — admin confirmed**" in runner
    assert "**Reused — checked**" in runner
    assert "an action receipt is never phase\ncompletion" in runner
    assert "Show\n`finalText` only when the controller" in runner
    assert '`planReason: "revision-reapproval"`' in runner
    assert "`stateInitializationRequired: false`" in runner
    assert '`status: "existing-compatible-state"`' in runner
    assert "preserve the state byte-for-byte" in runner
    assert "never infer\n  first-run initialization" in runner
    assert "never write a generic fallback" in runner
    assert "Do not write a state file before the plan" in runner
    assert '**`"waiting"`**' in runner
    assert "provider-owned question, discovery, decision" in runner
    assert "exactly one pause boundary per attempt" in runner
    assert "must not persist or ask separate questions" in runner
    assert "`handoffMode: identity-requirement`" in runner
    assert "routing-only Maker question" in runner_normalized
    assert "they are not `Completed`/`Not yet` admin evidence" in (
        runner_normalized
    )
    assert "options are label-only" in runner_normalized
    assert "`identityRequirementChoices`" in runner
    assert "never add `value`" in runner_normalized
    assert "`Not sure` returns waiting, writes no receipt" in runner_normalized
    assert "must not set `actionApplied`" in runner_normalized
    assert "Never dereference a missing `workbookPath`" in runner_normalized
    assert "`resumeActionWhenIncomplete` is `true`" in runner
    assert "historical facts,\nnot authorization" in runner
    assert "fresh read-only inspection" in runner
    assert "Never automatically replay the prior\nmutation" in runner
    assert "preserve the historical `actionApplied`" in runner
    assert '`NotConfigured` and `Skipped` are evaluated' in runner
    assert 'overall: `"NOT_READY"`' not in runner
    assert '`overall: "NOT_READY"` with `exitCode: 0`' in runner
    assert "Missing/failed required clients" in runner
    assert "python scripts/connect_lifecycle.py next-step" in runner
    assert "python scripts/flightcheck/cli.py --checkpoint {TARGET} \\" in runner
    assert '--agent-slug "{AGENT_SLUG}"' in runner
    assert "returns the complete exact\ncheckpoint `argv`" in runner
    assert "never reconstruct it from\n`activeAgent`" in runner
    assert "DA_LIFECYCLE_NEXT_JSON:" in runner
    assert "Do not fall back to interpreting" in runner
    assert "After an action or checkpoint updates state" in runner
    assert "empty set named `verifiedPhases`" in runner
    assert 'one --verified-phase "{PHASE_ID}" argument' in runner
    assert "Never initialize it from persisted `lastVerifiedAt`" in runner
    assert "add the phase ID to `verifiedPhases`" in runner
    assert "Add the current phase ID to `verifiedPhases`" in runner
    assert "must not add the phase to `verifiedPhases`" in runner
    assert "remove this and later phase IDs from both" in runner

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
    assert "exact full remediation" in runner
    assert "branch-loaded recovery" in runner
    for heading in (
        "**Problem**",
        "**Category**",
        "**Owner**",
        "**Where**",
        "**Values to use**",
        "**Action**",
        "**Success**",
        "**Recheck and resume**",
    ):
        assert heading in runner
    assert "first execution, completed-phase re-verification, and resume" in (
        runner
    )
    assert "Other providers retain their existing remediation format" in runner
    assert "**ServiceNow preflight pending input:**" in runner
    assert "instanceInputRequired: true" in runner
    assert "stop with `ACTION_RESULT = \"waiting\"`" in runner
    assert "before running the preflight checkpoint" in runner
    assert "Do not render the checkpoint's `NotConfigured` recovery" in runner
    assert "returns top-level `pendingInput`" in runner
    assert "show `pendingInput.question` exactly and stop" in runner
    assert "without running or reconstructing a checkpoint command" in runner
    assert "historical `NotConfigured`\nstate" in runner
    assert "exact returned `manualInstanceQuestion` once" in runner


def test_servicenow_hrsd_contract_uses_generic_lifecycle() -> None:
    contract = json.loads(
        (_CONNECT / "servicenow-da-hrsd" / "contract.json").read_text(
            encoding="utf-8"
        )
    )

    assert contract["provider"] == "servicenow-da-hrsd"
    assert contract["checkpointResultMode"] == "compact-stdout-v1"
    assert contract["attestedRoleScope"] == "lifecycle"
    assert contract["contractRevision"] == 10
    assert contract["planRoles"] == [
        "ESS Maker / Agent Developer",
        "ServiceNow Admin / security_admin",
        "Microsoft Entra Application Administrator or higher",
        "Power Platform Maker / Admin",
    ]
    assert contract["stateMigrationCommand"] == (
        "python scripts/connect_servicenow_da.py "
        "--provider servicenow-da-hrsd --agent-slug {agentSlug} "
        "migrate-state"
    )
    assert contract["stateInitializationCommand"] == (
        "python scripts/connect_servicenow_da.py "
        "--provider servicenow-da-hrsd --agent-slug {agentSlug} "
        "initialize-state "
        "--contract-revision {contractRevision}"
    )
    assert [phase["id"] for phase in contract["phases"]] == [
        "preflight",
        "plugin-prerequisites",
        "entra-registration",
        "servicenow-oidc",
        "credential",
        "topics",
        "portal-url",
        "agent-connection",
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
        "portal-url",
    ):
        assert by_id[phase_id]["actionExecution"] == "once"
    assert by_id["topics"]["resumeActionWhenIncomplete"] is True
    assert by_id["agent-connection"]["actionExecution"] == "every-invocation"
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
        "topics",
        "agent-connection",
        "test",
    ):
        acknowledgement = by_id[phase_id]["manualAcknowledgementEvidence"]
        assert "path" in acknowledgement
        assert "evidenceObjectPath" in acknowledgement
        assert acknowledgement["acceptedRecordStatuses"]
        assert acknowledgement["requiredEvidenceKind"]
    for phase_id in (
        "preflight",
        "credential",
    ):
        assert "manualAcknowledgementEvidence" not in by_id[phase_id]
    runner = (_CONNECT / "shared" / "lifecycle-runner.md").read_text(
        encoding="utf-8"
    )
    assert "When `TARGET` is a registered family/wildcard" in runner
    assert "Do not invoke family members again" in runner
    assert "--compact-result" in runner
    assert "--invocation-id" in runner
    assert "flightcheck.lifecycle-checkpoint.v1" in runner
    assert "wrong-identity" in runner
    assert "never fall back to an older result file" in runner
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
    assert "planRoles" not in workday
    assert "checkpointResultMode" not in workday
    assert "Append the contract's optional display-only `planRoles`" in runner
    assert "they do not create a role gate" in runner


def test_servicenow_itsm_contract_uses_isolated_generic_lifecycle() -> None:
    contract = json.loads(
        (_CONNECT / "servicenow-da-itsm" / "contract.json").read_text(
            encoding="utf-8"
        )
    )

    assert contract["provider"] == "servicenow-da-itsm"
    assert contract["profile"] == "itsm"
    assert contract["contractRevision"] == 5
    assert "stateMigrationCommand" not in contract
    assert contract["stateInitializationCommand"] == (
        "python scripts/connect_servicenow_da.py "
        "--provider servicenow-da-itsm --agent-slug {agentSlug} "
        "initialize-state --contract-revision {contractRevision}"
    )
    assert [phase["id"] for phase in contract["phases"]] == [
        "preflight",
        "entra-registration",
        "servicenow-oidc",
        "credential",
        "topics",
        "portal-url",
        "agent-connection",
        "test",
    ]
    assert all(
        "SN-DA-ITSM" in checkpoint
        for phase in contract["phases"]
        for checkpoint in phase["checkpoints"]
    )
    assert contract["phases"][-1][
        "manualAcknowledgementEvidence"
    ]["requiredValues"]["promptCategory"] == "list-my-open-it-tickets"
    by_id = {phase["id"]: phase for phase in contract["phases"]}
    assert by_id["topics"]["resumeActionWhenIncomplete"] is True
    for provider in ("servicenow-da-hrsd", "servicenow-da-itsm"):
        skill = (
            _CONNECT / provider / "SKILL.md"
        ).read_text(encoding="utf-8")
        action = (
            _CONNECT / provider / "actions" / "prepare-topics.md"
        ).read_text(encoding="utf-8")
        assert "connect_lifecycle.py next-step" in skill
        assert "topic-action-handoff" in action
        assert "exact returned" in action or "exactly as returned" in action


def _resolve_safe_path(value: object, path: str) -> object:
    if (
        ".." in path
        or "[" in path
        or "]" in path
        or "/" in path
        or "{" in path
        or "}" in path
    ):
        return None
    current = value
    for part in path.split(".") if path else ():
        if not part or not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _matching_action_evidence_acknowledges(
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
    if not isinstance(path, str) or path.count("{phaseId}") > 1:
        return False
    resolved = path.replace("{phaseId}", phase["id"])
    record = _resolve_safe_path(provider_state, resolved)
    if not isinstance(record, dict):
        return False
    evidence_path = config.get("evidenceObjectPath")
    if not isinstance(evidence_path, str):
        return False
    evidence = _resolve_safe_path(record, evidence_path)
    if not isinstance(evidence, dict):
        return False
    if (
        record.get("status") not in config.get("acceptedRecordStatuses", [])
        or evidence.get("kind") != config.get("requiredEvidenceKind")
        or not evidence.get("recordedAt")
    ):
        return False
    for field, expected in config.get("requiredValues", {}).items():
        if _resolve_safe_path(evidence, field) != expected:
            return False
    for binding in config.get("bindings", []):
        if (
            _resolve_safe_path(evidence, binding["evidencePath"])
            != _resolve_safe_path(provider_state, binding["statePath"])
        ):
            return False
    return True


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
    state["adminSetup"]["phaseHandoffs"]["servicenow-oidc"]["evidence"].update(
        {
            "oidcCapabilityConfirmed": True,
            "runbookCompleted": True,
            "mappingDetailsCollected": True,
            "claimMappingConfirmed": True,
        }
    )
    state["adminSetup"]["phaseHandoffs"]["entra-registration"]["evidence"][
        "tokenClaimEmissionConfirmed"
    ] = True

    for phase_id in (
        "plugin-prerequisites",
        "entra-registration",
        "servicenow-oidc",
    ):
        assert _matching_action_evidence_acknowledges(
            phases[phase_id],
            "Manual",
            state,
            action_succeeded_this_invocation=True,
        )

    assert not _matching_action_evidence_acknowledges(
        phases["plugin-prerequisites"],
        "Warning",
        state,
        action_succeeded_this_invocation=True,
    )
    assert not _matching_action_evidence_acknowledges(
        phases["plugin-prerequisites"],
        "Manual",
        state,
        action_succeeded_this_invocation=False,
    )
    state["adminSetup"]["phaseHandoffs"]["plugin-prerequisites"]["evidence"][
        "kind"
    ] = "unrelated"
    assert not _matching_action_evidence_acknowledges(
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
    assert not _matching_action_evidence_acknowledges(
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
    assert not _matching_action_evidence_acknowledges(
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
        assert not _matching_action_evidence_acknowledges(
            phases["plugin-prerequisites"],
            "Manual",
            state,
            action_succeeded_this_invocation=True,
        )
    phases["plugin-prerequisites"][
        "manualAcknowledgementEvidence"
    ]["path"] = original


def test_matching_maker_evidence_skips_only_current_bound_manual_ack() -> None:
    contract = json.loads(
        (_CONNECT / "servicenow-da-hrsd" / "contract.json").read_text(
            encoding="utf-8"
        )
    )
    phases = {phase["id"]: phase for phase in contract["phases"]}
    state = {
        "provider": "servicenow-da-hrsd",
        "profile": "hrsd",
        "agentSlug": "employee-self-service-hr",
        "agentId": "agent-id",
        "environmentId": "environment-id",
        "componentHash": "component-hash",
        "draftSemanticHash": "draft-semantic-hash",
        "connectionBindingHash": "connection-binding-hash",
        "evidence": {
            "credential": {"connectionId": "connection-id"},
            "topics": {
                "kind": "maker-attestation",
                "status": "recorded",
                "recordedAt": "2026-10-01T00:00:00Z",
                "customerChoice": "keep-current",
                "makerAttested": True,
                "boundComponentHash": "component-hash",
            },
            "agentConnection": {
                "kind": "maker-attestation",
                "status": "completed",
                "recordedAt": "2026-10-01T00:00:00Z",
                "makerAttested": True,
                "physicalStatus": "Connected",
                "authMode": "entraIDUserLogin",
                "connectionId": "connection-id",
                "binding": {
                    "provider": "servicenow-da-hrsd",
                    "profile": "hrsd",
                    "agentSlug": "employee-self-service-hr",
                    "agentId": "agent-id",
                    "environmentId": "environment-id",
                    "draftSemanticHash": "draft-semantic-hash",
                },
            },
            "publish": {
                "kind": "maker-attestation",
                "status": "confirmation-required",
                "recordedAt": "2026-10-01T00:00:00Z",
                "completedAt": "2026-10-01T00:00:00Z",
                "publishedComponentHash": "component-hash",
                "testedDraftSemanticHash": "draft-semantic-hash",
                "publishedSemanticHash": "draft-semantic-hash",
                "connectionBindingHash": "connection-binding-hash",
            },
            "test": {
                "kind": "maker-attestation",
                "status": "completed",
                "recordedAt": "2026-10-01T00:00:00Z",
                "promptCategory": "list-my-open-hr-cases",
                "result": "pass",
                "failureCategory": None,
                "binding": {
                    "provider": "servicenow-da-hrsd",
                    "profile": "hrsd",
                    "agentSlug": "employee-self-service-hr",
                    "agentId": "agent-id",
                    "environmentId": "environment-id",
                    "connectionId": "connection-id",
                    "draftSemanticHash": "draft-semantic-hash",
                    "connectionBindingHash": "connection-binding-hash",
                },
            },
        },
    }

    for phase_id in ("topics", "agent-connection", "test"):
        assert _matching_action_evidence_acknowledges(
            phases[phase_id],
            "Manual",
            state,
            action_succeeded_this_invocation=True,
        )

    state["componentHash"] = "later-drift"
    for phase_id in ("topics",):
        assert not _matching_action_evidence_acknowledges(
            phases[phase_id],
            "Manual",
            state,
            action_succeeded_this_invocation=True,
        )
    state["componentHash"] = "component-hash"
    state["draftSemanticHash"] = "later-draft"
    for phase_id in ("agent-connection", "test"):
        assert not _matching_action_evidence_acknowledges(
            phases[phase_id],
            "Manual",
            state,
            action_succeeded_this_invocation=True,
        )
    state["draftSemanticHash"] = "draft-semantic-hash"
    state["connectionBindingHash"] = "later-connection"
    for phase_id in ("test",):
        assert not _matching_action_evidence_acknowledges(
            phases[phase_id],
            "Manual",
            state,
            action_succeeded_this_invocation=True,
        )


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
    runtime_action = (
        _CONNECT / "workday" / "actions" / "wire-runtime-template-config.md"
    ).read_text(encoding="utf-8")
    normalized_action = " ".join(action.split())

    assert "workspace/agents/{AGENT_SLUG}/.component-map.json" in action
    assert "workspace/agents/{AGENT_SLUG}/{USER_CONTEXT_TOPIC_PATH}" in action
    assert 'ACTION_RESULT = "cancelled"' not in action
    assert 'ACTION_RESULT = "applied"' in action
    assert (
        "without asking for a separate publish confirmation"
        in normalized_action
    )
    assert 'dialog: "{USER_CONTEXT_DIALOG}"' in action
    assert 'dialog: "{WORKDAY_RUNTIME_TEMPLATE_DIALOG}"' in runtime_action
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
