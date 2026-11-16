# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Pure client-budget tests, not assertions about the backend's serializer."""

import pytest

from planner_payload import (
    PLAN_STORAGE_LIMIT_BYTES,
    PlanPayloadTooLarge,
    ensure_plan_payload_fits,
    json_utf8_size,
    measure_plan_payload,
    plan_metadata,
)


def test_limit_boundary_includes_server_metadata_headroom():
    body = {"context": [{"key": "scope", "value": ""}]}
    empty = measure_plan_payload(body)
    body["context"][0]["value"] = "x" * (PLAN_STORAGE_LIMIT_BYTES - empty.estimated_bytes)
    assert ensure_plan_payload_fits(body).estimated_bytes == PLAN_STORAGE_LIMIT_BYTES
    body["context"][0]["value"] += "x"
    with pytest.raises(PlanPayloadTooLarge) as error:
        ensure_plan_payload_fits(body)
    assert error.value.size.estimated_bytes == PLAN_STORAGE_LIMIT_BYTES + 1


def test_entry_metadata_can_exceed_budget_when_json_alone_fits():
    body = {"context": [{"key": f"scope.{i}", "value": "x" * 170} for i in range(65)]}
    size = measure_plan_payload(body)
    assert size.payload_bytes < PLAN_STORAGE_LIMIT_BYTES
    assert size.estimated_bytes > PLAN_STORAGE_LIMIT_BYTES
    with pytest.raises(PlanPayloadTooLarge):
        ensure_plan_payload_fits(body)


def test_utf8_is_measured_in_bytes_not_characters():
    ascii_body = {"context": [{"key": str(i), "value": "x" * 1000} for i in range(9)]}
    unicode_body = {"context": [{"key": str(i), "value": "\u6f22" * 1000} for i in range(9)]}
    assert ensure_plan_payload_fits(ascii_body)
    with pytest.raises(PlanPayloadTooLarge):
        ensure_plan_payload_fits(unicode_body)
    assert json_utf8_size("\u6f22") == 5


def test_inline_tasks_are_not_counted_as_one_plan_record():
    body = {
        "configuringAgentName": "EmployeeSelfServiceHRDA",
        "context": [{"key": "scope", "value": "Controlled pilot"}],
    }
    expected = ensure_plan_payload_fits(body)
    body["tasks"] = [{"title": f"Task {i}", "description": "x" * 800} for i in range(50)]
    assert json_utf8_size(body) > PLAN_STORAGE_LIMIT_BYTES
    assert ensure_plan_payload_fits(body) == expected


def test_readback_provenance_is_reserved_not_counted_twice():
    wire = {"context": [{"key": "scope", "value": "Pilot"}], "acceptanceCriteria": ["Reviewed"]}
    readback = {
        "PlanId": "plan",
        "Context": [{
            "Key": "scope", "Value": "Pilot", "Description": "", "Group": None,
            "Provenance": {"Source": "Agent", "CapturedAt": "2026-01-01T00:00:00Z"},
        }],
        "AcceptanceCriteria": ["Reviewed"],
    }
    assert plan_metadata(readback, from_readback=True) == wire
    assert measure_plan_payload(plan_metadata(readback, from_readback=True)) == measure_plan_payload(wire)


@pytest.mark.parametrize("context", ["not an array", {}])
def test_malformed_context_is_not_a_successful_budget(context):
    with pytest.raises(ValueError, match="plan.context"):
        ensure_plan_payload_fits({"context": context})


def test_ambiguous_casing_and_invalid_json_are_rejected():
    with pytest.raises(ValueError, match="duplicates field context"):
        plan_metadata({"context": [], "Context": []})
    with pytest.raises(ValueError, match="valid UTF-8 JSON"):
        ensure_plan_payload_fits({"context": [{"key": "scope", "value": float("nan")}]})
