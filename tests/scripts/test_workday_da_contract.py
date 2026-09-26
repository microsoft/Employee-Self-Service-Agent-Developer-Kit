# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the versioned Workday DA setup contract."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re

import pytest

from workday_da_contract import (
    DEFAULT_DEFINITION_PATH,
    WorkdayDAContractError,
    assess_package_version,
    load_definition,
    parse_solution_version,
    retry_schedule,
    validate_definition,
    validate_state,
)


REPO_ROOT = Path(__file__).parents[2]
TASKS_PATH = (
    REPO_ROOT
    / "solutions"
    / "ess-maker-skills"
    / "src"
    / "skills"
    / "setup"
    / "workday-da"
    / "tasks.md"
)
VISIBLE_ROW = re.compile(
    r"^- \[[ x]\] \*\*(?P<title>.+?)\*\* — (?P<description>.+)$"
)


def _task_rows() -> dict[str, dict[str, str]]:
    lines = TASKS_PATH.read_text(encoding="utf-8").splitlines()
    rows: dict[str, dict[str, str]] = {}
    for index, line in enumerate(lines[:-1]):
        visible = VISIBLE_ROW.match(line)
        if not visible:
            continue
        metadata_line = lines[index + 1].strip()
        assert metadata_line.startswith("<!-- ") and metadata_line.endswith(" -->")
        metadata = {}
        for field in metadata_line[5:-4].split(" | "):
            key, value = field.split(": ", 1)
            metadata[key] = value
        rows[metadata["id"]] = {
            **visible.groupdict(),
            **metadata,
        }
    return rows


def test_default_definition_is_valid_and_complete() -> None:
    definition = load_definition()

    assert DEFAULT_DEFINITION_PATH.is_file()
    assert definition["provider"] == "workday"
    assert definition["definitionVersion"] == 1
    assert definition["stateSchemaVersion"] == 1
    assert len(definition["steps"]) == 21
    assert [milestone["id"] for milestone in definition["customerMilestones"]] == [
        "preflight",
        "microsoft-entra",
        "workday-administrator",
        "connections",
        "runtime-configuration",
        "network-readiness",
        "employee-validation",
    ]
    assert {
        step_id
        for milestone in definition["customerMilestones"]
        for step_id in milestone["stepIds"]
    } == {step["id"] for step in definition["steps"]}
    assert definition["packages"]["runtime"]["flowNames"] == [
        "ESS Workday Runtime References",
        "ESS Workday Runtime REST Execution",
        "ESS Workday Runtime",
    ]
    assert definition["completion"]["finalStepId"] == "DA5.1"
    assert set(definition["completion"]["requiredStepIds"]) == {
        step["id"] for step in definition["steps"]
    }


def test_definition_matches_the_checked_in_checklist_template() -> None:
    definition = load_definition()
    task_rows = _task_rows()

    assert set(task_rows) == {step["id"] for step in definition["steps"]}
    for step in definition["steps"]:
        row = task_rows[step["id"]]
        assert row["title"] == step["title"]
        assert row["description"] == step["description"]
        assert row["role"] == step["role"]
        assert row["skill"] == step["owner"]
        assert row["automatable"] == step["automationLabel"]
        assert row["checkpoints"] == step["checkpointLabel"]
        assert row["gate"] == step["gateLabel"]
        assert row["status"] == "pending"


def test_definition_rejects_unknown_dependency() -> None:
    definition = load_definition()
    invalid = deepcopy(definition)
    invalid["steps"][0]["dependsOn"] = ["DA5.9"]

    with pytest.raises(WorkdayDAContractError, match="unknown dependency DA5.9"):
        validate_definition(invalid)


def test_definition_rejects_duplicate_customer_milestone_assignment() -> None:
    definition = load_definition()
    invalid = deepcopy(definition)
    invalid["customerMilestones"][1]["stepIds"].append("DA1.1")

    with pytest.raises(
        WorkdayDAContractError,
        match="assigned to multiple customer milestones",
    ):
        validate_definition(invalid)


def test_definition_requires_every_step_in_a_customer_milestone() -> None:
    definition = load_definition()
    invalid = deepcopy(definition)
    invalid["customerMilestones"][4]["stepIds"].remove("DA4.7")

    with pytest.raises(WorkdayDAContractError, match="do not cover steps: DA4.7"):
        validate_definition(invalid)


def test_definition_rejects_dependency_cycle() -> None:
    definition = load_definition()
    invalid = deepcopy(definition)
    invalid["steps"][0]["dependsOn"] = ["DA5.1"]

    with pytest.raises(WorkdayDAContractError, match="contain a cycle"):
        validate_definition(invalid)


def test_definition_rejects_unknown_package_flavor() -> None:
    definition = load_definition()
    invalid = deepcopy(definition)
    invalid["architectures"][0]["packageFlavor"] = "missing"

    with pytest.raises(WorkdayDAContractError, match="unknown package flavor"):
        validate_definition(invalid)


def test_state_schema_accepts_migrated_minimal_state() -> None:
    validate_state(
        {
            "definitionVersion": 1,
            "stateSchemaVersion": 1,
            "status": "in-progress",
            "vertical": "hr",
            "verticals": ["hr"],
            "setupStatus": {
                "DA1.1": {
                    "state": "pending",
                    "checkpoint": "WD-DA-PKG-001",
                    "gate": "prog",
                    "verifiedBy": None,
                }
            },
        }
    )


def test_state_schema_rejects_invalid_completion_marker() -> None:
    with pytest.raises(WorkdayDAContractError, match="verifiedBy"):
        validate_state(
            {
                "definitionVersion": 1,
                "stateSchemaVersion": 1,
                "status": "in-progress",
                "setupStatus": {
                    "DA1.1": {
                        "state": "done",
                        "checkpoint": "WD-DA-PKG-001",
                        "gate": "prog",
                        "verifiedBy": "claimed",
                    }
                },
            }
        )


def test_solution_versions_require_four_numeric_components() -> None:
    assert parse_solution_version("2.10.3.4") == (2, 10, 3, 4)
    with pytest.raises(WorkdayDAContractError, match="four numeric components"):
        parse_solution_version("2.10.3")
    with pytest.raises(WorkdayDAContractError, match="four numeric components"):
        parse_solution_version("2.10.preview.4")


def test_pending_package_policy_records_without_claiming_support() -> None:
    assessment = assess_package_version("runtime", "2.1.0.0")

    assert assessment.outcome == "pending-policy"
    assert "awaiting product confirmation" in assessment.message


def test_enforced_package_policy_applies_inclusive_minimum_and_exclusive_maximum() -> None:
    definition = load_definition()
    definition["packages"]["runtime"]["versionPolicy"] = {
        "status": "enforced",
        "minimumInclusive": "2.1.0.0",
        "maximumExclusive": "3.0.0.0",
    }
    validate_definition(definition)

    assert assess_package_version(
        "runtime", "2.1.0.0", definition=definition
    ).outcome == "supported"
    assert assess_package_version(
        "runtime", "2.9.9.9", definition=definition
    ).outcome == "supported"
    assert assess_package_version(
        "runtime", "2.0.9.9", definition=definition
    ).outcome == "unsupported"
    assert assess_package_version(
        "runtime", "3.0.0.0", definition=definition
    ).outcome == "unsupported"


def test_enforced_package_policy_requires_a_minimum() -> None:
    definition = load_definition()
    definition["packages"]["runtime"]["versionPolicy"]["status"] = "enforced"

    with pytest.raises(WorkdayDAContractError, match="minimumInclusive"):
        validate_definition(definition)


def test_failure_policy_retries_only_safe_transient_operations() -> None:
    assert retry_schedule("transient", "read") == (2, 5)
    assert retry_schedule("transient", "idempotent") == (2, 5)
    assert retry_schedule("transient", "mutation") == ()
    assert retry_schedule("permission", "read") == ()
    assert retry_schedule("ambiguous-mutation", "idempotent") == ()


def test_failure_policy_rejects_unknown_categories_and_operations() -> None:
    with pytest.raises(WorkdayDAContractError, match="failure category"):
        retry_schedule("mystery", "read")
    with pytest.raises(WorkdayDAContractError, match="operation kind"):
        retry_schedule("transient", "guess")
