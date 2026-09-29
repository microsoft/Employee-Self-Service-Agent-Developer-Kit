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
import uuid


STATE_SCHEMA_VERSION = 6
CONTROLLER_CONTRACT_VERSION = 1
CATALOG_PATH = Path(__file__).with_name("workday_connect_catalog.json")
LIFECYCLE_JOURNAL_MAX_EVENTS = 200


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


LIFECYCLE_EVENT_TYPES = frozenset(
    {
        "invoked",
        "plan-generated",
        "roles-attested",
        "phase-started",
        "phase-paused",
        "phase-resumed",
        "phase-completed",
        "blocked",
        "completed",
        "abandoned",
    }
)
LIFECYCLE_OUTCOMES = frozenset(
    {"", "success", "blocked", "failure", "cancelled"}
)
LIFECYCLE_BLOCKER_CATEGORIES = frozenset(
    {
        "",
        "auth",
        "permissions",
        "connection",
        "runtime",
        "validation",
        "state",
        "timeout",
        "platform",
        "unknown",
    }
)


@dataclass(frozen=True)
class PhaseDefinition:
    identifier: Phase
    title: str
    what_happens: tuple[str, ...]
    prerequisite: Phase | None


PHASE_DEFINITIONS = (
    PhaseDefinition(
        identifier=Phase.PREFLIGHT,
        title="Preflight",
        what_happens=(
            "Confirm the selected ESS HR agent, Power Platform environment, "
            "and maker account.",
            "Verify Dataverse is available in the selected environment.",
            "Install or verify the supported Workday package.",
        ),
        prerequisite=None,
    ),
    PhaseDefinition(
        identifier=Phase.ENTRA,
        title="Microsoft Entra",
        what_happens=(
            "Find the exact Workday enterprise application in the selected "
            "Microsoft Entra tenant.",
            "Guide an Entra administrator through the required SAML, "
            "permission, consent, assignment, and employee sign-in settings.",
            "Verify the application and signing-certificate configuration.",
        ),
        prerequisite=Phase.PREFLIGHT,
    ),
    PhaseDefinition(
        identifier=Phase.WORKDAY_ADMIN,
        title="Workday administrator",
        what_happens=(
            "Identify the existing Workday sign-in provider without replacing "
            "another federation.",
            "Configure certificate trust, OAuth, the employee API client, and "
            "the employee authentication policy.",
            "Validate the non-secret connection values needed by Power "
            "Platform.",
        ),
        prerequisite=Phase.ENTRA,
    ),
    PhaseDefinition(
        identifier=Phase.CONNECTIONS,
        title="Connections",
        what_happens=(
            "Find or guide creation of the Workday and Microsoft Dataverse "
            "connections in the selected environment.",
            "Use the verified Workday resource URL, token URL, and OAuth "
            "client ID.",
            "Verify both connections are live before runtime configuration.",
        ),
        prerequisite=Phase.WORKDAY_ADMIN,
    ),
    PhaseDefinition(
        identifier=Phase.RUNTIME,
        title="Runtime configuration",
        what_happens=(
            "Preview and approve the exact Workday runtime changes.",
            "Bind connections, activate required flows, configure permissions "
            "and employee context, and enable the Workday topics.",
            "Reread the agent and preserve any remaining blocker for safe "
            "resume.",
        ),
        prerequisite=Phase.CONNECTIONS,
    ),
    PhaseDefinition(
        identifier=Phase.EMPLOYEE_VALIDATION,
        title="Employee validation",
        what_happens=(
            "Publish the configured agent.",
            "Run a real Workday scenario as a signed-in non-maker employee.",
            "Confirm employee context and Workday data work without an "
            "unexpected repeated sign-in.",
        ),
        prerequisite=Phase.RUNTIME,
    ),
)
PHASE_BY_ID = {
    definition.identifier.value: definition for definition in PHASE_DEFINITIONS
}

PHASE_REQUIRED_ACTIONS = {
    Phase.PREFLIGHT.value: frozenset({"verify-target", "verify-package"}),
    Phase.ENTRA.value: frozenset(
        {
            "exact-application-discovered",
            "administrator-configuration-verified",
        }
    ),
    Phase.WORKDAY_ADMIN.value: frozenset({"administrator-response-validated"}),
    Phase.CONNECTIONS.value: frozenset({"physical-connections-verified"}),
    Phase.RUNTIME.value: frozenset(
        {
            "connection-references-bound",
            "runtime-flows-active",
            "delegated-authorization-configured",
            "user-context-v2-configured",
            "agent-parameter-sharing-verified",
            "flow-attachment-confirmed",
            "workday-topics-activated",
        }
    ),
    Phase.EMPLOYEE_VALIDATION.value: frozenset({"signed-in-scenario"}),
}
TENANT_FOUNDATION_REQUIRED_IDENTIFIER_KEYS = frozenset(
    {
        "entraAppId",
        "entraAppObjectId",
        "entraServicePrincipalId",
        "entraAppIdUri",
        "workdaySamlEntityId",
        "scopeGuid",
        "signingCertificate",
        "oauthClientId",
    }
)
TENANT_FOUNDATION_REQUIRED_ENDPOINT_KEYS = frozenset(
    {
        "oauthTokenUrl",
        "restBaseUrl",
        "soapBaseUrl",
    }
)

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
_CORRELATION_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
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


def default_lifecycle_state() -> dict[str, Any]:
    return {
        "correlationId": str(uuid.uuid4()),
        "startedAt": utc_now(),
        "retryCount": 0,
        "resumeCount": 0,
        "journal": [],
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
        "tenantFoundation": None,
        "lifecycle": default_lifecycle_state(),
        "phases": {
            definition.identifier.value: default_phase_state()
            for definition in PHASE_DEFINITIONS
        },
        "migration": None,
        "updatedAt": utc_now(),
    }


def _validate_lifecycle_state(value: Any) -> None:
    if not isinstance(value, dict):
        raise WorkdayConnectModelError(
            "Workday lifecycle telemetry state must be an object."
        )
    required = {
        "correlationId",
        "startedAt",
        "retryCount",
        "resumeCount",
        "journal",
    }
    missing = sorted(required - value.keys())
    if missing:
        raise WorkdayConnectModelError(
            "Workday lifecycle telemetry state is missing: "
            + ", ".join(missing)
        )
    correlation_id = value["correlationId"]
    if (
        not isinstance(correlation_id, str)
        or not _CORRELATION_ID_RE.fullmatch(correlation_id)
    ):
        raise WorkdayConnectModelError(
            "Workday lifecycle correlationId must be a UUID."
        )
    if not isinstance(value["startedAt"], str) or not value["startedAt"]:
        raise WorkdayConnectModelError(
            "Workday lifecycle startedAt is required."
        )
    for field in ("retryCount", "resumeCount"):
        if (
            not isinstance(value[field], int)
            or isinstance(value[field], bool)
            or value[field] < 0
        ):
            raise WorkdayConnectModelError(
                f"Workday lifecycle {field} must be a non-negative integer."
            )
    journal = value["journal"]
    if not isinstance(journal, list):
        raise WorkdayConnectModelError(
            "Workday lifecycle journal must be a list."
        )
    if len(journal) > LIFECYCLE_JOURNAL_MAX_EVENTS:
        raise WorkdayConnectModelError(
            "Workday lifecycle journal exceeds its bounded history."
        )
    previous_sequence = 0
    for record in journal:
        if not isinstance(record, dict):
            raise WorkdayConnectModelError(
                "Workday lifecycle journal must contain event objects."
            )
        event_required = {
            "sequence",
            "correlationId",
            "event",
            "phase",
            "outcome",
            "blockerCategory",
            "durationMs",
            "retryCount",
            "resumeCount",
            "timestamp",
        }
        event_missing = sorted(event_required - record.keys())
        if event_missing:
            raise WorkdayConnectModelError(
                "Workday lifecycle event is missing: "
                + ", ".join(event_missing)
            )
        sequence = record["sequence"]
        if (
            not isinstance(sequence, int)
            or isinstance(sequence, bool)
            or sequence <= previous_sequence
        ):
            raise WorkdayConnectModelError(
                "Workday lifecycle event sequences must increase."
            )
        previous_sequence = sequence
        event_correlation_id = record["correlationId"]
        if (
            not isinstance(event_correlation_id, str)
            or not _CORRELATION_ID_RE.fullmatch(event_correlation_id)
        ):
            raise WorkdayConnectModelError(
                "Workday lifecycle event correlationId must be a UUID."
            )
        if record["event"] not in LIFECYCLE_EVENT_TYPES:
            raise WorkdayConnectModelError(
                f"Unknown Workday lifecycle event: {record['event']!r}."
            )
        if record["phase"] not in {"", *PHASE_BY_ID}:
            raise WorkdayConnectModelError(
                f"Unknown Workday lifecycle event phase: {record['phase']!r}."
            )
        if record["outcome"] not in LIFECYCLE_OUTCOMES:
            raise WorkdayConnectModelError(
                f"Unknown Workday lifecycle event outcome: {record['outcome']!r}."
            )
        blocker_category = record["blockerCategory"]
        if (
            not isinstance(blocker_category, str)
            or blocker_category not in LIFECYCLE_BLOCKER_CATEGORIES
        ):
            raise WorkdayConnectModelError(
                "Workday lifecycle blockerCategory must use the bounded "
                "taxonomy."
            )
        for field in ("durationMs", "retryCount", "resumeCount"):
            if (
                not isinstance(record[field], int)
                or isinstance(record[field], bool)
                or record[field] < 0
            ):
                raise WorkdayConnectModelError(
                    f"Workday lifecycle event {field} must be non-negative."
                )
        if not isinstance(record["timestamp"], str) or not record["timestamp"]:
            raise WorkdayConnectModelError(
                "Workday lifecycle event timestamp is required."
            )


def _validate_phase_state(phase_id: str, value: Any) -> None:
    if not isinstance(value, dict):
        raise WorkdayConnectModelError(f"Phase '{phase_id}' state must be an object.")
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
    blocker = value["blocker"]
    if value["status"] == PhaseStatus.BLOCKED.value:
        if not isinstance(blocker, dict) or any(
            not str(blocker.get(key) or "").strip()
            for key in ("operation", "errorType", "message")
        ):
            raise WorkdayConnectModelError(
                f"Phase '{phase_id}' must include a complete blocker."
            )
    elif blocker is not None:
        raise WorkdayConnectModelError(
            f"Phase '{phase_id}' can contain a blocker only while blocked."
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
                details.append("actions=" + ", ".join(missing_actions))
            if missing_evidence:
                details.append("evidence=" + ", ".join(missing_evidence))
            raise WorkdayConnectModelError(
                f"Phase '{phase_id}' cannot be complete without required "
                + " and ".join(details)
                + "."
            )


def _validate_tenant_foundation(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise WorkdayConnectModelError(
            "Workday tenantFoundation must be an object or null."
        )
    required = {
        "scope",
        "identifiers",
        "endpoints",
        "phases",
        "capturedAt",
    }
    missing = sorted(required - value.keys())
    if missing:
        raise WorkdayConnectModelError(
            "Workday tenantFoundation is missing: " + ", ".join(missing)
        )
    for field in ("scope", "identifiers", "endpoints", "phases"):
        if not isinstance(value[field], dict):
            raise WorkdayConnectModelError(
                f"Workday tenantFoundation.{field} must be an object."
            )
    for key in ("entraTenantId", "workdayTenant"):
        if not str(value["scope"].get(key) or "").strip():
            raise WorkdayConnectModelError(
                f"Workday tenantFoundation.scope.{key} is required."
            )
    missing_identifiers = sorted(
        key
        for key in TENANT_FOUNDATION_REQUIRED_IDENTIFIER_KEYS
        if value["identifiers"].get(key) is None or value["identifiers"].get(key) == ""
    )
    if missing_identifiers:
        raise WorkdayConnectModelError(
            "Workday tenantFoundation identifiers are missing: "
            + ", ".join(missing_identifiers)
        )
    certificate = value["identifiers"].get("signingCertificate")
    if not isinstance(certificate, dict) or any(
        not str(certificate.get(key) or "").strip()
        for key in ("thumbprint", "validFrom", "validTo")
    ):
        raise WorkdayConnectModelError(
            "Workday tenantFoundation signingCertificate must contain "
            "thumbprint, validFrom, and validTo."
        )
    missing_endpoints = sorted(
        key
        for key in TENANT_FOUNDATION_REQUIRED_ENDPOINT_KEYS
        if not str(value["endpoints"].get(key) or "").strip()
    )
    if missing_endpoints:
        raise WorkdayConnectModelError(
            "Workday tenantFoundation endpoints are missing: "
            + ", ".join(missing_endpoints)
        )
    if set(value["phases"]) != {
        Phase.ENTRA.value,
        Phase.WORKDAY_ADMIN.value,
    }:
        raise WorkdayConnectModelError(
            "Workday tenantFoundation phases must contain exactly Entra and "
            "Workday administrator evidence."
        )
    for phase_id, snapshot in value["phases"].items():
        if not isinstance(snapshot, dict):
            raise WorkdayConnectModelError(
                f"Workday tenantFoundation phase '{phase_id}' must be an object."
            )
        actions = snapshot.get("completedActions")
        evidence = snapshot.get("evidence")
        if not isinstance(actions, list) or any(
            not isinstance(action, str) or not action for action in actions
        ):
            raise WorkdayConnectModelError(
                f"Workday tenantFoundation phase '{phase_id}' actions are invalid."
            )
        if not isinstance(evidence, list) or any(
            not isinstance(record, dict)
            or not isinstance(record.get("action"), str)
            or not record.get("action")
            for record in evidence
        ):
            raise WorkdayConnectModelError(
                f"Workday tenantFoundation phase '{phase_id}' evidence is invalid."
            )
        required_actions = PHASE_REQUIRED_ACTIONS[phase_id]
        if not required_actions <= set(actions):
            raise WorkdayConnectModelError(
                f"Workday tenantFoundation phase '{phase_id}' is incomplete."
            )
        evidence_actions = {str(record.get("action") or "") for record in evidence}
        if not required_actions <= evidence_actions:
            raise WorkdayConnectModelError(
                f"Workday tenantFoundation phase '{phase_id}' lacks evidence."
            )
    if not isinstance(value["capturedAt"], str) or not value["capturedAt"]:
        raise WorkdayConnectModelError(
            "Workday tenantFoundation.capturedAt is required."
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
    _validate_tenant_foundation(state.get("tenantFoundation"))
    _validate_lifecycle_state(state.get("lifecycle"))
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
            phase["status"] == PhaseStatus.COMPLETE.value for phase in phases.values()
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
        if phases[definition.identifier.value]["status"] != PhaseStatus.COMPLETE.value:
            return definition.identifier.value
    return None


def progress_text(state: Mapping[str, Any]) -> str:
    labels = {
        PhaseStatus.PENDING.value: "Pending",
        PhaseStatus.ACTIVE.value: "In progress",
        PhaseStatus.BLOCKED.value: "Needs attention",
        PhaseStatus.COMPLETE.value: "Complete",
    }
    next_phase = next_phase_id(state)
    rows = [
        "### Workday connection progress",
        "",
        "| # | Phase | Status |",
        "|---:|---|---|",
    ]
    for index, definition in enumerate(PHASE_DEFINITIONS, start=1):
        status = state["phases"][definition.identifier.value]["status"]
        label = labels[status]
        if status == PhaseStatus.PENDING.value and (
            definition.identifier.value == next_phase
        ):
            label = "Next"
        rows.append(f"| {index} | {definition.title} | {label} |")
    return "\n".join(rows)


def next_phase_summary(state: Mapping[str, Any]) -> dict[str, Any] | None:
    phase_id = next_phase_id(state)
    if phase_id is None:
        return None
    definition = PHASE_BY_ID[phase_id]
    return {
        "id": phase_id,
        "title": definition.title,
        "whatHappens": list(definition.what_happens),
    }
