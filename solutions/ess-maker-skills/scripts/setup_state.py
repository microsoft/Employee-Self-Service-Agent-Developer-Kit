# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Persistent state management for the integration-neutral ESS setup workflow."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 2
DEFAULT_STATE_PATH = Path(".local/setup/config.json")
SETUP_INTENT = "prereqs + base ESS install only"
STEP_ORDER = (
    "SETUP-01",
    "SETUP-02.1",
    "SETUP-02.2",
    "SETUP-03",
    "SETUP-04",
    "SETUP-05",
    "SETUP-06",
    "SETUP-07",
)
STEP_NOTES = {
    "SETUP-01": (
        "Records locked environment identity, type, endpoint, and foundation "
        "setup intent."
    ),
    "SETUP-02.1": (
        "Confirms selected environment is accessible and its Dataverse database "
        "is provisioned."
    ),
    "SETUP-02.2": (
        "Confirms MCP, allocated capacity, and governance prerequisites are fully "
        "satisfied."
    ),
    "SETUP-03": (
        "Confirms locked Power Platform environment identity remains valid for "
        "setup."
    ),
    "SETUP-04": (
        "Confirms preferred solution configuration or records the maker's "
        "explicit skip decision."
    ),
    "SETUP-05": (
        "Confirms selected ESS products are installed, accessible, bound, and "
        "connection-ready."
    ),
    "SETUP-06": (
        "Confirms selected ESS agents meet baseline readiness requirements "
        "before handoff."
    ),
    "SETUP-07": (
        "Confirms setup completed successfully and integration configuration "
        "can begin safely."
    ),
}


class SetupStateError(ValueError):
    """Raised when setup state is invalid or a transition is not allowed."""


class StepStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in-progress"
    BLOCKED = "blocked"
    DONE = "done"


class ProductId(StrEnum):
    DA_ESSHR = "da.esshr"
    DA_ESSIT = "da.essit"
    DA_ESSHUB = "da.esshub"
    CEA_ESSHR = "cea.esshr"
    CEA_ESSIT = "cea.essit"
    CEA_ESSHUB = "cea.esshub"


class InstallationStatus(StrEnum):
    NOT_SELECTED = "not-selected"
    PENDING = "pending"
    CONNECTION_REQUIRED = "connection-required"
    READY = "ready"
    INSTALLING = "installing"
    MANUAL_REQUIRED = "manual-required"
    INSTALLED = "installed"
    CONNECTION_ATTESTATION_REQUIRED = "connection-attestation-required"
    BOUND = "bound"
    FAILED = "failed"


class EnvironmentType(StrEnum):
    DEV = "Dev"
    TEST = "Test"
    PROD = "Prod"


class StepMode(StrEnum):
    AUTOMATED = "automated"
    MANUAL_ATTESTED = "manual-attested"
    SKIPPED = "skipped"


@dataclass
class StepRecord:
    state: str = StepStatus.PENDING
    updated_at: str | None = None
    failure_causes: list[str] = field(default_factory=list)
    checkpoint: str | None = None
    note: str | None = None
    mode: str | None = None
    recorded_at: str | None = None


@dataclass
class ProductInstallationRecord:
    selected: bool = False
    installation_status: str = InstallationStatus.NOT_SELECTED
    connection_name: str | None = None
    schema_name: str | None = None
    requires_connection_attestation: bool = False
    agent_id: str | None = None
    agent_name: str | None = None
    connection_settings_url: str | None = None
    connection_attested_at: str | None = None
    ready: bool = False
    failure_cause: str | None = None
    updated_at: str | None = None


def _default_products() -> dict[str, ProductInstallationRecord]:
    return {
        product_id.value: ProductInstallationRecord()
        for product_id in ProductId
    }


@dataclass
class SetupState:
    schema_version: int = SCHEMA_VERSION
    intent: str = SETUP_INTENT
    environment: dict[str, Any] = field(default_factory=dict)
    selected_products: list[str] = field(default_factory=list)
    prerequisites: dict[str, Any] = field(default_factory=dict)
    alm: dict[str, Any] = field(default_factory=dict)
    products: dict[str, ProductInstallationRecord] = field(
        default_factory=_default_products
    )
    steps: dict[str, StepRecord] = field(default_factory=lambda: {
        step_id: StepRecord() for step_id in STEP_ORDER
    })
    active_step: str = STEP_ORDER[0]
    connect_ready: bool = False
    open_issues: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: utc_now())
    updated_at: str = field(default_factory=lambda: utc_now())
    completed_at: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SetupState":
        if raw.get("schema_version") != SCHEMA_VERSION:
            raise SetupStateError(
                f"Unsupported setup schema version: {raw.get('schema_version')!r}"
            )
        unexpected = set(raw) - {item.name for item in fields(cls)}
        if unexpected:
            raise SetupStateError(
                "Setup state contains unexpected fields: "
                f"{', '.join(sorted(unexpected))}"
            )

        steps_raw = raw.get("steps")
        if not isinstance(steps_raw, dict):
            raise SetupStateError("Setup state must contain a steps object")
        if set(steps_raw) != set(STEP_ORDER):
            raise SetupStateError("Setup state contains an unexpected step set")

        products_raw = raw.get("products", {})
        if not isinstance(products_raw, dict):
            raise SetupStateError(
                "Setup state contains a malformed products object"
            )

        try:
            steps = {
                step_id: StepRecord(**record)
                for step_id, record in steps_raw.items()
            }
            products = _default_products()
            products.update({
                product_id: ProductInstallationRecord(**record)
                for product_id, record in products_raw.items()
            })
        except (AttributeError, TypeError, ValueError) as exc:
            raise SetupStateError(
                "Setup state contains malformed step or product records"
            ) from exc

        state = cls(
            schema_version=raw["schema_version"],
            intent=raw.get("intent", SETUP_INTENT),
            environment=raw.get("environment", {}),
            selected_products=list(raw.get("selected_products", [])),
            prerequisites=raw.get("prerequisites", {}),
            alm=raw.get("alm", {}),
            products=products,
            steps=steps,
            active_step=raw.get("active_step", STEP_ORDER[0]),
            connect_ready=bool(raw.get("connect_ready", False)),
            open_issues=list(raw.get("open_issues", [])),
            created_at=raw.get("created_at", utc_now()),
            updated_at=raw.get("updated_at", utc_now()),
            completed_at=raw.get("completed_at"),
        )
        SetupWorkflow.validate(state)
        return state

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SetupStateRepository(ABC):
    """Persistence boundary for setup state."""

    @abstractmethod
    def exists(self) -> bool:
        """Return whether setup state exists."""

    @abstractmethod
    def load(self) -> SetupState:
        """Load and validate setup state."""

    @abstractmethod
    def save(self, state: SetupState) -> None:
        """Persist setup state atomically."""


class JsonSetupStateRepository(SetupStateRepository):
    """JSON-backed setup repository with atomic replacement."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def exists(self) -> bool:
        return self._path.is_file()

    def load(self) -> SetupState:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise SetupStateError(f"Setup state not found: {self._path}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise SetupStateError(f"Setup state is unreadable: {exc}") from exc
        if not isinstance(raw, dict):
            raise SetupStateError("Setup state root must be an object")
        return SetupState.from_dict(raw)

    def save(self, state: SetupState) -> None:
        SetupWorkflow.validate(state)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(state.to_dict(), indent=2, ensure_ascii=False) + "\n"
        fd, tmp_name = tempfile.mkstemp(
            prefix=f"{self._path.name}.",
            suffix=".tmp",
            dir=self._path.parent,
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except OSError:
                    pass
            os.replace(tmp_name, self._path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)


class SetupWorkflow:
    """Domain service enforcing setup invariants and transitions."""

    @staticmethod
    def validate(state: SetupState) -> None:
        if state.intent != SETUP_INTENT:
            raise SetupStateError("Setup intent cannot include integration work")
        if set(state.steps) != set(STEP_ORDER):
            raise SetupStateError("Setup state must contain every canonical step")
        expected_products = {product_id.value for product_id in ProductId}
        if set(state.products) != expected_products:
            raise SetupStateError(
                "Setup state must contain every supported ESS product record"
            )

        in_progress = [
            step_id
            for step_id, record in state.steps.items()
            if record.state == StepStatus.IN_PROGRESS
        ]
        if len(in_progress) > 1:
            raise SetupStateError("Only one setup step may be in-progress")

        for step_id, record in state.steps.items():
            try:
                StepStatus(record.state)
            except ValueError as exc:
                raise SetupStateError(
                    f"Invalid state for {step_id}: {record.state!r}"
                ) from exc
            if record.mode not in {None, *[mode.value for mode in StepMode]}:
                raise SetupStateError(
                    f"Invalid checkpoint mode for {step_id}: {record.mode!r}"
                )
            if record.state == StepStatus.DONE and (
                not record.note
                or not record.mode
                or not record.recorded_at
            ):
                raise SetupStateError(
                    f"Completed {step_id} requires persisted step result"
                )

        if state.alm:
            alm_status = state.alm.get("status")
            if alm_status == "configured":
                required_alm = (
                    "solution_id",
                    "solution_name",
                    "publisher_prefix",
                    "version",
                )
                if any(not state.alm.get(key) for key in required_alm):
                    raise SetupStateError(
                        "Configured ALM state is missing solution metadata"
                    )
            elif alm_status == "skipped":
                if state.alm.get("reason") != "maker-selected":
                    raise SetupStateError(
                        "Skipped ALM state requires maker-selected evidence"
                    )
            else:
                raise SetupStateError(
                    f"Invalid ALM status: {alm_status!r}"
                )

        if (
            state.steps["SETUP-04"].state == StepStatus.DONE
            and state.alm.get("status") not in {"configured", "skipped"}
        ):
            raise SetupStateError(
                "Completed SETUP-04 requires configured or skipped ALM state"
            )
        if state.steps["SETUP-04"].state == StepStatus.DONE:
            alm_step = state.steps["SETUP-04"]
            configured = state.alm.get("status") == "configured"
            expected_mode = StepMode.AUTOMATED if configured else StepMode.SKIPPED
            expected_checkpoint = "ENV-009" if configured else None
            if (
                alm_step.checkpoint != expected_checkpoint
                or alm_step.mode != expected_mode
            ):
                raise SetupStateError(
                    "Completed SETUP-04 has inconsistent ALM step details"
                )
        if len(state.selected_products) != len(set(state.selected_products)):
            raise SetupStateError("Selected ESS products must be unique")
        for product_id in state.selected_products:
            try:
                ProductId(product_id)
            except ValueError as exc:
                raise SetupStateError(
                    f"Invalid ESS product: {product_id!r}"
                ) from exc
        selected = set(state.selected_products)
        for product_id, record in state.products.items():
            try:
                InstallationStatus(record.installation_status)
            except ValueError as exc:
                raise SetupStateError(
                    f"Invalid installation status for {product_id}: "
                    f"{record.installation_status!r}"
                ) from exc
            if record.selected != (product_id in selected):
                raise SetupStateError(
                    f"Product selection flag is inconsistent for {product_id}"
                )
            if not record.selected and (
                record.installation_status != InstallationStatus.NOT_SELECTED
            ):
                raise SetupStateError(
                    f"Unselected product {product_id} cannot have installation "
                    "progress"
                )
            if (
                record.installation_status
                == InstallationStatus.CONNECTION_ATTESTATION_REQUIRED
            ):
                required_metadata = (
                    record.connection_name,
                    record.agent_id,
                    record.agent_name,
                    record.connection_settings_url,
                )
                if (
                    not record.requires_connection_attestation
                    or any(not value for value in required_metadata)
                ):
                    raise SetupStateError(
                        f"Product {product_id} has incomplete connection "
                        "attestation state"
                    )
            if (
                record.installation_status == InstallationStatus.BOUND
                and record.requires_connection_attestation
                and not record.connection_attested_at
            ):
                raise SetupStateError(
                    f"Product {product_id} is bound without required maker "
                    "connection attestation"
                )

        if state.active_step not in STEP_ORDER:
            raise SetupStateError(f"Invalid active step: {state.active_step!r}")

        expected_active = SetupWorkflow.next_step(state)
        if state.active_step != expected_active:
            raise SetupStateError(
                f"Active step {state.active_step!r} does not match "
                f"deterministic next step {expected_active!r}"
            )

        if state.connect_ready and not SetupWorkflow.is_complete(state):
            raise SetupStateError("Connect cannot be ready before setup is complete")

    @staticmethod
    def next_step(state: SetupState) -> str:
        for step_id in STEP_ORDER:
            if state.steps[step_id].state != StepStatus.DONE:
                return step_id
        return STEP_ORDER[-1]

    @staticmethod
    def refresh_active_step(state: SetupState) -> None:
        state.active_step = SetupWorkflow.next_step(state)
        state.updated_at = utc_now()

    @staticmethod
    def set_scope(
        state: SetupState,
        *,
        environment_id: str,
        environment_name: str,
        environment_type: str,
        tenant_endpoint: str,
    ) -> None:
        verified_at = utc_now()
        proposed_environment = {
            "id": environment_id,
            "name": environment_name,
            "type": environment_type,
            "tenant_endpoint": tenant_endpoint.rstrip("/"),
            "locked": True,
            "selected_at": verified_at,
            "verified_at": verified_at,
        }
        current_environment = state.environment
        if current_environment.get("locked"):
            locked_identity = {
                key: current_environment.get(key)
                for key in ("id", "name", "type", "tenant_endpoint")
            }
            proposed_identity = {
                key: proposed_environment.get(key)
                for key in ("id", "name", "type", "tenant_endpoint")
            }
            if locked_identity != proposed_identity:
                raise SetupStateError(
                    "Setup scope is locked; start a new setup run to change "
                    "the environment"
                )

        state.environment = proposed_environment
        state.selected_products = []
        for product_id, record in state.products.items():
            record.selected = False
            record.installation_status = InstallationStatus.NOT_SELECTED
            record.connection_name = None
            record.schema_name = None
            record.requires_connection_attestation = False
            record.agent_id = None
            record.agent_name = None
            record.connection_settings_url = None
            record.connection_attested_at = None
            record.ready = False
            record.failure_cause = None
            record.updated_at = utc_now()
        SetupWorkflow.record_step_result(
            state,
            step_id="SETUP-01",
            mode=StepMode.AUTOMATED,
        )
        SetupWorkflow.update_step(state, "SETUP-01", StepStatus.DONE)

    @staticmethod
    def select_initial_product(
        state: SetupState,
        product_id: ProductId,
    ) -> None:
        if not state.environment.get("locked"):
            raise SetupStateError(
                "Cannot select a product before the environment is locked"
            )
        if state.selected_products:
            raise SetupStateError(
                "An initial ESS product is already selected"
            )

        product_id = ProductId(product_id)
        record = state.products[product_id.value]
        state.selected_products = [product_id.value]
        record.selected = True
        record.installation_status = InstallationStatus.PENDING
        record.updated_at = utc_now()
        SetupWorkflow.refresh_active_step(state)

    @staticmethod
    def update_step(
        state: SetupState,
        step_id: str,
        status: StepStatus,
        failure_causes: list[str] | None = None,
        *,
        finalizing: bool = False,
    ) -> None:
        if step_id not in state.steps:
            raise SetupStateError(f"Unknown setup step: {step_id}")
        if (
            step_id == "SETUP-07"
            and status == StepStatus.DONE
            and not finalizing
        ):
            raise SetupStateError(
                "SETUP-07 can only be completed by the final setup bundle"
            )
        current = StepStatus(state.steps[step_id].state)
        allowed = {
            StepStatus.PENDING: {
                StepStatus.IN_PROGRESS,
                StepStatus.BLOCKED,
                StepStatus.DONE,
            },
            StepStatus.IN_PROGRESS: {
                StepStatus.BLOCKED,
                StepStatus.DONE,
            },
            StepStatus.BLOCKED: {
                StepStatus.BLOCKED,
                StepStatus.IN_PROGRESS,
                StepStatus.DONE,
            },
            StepStatus.DONE: {StepStatus.DONE},
        }
        if status not in allowed[current]:
            raise SetupStateError(
                f"Invalid transition for {step_id}: {current} -> {status}"
            )
        step_index = STEP_ORDER.index(step_id)
        incomplete_prior = [
            prior_id
            for prior_id in STEP_ORDER[:step_index]
            if state.steps[prior_id].state != StepStatus.DONE
        ]
        if current != StepStatus.DONE and incomplete_prior:
            raise SetupStateError(
                f"Cannot update {step_id}; prior steps are incomplete: "
                f"{', '.join(incomplete_prior)}"
            )
        if status == StepStatus.DONE:
            step_result = state.steps[step_id]
            if (
                not step_result.note
                or not step_result.mode
                or not step_result.recorded_at
            ):
                raise SetupStateError(
                    f"Cannot complete {step_id}; step result is not recorded"
                )
            if step_id == "SETUP-01":
                required_environment = (
                    "id",
                    "name",
                    "type",
                    "tenant_endpoint",
                    "verified_at",
                )
                if (
                    not state.environment.get("locked")
                    or any(
                        not state.environment.get(key)
                        for key in required_environment
                    )
                ):
                    raise SetupStateError(
                        "Cannot complete SETUP-01; environment is not locked "
                        "and verified"
                    )
            if step_id == "SETUP-04":
                alm_status = state.alm.get("status")
                if alm_status not in {"configured", "skipped"}:
                    raise SetupStateError(
                        "Cannot complete SETUP-04; choose or skip the preferred "
                        "solution"
                    )
                if alm_status == "configured":
                    alm_step = state.steps["SETUP-04"]
                    if (
                        alm_step.checkpoint != "ENV-009"
                        or alm_step.mode != StepMode.AUTOMATED
                        or not alm_step.recorded_at
                    ):
                        raise SetupStateError(
                            "Cannot complete SETUP-04; ENV-009 has not passed"
                        )
            if step_id == "SETUP-05":
                if not state.selected_products:
                    raise SetupStateError(
                        "Cannot complete SETUP-05; no ESS product is selected"
                    )
                incomplete_products = [
                    product_id
                    for product_id in state.selected_products
                    if state.products[product_id].installation_status
                    != InstallationStatus.BOUND
                ]
                if incomplete_products:
                    raise SetupStateError(
                        "Cannot complete SETUP-05; products are not installed "
                        f"and bound: {', '.join(incomplete_products)}"
                    )
            if step_id == "SETUP-06":
                if not state.selected_products:
                    raise SetupStateError(
                        "Cannot complete SETUP-06; no ESS product is selected"
                    )
                unready_products = [
                    product_id
                    for product_id in state.selected_products
                    if not state.products[product_id].ready
                ]
                if unready_products:
                    raise SetupStateError(
                        "Cannot complete SETUP-06; products are not ready: "
                        f"{', '.join(unready_products)}"
                    )
        if status == StepStatus.IN_PROGRESS:
            for other_id, record in state.steps.items():
                if (
                    other_id != step_id
                    and record.state == StepStatus.IN_PROGRESS
                ):
                    raise SetupStateError(
                        f"{other_id} is already the active in-progress step"
                    )

        current_record = state.steps[step_id]
        state.steps[step_id] = StepRecord(
            state=status,
            updated_at=utc_now(),
            failure_causes=list(failure_causes or []),
            checkpoint=current_record.checkpoint,
            note=current_record.note,
            mode=current_record.mode,
            recorded_at=current_record.recorded_at,
        )
        SetupWorkflow.refresh_active_step(state)

    @staticmethod
    def record_step_result(
        state: SetupState,
        *,
        step_id: str,
        mode: StepMode,
        checkpoint: str | None = None,
    ) -> None:
        if step_id not in state.steps:
            raise SetupStateError(f"Unknown setup step: {step_id}")
        mode = StepMode(mode)
        expected_checkpoints = {
            "SETUP-02.1": "ENV-002",
            "SETUP-02.2": "ENV-CAPACITY-001",
            "SETUP-03": "ENV-001",
        }
        if step_id == "SETUP-04":
            expected_checkpoint = (
                None if mode == StepMode.SKIPPED else "ENV-009"
            )
            if checkpoint != expected_checkpoint:
                expected = expected_checkpoint or "no checkpoint"
                raise SetupStateError(
                    f"SETUP-04 in {mode} mode requires {expected}"
                )
        else:
            expected_checkpoint = expected_checkpoints.get(step_id)
        if expected_checkpoint and checkpoint != expected_checkpoint:
            raise SetupStateError(
                f"{step_id} only accepts checkpoint {expected_checkpoint}"
            )
        if not expected_checkpoint and checkpoint:
            raise SetupStateError(f"{step_id} does not accept a checkpoint")
        record = state.steps[step_id]
        record.checkpoint = checkpoint
        record.note = STEP_NOTES[step_id]
        record.mode = mode
        record.recorded_at = utc_now()
        if step_id == "SETUP-03":
            state.environment["verified_at"] = record.recorded_at
        state.updated_at = record.recorded_at

    @staticmethod
    def selected_starters(state: SetupState) -> tuple[str, ...]:
        return tuple(state.selected_products)

    @staticmethod
    def update_product_installation(
        state: SetupState,
        product_id: ProductId,
        status: InstallationStatus,
        *,
        connection_name: str | None = None,
        schema_name: str | None = None,
        requires_connection_attestation: bool | None = None,
        agent_id: str | None = None,
        agent_name: str | None = None,
        connection_settings_url: str | None = None,
        failure_cause: str | None = None,
    ) -> None:
        product_id = ProductId(product_id)
        status = InstallationStatus(status)
        record = state.products[product_id.value]
        if not record.selected:
            raise SetupStateError(
                f"Cannot update unselected product {product_id.value}"
            )
        current = InstallationStatus(record.installation_status)
        allowed = {
            InstallationStatus.PENDING: {
                InstallationStatus.PENDING,
                InstallationStatus.CONNECTION_REQUIRED,
                InstallationStatus.READY,
                InstallationStatus.INSTALLING,
                InstallationStatus.INSTALLED,
                InstallationStatus.FAILED,
            },
            InstallationStatus.CONNECTION_REQUIRED: {
                InstallationStatus.CONNECTION_REQUIRED,
                InstallationStatus.READY,
                InstallationStatus.FAILED,
            },
            InstallationStatus.READY: {
                InstallationStatus.READY,
                InstallationStatus.INSTALLING,
                InstallationStatus.INSTALLED,
                InstallationStatus.FAILED,
            },
            InstallationStatus.INSTALLING: {
                InstallationStatus.INSTALLING,
                InstallationStatus.INSTALLED,
                InstallationStatus.MANUAL_REQUIRED,
                InstallationStatus.FAILED,
            },
            InstallationStatus.MANUAL_REQUIRED: {
                InstallationStatus.MANUAL_REQUIRED,
                InstallationStatus.INSTALLING,
                InstallationStatus.INSTALLED,
                InstallationStatus.FAILED,
            },
            InstallationStatus.INSTALLED: {
                InstallationStatus.INSTALLED,
                InstallationStatus.CONNECTION_ATTESTATION_REQUIRED,
                InstallationStatus.BOUND,
                InstallationStatus.FAILED,
            },
            InstallationStatus.CONNECTION_ATTESTATION_REQUIRED: {
                InstallationStatus.CONNECTION_ATTESTATION_REQUIRED,
                InstallationStatus.BOUND,
                InstallationStatus.FAILED,
            },
            InstallationStatus.FAILED: {
                InstallationStatus.PENDING,
                InstallationStatus.CONNECTION_REQUIRED,
                InstallationStatus.READY,
                InstallationStatus.INSTALLING,
                InstallationStatus.INSTALLED,
                InstallationStatus.FAILED,
            },
            InstallationStatus.BOUND: {InstallationStatus.BOUND},
        }
        if status not in allowed.get(current, set()):
            raise SetupStateError(
                f"Invalid installation transition for {product_id.value}: "
                f"{current} -> {status}"
            )
        if status == InstallationStatus.CONNECTION_ATTESTATION_REQUIRED:
            required_metadata = {
                "connection name": connection_name or record.connection_name,
                "agent id": agent_id or record.agent_id,
                "agent name": agent_name or record.agent_name,
                "connection settings URL": (
                    connection_settings_url or record.connection_settings_url
                ),
            }
            missing = [
                label for label, value in required_metadata.items()
                if not isinstance(value, str) or not value.strip()
            ]
            if missing:
                raise SetupStateError(
                    "Connection attestation requires "
                    f"{', '.join(missing)}"
                )
            if requires_connection_attestation is not True:
                raise SetupStateError(
                    "Connection attestation status requires an invoker connection"
                )
        if (
            status == InstallationStatus.BOUND
            and record.requires_connection_attestation
            and not record.connection_attested_at
        ):
            raise SetupStateError(
                f"Product {product_id.value} requires maker connection "
                "attestation before it can be bound"
            )
        record.installation_status = status
        if connection_name is not None:
            record.connection_name = connection_name
        if schema_name is not None:
            record.schema_name = schema_name
        if requires_connection_attestation is not None:
            record.requires_connection_attestation = (
                requires_connection_attestation
            )
        if agent_id is not None:
            record.agent_id = agent_id
        if agent_name is not None:
            record.agent_name = agent_name
        if connection_settings_url is not None:
            record.connection_settings_url = connection_settings_url
        if status == InstallationStatus.INSTALLING:
            record.requires_connection_attestation = False
            record.agent_id = None
            record.agent_name = None
            record.connection_settings_url = None
            record.connection_attested_at = None
        record.failure_cause = failure_cause
        record.updated_at = utc_now()
        state.updated_at = record.updated_at

    @staticmethod
    def attest_product_connection(
        state: SetupState,
        product_id: ProductId,
    ) -> None:
        """Record the maker's mandatory post-binding invoker attestation."""
        product_id = ProductId(product_id)
        record = state.products[product_id.value]
        if (
            record.installation_status
            != InstallationStatus.CONNECTION_ATTESTATION_REQUIRED
        ):
            raise SetupStateError(
                f"Product {product_id.value} is not awaiting connection "
                "attestation"
            )
        if not record.requires_connection_attestation:
            raise SetupStateError(
                f"Product {product_id.value} does not require connection "
                "attestation"
            )

        attested_at = utc_now()
        record.connection_attested_at = attested_at
        SetupWorkflow.update_product_installation(
            state,
            product_id,
            InstallationStatus.BOUND,
        )

    @staticmethod
    def set_product_readiness(
        state: SetupState,
        product_id: ProductId,
        ready: bool,
    ) -> None:
        product_id = ProductId(product_id)
        record = state.products[product_id.value]
        if not record.selected:
            raise SetupStateError(
                f"Cannot update unselected product {product_id.value}"
            )
        if ready and record.installation_status != InstallationStatus.BOUND:
            raise SetupStateError(
                f"Product {product_id.value} must be installed and bound "
                "before readiness can pass"
            )
        record.ready = ready
        record.updated_at = utc_now()
        state.updated_at = record.updated_at

    @staticmethod
    def set_alm(
        state: SetupState,
        *,
        solution_id: str,
        solution_name: str,
        publisher_prefix: str,
        version: str,
    ) -> None:
        required = {
            "solution_id": solution_id,
            "solution_name": solution_name,
            "publisher_prefix": publisher_prefix,
            "version": version,
        }
        missing = [
            name for name, value in required.items()
            if not isinstance(value, str) or not value.strip()
        ]
        if missing:
            raise SetupStateError(
                f"ALM metadata is missing: {', '.join(missing)}"
            )
        state.alm = {
            "status": "configured",
            **required,
            "preferred": True,
            "updated_at": utc_now(),
        }
        state.updated_at = state.alm["updated_at"]

    @staticmethod
    def skip_alm(state: SetupState) -> None:
        """Persist the maker's decision to skip optional ALM configuration."""
        state.alm = {
            "status": "skipped",
            "reason": "maker-selected",
            "updated_at": utc_now(),
        }
        SetupWorkflow.record_step_result(
            state,
            step_id="SETUP-04",
            mode=StepMode.SKIPPED,
        )
        state.updated_at = state.alm["updated_at"]

    @staticmethod
    def add_products(
        state: SetupState,
        product_ids: tuple[ProductId, ...],
    ) -> None:
        """Extend a completed foundation scope and reopen dependent steps."""
        if not state.environment.get("locked"):
            raise SetupStateError(
                "Cannot add products before the environment is locked"
            )
        if not state.connect_ready or not SetupWorkflow.is_complete(state):
            raise SetupStateError(
                "Products can be added only after foundation setup is complete"
            )
        requested = {ProductId(product_id).value for product_id in product_ids}
        additions = requested - set(state.selected_products)
        if not additions:
            return

        state.selected_products = [
            product_id.value
            for product_id in ProductId
            if (
                product_id.value in state.selected_products
                or product_id.value in additions
            )
        ]
        for product_id in additions:
            record = state.products[product_id]
            record.selected = True
            record.installation_status = InstallationStatus.PENDING
            record.connection_name = None
            record.schema_name = None
            record.requires_connection_attestation = False
            record.agent_id = None
            record.agent_name = None
            record.connection_settings_url = None
            record.connection_attested_at = None
            record.ready = False
            record.failure_cause = None
            record.updated_at = utc_now()

        for step_id in ("SETUP-05", "SETUP-06", "SETUP-07"):
            state.steps[step_id] = StepRecord()
        state.connect_ready = False
        state.completed_at = None
        SetupWorkflow.refresh_active_step(state)

    @staticmethod
    def is_complete(state: SetupState) -> bool:
        return all(
            record.state == StepStatus.DONE
            for record in state.steps.values()
        )

    @staticmethod
    def finalize(state: SetupState) -> None:
        missing = [
            step_id
            for step_id, record in state.steps.items()
            if step_id != "SETUP-07" and record.state != StepStatus.DONE
        ]
        if missing:
            raise SetupStateError(
                f"Cannot finalize setup; incomplete steps: {', '.join(missing)}"
            )
        if not state.environment.get("locked"):
            raise SetupStateError(
                "Cannot finalize setup; environment is not locked"
            )
        if not state.selected_products:
            raise SetupStateError(
                "Cannot finalize setup; no ESS product is selected"
            )
        incomplete_products = [
            product_id
            for product_id in state.selected_products
            if (
                state.products[product_id].installation_status
                != InstallationStatus.BOUND
                or not state.products[product_id].ready
            )
        ]
        if incomplete_products:
            raise SetupStateError(
                "Cannot finalize setup; products are not bound and ready: "
                f"{', '.join(incomplete_products)}"
            )
        SetupWorkflow.update_step(
            state,
            "SETUP-07",
            StepStatus.DONE,
            finalizing=True,
        )
        state.connect_ready = True
        state.completed_at = utc_now()
        state.updated_at = state.completed_at


class SetupStateService:
    """Application service coordinating persistence, migration, and workflow."""

    def __init__(
        self,
        repository: SetupStateRepository,
    ) -> None:
        self._repository = repository

    def initialize(self) -> SetupState:
        state = self._repository.load() if self._repository.exists() else SetupState()
        SetupWorkflow.refresh_active_step(state)
        self._repository.save(state)
        return state

    def load(self) -> SetupState:
        return self._repository.load()

    def save(self, state: SetupState) -> None:
        self._repository.save(state)


def persist_product_installation_status(
    product_id: str,
    status: str,
    *,
    connection_name: str | None = None,
    schema_name: str | None = None,
    requires_connection_attestation: bool | None = None,
    agent_id: str | None = None,
    agent_name: str | None = None,
    connection_settings_url: str | None = None,
    failure_cause: str | None = None,
    state_path: Path = DEFAULT_STATE_PATH,
) -> None:
    """Persist one product lifecycle transition through the domain service."""
    service = SetupStateService(JsonSetupStateRepository(state_path))
    state = service.load()
    SetupWorkflow.update_product_installation(
        state,
        ProductId(product_id),
        InstallationStatus(status),
        connection_name=connection_name,
        schema_name=schema_name,
        requires_connection_attestation=requires_connection_attestation,
        agent_id=agent_id,
        agent_name=agent_name,
        connection_settings_url=connection_settings_url,
        failure_cause=failure_cause,
    )
    service.save(state)


def persist_alm_solution(
    *,
    solution_id: str,
    solution_name: str,
    publisher_prefix: str,
    version: str,
    state_path: Path = DEFAULT_STATE_PATH,
) -> None:
    """Persist verified preferred-solution metadata."""
    service = SetupStateService(JsonSetupStateRepository(state_path))
    state = service.load()
    SetupWorkflow.set_alm(
        state,
        solution_id=solution_id,
        solution_name=solution_name,
        publisher_prefix=publisher_prefix,
        version=version,
    )
    service.save(state)


def _service(args: argparse.Namespace) -> SetupStateService:
    repository = JsonSetupStateRepository(Path(args.state))
    return SetupStateService(repository)


def _state_view(state: SetupState, view: str) -> dict[str, Any]:
    if view == "full":
        return state.to_dict()
    if view == "environment":
        return {
            "active_step": state.active_step,
            "environment": state.environment,
        }
    if view == "products":
        return {
            "active_step": state.active_step,
            "selected_products": state.selected_products,
            "products": {
                product_id: asdict(state.products[product_id])
                for product_id in state.selected_products
            },
        }
    if view == "report":
        return {
            "environment": state.environment,
            "prerequisites": state.prerequisites,
            "alm": state.alm,
            "selected_products": state.selected_products,
            "products": {
                product_id: asdict(record)
                for product_id, record in state.products.items()
            },
            "open_issues": state.open_issues,
            "connect_ready": state.connect_ready,
            "completed_at": state.completed_at,
        }
    active = state.steps[state.active_step]
    return {
        "active_step": state.active_step,
        "state": active.state,
        "note": active.note,
        "failure_causes": active.failure_causes,
        "connect_ready": state.connect_ready,
        "environment": {
            "locked": bool(state.environment.get("locked")),
            "tenant_endpoint": state.environment.get("tenant_endpoint"),
        },
        "completed_steps": [
            step_id
            for step_id, record in state.steps.items()
            if record.state == StepStatus.DONE
        ],
    }


def _mutation_result(
    state: SetupState,
    *,
    command: str,
    changed: str,
) -> dict[str, Any]:
    return {
        "status": "ok",
        "command": command,
        "changed": changed,
        "active_step": state.active_step,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", default=str(DEFAULT_STATE_PATH))
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init")
    init.add_argument(
        "--view",
        choices=("current", "full"),
        default="current",
    )
    show = commands.add_parser("show")
    show.add_argument(
        "--view",
        choices=("current", "environment", "products", "report", "full"),
        default="current",
    )

    scope = commands.add_parser("set-scope")
    scope.add_argument("--environment-id", required=True)
    scope.add_argument("--environment-name", required=True)
    scope.add_argument(
        "--environment-type",
        required=True,
    )
    scope.add_argument("--tenant-endpoint", required=True)

    select_product = commands.add_parser("select-product")
    select_product.add_argument(
        "--product",
        required=True,
        choices=[item.value for item in ProductId],
    )

    step = commands.add_parser("update-step")
    step.add_argument("--step", required=True, choices=STEP_ORDER)
    step.add_argument(
        "--status",
        required=True,
        choices=[item.value for item in StepStatus],
    )
    step.add_argument("--cause", action="append", default=[])

    step_result = commands.add_parser("record-step-result")
    step_result.add_argument("--step", required=True, choices=STEP_ORDER)
    step_result.add_argument("--checkpoint")
    step_result.add_argument(
        "--mode",
        required=True,
        choices=[item.value for item in StepMode],
    )
    prerequisite = commands.add_parser("set-prerequisite")
    prerequisite.add_argument("--name", required=True)
    prerequisite.add_argument(
        "--status",
        required=True,
        choices=("complete", "pending"),
    )
    prerequisite.add_argument("--value")

    alm = commands.add_parser("set-alm")
    alm.add_argument("--solution-id", required=True)
    alm.add_argument("--solution-name", required=True)
    alm.add_argument("--publisher-prefix", required=True)
    alm.add_argument("--version", required=True)
    commands.add_parser("skip-alm")

    product = commands.add_parser("set-product-status")
    product.add_argument(
        "--product",
        required=True,
        choices=[item.value for item in ProductId],
    )
    product.add_argument(
        "--status",
        required=True,
        choices=[
            item.value
            for item in InstallationStatus
            if item != InstallationStatus.NOT_SELECTED
        ],
    )
    product.add_argument("--connection-name")
    product.add_argument("--schema-name")
    product.add_argument("--failure-cause")

    readiness = commands.add_parser("set-product-readiness")
    readiness.add_argument(
        "--product",
        required=True,
        choices=[item.value for item in ProductId],
    )
    readiness.add_argument(
        "--ready",
        required=True,
        action=argparse.BooleanOptionalAction,
    )

    attestation = commands.add_parser("attest-product-connection")
    attestation.add_argument(
        "--product",
        required=True,
        choices=[item.value for item in ProductId],
    )

    add_product = commands.add_parser("add-product")
    add_product.add_argument(
        "--product",
        required=True,
        action="append",
        choices=[item.value for item in ProductId],
        dest="products",
    )

    commands.add_parser("finalize")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    service = _service(args)

    try:
        if args.command == "init":
            state = service.initialize()
        else:
            state = service.load()

        output: dict[str, Any]
        if args.command in {"init", "show"}:
            output = _state_view(state, args.view)
        elif args.command == "set-scope":
            SetupWorkflow.set_scope(
                state,
                environment_id=args.environment_id,
                environment_name=args.environment_name,
                environment_type=args.environment_type,
                tenant_endpoint=args.tenant_endpoint,
            )
            service.save(state)
            output = _mutation_result(
                state,
                command=args.command,
                changed="SETUP-01 completed",
            )
        elif args.command == "select-product":
            SetupWorkflow.select_initial_product(
                state,
                ProductId(args.product),
            )
            service.save(state)
            output = _mutation_result(
                state,
                command=args.command,
                changed=f"selected {args.product}",
            )
        elif args.command == "update-step":
            SetupWorkflow.update_step(
                state,
                args.step,
                StepStatus(args.status),
                args.cause,
            )
            service.save(state)
            output = _mutation_result(
                state,
                command=args.command,
                changed=f"{args.step} is {args.status}",
            )
        elif args.command == "record-step-result":
            SetupWorkflow.record_step_result(
                state,
                step_id=args.step,
                mode=StepMode(args.mode),
                checkpoint=args.checkpoint,
            )
            service.save(state)
            output = _mutation_result(
                state,
                command=args.command,
                changed=f"recorded result for {args.step}",
            )
        elif args.command == "set-prerequisite":
            state.prerequisites[args.name] = {
                "status": args.status,
                "value": args.value,
                "updated_at": utc_now(),
            }
            state.updated_at = utc_now()
            service.save(state)
            output = _mutation_result(
                state,
                command=args.command,
                changed=f"prerequisite {args.name} is {args.status}",
            )
        elif args.command == "set-alm":
            SetupWorkflow.set_alm(
                state,
                solution_id=args.solution_id,
                solution_name=args.solution_name,
                publisher_prefix=args.publisher_prefix,
                version=args.version,
            )
            service.save(state)
            output = _mutation_result(
                state,
                command=args.command,
                changed="preferred solution configured",
            )
        elif args.command == "skip-alm":
            SetupWorkflow.skip_alm(state)
            service.save(state)
            output = _mutation_result(
                state,
                command=args.command,
                changed="preferred solution skipped",
            )
        elif args.command == "set-product-status":
            SetupWorkflow.update_product_installation(
                state,
                ProductId(args.product),
                InstallationStatus(args.status),
                connection_name=args.connection_name,
                schema_name=args.schema_name,
                failure_cause=args.failure_cause,
            )
            service.save(state)
            output = _mutation_result(
                state,
                command=args.command,
                changed=f"{args.product} is {args.status}",
            )
        elif args.command == "set-product-readiness":
            SetupWorkflow.set_product_readiness(
                state,
                ProductId(args.product),
                args.ready,
            )
            service.save(state)
            readiness = "ready" if args.ready else "not ready"
            output = _mutation_result(
                state,
                command=args.command,
                changed=f"{args.product} is {readiness}",
            )
        elif args.command == "attest-product-connection":
            SetupWorkflow.attest_product_connection(
                state,
                ProductId(args.product),
            )
            service.save(state)
            output = _mutation_result(
                state,
                command=args.command,
                changed=f"{args.product} connection attested",
            )
        elif args.command == "add-product":
            SetupWorkflow.add_products(
                state,
                tuple(ProductId(product_id) for product_id in args.products),
            )
            service.save(state)
            output = _mutation_result(
                state,
                command=args.command,
                changed=f"added {', '.join(args.products)}",
            )
        elif args.command == "finalize":
            try:
                SetupWorkflow.finalize(state)
            except SetupStateError as exc:
                SetupWorkflow.record_step_result(
                    state,
                    step_id="SETUP-07",
                    mode=StepMode.AUTOMATED,
                )
                recovery_step = SetupWorkflow.next_step(state)
                if state.steps[recovery_step].state == StepStatus.DONE:
                    state.steps[recovery_step] = StepRecord(
                        state=StepStatus.BLOCKED,
                        updated_at=utc_now(),
                        failure_causes=[str(exc)],
                    )
                    SetupWorkflow.refresh_active_step(state)
                else:
                    SetupWorkflow.update_step(
                        state,
                        recovery_step,
                        StepStatus.BLOCKED,
                        [str(exc)],
                    )
                service.save(state)
                raise
            service.save(state)
            output = _mutation_result(
                state,
                command=args.command,
                changed="foundation setup completed",
            )

        print(json.dumps(output, indent=2))
        return 0
    except SetupStateError as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
