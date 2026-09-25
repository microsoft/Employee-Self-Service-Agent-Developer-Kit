# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Load and validate the versioned Workday DA setup contract."""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
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


class WorkdayDAContractError(ValueError):
    """Raised when a Workday DA definition or state document is invalid."""


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
