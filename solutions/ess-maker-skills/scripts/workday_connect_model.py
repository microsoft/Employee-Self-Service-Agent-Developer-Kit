# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Typed lifecycle contracts for the Workday connect skill."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping


STATE_SCHEMA_VERSION = 3
CONTROLLER_CONTRACT_VERSION = 1
CATALOG_PATH = Path(__file__).with_name("workday_connect_catalog.json")


class WorkdayConnectModelError(ValueError):
    """Raised when lifecycle data violates the Workday connect contract."""


class Phase(str, Enum):
    PREFLIGHT = "preflight"
    ENTRA = "entra"
    WORKDAY_ADMIN = "workday-admin"
    CONNECTIONS = "connections"
    RUNTIME = "runtime"
    EMPLOYEE_VALIDATION = "employee-validation"


class PhaseStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    BLOCKED = "blocked"
    COMPLETE = "complete"


@dataclass(frozen=True)
class PhaseDefinition:
    identifier: Phase
    title: str
    short_title: str
    prerequisite: Phase | None


PHASE_DEFINITIONS = (
    PhaseDefinition(Phase.PREFLIGHT, "Preflight", "Preflight", None),
    PhaseDefinition(
        Phase.ENTRA,
        "Microsoft Entra",
        "Entra",
        Phase.PREFLIGHT,
    ),
    PhaseDefinition(
        Phase.WORKDAY_ADMIN,
        "Workday administrator",
        "Workday",
        Phase.ENTRA,
    ),
    PhaseDefinition(
        Phase.CONNECTIONS,
        "Connections",
        "Connections",
        Phase.WORKDAY_ADMIN,
    ),
    PhaseDefinition(
        Phase.RUNTIME,
        "Runtime configuration",
        "Runtime",
        Phase.CONNECTIONS,
    ),
    PhaseDefinition(
        Phase.EMPLOYEE_VALIDATION,
        "Employee validation",
        "Validate",
        Phase.RUNTIME,
    ),
)
PHASE_BY_ID = {
    definition.identifier.value: definition
    for definition in PHASE_DEFINITIONS
}

PHASE_REQUIRED_ACTIONS = {
    Phase.PREFLIGHT.value: frozenset({"verify-target", "verify-package"}),
    Phase.ENTRA.value: frozenset(
        {
            "exact-application-discovered",
            "administrator-configuration-verified",
        }
    ),
    Phase.WORKDAY_ADMIN.value: frozenset(
        {"administrator-response-validated"}
    ),
    Phase.CONNECTIONS.value: frozenset(
        {
            "physical-connections-verified",
            "agent-parameter-sharing-verified",
            "flow-attachment-confirmed",
        }
    ),
    Phase.RUNTIME.value: frozenset(
        {
            "connection-references-bound",
            "runtime-flows-active",
            "delegated-authorization-configured",
            "user-context-v2-configured",
        }
    ),
    Phase.EMPLOYEE_VALIDATION.value: frozenset({"signed-in-scenario"}),
}

LEGACY_PHASE_ROWS = {
    Phase.PREFLIGHT: ("DA1.1",),
    Phase.ENTRA: (
        "DA2.1",
        "DA2.2",
        "DA2.3",
        "DA2.4",
        "DA2.5",
        "DA2.6",
        "DA2.7",
    ),
    Phase.WORKDAY_ADMIN: ("DA3.1", "DA3.2", "DA3.3", "DA3.4"),
    Phase.CONNECTIONS: ("DA4.1", "DA4.2"),
    Phase.RUNTIME: (
        "DA4.3",
        "DA4.4",
        "DA4.5",
        "DA4.6",
        "DA4.7",
        "DA4.8",
    ),
    Phase.EMPLOYEE_VALIDATION: ("DA5.1",),
}

_TENANT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_SECRET_KEYS = {
    "password",
    "clientsecret",
    "access_token",
    "accesstoken",
    "refresh_token",
    "refreshtoken",
    "cookie",
    "certificatebody",
    "privatekey",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_catalog(path: Path = CATALOG_PATH) -> dict[str, Any]:
    try:
        catalog = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkdayConnectModelError(
            f"Workday connect catalog could not be loaded: {exc}"
        ) from exc
    if not isinstance(catalog, dict):
        raise WorkdayConnectModelError(
            "Workday connect catalog must contain a JSON object."
        )
    required = {
        "catalogVersion",
        "provider",
        "supportedAgents",
        "unsupportedAgents",
        "packages",
        "connectionReferences",
    }
    missing = sorted(required - catalog.keys())
    if missing:
        raise WorkdayConnectModelError(
            "Workday connect catalog is missing: " + ", ".join(missing)
        )
    if catalog["provider"] != "workday":
        raise WorkdayConnectModelError(
            "Workday connect catalog provider must be 'workday'."
        )
    return catalog


def workday_saml_entity_id(tenant: str) -> str:
    normalized = str(tenant or "").strip()
    if not _TENANT_RE.fullmatch(normalized):
        raise WorkdayConnectModelError(
            "Workday tenant must contain only letters, numbers, hyphens, "
            "and underscores."
        )
    return f"http://www.workday.com/{normalized}"


def canonical_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, Mapping):
        raise WorkdayConnectModelError("A Workday change plan must be an object.")
    document = dict(plan)
    document.pop("planHash", None)
    reject_sensitive_data(document)
    phase = str(document.get("phase") or "")
    if phase not in PHASE_BY_ID:
        raise WorkdayConnectModelError(f"Unknown Workday phase: {phase}.")
    actions = document.get("actions")
    if not isinstance(actions, list) or not actions:
        raise WorkdayConnectModelError(
            "A Workday change plan must contain at least one action."
        )
    if any(not isinstance(action, str) or not action.strip() for action in actions):
        raise WorkdayConnectModelError(
            "Workday change-plan actions must be non-empty strings."
        )
    scope = document.get("scope")
    if not isinstance(scope, dict) or not scope:
        raise WorkdayConnectModelError(
            "A Workday change plan must contain an exact scope."
        )
    return document


def plan_hash(plan: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        canonical_plan(plan),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def reject_sensitive_data(document: Any, path: str = "state") -> None:
    if isinstance(document, dict):
        for key, value in document.items():
            normalized = str(key).replace("-", "").replace("_", "").casefold()
            if normalized in _SECRET_KEYS:
                raise WorkdayConnectModelError(
                    f"Sensitive field '{path}.{key}' must not be persisted."
                )
            reject_sensitive_data(value, f"{path}.{key}")
    elif isinstance(document, list):
        for index, value in enumerate(document):
            reject_sensitive_data(value, f"{path}[{index}]")


def default_phase_state() -> dict[str, Any]:
    return {
        "status": PhaseStatus.PENDING.value,
        "completedActions": [],
        "approvedPlanHash": None,
        "approvedPlan": None,
        "evidence": [],
        "blocker": None,
        "updatedAt": None,
    }


def default_state() -> dict[str, Any]:
    return {
        "schemaVersion": STATE_SCHEMA_VERSION,
        "provider": "workday",
        "status": "in-progress",
        "scope": {},
        "identifiers": {},
        "endpoints": {},
        "operators": {},
        "phases": {
            definition.identifier.value: default_phase_state()
            for definition in PHASE_DEFINITIONS
        },
        "migration": None,
        "updatedAt": utc_now(),
    }


def _validate_phase_state(phase_id: str, value: Any) -> None:
    if not isinstance(value, dict):
        raise WorkdayConnectModelError(
            f"Phase '{phase_id}' state must be an object."
        )
    required = {
        "status",
        "completedActions",
        "approvedPlanHash",
        "approvedPlan",
        "evidence",
        "blocker",
        "updatedAt",
    }
    missing = sorted(required - value.keys())
    if missing:
        raise WorkdayConnectModelError(
            f"Phase '{phase_id}' is missing: " + ", ".join(missing)
        )
    if value["status"] not in {status.value for status in PhaseStatus}:
        raise WorkdayConnectModelError(
            f"Phase '{phase_id}' has invalid status '{value['status']}'."
        )
    if not isinstance(value["completedActions"], list) or any(
        not isinstance(action, str) or not action
        for action in value["completedActions"]
    ):
        raise WorkdayConnectModelError(
            f"Phase '{phase_id}' completedActions must contain strings."
        )
    if len(value["completedActions"]) != len(set(value["completedActions"])):
        raise WorkdayConnectModelError(
            f"Phase '{phase_id}' completedActions contains duplicates."
        )
    if not isinstance(value["evidence"], list) or any(
        not isinstance(record, dict)
        or not isinstance(record.get("action"), str)
        or not record.get("action")
        for record in value["evidence"]
    ):
        raise WorkdayConnectModelError(
            f"Phase '{phase_id}' evidence must contain action records."
        )
    approved_plan = value["approvedPlan"]
    approved_hash = value["approvedPlanHash"]
    if approved_plan is not None:
        observed_hash = plan_hash(approved_plan)
        if approved_hash != observed_hash:
            raise WorkdayConnectModelError(
                f"Phase '{phase_id}' approved plan hash does not match."
            )
    if value["status"] == PhaseStatus.COMPLETE.value:
        required_actions = PHASE_REQUIRED_ACTIONS[phase_id]
        completed_actions = set(value["completedActions"])
        missing_actions = sorted(required_actions - completed_actions)
        evidence_actions = {
            str(record.get("action") or "") for record in value["evidence"]
        }
        missing_evidence = sorted(required_actions - evidence_actions)
        if missing_actions or missing_evidence:
            details = []
            if missing_actions:
                details.append(
                    "actions=" + ", ".join(missing_actions)
                )
            if missing_evidence:
                details.append(
                    "evidence=" + ", ".join(missing_evidence)
                )
            raise WorkdayConnectModelError(
                f"Phase '{phase_id}' cannot be complete without required "
                + " and ".join(details)
                + "."
            )


def validate_state(state: Any) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise WorkdayConnectModelError(
            "Workday connect state must contain a JSON object."
        )
    reject_sensitive_data(state)
    if state.get("schemaVersion") != STATE_SCHEMA_VERSION:
        raise WorkdayConnectModelError(
            "Unsupported Workday connect state schema version: "
            f"{state.get('schemaVersion')!r}."
        )
    if state.get("provider") != "workday":
        raise WorkdayConnectModelError(
            "Workday connect state provider must be 'workday'."
        )
    for field in ("scope", "identifiers", "endpoints", "operators", "phases"):
        if not isinstance(state.get(field), dict):
            raise WorkdayConnectModelError(
                f"Workday connect state '{field}' must be an object."
            )
    phases = state["phases"]
    if set(phases) != set(PHASE_BY_ID):
        raise WorkdayConnectModelError(
            "Workday connect state must contain exactly the six phases."
        )
    for phase_id, value in phases.items():
        _validate_phase_state(phase_id, value)
    for definition in PHASE_DEFINITIONS:
        if definition.prerequisite is None:
            continue
        phase = phases[definition.identifier.value]
        prerequisite = phases[definition.prerequisite.value]
        if (
            phase["status"] == PhaseStatus.COMPLETE.value
            and prerequisite["status"] != PhaseStatus.COMPLETE.value
        ):
            raise WorkdayConnectModelError(
                f"Phase '{definition.identifier.value}' cannot be complete "
                f"before '{definition.prerequisite.value}'."
            )
    expected_status = (
        "ready"
        if all(
            phase["status"] == PhaseStatus.COMPLETE.value
            for phase in phases.values()
        )
        else "in-progress"
    )
    if state.get("status") != expected_status:
        raise WorkdayConnectModelError(
            f"Workday connect status must be '{expected_status}'."
        )
    return state


def next_phase_id(state: Mapping[str, Any]) -> str | None:
    phases = state["phases"]
    for definition in PHASE_DEFINITIONS:
        if (
            phases[definition.identifier.value]["status"]
            != PhaseStatus.COMPLETE.value
        ):
            return definition.identifier.value
    return None


def progress_text(state: Mapping[str, Any]) -> str:
    markers = {
        PhaseStatus.PENDING.value: "",
        PhaseStatus.ACTIVE.value: "→",
        PhaseStatus.BLOCKED.value: "!",
        PhaseStatus.COMPLETE.value: "✓",
    }
    parts = []
    for definition in PHASE_DEFINITIONS:
        status = state["phases"][definition.identifier.value]["status"]
        marker = markers[status]
        parts.append(
            f"{definition.short_title}{f' {marker}' if marker else ''}"
        )
    return "Progress: " + " · ".join(parts)
