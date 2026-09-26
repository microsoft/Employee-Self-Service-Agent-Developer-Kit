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
    PhaseStatus,
    WorkdayConnectModelError,
    default_state,
    plan_hash,
    progress_text,
    scope_hash,
    utc_now,
    validate_state,
    workday_saml_entity_id,
)


CONFIG_PATH = Path(".local/connect/workday-da/config.json")


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
        if phase_state["status"] != PhaseStatus.PENDING.value:
            phase_state["updatedAt"] = utc_now()

    if all(
        phase["status"] == PhaseStatus.COMPLETE.value
        for phase in state["phases"].values()
    ):
        state["status"] = "ready"
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
        self.backup_path = self.config_path.with_name("config.pre-v2.json")
        self.lock_timeout = lock_timeout

    def initialize(self) -> dict[str, Any]:
        with _file_lock(self.lock_path, self.lock_timeout):
            existing = _read_json(self.config_path)
            if not existing:
                state = default_state()
                _atomic_write_json(self.config_path, state)
                return state
            if existing.get("schemaVersion") == 2:
                return validate_state(existing)
            if not self.backup_path.exists():
                self.backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self.config_path, self.backup_path)
            state = migrate_legacy_state(existing)
            _atomic_write_json(self.config_path, state)
            return state

    def load(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return self.initialize()
        return validate_state(_read_json(self.config_path))

    def _mutate(self, mutation) -> dict[str, Any]:
        with _file_lock(self.lock_path, self.lock_timeout):
            current = _read_json(self.config_path)
            if not current:
                current = default_state()
            elif current.get("schemaVersion") != 2:
                if not self.backup_path.exists():
                    shutil.copy2(self.config_path, self.backup_path)
                current = migrate_legacy_state(current)
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
            state[section].update(dict(values))

        return self._mutate(mutation)

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
            raise WorkdayConnectStoreError(
                f"Unknown Workday phase status: {status}."
            )

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
            phase["status"] = status
            phase["blocker"] = dict(blocker) if blocker else None
            phase["updatedAt"] = utc_now()
            if status == PhaseStatus.COMPLETE.value:
                phase["scopeHash"] = scope_hash(state["scope"])

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
            phase = state["phases"][phase_id]
            if action not in phase["completedActions"]:
                phase["completedActions"].append(action)
            if evidence is not None:
                phase["evidence"].append(
                    {
                        "action": action,
                        "capturedAt": utc_now(),
                        **dict(evidence),
                    }
                )
            if phase["status"] == PhaseStatus.PENDING.value:
                phase["status"] = PhaseStatus.ACTIVE.value
            phase["blocker"] = None
            phase["updatedAt"] = utc_now()

        return self._mutate(mutation)

    def record_handoff(
        self,
        phase_id: str,
        handoff: Mapping[str, Any],
    ) -> dict[str, Any]:
        if phase_id not in PHASE_BY_ID:
            raise WorkdayConnectStoreError(f"Unknown Workday phase: {phase_id}.")

        def mutation(state: dict[str, Any]) -> None:
            phase = state["phases"][phase_id]
            phase["manualHandoff"] = {
                **dict(handoff),
                "capturedAt": utc_now(),
            }
            phase["status"] = PhaseStatus.WAITING.value
            phase["updatedAt"] = utc_now()

        return self._mutate(mutation)

    def approve_plan(
        self,
        phase_id: str,
        plan: Mapping[str, Any],
    ) -> tuple[dict[str, Any], str]:
        if phase_id not in PHASE_BY_ID:
            raise WorkdayConnectStoreError(f"Unknown Workday phase: {phase_id}.")
        if plan.get("phase") != phase_id:
            raise WorkdayConnectStoreError(
                "Workday plan phase does not match the requested phase."
            )
        approved_hash = plan_hash(plan)

        def mutation(state: dict[str, Any]) -> None:
            phase = state["phases"][phase_id]
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
            if (
                next_phase is None
                and phase["status"] != PhaseStatus.COMPLETE.value
            ):
                next_phase = definition.identifier.value
        return {
            "schemaVersion": 1,
            "provider": "workday",
            "status": state["status"],
            "phases": phases,
            "nextPhaseId": next_phase,
            "progressText": progress_text(state),
            "blocker": (
                state["phases"][next_phase]["blocker"]
                if next_phase is not None
                else None
            ),
        }
