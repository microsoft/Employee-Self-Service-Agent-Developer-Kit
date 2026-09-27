# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Deterministic controller for the six-phase Workday connect lifecycle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Callable

from workday_connect_agent import (
    WorkdayConnectAgentError,
    verify_agent_binding,
    verify_topic_activation,
)
from workday_connect_model import (
    CONTROLLER_CONTRACT_VERSION,
    WorkdayConnectModelError,
    workday_saml_entity_id,
)
from workday_connect_contracts import (
    WorkdayConnectContractError,
    build_entra_handoff,
    build_workday_admin_packet,
    validate_agent_binding_evidence,
    validate_employee_evidence,
    validate_entra_verification,
    validate_workday_admin_response,
)
from workday_connect_preflight import (
    WorkdayConnectPreflightError,
    run_preflight,
)
from workday_connect_runtime import (
    WorkdayConnectRuntimeError,
    run_runtime_operation,
    verify_physical_connections,
)
from workday_connect_store import (
    WorkdayConnectPlanChangedError,
    WorkdayConnectStore,
    WorkdayConnectStoreError,
)


RESULT_MARKER = "WORKDAY_CONNECT_RESULT_JSON:"
ERROR_MARKER = "WORKDAY_CONNECT_ERROR_JSON:"


def _json_object(value: str, label: str) -> dict[str, Any]:
    try:
        document = json.loads(value)
    except json.JSONDecodeError as exc:
        raise WorkdayConnectStoreError(f"{label} must be valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise WorkdayConnectStoreError(f"{label} must be a JSON object.")
    return document


def _emit(operation: str, result: dict[str, Any]) -> None:
    print(
        RESULT_MARKER
        + json.dumps(
            {
                "contractVersion": CONTROLLER_CONTRACT_VERSION,
                "operation": operation,
                **result,
            },
            sort_keys=True,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage the Workday connect lifecycle."
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Workspace root containing .local state.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")

    tenant = subparsers.add_parser("set-workday-tenant")
    tenant.add_argument("--tenant", required=True)

    entra_handoff = subparsers.add_parser("entra-handoff")
    entra_handoff.add_argument("--discovery-json", required=True)
    record_entra = subparsers.add_parser("record-entra")
    record_entra.add_argument("--verification-json", required=True)
    subparsers.add_parser("workday-admin-packet")
    record_admin = subparsers.add_parser("record-workday-admin")
    record_admin.add_argument("--response-json", required=True)

    runtime_plan = subparsers.add_parser("runtime-plan")
    runtime_plan.add_argument("--workday-connection-id")
    runtime_plan.add_argument("--dataverse-connection-id")

    runtime_apply = subparsers.add_parser("runtime-apply")
    runtime_apply.add_argument("--plan-hash", required=True)
    runtime_apply.add_argument("--workday-connection-id")
    runtime_apply.add_argument("--dataverse-connection-id")
    runtime_approve = subparsers.add_parser("runtime-approve")
    runtime_approve.add_argument("--plan-json", required=True)
    record_connections = subparsers.add_parser("record-connections")
    record_connections.add_argument("--workday-connection-id")
    record_connections.add_argument("--dataverse-connection-id")
    record_connections.add_argument(
        "--evidence-json",
        help=argparse.SUPPRESS,
    )
    subparsers.add_parser("record-topic-activation")
    record_binding = subparsers.add_parser("record-agent-binding")
    record_binding.add_argument("--evidence-json", help=argparse.SUPPRESS)
    record_validation = subparsers.add_parser("record-validation")
    record_validation.add_argument("--evidence-json", required=True)

    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--dataverse-url")
    preflight.add_argument("--maker-username")

    return parser


def _status(
    _args: argparse.Namespace,
    store: WorkdayConnectStore,
) -> dict[str, Any]:
    return store.status()


def _set_workday_tenant(
    args: argparse.Namespace,
    store: WorkdayConnectStore,
) -> dict[str, Any]:
    tenant = args.tenant.strip()
    workday_saml_entity_id(tenant)
    state = store.merge_section("scope", {"workdayTenant": tenant})
    return {
        "workdayTenant": state["scope"]["workdayTenant"],
        "status": store.status(),
    }


def _entra_handoff(
    args: argparse.Namespace,
    store: WorkdayConnectStore,
) -> dict[str, Any]:
    return {
        "packet": build_entra_handoff(
            store.load(),
            _json_object(args.discovery_json, "Entra discovery"),
        )
    }


def _record_entra(
    args: argparse.Namespace,
    store: WorkdayConnectStore,
) -> dict[str, Any]:
    result = validate_entra_verification(
        store.load(),
        _json_object(args.verification_json, "Entra verification"),
    )
    store.merge_section("identifiers", result["identifiers"])
    store.complete_action(
        "entra",
        "exact-application-discovered",
        evidence={
            "outcome": "verified",
            "tenantId": result["evidence"]["tenantId"],
            "applicationDisplayName": result["evidence"]["applicationDisplayName"],
        },
    )
    store.complete_action(
        "entra",
        "administrator-configuration-verified",
        evidence={
            "outcome": "verified",
            "checks": result["evidence"]["checks"],
        },
    )
    store.set_phase_status("entra", "complete")
    _, reused = store.restore_workday_foundation()
    return {
        "verified": True,
        "tenantFoundationReused": reused,
        "status": store.status(),
    }


def _workday_admin_packet(
    _args: argparse.Namespace,
    store: WorkdayConnectStore,
) -> dict[str, Any]:
    return {"packet": build_workday_admin_packet(store.load())}


def _record_workday_admin(
    args: argparse.Namespace,
    store: WorkdayConnectStore,
) -> dict[str, Any]:
    result = validate_workday_admin_response(
        store.load(),
        _json_object(
            args.response_json,
            "Workday administrator response",
        ),
    )
    store.merge_section("identifiers", result["identifiers"])
    store.merge_section("endpoints", result["endpoints"])
    store.complete_action(
        "workday-admin",
        "administrator-response-validated",
        evidence={"outcome": "verified", **result["evidence"]},
    )
    store.set_phase_status("workday-admin", "complete")
    store.capture_tenant_foundation()
    return {
        "verified": True,
        "status": store.status(),
    }


def _runtime_plan(
    args: argparse.Namespace,
    store: WorkdayConnectStore,
) -> dict[str, Any]:
    return run_runtime_operation(
        store.load(),
        apply=False,
        workday_connection_id=args.workday_connection_id,
        dataverse_connection_id=args.dataverse_connection_id,
    )


def _runtime_apply(
    args: argparse.Namespace,
    store: WorkdayConnectStore,
) -> dict[str, Any]:
    result = run_runtime_operation(
        store.load(),
        apply=True,
        approved_hash=args.plan_hash,
        verifier=lambda plan, approved_hash: store.verify_plan(
            "runtime",
            plan,
            approved_hash,
        ),
        workday_connection_id=args.workday_connection_id,
        dataverse_connection_id=args.dataverse_connection_id,
        stage_recorder=lambda action, evidence: store.complete_action(
            "runtime",
            action,
            evidence=evidence,
        ),
    )
    return {**result, "status": store.status()}


def _runtime_approve(
    args: argparse.Namespace,
    store: WorkdayConnectStore,
) -> dict[str, Any]:
    _, approved_hash = store.approve_plan(
        "runtime",
        _json_object(args.plan_json, "runtime plan"),
    )
    return {"planHash": approved_hash, "status": store.status()}


def _record_connections(
    args: argparse.Namespace,
    store: WorkdayConnectStore,
) -> dict[str, Any]:
    if getattr(args, "evidence_json", None) is not None:
        raise WorkdayConnectStoreError(
            "Manual connection evidence is no longer accepted. Run "
            "record-connections without --evidence-json so the controller "
            "can verify the live connections."
        )
    evidence = verify_physical_connections(
        store.load(),
        workday_connection_id=args.workday_connection_id,
        dataverse_connection_id=args.dataverse_connection_id,
    )
    store.complete_action(
        "connections",
        "physical-connections-verified",
        evidence={
            "outcome": "verified",
            "source": "live-power-platform-discovery",
            "makerUsername": evidence["makerUsername"],
            "connections": evidence["connections"],
        },
    )
    store.set_phase_status("connections", "complete")
    return {"verified": True, "status": store.status()}


def _record_agent_binding(
    args: argparse.Namespace,
    store: WorkdayConnectStore,
) -> dict[str, Any]:
    if getattr(args, "evidence_json", None) is not None:
        raise WorkdayConnectStoreError(
            "Manual agent-binding evidence is no longer accepted. Run "
            "record-agent-binding without --evidence-json so the controller "
            "can verify the live agent."
        )
    state = store.load()
    evidence = validate_agent_binding_evidence(
        state,
        verify_agent_binding(store.workspace_root, state),
    )
    store.complete_action(
        "runtime",
        "user-context-v2-configured",
        evidence={
            "outcome": "verified",
            "checkpoint": "WD-REST-002",
            "result": evidence["checkpoints"]["WD-REST-002"],
        },
    )
    store.complete_action(
        "runtime",
        "agent-parameter-sharing-verified",
        evidence={
            "outcome": "verified",
            "checkpoint": "WD-CONN-013",
            "result": evidence["checkpoints"]["WD-CONN-013"],
        },
    )
    store.complete_action(
        "runtime",
        "flow-attachment-confirmed",
        evidence={
            "outcome": "verified",
            "environmentId": evidence["environmentId"],
            "botId": evidence["botId"],
            "makerUsername": evidence["makerUsername"],
            "observedTopicDiagnostics": (
                evidence["workdayTopics"]["blockingDiagnostics"]
            ),
        },
    )
    store.complete_action(
        "runtime",
        "workday-topics-activated",
        evidence={
            "outcome": "verified",
            "expected": evidence["workdayTopics"]["expected"],
            "verified": evidence["workdayTopics"]["verified"],
            "active": evidence["workdayTopics"]["active"],
        },
    )
    store.set_phase_status("runtime", "complete")
    return {"verified": True, "status": store.status()}


def _record_topic_activation(
    _args: argparse.Namespace,
    store: WorkdayConnectStore,
) -> dict[str, Any]:
    evidence = verify_topic_activation(
        store.workspace_root,
        store.load(),
    )
    topics = evidence["workdayTopics"]
    store.complete_action(
        "runtime",
        "workday-topics-activated",
        evidence={
            "outcome": "verified",
            "environmentId": evidence["environmentId"],
            "botId": evidence["botId"],
            "makerUsername": evidence["makerUsername"],
            "expected": topics["expected"],
            "verified": topics["verified"],
            "active": topics["active"],
            "blockingDiagnostics": topics["blockingDiagnostics"],
        },
    )
    diagnostics = topics["blockingDiagnostics"]
    store.set_phase_status("runtime", "active")
    return {
        "verified": True,
        "diagnosticsObserved": len(diagnostics),
        "status": store.status(),
    }


def _record_validation(
    args: argparse.Namespace,
    store: WorkdayConnectStore,
) -> dict[str, Any]:
    evidence = validate_employee_evidence(
        _json_object(
            args.evidence_json,
            "employee validation evidence",
        )
    )
    store.complete_action(
        "employee-validation",
        "signed-in-scenario",
        evidence=evidence,
    )
    store.set_phase_status("employee-validation", "complete")
    return {"verified": True, "status": store.status()}


def _preflight(
    args: argparse.Namespace,
    store: WorkdayConnectStore,
) -> dict[str, Any]:
    return run_preflight(
        Path(args.root),
        dataverse_url=args.dataverse_url,
        maker_username=args.maker_username,
        store=store,
    )


_COMMAND_HANDLERS: dict[
    str,
    Callable[[argparse.Namespace, WorkdayConnectStore], dict[str, Any]],
] = {
    "status": _status,
    "set-workday-tenant": _set_workday_tenant,
    "entra-handoff": _entra_handoff,
    "record-entra": _record_entra,
    "workday-admin-packet": _workday_admin_packet,
    "record-workday-admin": _record_workday_admin,
    "runtime-plan": _runtime_plan,
    "runtime-apply": _runtime_apply,
    "runtime-approve": _runtime_approve,
    "record-connections": _record_connections,
    "record-topic-activation": _record_topic_activation,
    "record-agent-binding": _record_agent_binding,
    "record-validation": _record_validation,
    "preflight": _preflight,
}

_COMMAND_PHASES = {
    "preflight": "preflight",
    "set-workday-tenant": "entra",
    "entra-handoff": "entra",
    "record-entra": "entra",
    "workday-admin-packet": "workday-admin",
    "record-workday-admin": "workday-admin",
    "record-connections": "connections",
    "runtime-plan": "runtime",
    "runtime-approve": "runtime",
    "runtime-apply": "runtime",
    "record-topic-activation": "runtime",
    "record-agent-binding": "runtime",
    "record-validation": "employee-validation",
}


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    store = WorkdayConnectStore(Path(args.root))
    try:
        handler = _COMMAND_HANDLERS.get(args.command)
        if handler is None:
            parser.error(f"Unsupported command: {args.command}")
        _emit(args.command, handler(args, store))
    except (
        OSError,
        WorkdayConnectModelError,
        WorkdayConnectAgentError,
        WorkdayConnectContractError,
        WorkdayConnectPlanChangedError,
        WorkdayConnectPreflightError,
        WorkdayConnectRuntimeError,
        WorkdayConnectStoreError,
    ) as exc:
        phase_id = _COMMAND_PHASES.get(args.command)
        if phase_id:
            try:
                store.set_phase_status(
                    phase_id,
                    "blocked",
                    blocker={
                        "operation": args.command,
                        "errorType": type(exc).__name__,
                        "message": str(exc),
                    },
                )
            except (
                OSError,
                WorkdayConnectModelError,
                WorkdayConnectStoreError,
            ):
                pass
        print(
            ERROR_MARKER
            + json.dumps(
                {
                    "contractVersion": CONTROLLER_CONTRACT_VERSION,
                    "operation": args.command,
                    "error": str(exc),
                    "errorType": type(exc).__name__,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
