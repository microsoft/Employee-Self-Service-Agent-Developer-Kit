# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Atomic persisted-state operations for the Workday connect lifecycle."""

from __future__ import annotations

from contextlib import contextmanager
import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any, Iterator, Mapping

from workday_connect_model import (
    LEGACY_PHASE_ROWS,
    PHASE_BY_ID,
    PHASE_DEFINITIONS,
    PHASE_REQUIRED_ACTIONS,
    STATE_SCHEMA_VERSION,
    TENANT_FOUNDATION_REQUIRED_ENDPOINT_KEYS,
    TENANT_FOUNDATION_REQUIRED_IDENTIFIER_KEYS,
    PhaseStatus,
    WorkdayConnectModelError,
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
    "workdaySamlEntityId",
    "scopeGuid",
    "signingCertificate",
)
_OPERATOR_PHASES = {
    "powerPlatformMaker": "preflight",
    "entraAdmin": "entra",
    "workdayAdmin": "workday-admin",
}


class WorkdayConnectStoreError(RuntimeError):
    """Raised when Workday connect state cannot be persisted safely."""


class WorkdayConnectPlanChangedError(WorkdayConnectStoreError):
    """Raised when an approved plan no longer matches the current plan."""


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
                if phase.value == "runtime" and action == "workday-topics-activated":
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

    runtime = state["phases"]["runtime"]
    if (
        runtime["status"] == PhaseStatus.COMPLETE.value
        and "workday-topics-activated" not in runtime["completedActions"]
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
    phase.update(
        {
            "status": PhaseStatus.PENDING.value,
            "completedActions": [],
            "approvedPlanHash": None,
            "approvedPlan": None,
            "evidence": [],
            "blocker": None,
            "updatedAt": utc_now(),
        }
    )


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


def _upgrade_or_migrate_state(
    document: Mapping[str, Any],
) -> dict[str, Any]:
    source_version = document.get("schemaVersion")
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
    if "tenantFoundation" not in state:
        state["tenantFoundation"] = _tenant_foundation_from_state(state)
    first_incomplete: str | None = None
    for definition in PHASE_DEFINITIONS:
        phase_id = definition.identifier.value
        phase = state["phases"][phase_id]
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
    return _upgrade_structured_state(document, source_version=2)


def upgrade_v3_state(document: Mapping[str, Any]) -> dict[str, Any]:
    return _upgrade_structured_state(document, source_version=3)


def upgrade_v4_state(document: Mapping[str, Any]) -> dict[str, Any]:
    return _upgrade_structured_state(document, source_version=4)


class WorkdayConnectStore:
    """Own the single durable Workday connect state file."""

    def __init__(
        self,
        workspace_root: Path,
        *,
        lock_timeout: float = 5.0,
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        self.config_path = self.workspace_root / CONFIG_PATH
        self.lock_path = self.config_path.with_name("state.lock")
        self.backup_path = self.config_path.with_name("config.pre-v5.json")
        self.lock_timeout = lock_timeout

    def initialize(self) -> dict[str, Any]:
        with _file_lock(self.lock_path, self.lock_timeout):
            existing = _read_json(self.config_path)
            if not existing:
                state = default_state()
                _atomic_write_json(self.config_path, state)
                return state
            if existing.get("schemaVersion") == STATE_SCHEMA_VERSION:
                return validate_state(existing)
            if not self.backup_path.exists():
                self.backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self.config_path, self.backup_path)
            state = _upgrade_or_migrate_state(existing)
            _atomic_write_json(self.config_path, state)
            return state

    def load(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return self.initialize()
        current = _read_json(self.config_path)
        if current.get("schemaVersion") != STATE_SCHEMA_VERSION:
            return self.initialize()
        return validate_state(current)

    def _mutate(self, mutation) -> dict[str, Any]:
        with _file_lock(self.lock_path, self.lock_timeout):
            current = _read_json(self.config_path)
            if not current:
                current = default_state()
            elif current.get("schemaVersion") != STATE_SCHEMA_VERSION:
                if not self.backup_path.exists():
                    shutil.copy2(self.config_path, self.backup_path)
                current = _upgrade_or_migrate_state(current)
            state = copy.deepcopy(validate_state(current))
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
            return state

    def merge_section(
        self,
        section: str,
        values: Mapping[str, Any],
    ) -> dict[str, Any]:
        if section not in {"scope", "identifiers", "endpoints", "operators"}:
            raise WorkdayConnectStoreError(
                f"Unsupported Workday state section: {section}."
            )
        if not isinstance(values, Mapping):
            raise WorkdayConnectStoreError(
                f"Workday state section '{section}' must be an object."
            )

        def mutation(state: dict[str, Any]) -> None:
            changed_keys = {
                key for key, value in values.items() if state[section].get(key) != value
            }
            invalidation_phase = _section_invalidation_phase(
                section,
                changed_keys,
            )
            if invalidation_phase:
                _invalidate_from_phase(state, invalidation_phase)
            state[section].update(dict(values))

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
            phase["status"] = PhaseStatus.COMPLETE.value
            phase["completedActions"] = copy.deepcopy(
                list(snapshot.get("completedActions") or [])
            )
            phase["evidence"] = copy.deepcopy(list(snapshot.get("evidence") or []))
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
                phase["status"] == PhaseStatus.COMPLETE.value
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
                        f"Phase '{phase_id}' is missing required verified "
                        "actions: " + ", ".join(missing) + "."
                    )
            phase["status"] = status
            phase["blocker"] = dict(blocker) if blocker else None
            phase["updatedAt"] = utc_now()

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
            if phase["status"] in {
                PhaseStatus.PENDING.value,
                PhaseStatus.BLOCKED.value,
            }:
                phase["status"] = PhaseStatus.ACTIVE.value
            phase["blocker"] = None
            phase["updatedAt"] = utc_now()

        return self._mutate(mutation)

    def approve_plan(
        self,
        phase_id: str,
        plan: Mapping[str, Any],
    ) -> tuple[dict[str, Any], str]:
        if phase_id not in {"preflight", "runtime"}:
            raise WorkdayConnectStoreError(
                "Exact apply-plan approval is supported only for preflight "
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
            if phase["status"] == PhaseStatus.COMPLETE.value:
                _invalidate_after_phase(state, phase_id)
            phase["approvedPlan"] = dict(plan)
            phase["approvedPlanHash"] = approved_hash
            phase["status"] = PhaseStatus.ACTIVE.value
            phase["blocker"] = None
            phase["updatedAt"] = utc_now()

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
        state = self.load()
        phases = []
        next_phase = None
        for definition in PHASE_DEFINITIONS:
            phase = state["phases"][definition.identifier.value]
            phases.append(
                {
                    "id": definition.identifier.value,
                    "title": definition.title,
                    "status": phase["status"],
                }
            )
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
            "blocker": (
                state["phases"][next_phase]["blocker"]
                if next_phase is not None
                else None
            ),
        }
