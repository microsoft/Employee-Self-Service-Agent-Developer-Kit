# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Load and validate the versioned Workday DA setup contract."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


SOLUTION_ROOT = Path(__file__).resolve().parent.parent
DEFINITION_ROOT = (
    SOLUTION_ROOT / "src" / "skills" / "setup" / "workday-da"
)
DEFAULT_DEFINITION_PATH = DEFINITION_ROOT / "workday-da.definition.json"
DEFAULT_DEFINITION_SCHEMA_PATH = (
    DEFINITION_ROOT / "workday-da.definition.schema.json"
)
DEFAULT_STATE_SCHEMA_PATH = DEFINITION_ROOT / "workday-da.state.schema.json"
_SOLUTION_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$")


class WorkdayDAContractError(ValueError):
    """Raised when a Workday DA definition or state document is invalid."""


@dataclass(frozen=True)
class PackageVersionAssessment:
    """Result of evaluating one installed solution version."""

    outcome: str
    installed_version: str | None
    minimum_inclusive: str | None
    maximum_exclusive: str | None
    message: str


def _load_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WorkdayDAContractError(
            f"Workday DA contract file does not exist: {path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise WorkdayDAContractError(
            f"Workday DA contract file is not valid JSON: {path}: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise WorkdayDAContractError(
            f"Workday DA contract file must contain a JSON object: {path}"
        )
    return document


def _validate_schema(
    document: Mapping[str, Any],
    schema_path: Path,
    *,
    label: str,
) -> None:
    schema = _load_json(schema_path)
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as exc:
        raise WorkdayDAContractError(
            f"Invalid Workday DA {label} schema: {exc}"
        ) from exc
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(
        validator.iter_errors(document),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if not errors:
        return
    error = errors[0]
    location = ".".join(str(part) for part in error.absolute_path) or "<root>"
    raise WorkdayDAContractError(
        f"Invalid Workday DA {label} at {location}: {error.message}"
    )


def _validate_definition_semantics(document: Mapping[str, Any]) -> None:
    packages = document["packages"]
    for flavor, package in packages.items():
        policy = package["versionPolicy"]
        minimum = policy["minimumInclusive"]
        maximum = policy["maximumExclusive"]
        if policy["status"] == "enforced" and minimum is None:
            raise WorkdayDAContractError(
                f"Enforced package policy {flavor} must define "
                "minimumInclusive"
            )
        if minimum is not None and maximum is not None:
            if parse_solution_version(minimum) >= parse_solution_version(maximum):
                raise WorkdayDAContractError(
                    f"Package policy {flavor} minimumInclusive must be lower "
                    "than maximumExclusive"
                )
    architecture_ids: set[str] = set()
    supported_agent_schemas: set[str] = set()
    for architecture in document["architectures"]:
        architecture_id = architecture["id"]
        if architecture_id in architecture_ids:
            raise WorkdayDAContractError(
                f"Duplicate Workday DA architecture id: {architecture_id}"
            )
        architecture_ids.add(architecture_id)
        package_flavor = architecture["packageFlavor"]
        if package_flavor not in packages:
            raise WorkdayDAContractError(
                f"Architecture {architecture_id} references unknown package "
                f"flavor {package_flavor}"
            )
        for schema_name in architecture["agentSchemaNames"]:
            normalized = schema_name.casefold()
            if normalized in supported_agent_schemas:
                raise WorkdayDAContractError(
                    f"Agent schema is assigned to multiple architectures: "
                    f"{schema_name}"
                )
            supported_agent_schemas.add(normalized)

    unsupported = {
        schema_name.casefold()
        for schema_name in document["unsupportedAgentSchemaNames"]
    }
    overlap = supported_agent_schemas & unsupported
    if overlap:
        raise WorkdayDAContractError(
            "Agent schemas cannot be both supported and unsupported: "
            + ", ".join(sorted(overlap))
        )

    steps = document["steps"]
    step_by_id: dict[str, Mapping[str, Any]] = {}
    for step in steps:
        step_id = step["id"]
        if step_id in step_by_id:
            raise WorkdayDAContractError(
                f"Duplicate Workday DA step id: {step_id}"
            )
        if step["owner"] != f"da-{step['phase']}":
            raise WorkdayDAContractError(
                f"Step {step_id} owner {step['owner']} does not match phase "
                f"{step['phase']}"
            )
        step_by_id[step_id] = step

    for step_id, step in step_by_id.items():
        for dependency in step["dependsOn"]:
            if dependency not in step_by_id:
                raise WorkdayDAContractError(
                    f"Step {step_id} references unknown dependency {dependency}"
                )
            if dependency == step_id:
                raise WorkdayDAContractError(
                    f"Step {step_id} cannot depend on itself"
                )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(step_id: str) -> None:
        if step_id in visiting:
            raise WorkdayDAContractError(
                f"Workday DA step dependencies contain a cycle at {step_id}"
            )
        if step_id in visited:
            return
        visiting.add(step_id)
        for dependency in step_by_id[step_id]["dependsOn"]:
            visit(dependency)
        visiting.remove(step_id)
        visited.add(step_id)

    for step_id in step_by_id:
        visit(step_id)

    milestone_ids: set[str] = set()
    milestone_step_ids: set[str] = set()
    for milestone in document["customerMilestones"]:
        milestone_id = milestone["id"]
        if milestone_id in milestone_ids:
            raise WorkdayDAContractError(
                f"Duplicate Workday DA customer milestone id: {milestone_id}"
            )
        milestone_ids.add(milestone_id)
        for step_id in milestone["stepIds"]:
            if step_id not in step_by_id:
                raise WorkdayDAContractError(
                    f"Customer milestone {milestone_id} references unknown "
                    f"step {step_id}"
                )
            if step_id in milestone_step_ids:
                raise WorkdayDAContractError(
                    f"Workday DA step {step_id} is assigned to multiple "
                    "customer milestones"
                )
            milestone_step_ids.add(step_id)
    ungrouped_step_ids = set(step_by_id) - milestone_step_ids
    if ungrouped_step_ids:
        raise WorkdayDAContractError(
            "Workday DA customer milestones do not cover steps: "
            + ", ".join(sorted(ungrouped_step_ids))
        )

    completion = document["completion"]
    final_step_id = completion["finalStepId"]
    if final_step_id not in step_by_id:
        raise WorkdayDAContractError(
            f"Completion references unknown final step {final_step_id}"
        )
    required_step_ids = set(completion["requiredStepIds"])
    missing_required = required_step_ids - step_by_id.keys()
    if missing_required:
        raise WorkdayDAContractError(
            "Completion references unknown required steps: "
            + ", ".join(sorted(missing_required))
        )
    if final_step_id not in required_step_ids:
        raise WorkdayDAContractError(
            f"Final step {final_step_id} must be required for completion"
        )


def validate_definition(
    document: Mapping[str, Any],
    *,
    schema_path: Path = DEFAULT_DEFINITION_SCHEMA_PATH,
) -> None:
    """Validate one Workday DA definition against schema and invariants."""
    _validate_schema(document, schema_path, label="definition")
    _validate_definition_semantics(document)


def load_definition(
    path: Path = DEFAULT_DEFINITION_PATH,
    *,
    schema_path: Path = DEFAULT_DEFINITION_SCHEMA_PATH,
) -> dict[str, Any]:
    """Load and validate the Workday DA definition."""
    document = _load_json(path)
    validate_definition(document, schema_path=schema_path)
    return document


def validate_state(
    document: Mapping[str, Any],
    *,
    schema_path: Path = DEFAULT_STATE_SCHEMA_PATH,
) -> None:
    """Validate one migrated Workday DA persisted-state document."""
    _validate_schema(document, schema_path, label="state")


def parse_solution_version(value: str) -> tuple[int, int, int, int]:
    """Parse the four-part numeric version emitted by Dataverse solutions."""
    if not isinstance(value, str) or not _SOLUTION_VERSION_RE.fullmatch(value):
        raise WorkdayDAContractError(
            f"Invalid Dataverse solution version {value!r}; expected "
            "four numeric components such as 2.1.0.0."
        )
    return tuple(int(part) for part in value.split("."))  # type: ignore[return-value]


def architecture_for_agent_schema(
    agent_schema_name: str,
    *,
    definition: Mapping[str, Any] | None = None,
) -> Mapping[str, Any] | None:
    """Resolve the supported DA architecture for one exact agent schema."""
    active_definition = definition or load_definition()
    normalized = agent_schema_name.casefold()
    for architecture in active_definition["architectures"]:
        if normalized in {
            schema_name.casefold()
            for schema_name in architecture["agentSchemaNames"]
        }:
            return architecture
    return None


def assess_package_version(
    package_flavor: str,
    installed_version: str | None,
    *,
    definition: Mapping[str, Any] | None = None,
) -> PackageVersionAssessment:
    """Evaluate one installed version against its product-owned policy."""
    active_definition = definition or load_definition()
    try:
        package = active_definition["packages"][package_flavor]
    except KeyError as exc:
        raise WorkdayDAContractError(
            f"Unknown Workday DA package flavor: {package_flavor}"
        ) from exc
    policy = package["versionPolicy"]
    minimum = policy["minimumInclusive"]
    maximum = policy["maximumExclusive"]
    if installed_version is None:
        return PackageVersionAssessment(
            "invalid",
            None,
            minimum,
            maximum,
            "The installed solution did not report a version.",
        )
    try:
        parsed = parse_solution_version(installed_version)
    except WorkdayDAContractError as exc:
        return PackageVersionAssessment(
            "invalid",
            installed_version,
            minimum,
            maximum,
            str(exc),
        )
    if policy["status"] != "enforced":
        return PackageVersionAssessment(
            "pending-policy",
            installed_version,
            minimum,
            maximum,
            "Package version policy is awaiting product confirmation.",
        )
    parsed_minimum = parse_solution_version(minimum)
    if parsed < parsed_minimum:
        return PackageVersionAssessment(
            "unsupported",
            installed_version,
            minimum,
            maximum,
            f"Installed version {installed_version} is below the supported "
            f"minimum {minimum}.",
        )
    if maximum is not None and parsed >= parse_solution_version(maximum):
        return PackageVersionAssessment(
            "unsupported",
            installed_version,
            minimum,
            maximum,
            f"Installed version {installed_version} is not below the supported "
            f"maximum {maximum}.",
        )
    return PackageVersionAssessment(
        "supported",
        installed_version,
        minimum,
        maximum,
        f"Installed version {installed_version} is supported.",
    )


def retry_schedule(
    failure_category: str,
    operation_kind: str,
    *,
    definition: Mapping[str, Any] | None = None,
) -> tuple[int, ...]:
    """Return bounded retry delays for a safe operation, else no retries."""
    active_definition = definition or load_definition()
    policy = active_definition["failurePolicy"]
    try:
        category = policy["categories"][failure_category]
    except KeyError as exc:
        raise WorkdayDAContractError(
            f"Unknown Workday DA failure category: {failure_category}"
        ) from exc
    if operation_kind not in {"read", "idempotent"}:
        if operation_kind != "mutation":
            raise WorkdayDAContractError(
                f"Unknown Workday DA operation kind: {operation_kind}"
            )
        return ()
    if not category["retryable"]:
        return ()
    retry_count = max(policy["maxAttempts"] - 1, 0)
    return tuple(policy["backoffSeconds"][:retry_count])
