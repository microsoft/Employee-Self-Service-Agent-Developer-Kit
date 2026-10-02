# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Atomic persisted-state operations for the Workday connect lifecycle."""

from __future__ import annotations

from contextlib import contextmanager
import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any, Callable, Iterator, Mapping
import uuid

from workday_connect_model import (
    ADMINISTRATOR_PARTIAL_FIELDS,
    ADMINISTRATOR_PHASES,
    ADMINISTRATOR_REQUIRED_FIELDS,
    ADMINISTRATOR_SUBSTAGES,
    LEGACY_PHASE_ROWS,
    LIFECYCLE_BLOCKER_CATEGORIES,
    LIFECYCLE_EVENT_TYPES,
    LIFECYCLE_JOURNAL_MAX_EVENTS,
    LIFECYCLE_OUTCOMES,
    PHASE_BY_ID,
    PHASE_DEFINITIONS,
    PHASE_REQUIRED_ACTIONS,
    STATE_SCHEMA_VERSION,
    TENANT_FOUNDATION_REQUIRED_ENDPOINT_KEYS,
    TENANT_FOUNDATION_REQUIRED_IDENTIFIER_KEYS,
    PhaseStatus,
    WorkdayConnectModelError,
    default_lifecycle_state,
    default_administrator_state,
    default_state,
    next_phase_summary,
    plan_hash,
    progress_text,
    utc_now,
    validate_state,
    workday_saml_entity_id,
)


CONFIG_PATH = Path(".local/connect/workday-da/config.json")

_PREFLIGHT_SCOPE_KEYS = {
    "agent",
    "architecture",
    "dataverseUrl",
    "environmentId",
    "packageFlavor",
    "ring",
    "vertical",
}
_ENTRA_SCOPE_KEYS = {"entraTenantId", "workdayTenant"}
_ENTRA_IDENTIFIER_KEYS = {
    "entraAppId",
    "entraAppObjectId",
    "entraServicePrincipalId",
    "entraAppIdUri",
    "microsoftEntraIdentifier",
    "entraLoginUrl",
    "replyUrl",
    "workdaySamlEntityId",
    "scopeGuid",
    "signingCertificate",
}
_WORKDAY_IDENTIFIER_KEYS = {"oauthClientId"}
_FOUNDATION_SCOPE_KEYS = ("entraTenantId", "workdayTenant")
_FOUNDATION_ENTRA_IDENTIFIER_KEYS = (
    "entraAppId",
    "entraAppObjectId",
    "entraServicePrincipalId",
    "entraAppIdUri",
    "microsoftEntraIdentifier",
    "entraLoginUrl",
    "replyUrl",
    "workdaySamlEntityId",
    "scopeGuid",
    "signingCertificate",
)
_OPERATOR_PHASES = {
    "powerPlatformMaker": "preflight",
    "entraAdmin": "entra",
    "workdayAdmin": "workday-admin",
}
_LIFECYCLE_TARGET_SCOPE_KEYS = {
    "agent",
    "dataverseUrl",
    "environmentId",
    "entraTenantId",
    "workdayTenant",
}
_BLOCKER_CATEGORY_KEYWORDS = (
    ("timeout", ("timeout", "timedout")),
    (
        "permissions",
        (
            "permission",
            "access",
            "authorization",
            "unauthorized",
            "consent",
            "forbidden",
            "role",
        ),
    ),
    (
        "auth",
        ("auth", "credential", "signin", "sign-in", "token", "entra"),
    ),
    (
        "connection",
        ("connection", "network", "endpoint", "dns", "ssl", "http"),
    ),
    (
        "validation",
        ("validation", "contract", "evidence", "invalid"),
    ),
    ("state", ("state", "store", "schema", "migration", "planchanged")),
    (
        "platform",
        ("platform", "preflight", "dataverse", "package", "solution"),
    ),
    ("runtime", ("runtime", "flow", "topic", "agent")),
)
_BLOCKER_CATEGORY_EXACT = {
    "employee-authentication": "auth",
    "workday-connection": "connection",
    "runtime-flow": "runtime",
    "employee-context": "validation",
    "network": "connection",
    "workday-access": "permissions",
    "publish-or-agent": "runtime",
    "unknown": "unknown",
}
_REMEDIATION_ID_RE = re.compile(r"^WD-E2E-\d{3}$")


class WorkdayConnectStoreError(RuntimeError):
    """Raised when Workday connect state cannot be persisted safely."""


class WorkdayConnectPlanChangedError(WorkdayConnectStoreError):
    """Raised when an approved plan no longer matches the current plan."""


def _blocker_category(blocker: Mapping[str, Any] | None) -> str:
    if not blocker:
        return ""
    raw = str(
        blocker.get("category")
        or blocker.get("failureCategory")
        or blocker.get("errorType")
        or "unknown"
    ).strip().casefold()
    if raw in LIFECYCLE_BLOCKER_CATEGORIES:
        return raw
    if raw in _BLOCKER_CATEGORY_EXACT:
        return _BLOCKER_CATEGORY_EXACT[raw]
    compact = "".join(character for character in raw if character.isalnum())
    for category, keywords in _BLOCKER_CATEGORY_KEYWORDS:
        if any(
            "".join(character for character in keyword if character.isalnum())
            in compact
            for keyword in keywords
        ):
            return category
    return "unknown"


def _remediation_id(blocker: Mapping[str, Any] | None) -> str:
    if not blocker:
        return ""
    value = str(blocker.get("remediationId") or "").strip().upper()
    return value if _REMEDIATION_ID_RE.fullmatch(value) else ""


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _phase_active_segment_ms(
    state: Mapping[str, Any],
    phase_id: str,
) -> int:
    lifecycle = state.get("lifecycle") or {}
    started = _parse_timestamp(
        (lifecycle.get("activePhaseStartedAt") or {}).get(phase_id)
    )
    finished = _parse_timestamp(utc_now())
    if started is None or finished is None:
        return 0
    return max(0, int((finished - started).total_seconds() * 1000))


def _phase_total_duration_ms(
    state: Mapping[str, Any],
    phase_id: str,
) -> int:
    lifecycle = state.get("lifecycle") or {}
    paused_duration = max(
        0,
        int(
            (lifecycle.get("phaseDurationsMs") or {}).get(phase_id)
            or 0
        ),
    )
    return paused_duration + _phase_active_segment_ms(state, phase_id)


def _append_lifecycle_event(
    state: dict[str, Any],
    event: str,
    *,
    phase: str = "",
    outcome: str = "",
    blocker_category: str = "",
    remediation_id: str = "",
    duration_ms: int = 0,
    increment_retry: bool = False,
    increment_resume: bool = False,
) -> dict[str, Any]:
    if event not in LIFECYCLE_EVENT_TYPES:
        raise WorkdayConnectStoreError(
            f"Unknown Workday lifecycle event: {event}."
        )
    if phase not in {"", *PHASE_BY_ID}:
        raise WorkdayConnectStoreError(
            f"Unknown Workday lifecycle event phase: {phase}."
        )
    if outcome not in LIFECYCLE_OUTCOMES:
        raise WorkdayConnectStoreError(
            f"Unknown Workday lifecycle event outcome: {outcome}."
        )
    lifecycle = state["lifecycle"]
    if increment_retry:
        lifecycle["retryCount"] += 1
    if increment_resume:
        lifecycle["resumeCount"] += 1
    journal = lifecycle["journal"]
    sequence = int(journal[-1]["sequence"]) + 1 if journal else 1
    timestamp = utc_now()
    record = {
        "sequence": sequence,
        "correlationId": lifecycle["correlationId"],
        "event": event,
        "phase": phase,
        "outcome": outcome,
        "blockerCategory": blocker_category,
        "remediationId": remediation_id,
        "durationMs": max(0, int(duration_ms)),
        "retryCount": lifecycle["retryCount"],
        "resumeCount": lifecycle["resumeCount"],
        "timestamp": timestamp,
    }
    if phase:
        active_starts = lifecycle["activePhaseStartedAt"]
        phase_durations = lifecycle["phaseDurationsMs"]
        if event in {"phase-started", "phase-resumed"}:
            active_starts[phase] = timestamp
        elif event == "phase-paused":
            phase_durations[phase] += record["durationMs"]
            active_starts[phase] = None
        elif event == "phase-completed":
            phase_durations[phase] = record["durationMs"]
            active_starts[phase] = None
    journal.append(record)
    lifecycle["journal"] = journal[-LIFECYCLE_JOURNAL_MAX_EVENTS:]
    marker = f"{event}|{phase}"
    if marker not in lifecycle["eventMarkers"]:
        lifecycle["eventMarkers"].append(marker)
    return record


def _has_lifecycle_event(
    state: Mapping[str, Any],
    event: str,
    phase: str,
) -> bool:
    lifecycle = state.get("lifecycle") or {}
    return f"{event}|{phase}" in (lifecycle.get("eventMarkers") or [])


def _current_phase_id(state: Mapping[str, Any]) -> str:
    phases = state.get("phases") or {}
    for definition in PHASE_DEFINITIONS:
        phase_id = definition.identifier.value
        if (phases.get(phase_id) or {}).get("status") != PhaseStatus.COMPLETE.value:
            return phase_id
    return ""


def _target_scope_changed(
    state: Mapping[str, Any],
    values: Mapping[str, Any],
    changed_keys: set[str],
) -> bool:
    scope = state.get("scope") or {}
    for key in changed_keys & _LIFECYCLE_TARGET_SCOPE_KEYS:
        previous = scope.get(key)
        if previous in (None, "", (), [], {}):
            continue
        if key == "agent":
            previous_agent = previous if isinstance(previous, Mapping) else {}
            next_value = values.get(key)
            next_agent = next_value if isinstance(next_value, Mapping) else {}
            previous_identity = (
                str(previous_agent.get("slug") or "").casefold(),
                str(previous_agent.get("botId") or "").casefold(),
                str(previous_agent.get("schemaName") or "").casefold(),
            )
            next_identity = (
                str(next_agent.get("slug") or "").casefold(),
                str(next_agent.get("botId") or "").casefold(),
                str(next_agent.get("schemaName") or "").casefold(),
            )
            if previous_identity != next_identity:
                return True
            continue
        return True
    return False


def _rotate_lifecycle(state: dict[str, Any]) -> None:
    lifecycle = state["lifecycle"]
    was_invoked = _has_lifecycle_event(state, "invoked", "")
    has_progress = bool(lifecycle["journal"]) or any(
        phase["status"] != PhaseStatus.PENDING.value
        for phase in state["phases"].values()
    )
    if state.get("status") != "ready" and has_progress:
        _append_lifecycle_event(
            state,
            "abandoned",
            phase=_current_phase_id(state),
            outcome="cancelled",
        )
    lifecycle["correlationId"] = str(uuid.uuid4())
    lifecycle["startedAt"] = utc_now()
    lifecycle["retryCount"] = 0
    lifecycle["resumeCount"] = 0
    lifecycle["phaseDurationsMs"] = {
        phase_id: 0 for phase_id in PHASE_BY_ID
    }
    lifecycle["activePhaseStartedAt"] = {
        phase_id: None for phase_id in PHASE_BY_ID
    }
    lifecycle["eventMarkers"] = []
    if was_invoked:
        _append_lifecycle_event(state, "invoked")


def _normalize_current_state(
    document: Mapping[str, Any],
) -> dict[str, Any]:
    state = copy.deepcopy(dict(document))
    lifecycle = state.get("lifecycle")
    if not isinstance(lifecycle, dict):
        return state
    correlation_id = lifecycle.get("correlationId")
    journal = lifecycle.get("journal")
    if not isinstance(correlation_id, str) or not isinstance(journal, list):
        return state
    markers: list[str] = []
    phase_durations = {phase_id: 0 for phase_id in PHASE_BY_ID}
    active_starts = {phase_id: None for phase_id in PHASE_BY_ID}
    for record in journal:
        if not isinstance(record, dict):
            continue
        record.setdefault("correlationId", correlation_id)
        record.setdefault("remediationId", "")
        raw_category = record.get("blockerCategory")
        if raw_category:
            record["blockerCategory"] = _blocker_category(
                {"category": raw_category}
            )
        if record.get("correlationId") != correlation_id:
            continue
        event = str(record.get("event") or "")
        phase = str(record.get("phase") or "")
        marker = f"{event}|{phase}"
        if marker not in markers:
            markers.append(marker)
        if phase not in phase_durations:
            continue
        if event in {"phase-started", "phase-resumed"}:
            active_starts[phase] = record.get("timestamp")
        elif event == "phase-paused":
            phase_durations[phase] += max(
                0,
                int(record.get("durationMs") or 0),
            )
            active_starts[phase] = None
        elif event == "phase-completed":
            phase_durations[phase] = max(
                0,
                int(record.get("durationMs") or 0),
            )
            active_starts[phase] = None
    existing_durations = lifecycle.get("phaseDurationsMs")
    if isinstance(existing_durations, dict):
        merged_durations: dict[str, Any] = {}
        for phase_id in PHASE_BY_ID:
            existing_duration = existing_durations.get(phase_id)
            if (
                isinstance(existing_duration, int)
                and not isinstance(existing_duration, bool)
                and existing_duration >= 0
            ):
                merged_durations[phase_id] = max(
                    existing_duration,
                    phase_durations[phase_id],
                )
            else:
                merged_durations[phase_id] = existing_duration
        lifecycle["phaseDurationsMs"] = merged_durations
    else:
        lifecycle["phaseDurationsMs"] = phase_durations
    existing_starts = lifecycle.get("activePhaseStartedAt")
    if isinstance(existing_starts, dict):
        lifecycle["activePhaseStartedAt"] = {
            phase_id: (
                existing_starts.get(phase_id)
                or active_starts[phase_id]
            )
            for phase_id in PHASE_BY_ID
        }
    else:
        lifecycle["activePhaseStartedAt"] = active_starts
    existing_markers = lifecycle.get("eventMarkers")
    lifecycle["eventMarkers"] = list(
        dict.fromkeys(
            [
                *(
                    existing_markers
                    if isinstance(existing_markers, list)
                    else []
                ),
                *markers,
            ]
        )
    )
    return state


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkdayConnectStoreError(
            f"Workday connect state could not be read: {path}: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise WorkdayConnectStoreError(
            f"Workday connect state must contain an object: {path}"
        )
    return document


def _atomic_write_json(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(document, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            try:
                os.fsync(stream.fileno())
            except OSError:
                pass
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


@contextmanager
def _file_lock(path: Path, timeout: float) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+b")
    stream.seek(0, os.SEEK_END)
    if stream.tell() == 0:
        stream.write(b"\0")
        stream.flush()
    deadline = time.monotonic() + timeout
    locked = False
    try:
        while not locked:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    raise WorkdayConnectStoreError(
                        "Another /connect workday session is updating state. "
                        "Wait for it to finish, then retry."
                    )
                time.sleep(0.05)
        yield
    finally:
        if locked:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


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
        legacy_evidence = value.get("evidence")
        if isinstance(legacy_evidence, dict):
            for key in ("outcome", "provenance", "capturedAt"):
                if legacy_evidence.get(key) is not None:
                    record[key] = legacy_evidence[key]
        evidence.append(record)
    return evidence


def migrate_legacy_state(document: Mapping[str, Any]) -> dict[str, Any]:
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
            phase_state["administrator"]["substage"] = (
                "evidence-validated"
            )
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
        _reset_phase(state["phases"]["employee-validation"])

    if all(
        phase["status"] == PhaseStatus.COMPLETE.value
        for phase in state["phases"].values()
    ):
        state["status"] = "ready"
    state["tenantFoundation"] = _tenant_foundation_from_state(state)
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


def _reset_phase(phase: dict[str, Any]) -> None:
    administrator = (
        default_administrator_state()
        if "administrator" in phase
        else None
    )
    phase.update(
        {
            "status": PhaseStatus.PENDING.value,
            "completedActions": [],
            "approvedPlanHash": None,
            "approvedPlan": None,
            "evidence": [],
            "validationProfiles": {},
            "blocker": None,
            "updatedAt": utc_now(),
        }
    )
    if "employeeTestAttempt" in phase:
        phase["employeeTestAttempt"] = None
    if administrator is not None:
        phase["administrator"] = administrator


def _tenant_foundation_from_state(
    state: Mapping[str, Any],
) -> dict[str, Any] | None:
    phases = state.get("phases") or {}
    entra = phases.get("entra") or {}
    workday = phases.get("workday-admin") or {}
    if (
        entra.get("status") != PhaseStatus.COMPLETE.value
        or workday.get("status") != PhaseStatus.COMPLETE.value
    ):
        return None
    scope = state.get("scope") or {}
    if any(not str(scope.get(key) or "").strip() for key in _FOUNDATION_SCOPE_KEYS):
        return None
    identifiers = state.get("identifiers") or {}
    endpoints = state.get("endpoints") or {}
    if any(
        identifiers.get(key) is None or identifiers.get(key) == ""
        for key in TENANT_FOUNDATION_REQUIRED_IDENTIFIER_KEYS
    ):
        return None
    if any(
        not str(endpoints.get(key) or "").strip()
        for key in TENANT_FOUNDATION_REQUIRED_ENDPOINT_KEYS
    ):
        return None
    return {
        "scope": {key: copy.deepcopy(scope[key]) for key in _FOUNDATION_SCOPE_KEYS},
        "identifiers": copy.deepcopy(dict(identifiers)),
        "endpoints": copy.deepcopy(dict(endpoints)),
        "phases": {
            phase_id: {
                "completedActions": copy.deepcopy(phases[phase_id]["completedActions"]),
                "evidence": copy.deepcopy(phases[phase_id]["evidence"]),
                "administrator": copy.deepcopy(
                    phases[phase_id].get("administrator")
                ),
            }
            for phase_id in ("entra", "workday-admin")
        },
        "capturedAt": utc_now(),
    }


def _normalized_foundation_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().casefold()
    if isinstance(value, Mapping):
        return {
            str(key): _normalized_foundation_value(item)
            for key, item in sorted(value.items())
        }
    if isinstance(value, list):
        return [_normalized_foundation_value(item) for item in value]
    return value


def _certificate_identity(value: Any) -> tuple[str, str, str] | None:
    if not isinstance(value, Mapping):
        return None
    thumbprint = str(value.get("thumbprint") or "").replace(" ", "").strip().casefold()
    valid_from = str(value.get("validFrom") or "").strip()[:10]
    valid_to = str(value.get("validTo") or "").strip()[:10]
    if not thumbprint or not valid_from or not valid_to:
        return None
    return thumbprint, valid_from, valid_to


def _foundation_matches_current_entra(
    state: Mapping[str, Any],
    foundation: Mapping[str, Any],
) -> bool:
    scope = state.get("scope") or {}
    foundation_scope = foundation.get("scope") or {}
    for key in _FOUNDATION_SCOPE_KEYS:
        if _normalized_foundation_value(scope.get(key)) != (
            _normalized_foundation_value(foundation_scope.get(key))
        ):
            return False
    identifiers = state.get("identifiers") or {}
    foundation_identifiers = foundation.get("identifiers") or {}
    for key in _FOUNDATION_ENTRA_IDENTIFIER_KEYS:
        if key == "signingCertificate":
            if _certificate_identity(identifiers.get(key)) != (
                _certificate_identity(foundation_identifiers.get(key))
            ):
                return False
            continue
        if _normalized_foundation_value(identifiers.get(key)) != (
            _normalized_foundation_value(foundation_identifiers.get(key))
        ):
            return False
    return True


def _invalidate_from_phase(
    state: dict[str, Any],
    phase_id: str,
) -> None:
    invalidate = False
    for definition in PHASE_DEFINITIONS:
        if definition.identifier.value == phase_id:
            invalidate = True
        if invalidate:
            _reset_phase(state["phases"][definition.identifier.value])


def _invalidate_after_phase(
    state: dict[str, Any],
    phase_id: str,
) -> None:
    matched = False
    for definition in PHASE_DEFINITIONS:
        if matched:
            _reset_phase(state["phases"][definition.identifier.value])
        if definition.identifier.value == phase_id:
            matched = True


def _employee_target_fingerprint(
    state: Mapping[str, Any],
    flow_ids: list[str],
) -> str:
    scope = state.get("scope") or {}
    agent = scope.get("agent") or {}
    return plan_hash(
        {
            "phase": "employee-validation",
            "scope": {
                "environmentId": scope.get("environmentId"),
                "environmentUrl": scope.get("dataverseUrl"),
                "tenantId": scope.get("entraTenantId"),
                "agentSlug": (
                    agent.get("slug")
                    if isinstance(agent, Mapping)
                    else None
                ),
                "agentSchemaName": (
                    agent.get("schemaName")
                    if isinstance(agent, Mapping)
                    else None
                ),
                "agentId": (
                    agent.get("botId")
                    if isinstance(agent, Mapping)
                    else None
                ),
            },
            "actions": ["Run signed-in employee read scenario"],
            "flowIds": sorted(set(flow_ids)),
            "acceptanceGeneration": {
                phase_id: {
                    "status": (state.get("phases") or {})
                    .get(phase_id, {})
                    .get("status"),
                    "completedActions": (state.get("phases") or {})
                    .get(phase_id, {})
                    .get("completedActions"),
                    "approvedPlanHash": (state.get("phases") or {})
                    .get(phase_id, {})
                    .get("approvedPlanHash"),
                    "evidence": (state.get("phases") or {})
                    .get(phase_id, {})
                    .get("evidence"),
                }
                for phase_id in (
                    "preflight",
                    "entra",
                    "workday-admin",
                    "connections",
                    "runtime",
                )
            },
            "identifiers": state.get("identifiers") or {},
            "endpoints": state.get("endpoints") or {},
        }
    )


def _employee_runtime_flow_ids(state: Mapping[str, Any]) -> list[str]:
    runtime = (state.get("phases") or {}).get("runtime") or {}
    runtime_plan = runtime.get("approvedPlan") or {}
    flow_ids_by_name = {
        str(flow.get("name") or "").strip().casefold(): str(
            flow.get("workflowId") or ""
        ).strip()
        for flow in runtime_plan.get("flows") or []
        if isinstance(flow, Mapping)
        and str(flow.get("name") or "").strip()
        and str(flow.get("workflowId") or "").strip()
    }
    attachment = next(
        (
            record
            for record in runtime.get("evidence") or []
            if isinstance(record, Mapping)
            and record.get("action") == "flow-attachment-confirmed"
        ),
        None,
    )
    flow_names = (
        attachment.get("flowNames")
        if isinstance(attachment, Mapping)
        else None
    )
    if (
        not isinstance(flow_names, list)
        or not flow_names
        or any(not isinstance(name, str) or not name.strip() for name in flow_names)
    ):
        return []
    normalized_names = [name.strip().casefold() for name in flow_names]
    if (
        len(normalized_names) != len(set(normalized_names))
        or any(name not in flow_ids_by_name for name in normalized_names)
    ):
        return []
    return sorted(
        {
            flow_ids_by_name[name]
            for name in normalized_names
        }
    )


def _clear_employee_validation_evidence(phase: dict[str, Any]) -> None:
    phase["completedActions"] = [
        action
        for action in phase.get("completedActions") or []
        if action != "signed-in-scenario"
    ]
    phase["evidence"] = [
        record
        for record in phase.get("evidence") or []
        if record.get("action") != "signed-in-scenario"
    ]
    phase["employeeTestAttempt"] = None


def _transition_phase_state(
    state: dict[str, Any],
    phase_id: str,
    status: str,
    *,
    blocker: Mapping[str, Any] | None = None,
    invalidate_downstream: bool = True,
) -> None:
    definition = PHASE_BY_ID[phase_id]
    prerequisite = definition.prerequisite
    if status == PhaseStatus.COMPLETE.value and prerequisite:
        prerequisite_status = state["phases"][prerequisite.value]["status"]
        if prerequisite_status != PhaseStatus.COMPLETE.value:
            raise WorkdayConnectStoreError(
                f"Complete '{prerequisite.value}' before '{phase_id}'."
            )
    phase = state["phases"][phase_id]
    if (
        invalidate_downstream
        and phase["status"] == PhaseStatus.COMPLETE.value
        and status != PhaseStatus.COMPLETE.value
    ):
        _invalidate_after_phase(state, phase_id)
    if status == PhaseStatus.COMPLETE.value:
        required = PHASE_REQUIRED_ACTIONS[phase_id]
        completed = set(phase["completedActions"])
        evidence_actions = {
            str(record.get("action") or "") for record in phase["evidence"]
        }
        missing = sorted((required - completed) | (required - evidence_actions))
        if missing:
            raise WorkdayConnectStoreError(
                f"Phase '{phase_id}' is missing required verified actions: "
                + ", ".join(missing)
                + "."
            )
        if phase_id in ADMINISTRATOR_PHASES:
            administrator = phase["administrator"]
            administrator["substage"] = "evidence-validated"
            administrator["invalidFields"] = []
            administrator["updatedAt"] = utc_now()
    previous_status = phase["status"]
    phase["status"] = status
    phase["blocker"] = dict(blocker) if blocker else None
    phase["updatedAt"] = utc_now()
    if status == PhaseStatus.BLOCKED.value:
        if previous_status == PhaseStatus.PENDING.value:
            _append_lifecycle_event(state, "phase-started", phase=phase_id)
            previous_status = PhaseStatus.ACTIVE.value
        if previous_status == PhaseStatus.ACTIVE.value:
            _append_lifecycle_event(
                state,
                "phase-paused",
                phase=phase_id,
                outcome="blocked",
                duration_ms=_phase_active_segment_ms(state, phase_id),
            )
        _append_lifecycle_event(
            state,
            "blocked",
            phase=phase_id,
            outcome="blocked",
            blocker_category=_blocker_category(blocker),
            remediation_id=_remediation_id(blocker),
        )
    elif (
        status == PhaseStatus.ACTIVE.value
        and previous_status == PhaseStatus.BLOCKED.value
    ):
        _append_lifecycle_event(
            state,
            "phase-resumed",
            phase=phase_id,
            increment_retry=True,
            increment_resume=True,
        )
    elif (
        status == PhaseStatus.ACTIVE.value
        and previous_status != PhaseStatus.ACTIVE.value
    ):
        _append_lifecycle_event(state, "phase-started", phase=phase_id)
    elif (
        status == PhaseStatus.COMPLETE.value
        and previous_status != PhaseStatus.COMPLETE.value
    ):
        _append_lifecycle_event(
            state,
            "phase-completed",
            phase=phase_id,
            outcome="success",
            duration_ms=_phase_total_duration_ms(state, phase_id),
        )
        if all(
            item["status"] == PhaseStatus.COMPLETE.value
            for item in state["phases"].values()
        ):
            _append_lifecycle_event(state, "completed", outcome="success")


def _block_validation_state(
    state: dict[str, Any],
    *,
    phase_id: str,
    error_type: str,
    message: str,
    customer_remediation: str,
    remediation_id: str,
) -> None:
    reached_owner = False
    for definition in PHASE_DEFINITIONS:
        current_id = definition.identifier.value
        if current_id == phase_id:
            reached_owner = True
        if not reached_owner:
            continue
        current = state["phases"][current_id]
        current["validationProfiles"] = {}
        if current_id == phase_id:
            profile_blocker = {
                "operation": "readiness-validation",
                "errorType": error_type,
                "message": message,
                "remediation": customer_remediation,
                **(
                    {"remediationId": remediation_id}
                    if remediation_id
                    else {}
                ),
            }
            _transition_phase_state(
                state,
                current_id,
                PhaseStatus.BLOCKED.value,
                blocker=profile_blocker,
                invalidate_downstream=False,
            )
        else:
            if current_id == "employee-validation":
                _clear_employee_validation_evidence(current)
            current["status"] = PhaseStatus.PENDING.value
            current["blocker"] = None
        current["updatedAt"] = utc_now()
    state["status"] = "in-progress"


def _upgrade_or_migrate_state(
    document: Mapping[str, Any],
) -> dict[str, Any]:
    source_version = document.get("schemaVersion")
    if source_version == 8:
        return upgrade_v8_state(document)
    if source_version == 7:
        return upgrade_v7_state(document)
    if source_version == 6:
        return upgrade_v6_state(document)
    if source_version == 5:
        return upgrade_v5_state(document)
    if source_version == 4:
        return upgrade_v4_state(document)
    if source_version == 3:
        return upgrade_v3_state(document)
    if source_version == 2:
        return upgrade_v2_state(document)
    if "schemaVersion" in document:
        raise WorkdayConnectStoreError(
            "Unsupported Workday connect state schema version: "
            f"{source_version!r}. Use the kit version that created this state "
            "or restore a compatible backup."
        )
    return migrate_legacy_state(document)


def _scope_invalidation_phase(changed_keys: set[str]) -> str:
    if changed_keys & _PREFLIGHT_SCOPE_KEYS:
        return "preflight"
    if changed_keys and changed_keys <= _ENTRA_SCOPE_KEYS:
        return "entra"
    return "preflight"


def _section_invalidation_phase(
    section: str,
    changed_keys: set[str],
) -> str | None:
    if not changed_keys:
        return None
    if section == "scope":
        return _scope_invalidation_phase(changed_keys)
    if section == "identifiers":
        if changed_keys & _ENTRA_IDENTIFIER_KEYS:
            return "entra"
        if changed_keys <= _WORKDAY_IDENTIFIER_KEYS:
            return "workday-admin"
        return "entra"
    if section == "endpoints":
        return "workday-admin"
    if section == "operators":
        phases = {_OPERATOR_PHASES.get(key, "preflight") for key in changed_keys}
        return min(
            phases,
            key=lambda phase_id: next(
                index
                for index, definition in enumerate(PHASE_DEFINITIONS)
                if definition.identifier.value == phase_id
            ),
        )
    return None


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
    captured_foundation = _tenant_foundation_from_state(state)
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
                _reset_phase(phase)
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


def upgrade_v2_state(document: Mapping[str, Any]) -> dict[str, Any]:
    return _upgrade_pre_v7_state(document, source_version=2)


def upgrade_v3_state(document: Mapping[str, Any]) -> dict[str, Any]:
    return _upgrade_pre_v7_state(document, source_version=3)


def upgrade_v4_state(document: Mapping[str, Any]) -> dict[str, Any]:
    return _upgrade_pre_v7_state(document, source_version=4)


def upgrade_v5_state(document: Mapping[str, Any]) -> dict[str, Any]:
    return _upgrade_pre_v7_state(document, source_version=5)


def _legacy_administrator_partial_evidence(
    state: Mapping[str, Any],
    phase_id: str,
) -> dict[str, Any]:
    identifiers = state.get("identifiers") or {}
    endpoints = state.get("endpoints") or {}
    phases = state.get("phases") or {}
    phase = phases.get(phase_id) or {}
    evidence_by_action = {
        str(record.get("action") or ""): record
        for record in (phase.get("evidence") or [])
        if isinstance(record, Mapping)
    }
    if phase_id == "entra":
        administrator_evidence = evidence_by_action.get(
            "administrator-configuration-verified"
        ) or {}
        checks = administrator_evidence.get("checks") or {}
        certificate = identifiers.get("signingCertificate") or {}
        candidates = {
            "applicationId": identifiers.get("entraAppId"),
            "replyUrl": identifiers.get("replyUrl"),
            "microsoftEntraIdentifier": identifiers.get(
                "microsoftEntraIdentifier"
            ),
            "loginUrl": identifiers.get("entraLoginUrl"),
            "nameIdSource": (
                (checks.get("nameId") or {}).get("observedValue")
                if isinstance(checks, Mapping)
                else None
            ),
            "samlSigningOption": (
                (checks.get("samlSigningOption") or {}).get(
                    "observedValue"
                )
                if isinstance(checks, Mapping)
                else None
            ),
            "certificateThumbprint": (
                certificate.get("thumbprint")
                if isinstance(certificate, Mapping)
                else None
            ),
            "certificateValidFrom": (
                certificate.get("validFrom")
                if isinstance(certificate, Mapping)
                else None
            ),
            "certificateValidTo": (
                certificate.get("validTo")
                if isinstance(certificate, Mapping)
                else None
            ),
        }
    else:
        administrator_evidence = evidence_by_action.get(
            "administrator-response-validated"
        ) or {}
        candidates = {
            "identityProviderOutcome": administrator_evidence.get(
                "identityProviderOutcome"
            ),
            "enabledServiceProviderId": identifiers.get(
                "workdaySamlEntityId"
            ),
            "certificateSelectionOutcome": administrator_evidence.get(
                "certificateSelectionOutcome"
            ),
            "certificateValidityOutcome": administrator_evidence.get(
                "certificateValidityOutcome"
            ),
            "oauthClientId": identifiers.get("oauthClientId"),
            "oauthTokenUrl": endpoints.get("oauthTokenUrl"),
            "restBaseUrl": endpoints.get("restBaseUrl"),
            "soapBaseUrl": endpoints.get("soapBaseUrl"),
            "authenticationPolicyOutcome": administrator_evidence.get(
                "authenticationPolicyOutcome"
            ),
            "networkReadinessOutcome": administrator_evidence.get(
                "networkReadinessOutcome"
            ),
        }
    return {
        key: copy.deepcopy(value)
        for key, value in candidates.items()
        if value not in (None, "", [], {})
        and key in ADMINISTRATOR_PARTIAL_FIELDS[phase_id]
    }


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
        phase_id: _legacy_administrator_partial_evidence(
            state,
            phase_id,
        )
        for phase_id in ADMINISTRATOR_PHASES
    }
    _invalidate_from_phase(state, "entra")
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


def upgrade_v6_state(document: Mapping[str, Any]) -> dict[str, Any]:
    return _upgrade_pre_v7_state(document, source_version=6)


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


def upgrade_v7_state(document: Mapping[str, Any]) -> dict[str, Any]:
    return _upgrade_readiness_state(document, source_version=7)


def upgrade_v8_state(document: Mapping[str, Any]) -> dict[str, Any]:
    return _upgrade_readiness_state(document, source_version=8)


class WorkdayConnectStore:
    """Own the single durable Workday connect state file."""

    def __init__(
        self,
        workspace_root: Path,
        *,
        lock_timeout: float = 5.0,
        event_sink: (
            Callable[[Mapping[str, Any], Mapping[str, Any]], None] | None
        ) = None,
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        self.config_path = self.workspace_root / CONFIG_PATH
        self.lock_path = self.config_path.with_name("state.lock")
        self.migration_lock_path = self.config_path.with_name(
            "flightcheck-migration.lock"
        )
        self.employee_validation_lock_path = self.config_path.with_name(
            "employee-validation.lock"
        )
        self.operation_lock_path = self.config_path.with_name(
            "operation.lock"
        )
        self.backup_path = self.config_path.with_name(
            f"config.pre-v{STATE_SCHEMA_VERSION}.json"
        )
        self.lock_timeout = lock_timeout
        self.event_sink = event_sink

    def _ensure_migration_backup(
        self,
        existing: Mapping[str, Any],
    ) -> None:
        backup_valid = False
        if self.backup_path.exists():
            try:
                backup = _read_json(self.backup_path)
                backup_valid = backup == dict(existing)
            except WorkdayConnectStoreError:
                backup_valid = False
        if not backup_valid:
            _atomic_write_json(self.backup_path, existing)

    def _refresh_validation_profile_fingerprints(
        self,
        state: dict[str, Any],
    ) -> None:
        from workday_connect_flightcheck import (
            effective_validation_state,
            validation_input_fingerprint,
        )

        effective_state = effective_validation_state(
            self.workspace_root,
            state,
        )
        for phase in state["phases"].values():
            for profile_name, summary in phase[
                "validationProfiles"
            ].items():
                summary["inputFingerprint"] = (
                    validation_input_fingerprint(
                        effective_state,
                        str(
                            summary.get("sourceProfile")
                            or profile_name
                        ),
                    )
                )

    @contextmanager
    def migration_guard(self) -> Iterator[None]:
        lock = _file_lock(self.migration_lock_path, self.lock_timeout)
        try:
            lock.__enter__()
        except WorkdayConnectStoreError as exc:
            exc.profile_blocker_persisted = True
            raise
        try:
            yield
        finally:
            lock.__exit__(None, None, None)

    @contextmanager
    def employee_validation_guard(self) -> Iterator[None]:
        lock = _file_lock(
            self.employee_validation_lock_path,
            self.lock_timeout,
        )
        try:
            lock.__enter__()
        except WorkdayConnectStoreError as exc:
            exc.profile_blocker_persisted = True
            raise
        try:
            yield
        finally:
            lock.__exit__(None, None, None)

    @contextmanager
    def operation_guard(self) -> Iterator[None]:
        lock = _file_lock(self.operation_lock_path, self.lock_timeout)
        try:
            lock.__enter__()
        except WorkdayConnectStoreError as exc:
            exc.profile_blocker_persisted = True
            raise
        try:
            yield
        finally:
            lock.__exit__(None, None, None)

    def initialize(self) -> dict[str, Any]:
        with _file_lock(self.lock_path, self.lock_timeout):
            existing = _read_json(self.config_path)
            if not existing:
                state = default_state()
                _atomic_write_json(self.config_path, state)
                return state
            if existing.get("schemaVersion") == STATE_SCHEMA_VERSION:
                state = _normalize_current_state(existing)
                validate_state(state)
                if state != existing:
                    _atomic_write_json(self.config_path, state)
                return state
            self._ensure_migration_backup(existing)
            state = _upgrade_or_migrate_state(existing)
            _atomic_write_json(self.config_path, state)
            return state

    def load(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return self.initialize()
        current = _read_json(self.config_path)
        if current.get("schemaVersion") != STATE_SCHEMA_VERSION:
            return self.initialize()
        normalized = _normalize_current_state(current)
        if normalized != current:
            return self.initialize()
        return validate_state(normalized)

    def _mutate(self, mutation) -> dict[str, Any]:
        new_events: list[dict[str, Any]] = []
        with _file_lock(self.lock_path, self.lock_timeout):
            current = _read_json(self.config_path)
            if not current:
                current = default_state()
            elif current.get("schemaVersion") != STATE_SCHEMA_VERSION:
                self._ensure_migration_backup(current)
                current = _upgrade_or_migrate_state(current)
            else:
                current = _normalize_current_state(current)
            state = copy.deepcopy(validate_state(current))
            journal = state["lifecycle"]["journal"]
            previous_sequence = int(journal[-1]["sequence"]) if journal else 0
            mutation(state)
            state["status"] = (
                "ready"
                if all(
                    phase["status"] == PhaseStatus.COMPLETE.value
                    for phase in state["phases"].values()
                )
                else "in-progress"
            )
            state["updatedAt"] = utc_now()
            validate_state(state)
            _atomic_write_json(self.config_path, state)
            new_events = [
                copy.deepcopy(record)
                for record in state["lifecycle"]["journal"]
                if int(record["sequence"]) > previous_sequence
            ]
        self._publish_events(state, new_events)
        return state

    def _publish_events(
        self,
        state: Mapping[str, Any],
        events: list[Mapping[str, Any]],
    ) -> None:
        if self.event_sink is None:
            return
        for event in events:
            try:
                self.event_sink(state, event)
            except Exception:  # noqa: BLE001 - telemetry cannot break lifecycle
                continue

    def record_lifecycle_event(
        self,
        event: str,
        *,
        phase: str = "",
        outcome: str = "",
        blocker_category: str = "",
        remediation_id: str = "",
        duration_ms: int = 0,
        once_per_lifecycle: bool = False,
    ) -> dict[str, Any]:
        def mutation(state: dict[str, Any]) -> None:
            if (
                once_per_lifecycle
                and _has_lifecycle_event(state, event, phase)
            ):
                return
            _append_lifecycle_event(
                state,
                event,
                phase=phase,
                outcome=outcome,
                blocker_category=blocker_category,
                remediation_id=remediation_id,
                duration_ms=duration_ms,
            )

        return self._mutate(mutation)

    def merge_section(
        self,
        section: str,
        values: Mapping[str, Any],
        *,
        verified_phase: str | None = None,
    ) -> dict[str, Any]:
        if section not in {"scope", "identifiers", "endpoints", "operators"}:
            raise WorkdayConnectStoreError(
                f"Unsupported Workday state section: {section}."
            )
        if not isinstance(values, Mapping):
            raise WorkdayConnectStoreError(
                f"Workday state section '{section}' must be an object."
            )
        if verified_phase is not None and verified_phase not in PHASE_BY_ID:
            raise WorkdayConnectStoreError(
                f"Unknown verified Workday phase: {verified_phase}."
            )

        def mutation(state: dict[str, Any]) -> None:
            changed_keys = {
                key for key, value in values.items() if state[section].get(key) != value
            }
            invalidation_phase = _section_invalidation_phase(
                section,
                changed_keys,
            )
            if (
                section == "scope"
                and _target_scope_changed(state, values, changed_keys)
            ):
                _rotate_lifecycle(state)
            if invalidation_phase:
                if verified_phase == invalidation_phase:
                    _invalidate_after_phase(state, invalidation_phase)
                else:
                    _invalidate_from_phase(state, invalidation_phase)
            if (
                (section == "scope" and "workdayTenant" in changed_keys)
                or (
                    section == "identifiers"
                    and bool(changed_keys & _WORKDAY_IDENTIFIER_KEYS)
                )
                or (section == "endpoints" and bool(changed_keys))
            ):
                state["tenantFoundation"] = None
            state[section].update(dict(values))
            if section == "operators":
                phases = {
                    _OPERATOR_PHASES.get(key, "preflight")
                    for key in changed_keys
                }
                for definition in PHASE_DEFINITIONS:
                    phase_id = definition.identifier.value
                    if (
                        phase_id in phases
                        and not _has_lifecycle_event(
                            state,
                            "roles-attested",
                            phase_id,
                        )
                    ):
                        _append_lifecycle_event(
                            state,
                            "roles-attested",
                            phase=phase_id,
                            outcome="success",
                        )

        return self._mutate(mutation)

    def record_administrator_progress(
        self,
        phase_id: str,
        substage: str,
        *,
        valid_fields: Mapping[str, Any] | None = None,
        invalid_fields: list[str] | tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        if phase_id not in ADMINISTRATOR_PHASES:
            raise WorkdayConnectStoreError(
                "Administrator progress is supported only for Entra and "
                "Workday administrator phases."
            )
        if substage not in ADMINISTRATOR_SUBSTAGES:
            raise WorkdayConnectStoreError(
                f"Unknown administrator substage: {substage}."
            )
        safe_fields = dict(valid_fields or {})
        unsupported = sorted(
            set(safe_fields) - ADMINISTRATOR_PARTIAL_FIELDS[phase_id]
        )
        if unsupported:
            raise WorkdayConnectStoreError(
                "Administrator evidence contains unsupported fields: "
                + ", ".join(unsupported)
            )
        requested_invalid = list(invalid_fields or [])
        if any(not isinstance(field, str) for field in requested_invalid):
            raise WorkdayConnectStoreError(
                "Administrator invalid fields must contain field names."
            )
        invalid_unsupported = sorted(
            set(requested_invalid) - ADMINISTRATOR_PARTIAL_FIELDS[phase_id]
        )
        if invalid_unsupported:
            raise WorkdayConnectStoreError(
                "Administrator invalid fields contain unsupported names: "
                + ", ".join(invalid_unsupported)
            )

        def mutation(state: dict[str, Any]) -> None:
            definition = PHASE_BY_ID[phase_id]
            prerequisite = definition.prerequisite
            if (
                prerequisite is not None
                and state["phases"][prerequisite.value]["status"]
                != PhaseStatus.COMPLETE.value
            ):
                raise WorkdayConnectStoreError(
                    f"Complete '{prerequisite.value}' before recording "
                    f"'{phase_id}' administrator progress."
                )
            phase = state["phases"][phase_id]
            administrator = phase["administrator"]
            current_index = ADMINISTRATOR_SUBSTAGES.index(
                administrator["substage"]
            )
            requested_index = ADMINISTRATOR_SUBSTAGES.index(substage)
            if requested_index not in {current_index, current_index + 1}:
                raise WorkdayConnectStoreError(
                    "Administrator substages cannot move backward or skip "
                    "the supported sequence. Invalidate the affected phase "
                    "before restarting its handoff."
                )
            if substage == "evidence-validated" and (
                phase["status"] != PhaseStatus.COMPLETE.value
            ):
                raise WorkdayConnectStoreError(
                    "Complete the administrator phase before marking its "
                    "evidence validated."
                )
            administrator["partialEvidence"].update(
                copy.deepcopy(safe_fields)
            )
            for field in requested_invalid:
                administrator["partialEvidence"].pop(field, None)
            administrator["invalidFields"] = list(
                dict.fromkeys(requested_invalid)
            )
            administrator["substage"] = substage
            administrator["updatedAt"] = utc_now()
            if phase["status"] in {
                PhaseStatus.PENDING.value,
                PhaseStatus.BLOCKED.value,
            }:
                previous_status = phase["status"]
                phase["status"] = PhaseStatus.ACTIVE.value
                phase["blocker"] = None
                phase["updatedAt"] = utc_now()
                if previous_status == PhaseStatus.BLOCKED.value:
                    _append_lifecycle_event(
                        state,
                        "phase-resumed",
                        phase=phase_id,
                        increment_retry=True,
                        increment_resume=True,
                    )
                else:
                    _append_lifecycle_event(
                        state,
                        "phase-started",
                        phase=phase_id,
                    )

        return self._mutate(mutation)

    def record_operator_credential_store(
        self,
        operator_key: str,
        credential_store: str,
        status: str,
    ) -> dict[str, Any]:
        if operator_key not in _OPERATOR_PHASES:
            raise WorkdayConnectStoreError(
                f"Unknown Workday operator: {operator_key}."
            )
        if not credential_store.strip() or not status.strip():
            raise WorkdayConnectStoreError(
                "Credential store name and status are required."
            )

        def mutation(state: dict[str, Any]) -> None:
            operator = state["operators"].get(operator_key)
            if not isinstance(operator, Mapping):
                raise WorkdayConnectStoreError(
                    f"Workday operator '{operator_key}' is not recorded."
                )
            credential_stores = dict(operator.get("credentialStores") or {})
            credential_stores[credential_store] = status
            state["operators"][operator_key] = {
                **dict(operator),
                "credentialStores": credential_stores,
            }

        return self._mutate(mutation)

    def capture_tenant_foundation(self) -> dict[str, Any]:
        """Persist reusable Entra and Workday tenant configuration evidence."""

        def mutation(state: dict[str, Any]) -> None:
            foundation = _tenant_foundation_from_state(state)
            if foundation is None:
                raise WorkdayConnectStoreError(
                    "Complete Entra and Workday administrator verification "
                    "before capturing reusable tenant configuration."
                )
            state["tenantFoundation"] = foundation

        return self._mutate(mutation)

    def restore_workday_foundation(self) -> tuple[dict[str, Any], bool]:
        """Reuse Workday administrator evidence after a fresh Entra reread."""
        reused = False

        def mutation(state: dict[str, Any]) -> None:
            nonlocal reused
            foundation = state.get("tenantFoundation")
            if not isinstance(foundation, Mapping):
                return
            if (
                state["phases"]["preflight"]["status"] != PhaseStatus.COMPLETE.value
                or state["phases"]["entra"]["status"] != PhaseStatus.COMPLETE.value
            ):
                return
            if not _foundation_matches_current_entra(state, foundation):
                return
            foundation_identifiers = foundation.get("identifiers") or {}
            for key in _WORKDAY_IDENTIFIER_KEYS:
                if foundation_identifiers.get(key) is not None:
                    state["identifiers"][key] = copy.deepcopy(
                        foundation_identifiers[key]
                    )
            state["endpoints"].update(
                copy.deepcopy(dict(foundation.get("endpoints") or {}))
            )
            snapshot = (foundation.get("phases") or {}).get("workday-admin")
            if not isinstance(snapshot, Mapping):
                return
            phase = state["phases"]["workday-admin"]
            _reset_phase(phase)
            phase["status"] = PhaseStatus.ACTIVE.value
            phase["completedActions"] = copy.deepcopy(
                list(snapshot.get("completedActions") or [])
            )
            phase["evidence"] = copy.deepcopy(list(snapshot.get("evidence") or []))
            snapshot_administrator = snapshot.get("administrator")
            if isinstance(snapshot_administrator, Mapping):
                phase["administrator"] = copy.deepcopy(
                    dict(snapshot_administrator)
                )
            else:
                phase["administrator"] = default_administrator_state()
                phase["administrator"]["partialEvidence"] = (
                    _legacy_administrator_partial_evidence(
                        state,
                        "workday-admin",
                    )
                )
            phase["administrator"]["substage"] = "collecting-evidence"
            phase["administrator"]["invalidFields"] = []
            phase["administrator"]["updatedAt"] = utc_now()
            phase["evidence"].append(
                {
                    "action": "tenant-foundation-reused",
                    "outcome": "verified",
                    "provenance": "stored-tenant-foundation",
                    "foundationCapturedAt": foundation["capturedAt"],
                    "capturedAt": utc_now(),
                }
            )
            phase["updatedAt"] = utc_now()
            reused = True

        state = self._mutate(mutation)
        return state, reused

    def set_phase_status(
        self,
        phase_id: str,
        status: str,
        *,
        blocker: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if phase_id not in PHASE_BY_ID:
            raise WorkdayConnectStoreError(f"Unknown Workday phase: {phase_id}.")
        if status not in {value.value for value in PhaseStatus}:
            raise WorkdayConnectStoreError(f"Unknown Workday phase status: {status}.")

        def mutation(state: dict[str, Any]) -> None:
            _transition_phase_state(
                state,
                phase_id,
                status,
                blocker=blocker,
            )

        return self._mutate(mutation)

    def complete_action(
        self,
        phase_id: str,
        action: str,
        *,
        evidence: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if phase_id not in PHASE_BY_ID:
            raise WorkdayConnectStoreError(f"Unknown Workday phase: {phase_id}.")
        if not action or not isinstance(action, str):
            raise WorkdayConnectStoreError(
                "Workday completed action must be a non-empty string."
            )

        def mutation(state: dict[str, Any]) -> None:
            prerequisite = PHASE_BY_ID[phase_id].prerequisite
            if (
                prerequisite is not None
                and state["phases"][prerequisite.value]["status"]
                != PhaseStatus.COMPLETE.value
            ):
                raise WorkdayConnectStoreError(
                    f"Complete '{prerequisite.value}' before recording "
                    f"'{phase_id}' evidence."
                )
            phase = state["phases"][phase_id]
            existing_evidence = next(
                (
                    record
                    for record in phase["evidence"]
                    if record.get("action") == action
                ),
                None,
            )
            evidence_changed = evidence is not None and (
                not isinstance(existing_evidence, Mapping)
                or {
                    key: value
                    for key, value in existing_evidence.items()
                    if key not in {"action", "capturedAt"}
                }
                != dict(evidence)
            )
            if (
                action in phase["completedActions"]
                and not evidence_changed
                and evidence is not None
            ):
                return
            if evidence_changed:
                phase["validationProfiles"] = {}
                _invalidate_after_phase(state, phase_id)
                if phase["status"] == PhaseStatus.COMPLETE.value:
                    _transition_phase_state(
                        state,
                        phase_id,
                        PhaseStatus.ACTIVE.value,
                        invalidate_downstream=False,
                    )
            if action not in phase["completedActions"]:
                phase["completedActions"].append(action)
            if evidence is not None:
                phase["evidence"] = [
                    record
                    for record in phase["evidence"]
                    if record.get("action") != action
                ]
                phase["evidence"].append(
                    {
                        **dict(evidence),
                        "action": action,
                        "capturedAt": utc_now(),
                    }
                )
            previous_status = phase["status"]
            if phase["status"] in {
                PhaseStatus.PENDING.value,
                PhaseStatus.BLOCKED.value,
            }:
                phase["status"] = PhaseStatus.ACTIVE.value
            phase["blocker"] = None
            phase["updatedAt"] = utc_now()
            if previous_status == PhaseStatus.BLOCKED.value:
                _append_lifecycle_event(
                    state,
                    "phase-resumed",
                    phase=phase_id,
                    increment_retry=True,
                    increment_resume=True,
                )
            elif previous_status == PhaseStatus.PENDING.value:
                _append_lifecycle_event(
                    state,
                    "phase-started",
                    phase=phase_id,
                )

        return self._mutate(mutation)

    def record_validation_profile(
        self,
        phase_id: str,
        summary: Mapping[str, Any],
    ) -> dict[str, Any]:
        if phase_id not in PHASE_BY_ID:
            raise WorkdayConnectStoreError(f"Unknown Workday phase: {phase_id}.")
        profile_name = str(summary.get("profile") or "")
        if not profile_name.startswith("workday-da:"):
            raise WorkdayConnectStoreError(
                "Workday validation profile summary is missing its profile."
            )

        def mutation(state: dict[str, Any]) -> None:
            from workday_connect_flightcheck import (
                effective_validation_state,
                validation_input_fingerprint,
            )

            expected_fingerprint = str(
                summary.get("inputFingerprint") or ""
            )
            source_profile = str(
                summary.get("sourceProfile") or profile_name
            )
            current_fingerprint = validation_input_fingerprint(
                effective_validation_state(self.workspace_root, state),
                source_profile,
            )
            if current_fingerprint != expected_fingerprint:
                raise WorkdayConnectStoreError(
                    "Workday lifecycle state changed while readiness "
                    "validation was running. Retry the current operation."
                )
            phase = state["phases"][phase_id]
            if phase["status"] == PhaseStatus.BLOCKED.value:
                phase["status"] = PhaseStatus.ACTIVE.value
                phase["blocker"] = None
                _append_lifecycle_event(
                    state,
                    "phase-resumed",
                    phase=phase_id,
                    increment_retry=True,
                    increment_resume=True,
                )
            persisted_summary = copy.deepcopy(dict(summary))
            persisted_summary["inputFingerprint"] = (
                validation_input_fingerprint(
                    effective_validation_state(self.workspace_root, state),
                    source_profile,
                )
            )
            phase["validationProfiles"][profile_name] = {
                **persisted_summary,
                "validatedAt": utc_now(),
            }
            phase["updatedAt"] = utc_now()

        return self._mutate(mutation)

    def block_validation_profile(
        self,
        phase_id: str,
        profile_name: str,
        *,
        error_type: str,
        message: str,
        customer_remediation: str,
        input_fingerprint: str,
        source_profile: str,
        remediation_id: str = "",
    ) -> dict[str, Any]:
        if phase_id not in PHASE_BY_ID:
            raise WorkdayConnectStoreError(f"Unknown Workday phase: {phase_id}.")

        def mutation(state: dict[str, Any]) -> None:
            from workday_connect_flightcheck import (
                effective_validation_state,
                validation_input_fingerprint,
            )

            current_fingerprint = validation_input_fingerprint(
                effective_validation_state(self.workspace_root, state),
                source_profile,
            )
            if current_fingerprint != input_fingerprint:
                raise WorkdayConnectStoreError(
                    "Workday lifecycle state changed while readiness "
                    "validation was running. Retry the current operation."
                )
            _block_validation_state(
                state,
                phase_id=phase_id,
                error_type=error_type,
                message=message,
                customer_remediation=customer_remediation,
                remediation_id=remediation_id,
            )

        return self._mutate(mutation)

    def begin_employee_test_attempt(self) -> dict[str, Any]:
        def mutation(state: dict[str, Any]) -> None:
            if (
                state["phases"]["runtime"]["status"]
                != PhaseStatus.COMPLETE.value
            ):
                raise WorkdayConnectStoreError(
                    "Complete runtime wiring before starting employee validation."
                )
            flow_ids = _employee_runtime_flow_ids(state)
            if not flow_ids:
                raise WorkdayConnectStoreError(
                    "The recorded agent attachment does not map to reviewed "
                    "runtime flow IDs."
                )
            phase = state["phases"]["employee-validation"]
            existing = phase.get("employeeTestAttempt")
            if isinstance(existing, Mapping) and existing.get("status") in {
                "active",
                "validating",
            }:
                if not (
                    existing.get("status") == "validating"
                    and phase.get("status") == PhaseStatus.BLOCKED.value
                ):
                    raise WorkdayConnectStoreError(
                        "The current employee test attempt is still active. "
                        "Finish or record that attempt before starting another."
                    )
            _clear_employee_validation_evidence(phase)
            phase["employeeTestAttempt"] = {
                "attemptId": str(uuid.uuid4()),
                "scenarioId": "workday-signed-in-employee-read",
                "status": "active",
                "startedAt": utc_now(),
                "completedAt": None,
                "expectedFlowIds": sorted(set(flow_ids)),
                "clockSkewSeconds": 120,
                "targetFingerprint": _employee_target_fingerprint(
                    state,
                    flow_ids,
                ),
                "correlationMode": "bounded-window-flow-set",
                "outcome": "",
            }
            _transition_phase_state(
                state,
                "employee-validation",
                PhaseStatus.ACTIVE.value,
                invalidate_downstream=False,
            )
            phase["validationProfiles"] = {}
            phase["updatedAt"] = utc_now()

        return self._mutate(mutation)

    def freeze_employee_test_attempt(
        self,
        *,
        evidence_timestamp: str,
    ) -> dict[str, Any]:
        def mutation(state: dict[str, Any]) -> None:
            phase = state["phases"]["employee-validation"]
            attempt = phase.get("employeeTestAttempt")
            if (
                not isinstance(attempt, dict)
                or attempt.get("status") not in {"active", "validating"}
            ):
                raise WorkdayConnectStoreError(
                    "Start a bounded employee test attempt before recording "
                    "its outcome."
                )
            current_fingerprint = _employee_target_fingerprint(
                state,
                list(attempt["expectedFlowIds"]),
            )
            if current_fingerprint != attempt["targetFingerprint"]:
                raise WorkdayConnectStoreError(
                    "The selected Workday target or reviewed runtime flows "
                    "changed during employee validation. Start a new attempt."
                )
            try:
                observed = datetime.fromisoformat(
                    evidence_timestamp.replace("Z", "+00:00")
                ).astimezone(timezone.utc)
                started = datetime.fromisoformat(
                    attempt["startedAt"].replace("Z", "+00:00")
                ).astimezone(timezone.utc)
                upper = (
                    datetime.fromisoformat(
                        attempt["completedAt"].replace("Z", "+00:00")
                    ).astimezone(timezone.utc)
                    if attempt["completedAt"]
                    else datetime.now(timezone.utc)
                )
            except (AttributeError, ValueError) as exc:
                raise WorkdayConnectStoreError(
                    "Employee validation timestamps must be timezone-qualified "
                    "ISO-8601 values."
                ) from exc
            skew = timedelta(seconds=attempt["clockSkewSeconds"])
            if observed < started - skew or observed > upper + skew:
                raise WorkdayConnectStoreError(
                    "Employee validation evidence is outside the bounded "
                    "test attempt window. Abandon this attempt, then start "
                    "a new attempt and rerun the scenario."
                )
            if attempt["status"] == "active":
                attempt["status"] = "validating"
                attempt["completedAt"] = utc_now()
                attempt["outcome"] = ""
            phase["updatedAt"] = utc_now()

        return self._mutate(mutation)

    def abandon_employee_test_attempt(self) -> dict[str, Any]:
        def mutation(state: dict[str, Any]) -> None:
            phase = state["phases"]["employee-validation"]
            attempt = phase.get("employeeTestAttempt")
            if (
                not isinstance(attempt, dict)
                or attempt.get("status") not in {"active", "validating"}
            ):
                return
            attempt["status"] = "failed"
            attempt["completedAt"] = attempt["completedAt"] or utc_now()
            attempt["outcome"] = "abandoned"
            phase["validationProfiles"] = {}
            phase["completedActions"] = [
                action
                for action in phase["completedActions"]
                if action != "signed-in-scenario"
            ]
            phase["evidence"] = [
                record
                for record in phase["evidence"]
                if record.get("action") != "signed-in-scenario"
            ]
            _transition_phase_state(
                state,
                "employee-validation",
                PhaseStatus.ACTIVE.value,
                invalidate_downstream=False,
            )
            _append_lifecycle_event(
                state,
                "abandoned",
                phase="employee-validation",
            )

        return self._mutate(mutation)

    def complete_employee_test_attempt(
        self,
        *,
        succeeded: bool,
    ) -> dict[str, Any]:
        def mutation(state: dict[str, Any]) -> None:
            phase = state["phases"]["employee-validation"]
            attempt = phase.get("employeeTestAttempt")
            allowed_statuses = (
                {"validating"}
                if succeeded
                else {"active", "validating"}
            )
            if (
                not isinstance(attempt, dict)
                or attempt.get("status") not in allowed_statuses
            ):
                raise WorkdayConnectStoreError(
                    "Start a bounded employee test attempt before recording "
                    "its outcome."
                )
            attempt["status"] = "succeeded" if succeeded else "failed"
            attempt["completedAt"] = attempt["completedAt"] or utc_now()
            attempt["outcome"] = "success" if succeeded else "failure"
            phase["updatedAt"] = utc_now()

        return self._mutate(mutation)

    def finalize_employee_validation_success(self) -> dict[str, Any]:
        def mutation(state: dict[str, Any]) -> None:
            phase = state["phases"]["employee-validation"]
            attempt = phase.get("employeeTestAttempt")
            if (
                isinstance(attempt, dict)
                and attempt.get("status") == "succeeded"
                and phase["status"] == PhaseStatus.COMPLETE.value
            ):
                return
            if (
                not isinstance(attempt, dict)
                or attempt.get("status") != "validating"
            ):
                raise WorkdayConnectStoreError(
                    "Start a bounded employee test attempt before recording "
                    "its outcome."
                )
            attempt["status"] = "succeeded"
            attempt["completedAt"] = attempt["completedAt"] or utc_now()
            attempt["outcome"] = "success"
            _transition_phase_state(
                state,
                "employee-validation",
                PhaseStatus.COMPLETE.value,
                invalidate_downstream=False,
            )
            self._refresh_validation_profile_fingerprints(state)

        return self._mutate(mutation)

    def finalize_employee_validation_failure(
        self,
        *,
        blocker: Mapping[str, Any],
    ) -> dict[str, Any]:
        def mutation(state: dict[str, Any]) -> None:
            phase = state["phases"]["employee-validation"]
            attempt = phase.get("employeeTestAttempt")
            if (
                not isinstance(attempt, dict)
                or attempt.get("status") != "validating"
            ):
                raise WorkdayConnectStoreError(
                    "Start a bounded employee test attempt before recording "
                    "its outcome."
                )
            attempt["status"] = "failed"
            attempt["completedAt"] = attempt["completedAt"] or utc_now()
            attempt["outcome"] = "failure"
            _transition_phase_state(
                state,
                "employee-validation",
                PhaseStatus.BLOCKED.value,
                blocker=copy.deepcopy(dict(blocker)),
                invalidate_downstream=False,
            )

        return self._mutate(mutation)

    def prepare_migration_employee_test_attempt(self) -> bool:
        prepared = False

        def mutation(state: dict[str, Any]) -> None:
            nonlocal prepared
            phase = state["phases"]["employee-validation"]
            evidence = next(
                (
                    record
                    for record in phase.get("evidence") or []
                    if record.get("action") == "signed-in-scenario"
                ),
                None,
            )
            migration = dict(state.get("migration") or {})
            if (
                not migration.get("flightcheckBaselineRequired")
                or migration.get("legacyReady") is not True
            ):
                return
            flow_ids = _employee_runtime_flow_ids(state)
            timestamp = str((evidence or {}).get("timestamp") or "").strip()
            try:
                observed = datetime.fromisoformat(
                    timestamp.replace("Z", "+00:00")
                )
                if observed.tzinfo is None:
                    raise ValueError
                observed = observed.astimezone(timezone.utc)
            except ValueError:
                observed = None
            if observed is None or not flow_ids:
                phase["status"] = PhaseStatus.ACTIVE.value
                phase["blocker"] = None
                phase["validationProfiles"] = {}
                _clear_employee_validation_evidence(phase)
                phase["updatedAt"] = utc_now()
                state["status"] = "in-progress"
                migration["flightcheckBaselineRequired"] = False
                migration["flightcheckBaselineOutcome"] = (
                    "employee-validation-required"
                )
                state["migration"] = migration
                return
            phase["employeeTestAttempt"] = {
                "attemptId": str(uuid.uuid4()),
                "scenarioId": "workday-signed-in-employee-read",
                "status": "validating",
                "startedAt": observed.isoformat().replace("+00:00", "Z"),
                "completedAt": observed.isoformat().replace("+00:00", "Z"),
                "expectedFlowIds": flow_ids,
                "clockSkewSeconds": 120,
                "targetFingerprint": _employee_target_fingerprint(
                    state,
                    flow_ids,
                ),
                "correlationMode": "bounded-window-flow-set",
                "outcome": "",
            }
            _transition_phase_state(
                state,
                "employee-validation",
                PhaseStatus.ACTIVE.value,
                invalidate_downstream=False,
            )
            phase["updatedAt"] = utc_now()
            prepared = True

        self._mutate(mutation)
        return prepared

    def complete_flightcheck_migration(self) -> dict[str, Any]:
        def mutation(state: dict[str, Any]) -> None:
            phase = state["phases"]["employee-validation"]
            attempt = phase.get("employeeTestAttempt")
            migration = dict(state.get("migration") or {})
            if migration.get("legacyReady") is True and (
                migration.get("flightcheckBaselineOutcome") != "accepted"
            ):
                final_profile = (phase.get("validationProfiles") or {}).get(
                    "workday-da:final"
                )
                if (
                    not isinstance(attempt, dict)
                    or attempt.get("status") != "validating"
                    or not isinstance(final_profile, Mapping)
                    or final_profile.get("accepted") is not True
                ):
                    raise WorkdayConnectStoreError(
                        "Complete a bounded employee test attempt and the final "
                        "readiness profile before accepting the migrated Ready "
                        "state."
                    )
            if isinstance(attempt, dict) and attempt.get("status") == "validating":
                attempt["status"] = "succeeded"
                attempt["completedAt"] = attempt["completedAt"] or utc_now()
                attempt["outcome"] = "success"
            if (
                phase["status"] != PhaseStatus.COMPLETE.value
                and PHASE_REQUIRED_ACTIONS["employee-validation"]
                <= set(phase["completedActions"])
            ):
                _transition_phase_state(
                    state,
                    "employee-validation",
                    PhaseStatus.COMPLETE.value,
                    invalidate_downstream=False,
                )
            self._refresh_validation_profile_fingerprints(state)
            migration["flightcheckBaselineRequired"] = False
            migration["flightcheckBaselineOutcome"] = "accepted"
            migration["flightcheckBaselineAt"] = utc_now()
            state["migration"] = migration

        return self._mutate(mutation)

    def block_flightcheck_migration(
        self,
        phase_id: str,
        *,
        error_type: str,
        message: str,
        customer_remediation: str,
        input_fingerprint: str,
        source_profile: str,
    ) -> dict[str, Any]:
        def mutation(state: dict[str, Any]) -> None:
            from workday_connect_flightcheck import (
                effective_validation_state,
                validation_input_fingerprint,
            )

            current_fingerprint = validation_input_fingerprint(
                effective_validation_state(self.workspace_root, state),
                source_profile,
            )
            if current_fingerprint != input_fingerprint:
                raise WorkdayConnectStoreError(
                    "Workday lifecycle state changed while readiness "
                    "validation was running. Retry the current operation."
                )
            _block_validation_state(
                state,
                phase_id=phase_id,
                error_type=error_type,
                message=message,
                customer_remediation=customer_remediation,
                remediation_id="",
            )
            migration = dict(state.get("migration") or {})
            migration["flightcheckBaselineRequired"] = False
            migration["flightcheckBaselineOutcome"] = "remediation-required"
            migration["flightcheckBaselineAt"] = utc_now()
            state["migration"] = migration

        return self._mutate(mutation)

    def approve_plan(
        self,
        phase_id: str,
        plan: Mapping[str, Any],
    ) -> tuple[dict[str, Any], str]:
        if phase_id not in {"preflight", "connections", "runtime"}:
            raise WorkdayConnectStoreError(
                "Exact apply-plan approval is supported only for package "
                "installation and controller-owned runtime changes."
            )
        if plan.get("phase") != phase_id:
            raise WorkdayConnectStoreError(
                "Workday plan phase does not match the requested phase."
            )
        approved_hash = plan_hash(plan)

        def mutation(state: dict[str, Any]) -> None:
            prerequisite = PHASE_BY_ID[phase_id].prerequisite
            if (
                prerequisite is not None
                and state["phases"][prerequisite.value]["status"]
                != PhaseStatus.COMPLETE.value
            ):
                raise WorkdayConnectStoreError(
                    f"Complete '{prerequisite.value}' before approving '{phase_id}'."
                )
            phase = state["phases"][phase_id]
            previous_status = phase["status"]
            plan_changed = phase.get("approvedPlanHash") != approved_hash
            if (
                phase["status"] == PhaseStatus.COMPLETE.value
                or plan_changed
            ):
                _invalidate_after_phase(state, phase_id)
            if plan_changed:
                _reset_phase(phase)
            phase["approvedPlan"] = dict(plan)
            phase["approvedPlanHash"] = approved_hash
            phase["status"] = PhaseStatus.ACTIVE.value
            phase["blocker"] = None
            phase["updatedAt"] = utc_now()
            if previous_status == PhaseStatus.BLOCKED.value:
                _append_lifecycle_event(
                    state,
                    "phase-resumed",
                    phase=phase_id,
                    increment_retry=True,
                    increment_resume=True,
                )
            elif previous_status != PhaseStatus.ACTIVE.value:
                _append_lifecycle_event(
                    state,
                    "phase-started",
                    phase=phase_id,
                )

        return self._mutate(mutation), approved_hash

    def verify_plan(
        self,
        phase_id: str,
        current_plan: Mapping[str, Any],
        approved_hash: str,
    ) -> str:
        state = self.load()
        phase = state["phases"].get(phase_id)
        if phase is None:
            raise WorkdayConnectStoreError(f"Unknown Workday phase: {phase_id}.")
        current_hash = plan_hash(current_plan)
        stored_hash = phase.get("approvedPlanHash")
        if current_hash != approved_hash or stored_hash != approved_hash:
            raise WorkdayConnectPlanChangedError(
                "The Workday change plan or target changed after approval. "
                "Review and approve the current plan before applying it."
            )
        return current_hash

    def status(self) -> dict[str, Any]:
        from workday_connect_flightcheck import (
            PHASE_REQUIRED_PROFILES,
            effective_validation_state,
            validation_input_fingerprint,
        )

        state = self.load()
        effective_state = effective_validation_state(
            self.workspace_root,
            state,
        )
        phases = []
        next_phase = None
        for definition in PHASE_DEFINITIONS:
            phase = state["phases"][definition.identifier.value]
            profiles = list(phase["validationProfiles"].values())
            profile_names = {
                str(profile.get("profile") or "") for profile in profiles
            }
            required_profiles = set(
                PHASE_REQUIRED_PROFILES[definition.identifier.value]
            )
            current_profiles = {
                str(profile.get("profile") or ""): profile
                for profile in profiles
            }
            profiles_current = all(
                current_profiles[profile_name].get("inputFingerprint")
                == validation_input_fingerprint(
                    effective_state,
                    str(
                        current_profiles[profile_name].get(
                            "sourceProfile"
                        )
                        or profile_name
                    ),
                )
                for profile_name in required_profiles
                if profile_name in current_profiles
            )
            readiness_accepted = (
                bool(required_profiles)
                and
                phase["status"] == PhaseStatus.COMPLETE.value
                and required_profiles <= profile_names
                and profiles_current
            )
            phase_status = {
                "id": definition.identifier.value,
                "title": definition.title,
                "status": phase["status"],
                "readiness": {
                    "accepted": readiness_accepted,
                    "summary": (
                        f"{definition.title} readiness checks passed."
                        if readiness_accepted
                        else None
                    ),
                    "validatedAt": (
                        max(profile["validatedAt"] for profile in profiles)
                        if profiles
                        else None
                    ),
                    "migrationBaseline": any(
                        profile["migrationBaseline"] for profile in profiles
                    ),
                },
            }
            if definition.identifier.value == "employee-validation":
                attempt = phase.get("employeeTestAttempt")
                phase_status["employeeTestAttempt"] = (
                    {
                        "scenarioId": attempt["scenarioId"],
                        "status": attempt["status"],
                        "startedAt": attempt["startedAt"],
                        "completedAt": attempt["completedAt"],
                    }
                    if isinstance(attempt, Mapping)
                    else None
                )
            administrator = phase.get("administrator")
            if isinstance(administrator, Mapping):
                required_fields = set(
                    ADMINISTRATOR_REQUIRED_FIELDS[
                        definition.identifier.value
                    ]
                )
                if (
                    definition.identifier.value == "workday-admin"
                    and administrator["partialEvidence"].get(
                        "authorizationOutcome"
                    )
                    != "task-not-authorized-remediated"
                ):
                    required_fields -= {
                        "authorizationRemediationDomain",
                        "authorizationRemediationScenario",
                        "authorizationRetestOutcome",
                    }
                phase_status["administrator"] = {
                    "substage": administrator["substage"],
                    "capturedFields": sorted(
                        administrator["partialEvidence"]
                    ),
                    "invalidFields": list(
                        administrator["invalidFields"]
                    ),
                    "outstandingFields": sorted(
                        required_fields
                        - administrator["partialEvidence"].keys()
                    ),
                }
            phases.append(phase_status)
            if next_phase is None and phase["status"] != PhaseStatus.COMPLETE.value:
                next_phase = definition.identifier.value
        return {
            "schemaVersion": 1,
            "provider": "workday",
            "status": state["status"],
            "phases": phases,
            "nextPhaseId": next_phase,
            "nextPhaseSummary": next_phase_summary(state),
            "progressText": progress_text(state),
            "blocker": self._customer_safe_blocker(
                next_phase,
                state["phases"][next_phase]["blocker"]
                if next_phase is not None
                else None
            ),
        }

    @staticmethod
    def _customer_safe_blocker(
        phase_id: str | None,
        blocker: Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not isinstance(blocker, Mapping) or phase_id is None:
            return None
        next_action = str(blocker.get("remediation") or "").strip()
        if not next_action:
            next_action = (
                f"Review the {PHASE_BY_ID[phase_id].title} guidance, correct "
                "the reported issue, and retry this phase."
            )
        return {
            "summary": (
                f"{PHASE_BY_ID[phase_id].title} needs attention before "
                "setup can continue."
            ),
            **({"nextAction": next_action} if next_action else {}),
        }
