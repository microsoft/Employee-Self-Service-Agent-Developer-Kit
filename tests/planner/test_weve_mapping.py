# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for planner.weve_mapping — WeveNova <-> local model round-trips.

Grounded in a real ``get_project_plan`` response captured from the live
``weve-plan`` MCP server (``fixtures/weve_project_plan.json``).
"""

from __future__ import annotations

import json
import os

from planner import weve_mapping as wm
from planner.plan_model import (
    Plan,
    new_task,
    plan_artifact,
    principal_person,
    principal_pool,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "weve_project_plan.json")


def _load_fixture() -> dict:
    with open(FIXTURE, "r", encoding="utf-8") as fh:
        return json.load(fh)


def test_plan_from_weve_maps_real_payload():
    doc = _load_fixture()
    data = wm.plan_from_weve(doc, tasks=[])
    assert data["planId"] == doc["PlanId"]
    assert data["projectId"] == doc["ProjectId"]
    assert data["status"] == doc["Status"]
    assert data["etag"] == doc["ETag"]
    # Context entries are camelCased.
    scenario = next(e for e in data["context"] if e["key"] == "scenario")
    assert scenario["value"] == "HR-Ticketing"
    assert scenario["group"] == "scenarioContext"
    assert scenario["provenance"]["source"] == "User"
    # AcceptanceCriteria folds into the acceptanceCriteria context group.
    crits = wm.acceptance_criteria_from_plan(data)
    assert "HR knowledge grounded in Workday" in crits
    assert "Eval pass-rate >= 90%" in crits


def test_output_from_weve_flattens_attributes():
    doc = _load_fixture()
    data = wm.plan_from_weve(doc)
    art = next(a for a in data["outputs"] if a["key"] == "primaryEnvironment")
    assert art["kind"] == "Environment"
    assert art["state"] == "Active"
    assert art["producedByTaskId"] == "bfcedfec-8f3d-4ba8-a487-f36b0b968f92"
    # WeveNova Attributes[] (list of {Key,Value}) -> local flat attributes dict.
    assert art["attributes"]["environmentId"] == "d3f1e2a4-0000-4a10-9c00-abcdef012345"
    assert art["attributes"]["environmentUrl"].startswith("https://make.powerapps.com/")


def test_loaded_plan_validates_and_renders():
    doc = _load_fixture()
    # The plan's output references its producing task; in a real load the task
    # list is fetched alongside, so include it here for a faithful validation.
    producing = new_task("bfcedfec-8f3d-4ba8-a487-f36b0b968f92", "Run setup",
                         assigned_to=principal_pool("power-platform-admin"),
                         produces=["primaryEnvironment"])
    plan = Plan(wm.plan_from_weve(doc, tasks=[producing]))
    assert plan.validate() == []          # a real WeveNova plan is a valid local Plan
    md = plan.render_summary()
    assert "HR-Ticketing" in md
    assert "primaryEnvironment" in md


def test_output_round_trip_local_to_weve_to_local():
    art = plan_artifact(
        "primaryEnvironment",
        "Environment",
        {"environmentId": "e-123", "environmentUrl": "https://x"},
        produced_by_task_id="T1",
        inventory_ref="environment:e-123",
    )
    weve = wm.output_to_weve(art)
    assert weve["Key"] == "primaryEnvironment"
    assert {a["Key"] for a in weve["Attributes"]} == {"environmentId", "environmentUrl"}
    back = wm.output_from_weve(weve)
    assert back["attributes"] == art["attributes"]
    assert back["kind"] == "Environment"
    assert back["producedByTaskId"] == "T1"


def test_output_to_completion_shape_and_kind_clamp():
    # The completion projection is camelCase, carries only key/kind/attributes
    # (+ optional inventoryRef), and clamps kind to the tool's four-value enum:
    # an in-enum kind is preserved; a local-only kind (Agent) folds to Custom.
    env = wm.output_to_completion(plan_artifact(
        "primaryEnvironment", "Environment",
        {"environmentId": "e-1", "environmentUrl": "https://x"},
        produced_by_task_id="T1", inventory_ref="Environment:e-1",
    ))
    assert env["key"] == "primaryEnvironment"
    assert env["kind"] == "Environment"
    assert env["inventoryRef"] == "Environment:e-1"
    assert {"key": "environmentId", "value": "e-1"} in env["attributes"]

    agent = wm.output_to_completion(plan_artifact(
        "essAgent", "Agent", {"botId": "b-1"}, produced_by_task_id="T1",
    ))
    assert agent["kind"] == "Custom"                 # non-enum local kind folds to Custom
    assert "inventoryRef" not in agent               # omitted when empty
    assert agent["attributes"] == [{"key": "botId", "value": "b-1"}]


def test_context_round_trip():
    entry = {
        "key": "market", "value": "DE", "group": "market",
        "description": "Target market",
        "provenance": {"source": "User", "addedBy": {"oid": "u-1"}, "addedAt": "2026-01-01T00:00:00Z"},
    }
    weve = wm.context_to_weve(entry)
    assert weve["Key"] == "market" and weve["Value"] == "DE" and weve["Group"] == "market"
    assert weve["Provenance"]["Source"] == "User"
    back = wm.context_from_weve(weve)
    assert back["key"] == "market" and back["value"] == "DE"
    assert back["provenance"]["source"] == "User"


def test_plan_fields_to_weve_splits_context_and_criteria():
    doc = _load_fixture()
    data = wm.plan_from_weve(doc, tasks=[])
    fields = wm.plan_fields_to_weve(data)
    # Context is the PascalCase bag MINUS the acceptance-criteria entries...
    keys = {c["Key"] for c in fields["Context"]}
    assert {"scenario", "system", "market"} <= keys
    assert all(c.get("Group") != wm.ACCEPTANCE_GROUP for c in fields["Context"])
    # ...and the criteria travel in their own string list (folded in on read).
    assert "HR knowledge grounded in Workday" in fields["AcceptanceCriteria"]
    assert "Eval pass-rate >= 90%" in fields["AcceptanceCriteria"]
    # Outputs are intentionally excluded from the writable plan-level projection.
    assert "Outputs" not in fields


def test_plan_fields_to_weve_round_trips_unchanged():
    # A plan read then projected back must equal the projection of that same plan
    # re-read — this is what lets the store skip a no-op update_project_plan.
    doc = _load_fixture()
    data = wm.plan_from_weve(doc, tasks=[])
    assert wm.plan_fields_to_weve(data) == wm.plan_fields_to_weve(wm.plan_from_weve(doc, tasks=[]))


def test_task_from_weve_maps_real_task_fixture():
    with open(os.path.join(os.path.dirname(__file__), "fixtures", "weve_project_plan_task.json"), "r", encoding="utf-8") as fh:
        t = json.load(fh)
    task = wm.task_from_weve(t)
    assert task["id"] == "92f47d60-fa6a-4210-ad3a-d2789e234022"
    assert task["title"] == "author evals"
    assert task["consumes"] == ["primaryEnvironment"]
    assert task["state"] == "Completed"
    assert task["assignedTo"] == {}          # AssignedToId/RoleId both null -> unassigned


def test_task_round_trip_pool_and_person():
    pooled = new_task("T1", "Set up Workday SSO", description="Register the app",
                      assigned_to=principal_pool("WorkdayAdmin"),
                      produces=["workdayEntraApp"], consumes=["primaryEnvironment"])
    weve = wm.task_to_weve(pooled, include_id=False)
    assert weve["Title"] == "Set up Workday SSO"
    # A pooled role task writes the spec-§3 shape: Type=Role, Id=RoleId=<role>.
    assert weve["AssignedToType"] == "Role"
    assert weve["AssignedToRoleId"] == "WorkdayAdmin"
    assert weve["AssignedToId"] == "WorkdayAdmin"
    assert "AssignedTo" not in weve          # no nested object on write
    assert weve["Produces"] == ["workdayEntraApp"]
    back = wm.task_from_weve({**weve, "TaskId": "srv-1"})
    assert back["id"] == "srv-1"
    assert back["assignedTo"]["type"] == "Role"
    assert back["assignedTo"]["role"]["roleId"] == "WorkdayAdmin"

    owned = new_task("T2", "Run setup",
                     assigned_to=principal_person("oid-9", role_id="Power Platform Administrator"),
                     produces=["primaryEnvironment"])
    weve2 = wm.task_to_weve(owned)
    assert weve2["AssignedToType"] == "User"
    assert weve2["AssignedToId"] == "oid-9"
    assert weve2["AssignedToRoleId"] == "Power Platform Administrator"
    assert weve2["TaskId"] == "T2"
    back2 = wm.task_from_weve(weve2)
    assert back2["assignedTo"]["user"]["oid"] == "oid-9"
    assert back2["assignedTo"]["role"]["roleId"] == "Power Platform Administrator"


def test_task_round_trip_pooled_from_expanded_assignedto():
    # A real read returns pooled assignment via the expanded AssignedTo object
    # (no AssignedToType scalar), with AssignedToId carrying the role id.
    server_task = {
        "TaskId": "srv-2",
        "Title": "Allow Workday egress",
        "AssignedToId": "Network Administrator",
        "AssignedToRoleId": "Network Administrator",
        "AssignedTo": {"Type": "Role", "Id": "Network Administrator",
                       "Role": {"RoleId": "Network Administrator"}},
        "State": "NotStarted",
    }
    task = wm.task_from_weve(server_task)
    assert task["assignedTo"]["type"] == "Role"
    assert task["assignedTo"]["role"]["roleId"] == "Network Administrator"
    # Round-trips back to a stable writable projection (change-detection no-op).
    assert wm.task_to_weve(task, include_id=False) == wm.task_to_weve(
        wm.task_from_weve(wm.task_to_weve(task, include_id=False)), include_id=False
    )
