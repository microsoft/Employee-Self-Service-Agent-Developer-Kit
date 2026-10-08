# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Deterministic controller for the six-phase Workday connect lifecycle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Callable, Mapping

from workday_connect_agent import (
    WorkdayConnectAgentError,
    verify_agent_binding,
    verify_runtime_template_wiring,
    verify_topic_activation,
)
from workday_connect_model import (
    ADMINISTRATOR_PHASES,
    ADMINISTRATOR_SUBSTAGES,
    CONTROLLER_CONTRACT_VERSION,
    WorkdayConnectModelError,
    normalize_workday_tenant_input,
    workday_saml_entity_id,
)
from workday_connect_contracts import (
    build_entra_handoff,
    build_workday_admin_packet,
    parse_entra_return_worksheet,
    parse_workday_admin_return_worksheet,
    validate_administrator_partial_evidence,
    validate_entra_verification,
    validate_workday_admin_response,
)
from workday_connect_evidence_contracts import (
    WorkdayConnectContractError,
    validate_agent_binding_evidence,
    validate_maker_evidence,
    validate_maker_failure_evidence,
)
from workday_connect_flightcheck import (
    WorkdayConnectFlightCheckError,
    run_profile,
)
from workday_connect_preflight import (
    WorkdayConnectPreflightError,
    prepare_connections_package,
    run_preflight,
)
from workday_connect_readiness import (
    ensure_migration_baseline,
    run_final_readiness,
    run_profile_gate,
)
from workday_connect_realms import (
    WorkdayConnectRealmError,
    discover_and_record_realm_target,
    revalidate_active_realm_target,
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
from workday_connect_telemetry import (
    emit_lifecycle_event,
    flush_lifecycle_telemetry,
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


def _add_json_input(
    parser: argparse.ArgumentParser,
    name: str,
    *,
    allow_legacy_inline: bool = True,
    allow_worksheet: bool = False,
    required: bool = True,
) -> None:
    group = parser.add_mutually_exclusive_group(required=required)
    group.add_argument(
        f"--{name}-file",
        type=Path,
        help=f"Path to the {name.replace('-', ' ')} JSON object.",
    )
    if allow_legacy_inline:
        group.add_argument(
            f"--{name}-json",
            help=argparse.SUPPRESS,
        )
    if allow_worksheet:
        group.add_argument(
            f"--{name}-worksheet-file",
            type=Path,
            help=(
                "Path to the exact labeled administrator worksheet text."
            ),
        )


def _json_input(
    args: argparse.Namespace,
    name: str,
    label: str,
    *,
    worksheet_parser: (
        Callable[[Mapping[str, Any], str], dict[str, Any]] | None
    ) = None,
    worksheet_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    worksheet_path = getattr(
        args,
        f"{name.replace('-', '_')}_worksheet_file",
        None,
    )
    if worksheet_path is not None:
        if worksheet_parser is None or worksheet_state is None:
            raise WorkdayConnectStoreError(
                f"{label} does not support worksheet input."
            )
        try:
            worksheet = worksheet_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise WorkdayConnectStoreError(
                f"{label} worksheet could not be read: {worksheet_path}: {exc}"
            ) from exc
        return worksheet_parser(worksheet_state, worksheet)
    file_path = getattr(args, f"{name.replace('-', '_')}_file", None)
    if file_path is not None:
        try:
            value = file_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise WorkdayConnectStoreError(
                f"{label} file could not be read: {file_path}: {exc}"
            ) from exc
        return _json_object(value, label)
    value = getattr(args, f"{name.replace('-', '_')}_json", None)
    if value is None:
        raise WorkdayConnectStoreError(
            f"{label} requires a JSON input file."
        )
    return _json_object(value, label)


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
    discover_target = subparsers.add_parser("discover-realm-target")
    discover_target.add_argument(
        "--realm",
        choices=("test", "prod"),
        required=True,
    )
    discover_target.add_argument("--environment")
    discover_target.add_argument("--environment-id")
    discover_target.add_argument("--dataverse-url")
    discover_target.add_argument("--maker-username")

    tenant = subparsers.add_parser("set-workday-tenant")
    tenant.add_argument("--tenant", required=True)

    entra_handoff = subparsers.add_parser("entra-handoff")
    _add_json_input(entra_handoff, "discovery", required=False)
    record_entra = subparsers.add_parser("record-entra")
    _add_json_input(
        record_entra,
        "verification",
        allow_worksheet=True,
    )
    administrator_stage = subparsers.add_parser("administrator-stage")
    administrator_stage.add_argument(
        "--phase",
        choices=sorted(ADMINISTRATOR_PHASES),
        required=True,
    )
    administrator_stage.add_argument(
        "--substage",
        choices=ADMINISTRATOR_SUBSTAGES,
        required=True,
    )
    record_administrator_evidence = subparsers.add_parser(
        "record-administrator-evidence"
    )
    record_administrator_evidence.add_argument(
        "--phase",
        choices=sorted(ADMINISTRATOR_PHASES),
        required=True,
    )
    _add_json_input(
        record_administrator_evidence,
        "evidence",
        allow_legacy_inline=False,
    )
    subparsers.add_parser("workday-admin-packet")
    record_admin = subparsers.add_parser("record-workday-admin")
    _add_json_input(
        record_admin,
        "response",
        allow_worksheet=True,
    )

    runtime_plan = subparsers.add_parser("runtime-plan")
    runtime_plan.add_argument("--workday-connection-id")
    runtime_plan.add_argument("--dataverse-connection-id")

    runtime_apply = subparsers.add_parser("runtime-apply")
    runtime_apply.add_argument("--plan-hash", required=True)
    runtime_apply.add_argument("--workday-connection-id")
    runtime_apply.add_argument("--dataverse-connection-id")
    runtime_approve = subparsers.add_parser("runtime-approve")
    _add_json_input(runtime_approve, "plan")
    record_connections = subparsers.add_parser("record-connections")
    record_connections.add_argument("--workday-connection-id")
    record_connections.add_argument("--dataverse-connection-id")
    record_connections.add_argument(
        "--confirm-workday-target",
        action="store_true",
    )
    record_connections.add_argument(
        "--evidence-json",
        help=argparse.SUPPRESS,
    )
    subparsers.add_parser("record-topic-activation")
    subparsers.add_parser("record-runtime-template-wiring")
    record_binding = subparsers.add_parser("record-agent-binding")
    _add_json_input(
        record_binding,
        "attachment",
        allow_legacy_inline=False,
    )
    record_validation = subparsers.add_parser("record-validation")
    _add_json_input(record_validation, "evidence")
    record_validation_failure = subparsers.add_parser(
        "record-validation-failure"
    )
    _add_json_input(
        record_validation_failure,
        "evidence",
        allow_legacy_inline=False,
    )

    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--dataverse-url")
    preflight.add_argument("--maker-username")
    prepare_connections = subparsers.add_parser("prepare-connections")
    prepare_connections.add_argument("--install-plan-hash")
    prepare_connections_approve = subparsers.add_parser(
        "prepare-connections-approve"
    )
    _add_json_input(
        prepare_connections_approve,
        "plan",
        allow_legacy_inline=False,
    )

    return parser


def _status(
    _args: argparse.Namespace,
    store: WorkdayConnectStore,
) -> dict[str, Any]:
    return store.status()


def _discover_realm_target(
    args: argparse.Namespace,
    store: WorkdayConnectStore,
) -> dict[str, Any]:
    return discover_and_record_realm_target(
        Path(args.root),
        store,
        realm=args.realm,
        environment_id=args.environment_id,
        environment_url=args.dataverse_url,
        environment_selector=getattr(args, "environment", None),
        account_hint=args.maker_username,
    )


def _run_profile_gate(
    store: WorkdayConnectStore,
    profile_name: str,
) -> dict[str, Any]:
    return run_profile_gate(
        store,
        profile_name,
        profile_runner=run_profile,
    )


def _run_final_readiness(
    store: WorkdayConnectStore,
) -> dict[str, Any]:
    return run_final_readiness(
        store,
        profile_runner=run_profile,
    )


def _ensure_migration_baseline(store: WorkdayConnectStore) -> None:
    ensure_migration_baseline(store, profile_runner=run_profile)


def _set_workday_tenant(
    args: argparse.Namespace,
    store: WorkdayConnectStore,
) -> dict[str, Any]:
    tenant = normalize_workday_tenant_input(args.tenant)
    workday_saml_entity_id(tenant)
    state = store.merge_section("scope", {"workdayTenant": tenant})
    return {
        "workdayTenant": state["scope"]["workdayTenant"],
        "status": store.status(),
    }


def _require_administrator_completion(
    state: Mapping[str, Any],
    phase_id: str,
) -> None:
    substage = state["phases"][phase_id]["administrator"]["substage"]
    if ADMINISTRATOR_SUBSTAGES.index(substage) < (
        ADMINISTRATOR_SUBSTAGES.index("completion-confirmed")
    ):
        raise WorkdayConnectStoreError(
            f"Confirm the '{phase_id}' administrator completed the presented "
            "handoff before collecting evidence."
        )


def _merge_entra_verification(
    state: Mapping[str, Any],
    verification: Mapping[str, Any],
) -> dict[str, Any]:
    scope = state.get("scope") or {}
    expected_tenant_id = str(scope.get("entraTenantId") or "").strip()
    partial = dict(
        state["phases"]["entra"]["administrator"]["partialEvidence"]
    )
    merged = dict(verification)
    merged.setdefault(
        "tenantId",
        partial.get("selectedDirectoryId") or expected_tenant_id,
    )
    selected_directory_value = merged.get("selectedDirectory")
    if selected_directory_value is None or isinstance(
        selected_directory_value,
        Mapping,
    ):
        selected_directory = dict(selected_directory_value or {})
        selected_directory.setdefault(
            "tenantId",
            partial.get("selectedDirectoryId") or expected_tenant_id,
        )
        selected_directory.setdefault(
            "displayName",
            partial.get("selectedDirectoryDisplayName"),
        )
        if selected_directory:
            merged["selectedDirectory"] = selected_directory
    application_value = merged.get("application")
    if application_value is None or isinstance(application_value, Mapping):
        application = dict(application_value or {})
        for target, source in (
            ("displayName", "applicationDisplayName"),
            ("appId", "applicationId"),
            ("objectId", "applicationObjectId"),
            ("servicePrincipalId", "servicePrincipalId"),
            ("identifierUris", "applicationIdentifierUris"),
            ("replyUrls", "applicationReplyUrls"),
        ):
            application.setdefault(target, partial.get(source))
        app_id = str(application.get("appId") or "").strip()
        workday_tenant = str(scope.get("workdayTenant") or "").strip()
        if not application.get("identifierUris") and app_id and workday_tenant:
            application["identifierUris"] = [
                workday_saml_entity_id(workday_tenant),
                f"api://{app_id}",
            ]
        reply_url = str(
            merged.get("replyUrl") or partial.get("replyUrl") or ""
        ).strip()
        if not application.get("replyUrls") and reply_url:
            application["replyUrls"] = [reply_url]
        if application:
            merged["application"] = application
    certificate_value = merged.get("certificate")
    if certificate_value is None or isinstance(certificate_value, Mapping):
        certificate = dict(certificate_value or {})
        for target, source in (
            ("thumbprint", "certificateThumbprint"),
            ("validFrom", "certificateValidFrom"),
            ("validTo", "certificateValidTo"),
        ):
            certificate.setdefault(target, partial.get(source))
        if certificate:
            merged["certificate"] = certificate
    for key, partial_key in (
        ("scopeGuid", "scopeGuid"),
        ("replyUrl", "replyUrl"),
        ("microsoftEntraIdentifier", "microsoftEntraIdentifier"),
        ("loginUrl", "loginUrl"),
        ("checks", "entraChecks"),
    ):
        merged.setdefault(key, partial.get(partial_key))
    if expected_tenant_id:
        merged.setdefault(
            "microsoftEntraIdentifier",
            f"https://sts.windows.net/{expected_tenant_id}/",
        )
        merged.setdefault(
            "loginUrl",
            "https://login.microsoftonline.com/"
            f"{expected_tenant_id}/saml2",
        )
    return merged


def _section_matches(
    state: Mapping[str, Any],
    section: str,
    values: Mapping[str, Any],
) -> bool:
    current = state.get(section) or {}
    return all(current.get(key) == value for key, value in values.items())


def _action_evidence(
    state: Mapping[str, Any],
    phase_id: str,
    action: str,
) -> dict[str, Any] | None:
    for record in state["phases"][phase_id]["evidence"]:
        if record.get("action") != action:
            continue
        return {
            key: value
            for key, value in record.items()
            if key not in {"action", "capturedAt"}
        }
    return None


def _post_skill_next_steps(realm: str) -> list[str]:
    if realm == "dev":
        return [
            "Promote the agent from Development to Test when ready.",
            (
                "Return to Connect Workday and say that the agent was "
                "promoted to Test."
            ),
        ]
    if realm == "test":
        return [
            "Promote the agent from Test to Production when ready.",
            (
                "Return to Connect Workday and say that the agent was "
                "promoted to Production."
            ),
        ]
    if realm == "prod":
        return [
            "Publish and deploy the Production agent when ready.",
            (
                "Have each non-maker employee establish their own Workday "
                "connections in Microsoft 365 Chat."
            ),
            (
                "Validate an enabled Workday scenario with the published "
                "Production agent."
            ),
        ]
    raise WorkdayConnectStoreError(
        f"Unsupported Workday target realm: {realm}"
    )


def _entra_handoff(
    args: argparse.Namespace,
    store: WorkdayConnectStore,
) -> dict[str, Any]:
    state = store.load()
    administrator = state["phases"]["entra"]["administrator"]
    discovery = None
    if (
        getattr(args, "discovery_file", None) is not None
        or getattr(args, "discovery_json", None) is not None
    ):
        discovery = _json_input(args, "discovery", "Entra discovery")
    packet = build_entra_handoff(
        state,
        discovery,
    )
    already_presented = ADMINISTRATOR_SUBSTAGES.index(
        administrator["substage"]
    ) >= ADMINISTRATOR_SUBSTAGES.index("handoff-presented")
    return {
        "packet": packet,
        "alreadyPresented": already_presented,
        "rediscoveryRequired": packet["requiresRediscovery"],
        "status": store.status(),
    }


def _administrator_stage(
    args: argparse.Namespace,
    store: WorkdayConnectStore,
) -> dict[str, Any]:
    state = store.record_administrator_progress(
        args.phase,
        args.substage,
    )
    return {
        "phase": args.phase,
        "substage": state["phases"][args.phase]["administrator"]["substage"],
        "status": store.status(),
    }


def _record_administrator_evidence(
    args: argparse.Namespace,
    store: WorkdayConnectStore,
) -> dict[str, Any]:
    evidence = _json_input(
        args,
        "evidence",
        "administrator partial evidence",
    )
    allowed = {"fields", "invalidFields"}
    unexpected = sorted(set(evidence) - allowed)
    if unexpected:
        raise WorkdayConnectStoreError(
            "Administrator partial evidence contains unsupported fields: "
            + ", ".join(unexpected)
        )
    fields = evidence.get("fields") or {}
    invalid_fields = evidence.get("invalidFields") or []
    if not isinstance(fields, dict):
        raise WorkdayConnectStoreError(
            "Administrator partial evidence fields must be an object."
        )
    if not isinstance(invalid_fields, list):
        raise WorkdayConnectStoreError(
            "Administrator invalidFields must be an array."
        )
    if any(not isinstance(field, str) for field in invalid_fields):
        raise WorkdayConnectStoreError(
            "Administrator invalidFields must contain field names."
        )
    state = store.load()
    _require_administrator_completion(state, args.phase)
    validated = validate_administrator_partial_evidence(
        state,
        args.phase,
        fields,
    )
    combined_invalid = list(
        dict.fromkeys(
            [
                *invalid_fields,
                *validated["fieldErrors"].keys(),
            ]
        )
    )
    state = store.record_administrator_progress(
        args.phase,
        "collecting-evidence",
        valid_fields=validated["validFields"],
        invalid_fields=combined_invalid,
    )
    administrator = state["phases"][args.phase]["administrator"]
    return {
        "phase": args.phase,
        "acceptedFields": sorted(validated["validFields"]),
        "invalidFields": administrator["invalidFields"],
        "fieldErrors": validated["fieldErrors"],
        "outstandingFields": next(
            phase["administrator"]["outstandingFields"]
            for phase in store.status()["phases"]
            if phase["id"] == args.phase
        ),
        "status": store.status(),
    }


def _record_entra(
    args: argparse.Namespace,
    store: WorkdayConnectStore,
) -> dict[str, Any]:
    state = store.load()
    _require_administrator_completion(state, "entra")
    result = validate_entra_verification(
        state,
        _merge_entra_verification(
            state,
            _json_input(
                args,
                "verification",
                "Entra verification",
                worksheet_parser=parse_entra_return_worksheet,
                worksheet_state=state,
            ),
        ),
    )
    if state["phases"]["entra"]["status"] == "complete":
        identifiers_match = _section_matches(
            state,
            "identifiers",
            result["identifiers"],
        )
        application_evidence_match = _action_evidence(
            state,
            "entra",
            "exact-application-discovered",
        ) == {
            "outcome": "verified",
            "tenantId": result["evidence"]["tenantId"],
            "applicationDisplayName": result["evidence"][
                "applicationDisplayName"
            ],
        }
        configuration_evidence_match = _action_evidence(
            state,
            "entra",
            "administrator-configuration-verified",
        ) == {
            "outcome": "verified",
            "checks": result["evidence"]["checks"],
        }
        if (
            identifiers_match
            and application_evidence_match
            and configuration_evidence_match
        ):
            return {
                "verified": True,
                "replayed": True,
                "tenantFoundationReused": (
                    state["phases"]["workday-admin"]["status"]
                    == "complete"
                ),
                "status": store.status(),
            }
        store.merge_section("identifiers", result["identifiers"])
        return {
            "verified": False,
            "replayed": False,
            "driftDetected": True,
            "status": store.status(),
        }
    store.merge_section(
        "identifiers",
        result["identifiers"],
        verified_phase="entra",
    )
    if ADMINISTRATOR_SUBSTAGES.index(
        state["phases"]["entra"]["administrator"]["substage"]
    ) <= ADMINISTRATOR_SUBSTAGES.index("collecting-evidence"):
        store.record_administrator_progress(
            "entra",
            "collecting-evidence",
            valid_fields=result["partialEvidence"],
        )
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
    store.record_lifecycle_event(
        "roles-attested",
        phase="entra",
        outcome="success",
        once_per_lifecycle=True,
    )
    store.set_phase_status("entra", "complete")
    _, reused = store.restore_workday_foundation()
    if reused:
        _run_profile_gate(store, "workday-da:external-prerequisites")
        store.set_phase_status("workday-admin", "complete")
        store.record_lifecycle_event(
            "roles-attested",
            phase="workday-admin",
            outcome="success",
            once_per_lifecycle=True,
        )
    return {
        "verified": True,
        "tenantFoundationReused": reused,
        "status": store.status(),
    }


def _workday_admin_packet(
    _args: argparse.Namespace,
    store: WorkdayConnectStore,
) -> dict[str, Any]:
    state = store.load()
    if state["phases"]["entra"]["status"] != "complete":
        raise WorkdayConnectStoreError(
            "Complete the Microsoft Entra administrator sign-off before "
            "starting the Workday administrator handoff."
        )
    administrator = state["phases"]["workday-admin"]["administrator"]
    packet = build_workday_admin_packet(state)
    already_presented = ADMINISTRATOR_SUBSTAGES.index(
        administrator["substage"]
    ) >= ADMINISTRATOR_SUBSTAGES.index("handoff-presented")
    return {
        "packet": packet,
        "alreadyPresented": already_presented,
        "status": store.status(),
    }


def _record_workday_admin(
    args: argparse.Namespace,
    store: WorkdayConnectStore,
) -> dict[str, Any]:
    state = store.load()
    if state["phases"]["entra"]["status"] != "complete":
        raise WorkdayConnectStoreError(
            "Complete the Microsoft Entra administrator sign-off before "
            "recording Workday administrator evidence."
        )
    _require_administrator_completion(state, "workday-admin")
    response = {
        **dict(
            state["phases"]["workday-admin"]["administrator"][
                "partialEvidence"
            ]
        ),
        **_json_input(
            args,
            "response",
            "Workday administrator response",
            worksheet_parser=parse_workday_admin_return_worksheet,
            worksheet_state=state,
        ),
    }
    result = validate_workday_admin_response(
        state,
        response,
    )
    if state["phases"]["workday-admin"]["status"] == "complete":
        evidence_match = _action_evidence(
            state,
            "workday-admin",
            "administrator-response-validated",
        ) == {
            "outcome": "verified",
            **result["evidence"],
        }
        if (
            _section_matches(
                state,
                "identifiers",
                result["identifiers"],
            )
            and _section_matches(
                state,
                "endpoints",
                result["endpoints"],
            )
            and evidence_match
        ):
            _run_profile_gate(
                store,
                "workday-da:external-prerequisites",
            )
            if state.get("tenantFoundation") is None:
                store.capture_tenant_foundation()
            return {
                "verified": True,
                "replayed": True,
                "status": store.status(),
            }
        store.merge_section("identifiers", result["identifiers"])
        store.merge_section("endpoints", result["endpoints"])
        return {
            "verified": False,
            "replayed": False,
            "driftDetected": True,
            "status": store.status(),
        }
    store.merge_section(
        "identifiers",
        result["identifiers"],
        verified_phase="workday-admin",
    )
    store.merge_section(
        "endpoints",
        result["endpoints"],
        verified_phase="workday-admin",
    )
    if ADMINISTRATOR_SUBSTAGES.index(
        state["phases"]["workday-admin"]["administrator"]["substage"]
    ) <= ADMINISTRATOR_SUBSTAGES.index("collecting-evidence"):
        store.record_administrator_progress(
            "workday-admin",
            "collecting-evidence",
            valid_fields=result["partialEvidence"],
        )
    store.complete_action(
        "workday-admin",
        "administrator-response-validated",
        evidence={"outcome": "verified", **result["evidence"]},
    )
    store.record_lifecycle_event(
        "roles-attested",
        phase="workday-admin",
        outcome="success",
        once_per_lifecycle=True,
    )
    _run_profile_gate(store, "workday-da:external-prerequisites")
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
    result = run_runtime_operation(
        store.load(),
        apply=False,
        workday_connection_id=args.workday_connection_id,
        dataverse_connection_id=args.dataverse_connection_id,
    )
    store.record_lifecycle_event("plan-generated", phase="runtime")
    return result


def _runtime_apply(
    args: argparse.Namespace,
    store: WorkdayConnectStore,
) -> dict[str, Any]:
    revalidate_active_realm_target(args.root, store)
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
        _json_input(args, "plan", "runtime plan"),
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
    state = store.load()
    if "verify-package" not in state["phases"]["connections"][
        "completedActions"
    ]:
        raise WorkdayConnectStoreError(
            "Install or verify the Workday package before checking physical "
            "connections."
        )
    evidence = verify_physical_connections(
        state,
        workday_connection_id=args.workday_connection_id,
        dataverse_connection_id=args.dataverse_connection_id,
    )
    if not getattr(args, "confirm_workday_target", False):
        identifiers = state.get("identifiers") or {}
        endpoints = state.get("endpoints") or {}
        scope = state.get("scope") or {}
        return {
            "requiresConfirmation": True,
            "connections": evidence["connections"],
            "workdayTarget": {
                "displayName": "",
                "authenticationType": "Microsoft Entra ID Integrated",
                "resourceUrl": identifiers.get("workdaySamlEntityId"),
                "oauthTokenUrl": endpoints.get("oauthTokenUrl"),
                "oauthClientId": identifiers.get("oauthClientId"),
                "soapBaseUrl": endpoints.get("soapBaseUrl"),
                "restBaseUrl": endpoints.get("restBaseUrl"),
                "tenantName": scope.get("workdayTenant"),
            },
            "status": store.status(),
        }
    store.complete_action(
        "connections",
        "physical-connections-verified",
        evidence={
            "outcome": "verified",
            "source": "live-power-platform-discovery",
            "makerUsername": evidence["makerUsername"],
            "connections": evidence["connections"],
            "connectionIds": evidence["connectionIds"],
            "workdayTargetOutcome": "maker-confirmed-against-workday-packet",
        },
    )
    store.set_phase_status("connections", "complete")
    return {"verified": True, "status": store.status()}


def _record_agent_binding(
    args: argparse.Namespace,
    store: WorkdayConnectStore,
) -> dict[str, Any]:
    flow_attachment = _json_input(
        args,
        "attachment",
        "Workday flow attachment confirmation",
    )
    state = store.load()
    live_evidence = verify_agent_binding(store.workspace_root, state)
    live_evidence["flowAttachment"] = flow_attachment
    evidence = validate_agent_binding_evidence(
        state,
        live_evidence,
    )
    store.complete_action(
        "runtime",
        "agent-parameter-sharing-verified",
        evidence={
            "outcome": "verified",
            "result": evidence["flowAttachment"][
                "parameterSharingOutcome"
            ],
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
            "flowNames": evidence["flowAttachment"]["flowNames"],
            "parameterSharingOutcome": (
                evidence["flowAttachment"]["parameterSharingOutcome"]
            ),
            "provenance": "maker-confirmed-selected-agent-settings",
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
            "blockingDiagnostics": (
                evidence["workdayTopics"]["blockingDiagnostics"]
            ),
        },
    )
    store.complete_action(
        "runtime",
        "user-context-v2-configured",
        evidence={
            "outcome": "verified",
            "result": "live-agent-binding-verified",
        },
    )
    _run_profile_gate(
        store,
        "workday-da:dataverse-ready",
    )
    _run_profile_gate(
        store,
        "workday-da:post-connection",
    )
    _run_profile_gate(
        store,
        "workday-da:post-agent-wiring",
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
    return {
        "verified": True,
        "diagnosticsObserved": len(diagnostics),
        "status": store.status(),
    }


def _record_runtime_template_wiring(
    _args: argparse.Namespace,
    store: WorkdayConnectStore,
) -> dict[str, Any]:
    state = store.load()
    if "workday-topics-activated" not in state["phases"]["runtime"][
        "completedActions"
    ]:
        raise WorkdayConnectStoreError(
            "Enable and verify all Workday topics before wiring the runtime "
            "template into Conversation Start."
        )
    evidence = verify_runtime_template_wiring(
        store.workspace_root,
        state,
    )
    store.complete_action(
        "runtime",
        "runtime-template-configured",
        evidence={
            "outcome": "verified",
            **evidence,
        },
    )
    return {
        "verified": True,
        "blockingDiagnostics": evidence["blockingDiagnostics"],
        "status": store.status(),
    }


def _record_validation(
    args: argparse.Namespace,
    store: WorkdayConnectStore,
) -> dict[str, Any]:
    with store.maker_validation_guard():
        evidence = validate_maker_evidence(
            _json_input(args, "evidence", "maker validation evidence")
        )
        phase = store.load()["phases"]["maker-validation"]
        maker_evidence = {
            "testUserCategory": "maker",
            "timestamp": evidence["timestamp"],
            "outcome": evidence["outcome"],
        }
        blocker = phase.get("blocker")
        if (
            isinstance(blocker, Mapping)
            and blocker.get("remediationId") == "WD-E2E-006"
        ):
            scenario_name = str(evidence.get("scenarioName") or "").strip()
            if scenario_name != blocker.get("scenarioName"):
                raise WorkdayConnectContractError(
                    "Retest the same named scenario that observed "
                    "'Task not authorized'."
                )
            maker_evidence.update(
                {
                    "scenarioName": scenario_name,
                    "authorizationOutcome": (
                        "task-not-authorized-remediated"
                    ),
                    "authorizationRemediationDomain": blocker[
                        "affectedDomain"
                    ],
                    "authorizationRetestOutcome": (
                        "verified-after-remediation"
                    ),
                }
            )
        elif evidence.get("scenarioName"):
            maker_evidence["scenarioName"] = evidence["scenarioName"]
        replayed = (
            phase["status"] == "complete"
            and _action_evidence(
                {"phases": {"maker-validation": phase}},
                "maker-validation",
                "maker-smoke-test",
            )
            == maker_evidence
        )
        if not replayed:
            store.complete_action(
                "maker-validation",
                "maker-smoke-test",
                evidence=maker_evidence,
            )
        _run_final_readiness(store)
        final_state = store.finalize_maker_validation_success()
        active_realm = final_state["activeTargetRealm"]
        status = store.status()
        if replayed:
            return {
                "verified": True,
                "replayed": True,
                "lifecycleComplete": True,
                "activeTargetRealm": active_realm,
                "postSkillNextSteps": _post_skill_next_steps(active_realm),
                "status": status,
            }
        return {
            "verified": True,
            "lifecycleComplete": True,
            "activeTargetRealm": active_realm,
            "postSkillNextSteps": _post_skill_next_steps(active_realm),
            "status": status,
        }


def _record_validation_failure(
    args: argparse.Namespace,
    store: WorkdayConnectStore,
) -> dict[str, Any]:
    evidence = validate_maker_failure_evidence(
        _json_input(args, "evidence", "maker validation failure")
    )
    state = store.load()
    if state["phases"]["runtime"]["status"] != "complete":
        raise WorkdayConnectStoreError(
            "Complete runtime configuration before recording Maker "
            "validation remediation."
        )
    store.set_phase_status(
        "maker-validation",
        "blocked",
        blocker={
            "operation": "record-validation",
            "errorType": "WorkdayAuthorizationRemediationRequired",
            "message": (
                "The maker observed 'Task not authorized'. Correct the "
                "recorded Workday domain and retest the same scenario."
            ),
            **evidence,
        },
    )
    return {
        "recorded": True,
        "remediationId": evidence["remediationId"],
        "scenarioName": evidence["scenarioName"],
        "status": store.status(),
    }


def _preflight(
    args: argparse.Namespace,
    store: WorkdayConnectStore,
) -> dict[str, Any]:
    result = run_preflight(
        Path(args.root),
        dataverse_url=args.dataverse_url,
        maker_username=args.maker_username,
        store=store,
        defer_completion=True,
    )
    _run_profile_gate(store, "workday-da:setup-readiness")
    store.set_phase_status("preflight", "complete")
    result["verificationChecks"].append(
        {
            "name": "Selected agent availability and content readiness",
            "status": "verified",
        }
    )
    result["status"] = store.status()
    return result


def _prepare_connections(
    args: argparse.Namespace,
    store: WorkdayConnectStore,
) -> dict[str, Any]:
    result = prepare_connections_package(
        store.workspace_root,
        store=store,
        approved_install_hash=args.install_plan_hash,
        plan_verifier=lambda plan, approved_hash: store.verify_plan(
            "connections",
            plan,
            approved_hash,
        ),
    )
    if result.get("requiresApproval"):
        store.record_lifecycle_event("plan-generated", phase="connections")
        return result
    _run_profile_gate(store, "workday-da:package-ready")
    result["status"] = store.status()
    return result


def _prepare_connections_approve(
    args: argparse.Namespace,
    store: WorkdayConnectStore,
) -> dict[str, Any]:
    _, approved_hash = store.approve_plan(
        "connections",
        _json_input(args, "plan", "Connections package installation plan"),
    )
    return {"planHash": approved_hash, "status": store.status()}


_COMMAND_HANDLERS: dict[
    str,
    Callable[[argparse.Namespace, WorkdayConnectStore], dict[str, Any]],
] = {
    "status": _status,
    "discover-realm-target": _discover_realm_target,
    "set-workday-tenant": _set_workday_tenant,
    "entra-handoff": _entra_handoff,
    "record-entra": _record_entra,
    "administrator-stage": _administrator_stage,
    "record-administrator-evidence": _record_administrator_evidence,
    "workday-admin-packet": _workday_admin_packet,
    "record-workday-admin": _record_workday_admin,
    "runtime-plan": _runtime_plan,
    "runtime-apply": _runtime_apply,
    "runtime-approve": _runtime_approve,
    "record-connections": _record_connections,
    "record-topic-activation": _record_topic_activation,
    "record-runtime-template-wiring": _record_runtime_template_wiring,
    "record-agent-binding": _record_agent_binding,
    "record-validation": _record_validation,
    "record-validation-failure": _record_validation_failure,
    "preflight": _preflight,
    "prepare-connections": _prepare_connections,
    "prepare-connections-approve": _prepare_connections_approve,
}

_COMMAND_PHASES = {
    "discover-realm-target": None,
    "preflight": "preflight",
    "set-workday-tenant": "entra",
    "entra-handoff": "entra",
    "record-entra": "entra",
    "administrator-stage": None,
    "record-administrator-evidence": None,
    "workday-admin-packet": "workday-admin",
    "record-workday-admin": "workday-admin",
    "record-connections": "connections",
    "runtime-plan": "runtime",
    "runtime-approve": "runtime",
    "runtime-apply": "runtime",
    "record-topic-activation": "runtime",
    "record-runtime-template-wiring": "runtime",
    "record-agent-binding": "runtime",
    "record-validation": "maker-validation",
    "record-validation-failure": "maker-validation",
    "prepare-connections": "connections",
    "prepare-connections-approve": "connections",
}


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    store = WorkdayConnectStore(
        Path(args.root),
        event_sink=emit_lifecycle_event,
    )
    try:
        if args.command == "status":
            store.record_lifecycle_event(
                "invoked",
                once_per_lifecycle=True,
            )
        handler = _COMMAND_HANDLERS.get(args.command)
        if handler is None:
            parser.error(f"Unsupported command: {args.command}")
        if args.command == "status":
            result = handler(args, store)
        else:
            with store.operation_guard():
                _ensure_migration_baseline(store)
                result = handler(args, store)
        _emit(args.command, result)
    except (
        OSError,
        WorkdayConnectModelError,
        WorkdayConnectAgentError,
        WorkdayConnectContractError,
        WorkdayConnectPlanChangedError,
        WorkdayConnectPreflightError,
        WorkdayConnectRealmError,
        WorkdayConnectRuntimeError,
        WorkdayConnectStoreError,
        WorkdayConnectFlightCheckError,
    ) as exc:
        phase_id = _COMMAND_PHASES.get(args.command)
        blocker_persistence_error = None
        if (
            phase_id
            and not getattr(exc, "profile_blocker_persisted", False)
            and not getattr(exc, "suppress_blocker_persistence", False)
        ):
            try:
                blocker = {
                    "operation": args.command,
                    "errorType": type(exc).__name__,
                    "message": str(exc),
                }
                if phase_id == "maker-validation":
                    existing_phase = (
                        store.load().get("phases", {}).get(phase_id, {})
                    )
                    existing_blocker = existing_phase.get("blocker") or {}
                    for key in (
                        "remediationId",
                        "failureCategory",
                        "failureSurface",
                        "timestamp",
                        "remediation",
                        "scenarioName",
                        "affectedDomain",
                        "capturedAt",
                    ):
                        if key in existing_blocker:
                            blocker[key] = existing_blocker[key]
                store.set_phase_status(
                    phase_id,
                    "blocked",
                    blocker=blocker,
                )
            except (
                OSError,
                WorkdayConnectModelError,
                WorkdayConnectStoreError,
            ) as persistence_exc:
                blocker_persistence_error = str(persistence_exc)
        error_payload = {
            "contractVersion": CONTROLLER_CONTRACT_VERSION,
            "operation": args.command,
            "error": str(exc),
            "errorType": type(exc).__name__,
        }
        details = getattr(exc, "details", None)
        if isinstance(details, dict) and details:
            error_payload["details"] = details
        customer_remediation = getattr(
            exc,
            "customer_remediation",
            "",
        )
        if customer_remediation:
            error_payload["remediation"] = customer_remediation
        if blocker_persistence_error:
            error_payload["blockerPersistenceError"] = blocker_persistence_error
        print(
            ERROR_MARKER
            + json.dumps(error_payload, sort_keys=True),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    finally:
        flush_lifecycle_telemetry()


if __name__ == "__main__":
    main()
