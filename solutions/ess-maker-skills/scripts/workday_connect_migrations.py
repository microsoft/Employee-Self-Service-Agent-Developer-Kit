# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Pure schema migrations for persisted Workday Connect state."""

from __future__ import annotations

import copy
from typing import Any, Callable, Mapping

from workday_connect_model import (
    ADMINISTRATOR_PHASES,
    LEGACY_PHASE_ROWS,
    PHASE_DEFINITIONS,
    PHASE_REQUIRED_ACTIONS,
    STATE_SCHEMA_VERSION,
    PhaseStatus,
    WorkdayConnectModelError,
    default_administrator_state,
    default_lifecycle_state,
    default_state,
    utc_now,
    validate_state,
    workday_saml_entity_id,
)
from workday_connect_state_policy import (
    invalidate_from_phase,
    legacy_administrator_partial_evidence,
    reset_phase,
    tenant_foundation_from_state,
)


class WorkdayConnectMigrationError(ValueError):
    """Raised when no supported Workday Connect migration path exists."""


def _legacy_phase_status(
    setup_status: Mapping[str, Any],
    rows: tuple[str, ...],
) -> str:
    values = [
        setup_status.get(row) for row in rows if isinstance(setup_status.get(row), dict)
    ]
    statuses = {str(value.get("state") or "pending") for value in values}
    if values and len(values) == len(rows) and statuses == {"done"}:
        return PhaseStatus.COMPLETE.value
    if "blocked" in statuses:
        return PhaseStatus.BLOCKED.value
    if statuses & {"done", "in-progress"}:
        return PhaseStatus.ACTIVE.value
    return PhaseStatus.PENDING.value


def _legacy_evidence(
    setup_status: Mapping[str, Any],
    rows: tuple[str, ...],
) -> list[dict[str, Any]]:
    evidence = []
    for row in rows:
        value = setup_status.get(row)
        if not isinstance(value, dict) or value.get("state") != "done":
            continue
        record = {
            "source": "legacy-state",
            "action": f"legacy:{row}",
            "verifiedBy": value.get("verifiedBy"),
        }
        source_evidence = value.get("evidence")
        if isinstance(source_evidence, dict):
            for key in ("outcome", "provenance", "capturedAt"):
                if source_evidence.get(key) is not None:
                    record[key] = source_evidence[key]
        evidence.append(record)
    return evidence


def _source_state_was_ready(document: Mapping[str, Any]) -> bool:
    phases = document.get("phases")
    return (
        document.get("status") == "ready"
        and isinstance(phases, Mapping)
        and all(
            isinstance(phases.get(definition.identifier.value), Mapping)
            and phases[definition.identifier.value].get("status")
            == PhaseStatus.COMPLETE.value
            for definition in PHASE_DEFINITIONS
        )
    )


def _normalize_package_evidence_ownership(
    document: Mapping[str, Any],
) -> dict[str, Any]:
    migrated = copy.deepcopy(dict(document))
    preflight = migrated["phases"]["preflight"]
    connections = migrated["phases"]["connections"]
    package_evidence = next(
        (
            copy.deepcopy(record)
            for record in preflight.get("evidence") or []
            if isinstance(record, Mapping) and record.get("action") == "verify-package"
        ),
        None,
    )
    preflight["completedActions"] = [
        action
        for action in preflight.get("completedActions") or []
        if action != "verify-package"
    ]
    preflight["evidence"] = [
        record
        for record in preflight.get("evidence") or []
        if not (
            isinstance(record, Mapping) and record.get("action") == "verify-package"
        )
    ]
    if package_evidence is not None:
        if "verify-package" not in connections["completedActions"]:
            connections["completedActions"].append("verify-package")
        if not any(
            isinstance(record, Mapping) and record.get("action") == "verify-package"
            for record in connections["evidence"]
        ):
            connections["evidence"].append(package_evidence)
    return migrated


def _migrate_legacy_state(document: Mapping[str, Any]) -> dict[str, Any]:
    state = default_state()
    setup_status = document.get("setupStatus")
    if not isinstance(setup_status, dict):
        setup_status = {}

    scope = state["scope"]
    if document.get("sidecarDataverseEndpoint"):
        scope["dataverseUrl"] = document["sidecarDataverseEndpoint"]
    if document.get("tenantId"):
        scope["entraTenantId"] = document["tenantId"]
    if document.get("tenant"):
        scope["workdayTenant"] = document["tenant"]
    if document.get("vertical"):
        scope["vertical"] = document["vertical"]
    if document.get("packageFlavor"):
        scope["packageFlavor"] = document["packageFlavor"]
    active_agent = document.get("activeAgent")
    if isinstance(active_agent, dict):
        scope["agent"] = {
            key: active_agent[key]
            for key in ("slug", "botId", "schemaName")
            if active_agent.get(key)
        }

    identifiers = state["identifiers"]
    field_map = {
        "entraAppId": "entraAppId",
        "entraAppObjectId": "entraAppObjectId",
        "scopeGuid": "scopeGuid",
        "oauthClientId": "oauthClientId",
        "entraSSO": "entraSSO",
    }
    for legacy, current in field_map.items():
        if document.get(legacy) is not None:
            identifiers[current] = document[legacy]
    app_id_uri = document.get("entraAppIdUri") or document.get("appIdUri")
    if app_id_uri:
        identifiers["entraAppIdUri"] = app_id_uri
    if scope.get("workdayTenant"):
        try:
            identifiers["workdaySamlEntityId"] = workday_saml_entity_id(
                scope["workdayTenant"]
            )
        except WorkdayConnectModelError:
            pass

    endpoints = state["endpoints"]
    endpoint_map = {
        "baseUrl": "workdayBaseUrl",
        "tokenHost": "tokenHost",
        "oauthTokenUrl": "oauthTokenUrl",
        "tokenEndpoint": "oauthTokenUrl",
        "restBaseUrl": "restBaseUrl",
        "soapBaseUrl": "soapBaseUrl",
        "domainName": "domainName",
    }
    for legacy, current in endpoint_map.items():
        if document.get(legacy) and current not in endpoints:
            endpoints[current] = document[legacy]

    operator_map = {
        "entraAdminUsername": ("entraAdmin", "username"),
        "entraAdminAccount": ("entraAdmin", "username"),
        "makerUsername": ("powerPlatformMaker", "username"),
    }
    for legacy, (operator, field) in operator_map.items():
        if document.get(legacy):
            state["operators"].setdefault(operator, {})[field] = document[legacy]

    for phase, rows in LEGACY_PHASE_ROWS.items():
        phase_state = state["phases"][phase.value]
        phase_state["status"] = _legacy_phase_status(setup_status, rows)
        phase_state["completedActions"] = [
            f"legacy:{row}"
            for row in rows
            if isinstance(setup_status.get(row), dict)
            and setup_status[row].get("state") == "done"
        ]
        phase_state["evidence"] = _legacy_evidence(setup_status, rows)
        if phase_state["status"] == PhaseStatus.COMPLETE.value:
            for action in PHASE_REQUIRED_ACTIONS[phase.value]:
                if phase.value == "runtime" and action in {
                    "runtime-template-configured",
                    "workday-topics-activated",
                }:
                    continue
                if action not in phase_state["completedActions"]:
                    phase_state["completedActions"].append(action)
                phase_state["evidence"].append(
                    {
                        "source": "legacy-state",
                        "action": action,
                        "outcome": "verified",
                        "capturedAt": utc_now(),
                    }
                )
        if phase_state["status"] != PhaseStatus.PENDING.value:
            phase_state["updatedAt"] = utc_now()
        if (
            phase.value in ADMINISTRATOR_PHASES
            and phase_state["status"] == PhaseStatus.COMPLETE.value
        ):
            phase_state["administrator"]["substage"] = "evidence-validated"
            phase_state["administrator"]["updatedAt"] = utc_now()

    runtime = state["phases"]["runtime"]
    if runtime["status"] == PhaseStatus.COMPLETE.value and not (
        {
            "runtime-template-configured",
            "workday-topics-activated",
        }
        <= set(runtime["completedActions"])
    ):
        runtime["status"] = PhaseStatus.ACTIVE.value
        runtime["updatedAt"] = utc_now()
        reset_phase(state["phases"]["employee-validation"])

    if all(
        phase["status"] == PhaseStatus.COMPLETE.value
        for phase in state["phases"].values()
    ):
        state["status"] = "ready"
    state["tenantFoundation"] = tenant_foundation_from_state(state)
    state["migration"] = {
        "source": (
            "workday-da-state-v1"
            if document.get("stateSchemaVersion")
            else "legacy-workday-da-config"
        ),
        "migratedAt": utc_now(),
    }
    state["updatedAt"] = utc_now()
    return validate_state(state)


def _upgrade_structured_state(
    document: Mapping[str, Any],
    *,
    source_version: int,
) -> dict[str, Any]:
    state = copy.deepcopy(dict(document))
    state["schemaVersion"] = STATE_SCHEMA_VERSION
    if "lifecycle" not in state:
        state["lifecycle"] = default_lifecycle_state()
    existing_foundation = state.get("tenantFoundation")
    captured_foundation = tenant_foundation_from_state(state)
    if captured_foundation is not None:
        state["tenantFoundation"] = captured_foundation
    elif (
        isinstance(existing_foundation, Mapping)
        and {
            "scope",
            "identifiers",
            "endpoints",
            "phases",
            "capturedAt",
        }
        <= existing_foundation.keys()
    ):
        state["tenantFoundation"] = copy.deepcopy(dict(existing_foundation))
    else:
        state["tenantFoundation"] = None
    first_incomplete: str | None = None
    for definition in PHASE_DEFINITIONS:
        phase_id = definition.identifier.value
        phase = state["phases"][phase_id]
        phase.setdefault("validationProfiles", {})
        if phase_id == "employee-validation":
            phase.setdefault("employeeTestAttempt", None)
        else:
            phase.pop("employeeTestAttempt", None)
        if phase_id in ADMINISTRATOR_PHASES:
            phase.setdefault("administrator", default_administrator_state())
        else:
            phase.pop("administrator", None)
        phase.pop("scopeHash", None)
        phase.pop("manualHandoff", None)
        if phase["status"] == "waiting":
            phase["status"] = PhaseStatus.ACTIVE.value
        if first_incomplete is not None:
            if phase["status"] == PhaseStatus.COMPLETE.value:
                reset_phase(phase)
            continue
        if phase["status"] != PhaseStatus.COMPLETE.value:
            first_incomplete = phase_id
            continue
        required = PHASE_REQUIRED_ACTIONS[phase_id]
        completed = set(phase.get("completedActions") or [])
        evidence_actions = {
            str(record.get("action") or "")
            for record in (phase.get("evidence") or [])
            if isinstance(record, dict)
        }
        if not required <= completed or not required <= evidence_actions:
            phase["status"] = PhaseStatus.ACTIVE.value
            phase["updatedAt"] = utc_now()
            first_incomplete = phase_id
        elif phase_id in ADMINISTRATOR_PHASES:
            phase["administrator"]["substage"] = "evidence-validated"
            phase["administrator"]["invalidFields"] = []
            phase["administrator"]["updatedAt"] = utc_now()
    state["status"] = (
        "ready"
        if all(
            phase["status"] == PhaseStatus.COMPLETE.value
            for phase in state["phases"].values()
        )
        else "in-progress"
    )
    state["migration"] = {
        "source": f"workday-connect-state-v{source_version}",
        "migratedAt": utc_now(),
    }
    state["updatedAt"] = utc_now()
    return validate_state(state)


def _upgrade_pre_v7_state(
    document: Mapping[str, Any],
    *,
    source_version: int,
) -> dict[str, Any]:
    state = _upgrade_structured_state(
        document,
        source_version=source_version,
    )
    if state["phases"]["entra"]["status"] != PhaseStatus.COMPLETE.value:
        return state
    preserved = {
        phase_id: legacy_administrator_partial_evidence(
            state,
            phase_id,
        )
        for phase_id in ADMINISTRATOR_PHASES
    }
    invalidate_from_phase(state, "entra")
    for phase_id, fields in preserved.items():
        if not fields:
            continue
        administrator = state["phases"][phase_id]["administrator"]
        administrator["partialEvidence"] = fields
        administrator["substage"] = "collecting-evidence"
        administrator["updatedAt"] = utc_now()
    if preserved["entra"]:
        state["phases"]["entra"]["status"] = PhaseStatus.ACTIVE.value
        state["phases"]["entra"]["updatedAt"] = utc_now()
    state["status"] = "in-progress"
    state["updatedAt"] = utc_now()
    return validate_state(state)


def _upgrade_readiness_state(
    document: Mapping[str, Any],
    *,
    source_version: int,
) -> dict[str, Any]:
    legacy_ready = _source_state_was_ready(document)
    normalized = _normalize_package_evidence_ownership(document)
    state = _upgrade_structured_state(
        normalized,
        source_version=source_version,
    )
    baseline_required = any(
        state["phases"][phase_id]["status"] == PhaseStatus.COMPLETE.value
        for phase_id in ("preflight", "workday-admin", "runtime")
    )
    migration = dict(state.get("migration") or {})
    migration.update(
        {
            "source": f"workday-connect-state-v{source_version}",
            "migratedAt": utc_now(),
            "flightcheckBaselineRequired": baseline_required,
            "legacyReady": legacy_ready,
        }
    )
    state["migration"] = migration
    if baseline_required:
        if legacy_ready:
            employee_phase = state["phases"]["employee-validation"]
            employee_phase["status"] = PhaseStatus.ACTIVE.value
            employee_phase["updatedAt"] = utc_now()
        state["status"] = "in-progress"
    state["updatedAt"] = utc_now()
    return validate_state(state)


def _upgrade_v2_state(document: Mapping[str, Any]) -> dict[str, Any]:
    return _upgrade_pre_v7_state(document, source_version=2)


def _upgrade_v3_state(document: Mapping[str, Any]) -> dict[str, Any]:
    return _upgrade_pre_v7_state(document, source_version=3)


def _upgrade_v4_state(document: Mapping[str, Any]) -> dict[str, Any]:
    return _upgrade_pre_v7_state(document, source_version=4)


def _upgrade_v5_state(document: Mapping[str, Any]) -> dict[str, Any]:
    return _upgrade_pre_v7_state(document, source_version=5)


def _upgrade_v6_state(document: Mapping[str, Any]) -> dict[str, Any]:
    return _upgrade_pre_v7_state(document, source_version=6)


def _upgrade_v7_state(document: Mapping[str, Any]) -> dict[str, Any]:
    return _upgrade_readiness_state(document, source_version=7)


def _upgrade_v8_state(document: Mapping[str, Any]) -> dict[str, Any]:
    return _upgrade_readiness_state(document, source_version=8)


_UPGRADES: dict[int, Callable[[Mapping[str, Any]], dict[str, Any]]] = {
    2: _upgrade_v2_state,
    3: _upgrade_v3_state,
    4: _upgrade_v4_state,
    5: _upgrade_v5_state,
    6: _upgrade_v6_state,
    7: _upgrade_v7_state,
    8: _upgrade_v8_state,
}


def migrate_state(document: Mapping[str, Any]) -> dict[str, Any]:
    """Return a validated schema-v9 state without performing any I/O."""
    source_version = document.get("schemaVersion")
    if "schemaVersion" in document and not isinstance(
        source_version,
        (str, int, float, bool, type(None)),
    ):
        raise WorkdayConnectMigrationError(
            "Unsupported Workday connect state schema version: "
            f"{source_version!r}. Use the kit version that created this state "
            "or restore a compatible backup."
        )
    upgrade = _UPGRADES.get(source_version)
    if upgrade is not None:
        return upgrade(document)
    if "schemaVersion" in document:
        raise WorkdayConnectMigrationError(
            "Unsupported Workday connect state schema version: "
            f"{source_version!r}. Use the kit version that created this state "
            "or restore a compatible backup."
        )
    return _migrate_legacy_state(document)
