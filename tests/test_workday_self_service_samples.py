# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Static contracts for self-service Workday sample and bundled topics."""

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = (
    "WorkdayGetContactInformation",
    "WorkdayGetEducation",
    "WorkdayGetGovernmentIDs",
)
TOPICS = sorted(
    path
    for directory in (
        ROOT / "samples",
        ROOT / "solutions/ess-maker-skills/src/examples/ess-samples",
    )
    for path in directory.rglob("topic.yaml")
    if path.parent.name in SCENARIOS
)


def test_all_self_service_scenarios_are_present():
    assert {path.parent.name for path in TOPICS} == set(SCENARIOS)


@pytest.mark.parametrize("path", TOPICS, ids=lambda path: str(path.relative_to(ROOT)))
def test_self_service_topic_does_not_call_retired_access_helper(path):
    assert "WorkdaySystemAccessCheck" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", TOPICS, ids=lambda path: str(path.relative_to(ROOT)))
def test_self_service_requests_remain_bound_to_authenticated_employee_id(path):
    text = path.read_text(encoding="utf-8")
    requests = [line for line in text.splitlines() if "{Employee_ID}" in line]
    assert len(requests) == (3 if path.parent.name == SCENARIOS[0] else 1)
    for request in requests:
        assert "Global.ESS_UserContext_Employee_Id" in request
        assert "Topic.EmployeeName" not in request
