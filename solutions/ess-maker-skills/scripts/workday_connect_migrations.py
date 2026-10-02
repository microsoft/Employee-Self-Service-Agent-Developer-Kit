# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Pure migration helpers for persisted Workday Connect state."""

from __future__ import annotations

import copy
from typing import Any, Callable, Mapping

from workday_connect_model import PHASE_DEFINITIONS, PhaseStatus


StateUpgrade = Callable[[Mapping[str, Any]], dict[str, Any]]


class UnsupportedStateSchemaError(ValueError):
    """Raised when no supported Workday Connect migration path exists."""


def legacy_phase_status(
    setup_status: Mapping[str, Any],
    rows: tuple[str, ...],
) -> str:
    values = [
        setup_status.get(row)
        for row in rows
        if isinstance(setup_status.get(row), dict)
    ]
    statuses = {str(value.get("state") or "pending") for value in values}
    if values and len(values) == len(rows) and statuses == {"done"}:
        return PhaseStatus.COMPLETE.value
    if "blocked" in statuses:
        return PhaseStatus.BLOCKED.value
    if statuses & {"done", "in-progress"}:
        return PhaseStatus.ACTIVE.value
    return PhaseStatus.PENDING.value


def legacy_evidence(
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


def source_state_was_ready(document: Mapping[str, Any]) -> bool:
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


def normalize_package_evidence_ownership(
    document: Mapping[str, Any],
) -> dict[str, Any]:
    migrated = copy.deepcopy(dict(document))
    preflight = migrated["phases"]["preflight"]
    connections = migrated["phases"]["connections"]
    package_evidence = next(
        (
            copy.deepcopy(record)
            for record in preflight.get("evidence") or []
            if isinstance(record, Mapping)
            and record.get("action") == "verify-package"
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
            isinstance(record, Mapping)
            and record.get("action") == "verify-package"
        )
    ]
    if package_evidence is not None:
        if "verify-package" not in connections["completedActions"]:
            connections["completedActions"].append("verify-package")
        if not any(
            isinstance(record, Mapping)
            and record.get("action") == "verify-package"
            for record in connections["evidence"]
        ):
            connections["evidence"].append(package_evidence)
    return migrated


def upgrade_or_migrate_state(
    document: Mapping[str, Any],
    *,
    upgrades: Mapping[int, StateUpgrade],
    migrate_legacy: StateUpgrade,
) -> dict[str, Any]:
    source_version = document.get("schemaVersion")
    upgrade = upgrades.get(source_version)
    if upgrade is not None:
        return upgrade(document)
    if "schemaVersion" in document:
        raise UnsupportedStateSchemaError(
            "Unsupported Workday connect state schema version: "
            f"{source_version!r}. Use the kit version that created this state "
            "or restore a compatible backup."
        )
    return migrate_legacy(document)
