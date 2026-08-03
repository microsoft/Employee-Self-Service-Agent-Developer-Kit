# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for planner.plan_model — the local Plan document.

Pure logic + local file IO (no network), so exempt from the FlightCheck
cassette policy per tests/AGENTS.md.
"""

from __future__ import annotations

import json

import pytest

from planner.plan_model import (
    Limits,
    Plan,
    action_kit_skill,
    assignee_role_id,
    assignee_user_oid,
    context_entry,
    new_task,
    plan_artifact,
    principal_person,
    principal_pool,
)

PAUL = "00000000-0000-0000-0000-0000000000b1"
ANN = "00000000-0000-0000-0000-0000000000b2"


def _plan_with_tasks() -> Plan:
    plan = Plan.new(objective="ESS HR ticketing on Workday")
    plan.add_task(
        new_task(
            "T1",
            "Create environment & run setup",
            action=action_kit_skill("onboarding"),
            assigned_to=principal_pool("power-platform-admin"),
            produces=["primaryEnvironment"],
        )
    )
    plan.add_task(
        new_task(
            "T2",
            "Connect Workday",
            action=action_kit_skill("connect"),
            assigned_to=principal_pool("integration-owner"),
            consumes=["primaryEnvironment"],
        )
    )
    return plan


# --------------------------------------------------------------------------- #
# Construction, IO, round-trip
# --------------------------------------------------------------------------- #

def test_new_plan_has_objective_context_entry():
    plan = Plan.new(objective="Do the thing")
    assert plan.output_value_or_context("objective") == "Do the thing"
    entry = plan.context[0]
    assert entry["group"] == "objective"
    assert entry["provenance"]["source"] == "User"


def test_save_is_atomic_and_round_trips(tmp_path):
    plan = _plan_with_tasks()
    path = tmp_path / "plan.json"
    plan.save(path)
    assert not (tmp_path / "plan.json.tmp").exists()  # no leftover temp file
    reloaded = Plan.load(path)
    assert reloaded.data == plan.data


def test_save_all_writes_summary(tmp_path):
    plan = _plan_with_tasks()
    path = tmp_path / "plan.json"
    plan.save_all(path)
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "Connect Workday" in summary
    assert "## Tasks" in summary


def test_load_backfills_missing_collections(tmp_path):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({"objective": "x"}), encoding="utf-8")
    plan = Plan.load(path)
    assert plan.tasks == []
    assert plan.context == []
    assert plan.outputs == []
    assert plan.data["status"] == "Draft"


def test_load_or_new_when_absent(tmp_path):
    plan = Plan.load_or_new(tmp_path / "nope.json")
    assert plan.tasks == []


# --------------------------------------------------------------------------- #
# Context bag (intent) — overwrite-in-place with provenance
# --------------------------------------------------------------------------- #

def test_set_context_overwrites_in_place_and_keeps_creator():
    plan = Plan.new()
    plan.set_context("market", "DE", group="market", source="User")
    first_added = plan.context[0]["provenance"]["addedAt"]
    plan.set_context("market", "FR", source="Agent")
    assert len(plan.context) == 1  # overwritten, not duplicated
    prov = plan.context[0]["provenance"]
    assert plan.context[0]["value"] == "FR"
    assert prov["addedAt"] == first_added  # creator stamp preserved
    assert prov["updatedAt"]  # last editor stamp added
    assert prov["source"] == "Agent"


def test_set_system_scopes_keys_per_area():
    plan = Plan.new()
    plan.set_system("hr-knowledge", "SharePoint")
    plan.set_system("hr-ticketing", "ServiceNow HRSD")
    plan.set_system("IT Ticketing", "ServiceNow ITSM")  # slugified
    systems = {e["key"]: e["value"] for e in plan.context if e.get("group") == "system"}
    assert systems == {
        "system.hr-knowledge": "SharePoint",
        "system.hr-ticketing": "ServiceNow HRSD",
        "system.it-ticketing": "ServiceNow ITSM",
    }


def test_save_bumps_updated_at_and_summary_shows_it(tmp_path):
    plan = Plan.new(objective="x")
    created = plan.data["updatedAt"]
    plan.data["updatedAt"] = "2000-01-01T00:00:00Z"  # simulate an older stamp
    plan.data["generatedAt"] = "2000-01-01T00:00:00Z"
    plan.save(tmp_path / "plan.json")
    assert plan.data["updatedAt"] != "2000-01-01T00:00:00Z"  # bumped on save
    assert created  # new() set an updatedAt
    summary = plan.render_summary()
    assert "Updated:" in summary


# --------------------------------------------------------------------------- #
# Tasks + assignment (the extended Principal states)
# --------------------------------------------------------------------------- #

def test_add_task_rejects_duplicate_id():
    plan = _plan_with_tasks()
    with pytest.raises(ValueError, match="duplicate task id"):
        plan.add_task(new_task("T1", "dup"))


def test_assign_pool_then_direct():
    plan = _plan_with_tasks()
    plan.assign_task("T1", role_id="power-platform-admin")  # pool
    at = plan.task("T1")["assignedTo"]
    assert at["type"] == "Role"
    assert assignee_role_id(at) == "power-platform-admin"
    assert assignee_user_oid(at) is None
    plan.assign_task("T1", role_id="power-platform-admin", person_oid=PAUL)  # direct-for-role
    at = plan.task("T1")["assignedTo"]
    assert at["type"] == "User"
    assert assignee_user_oid(at) == PAUL
    assert assignee_role_id(at) == "power-platform-admin"


def test_claim_retains_role():
    plan = _plan_with_tasks()
    plan.assign_task("T2", role_id="integration-owner")  # pool
    plan.claim_task("T2", PAUL)
    at = plan.task("T2")["assignedTo"]
    assert at["type"] == "User"
    assert assignee_user_oid(at) == PAUL
    assert assignee_role_id(at) == "integration-owner"  # role survives the claim


def test_assign_requires_something():
    plan = _plan_with_tasks()
    with pytest.raises(ValueError):
        plan.assign_task("T1")


def test_set_state_validates():
    plan = _plan_with_tasks()
    plan.set_task_state("T1", "Completed")
    assert plan.task("T1")["state"] == "Completed"
    with pytest.raises(ValueError):
        plan.set_task_state("T1", "Bogus")


def test_require_task_missing():
    plan = _plan_with_tasks()
    with pytest.raises(KeyError):
        plan.set_task_state("nope", "Completed")


# --------------------------------------------------------------------------- #
# Output ledger — supersede-by-key, filter-by-task
# --------------------------------------------------------------------------- #

def test_add_output_supersedes_by_key():
    plan = _plan_with_tasks()
    plan.add_output(plan_artifact("primaryEnvironment", "Environment", {"environmentId": "one"}, produced_by_task_id="T1"))
    plan.add_output(plan_artifact("primaryEnvironment", "Environment", {"environmentId": "two"}, produced_by_task_id="T1"))
    active = [a for a in plan.outputs if a["state"] == "Active"]
    assert len(active) == 1
    assert active[0]["attributes"]["environmentId"] == "two"
    assert plan.output("primaryEnvironment")["attributes"]["environmentId"] == "two"


def test_outputs_of_task_is_ledger_filter():
    plan = _plan_with_tasks()
    plan.add_output(plan_artifact("primaryEnvironment", "Environment", {"environmentId": "e"}, produced_by_task_id="T1"))
    plan.add_output(plan_artifact("evalSuite", "Custom", {"id": "s"}, produced_by_task_id="T2"))
    assert [a["key"] for a in plan.outputs_of_task("T1")] == ["primaryEnvironment"]


# --------------------------------------------------------------------------- #
# Flow 2 — discovery grouped by role, multi-role
# --------------------------------------------------------------------------- #

def test_tasks_for_person_groups_by_role_and_relation():
    plan = Plan.new()
    plan.add_task(new_task("P1", "pooled", assigned_to=principal_pool("integration-owner")))
    plan.add_task(new_task("P2", "mine", assigned_to=principal_person(ANN, role_id="eval-author")))
    plan.add_task(new_task("P3", "other", assigned_to=principal_pool("workday-admin")))
    plan.add_task(new_task("P4", "theirs", assigned_to=principal_person(PAUL, role_id="eval-author")))

    grouped = plan.tasks_for_person(ANN, ["integration-owner", "eval-author"])
    assert set(grouped) == {"integration-owner", "eval-author"}
    assert grouped["integration-owner"][0]["relation"] == "pool"
    assert grouped["eval-author"][0]["relation"] == "assigned"
    assert grouped["eval-author"][0]["task"]["id"] == "P2"


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #

def test_valid_plan_has_no_errors():
    plan = _plan_with_tasks()
    plan.add_output(plan_artifact("primaryEnvironment", "Environment", {"environmentId": "e"}, produced_by_task_id="T1"))
    assert plan.validate() == []


def test_validate_flags_nested_context_value():
    plan = Plan.new()
    plan.context.append(context_entry("bad", {"nested": "object"}))
    assert any("must be scalar" in e for e in plan.validate())


def test_validate_flags_duplicate_context_key():
    plan = Plan.new()
    plan.context.append(context_entry("dup", "1"))
    plan.context.append(context_entry("dup", "2"))
    assert any("not unique" in e for e in plan.validate())


def test_validate_flags_bad_action_missing_skill():
    plan = Plan.new()
    plan.add_task(new_task("T", "t", action={"kind": "kitSkill"}))  # missing skill
    assert any("missing 'skill'" in e for e in plan.validate())


def test_validate_flags_invalid_artifact_kind():
    plan = Plan.new()
    plan.add_task(new_task("T1", "t"))
    plan.outputs.append(plan_artifact("k", "NotAKind", {"a": 1}, produced_by_task_id="T1"))
    assert any("invalid kind" in e for e in plan.validate())


def test_validate_flags_two_active_same_key():
    plan = Plan.new()
    plan.add_task(new_task("T1", "t"))
    plan.outputs.append(plan_artifact("k", "Custom", {"a": 1}, produced_by_task_id="T1"))
    plan.outputs.append(plan_artifact("k", "Custom", {"a": 2}, produced_by_task_id="T1"))
    assert any("Active artifacts" in e for e in plan.validate())


def test_validate_flags_too_many_tasks():
    plan = Plan.new()
    for i in range(Limits.MAX_TASKS + 1):
        plan.tasks.append(new_task(f"T{i}", "t"))
    assert any("too many tasks" in e for e in plan.validate())
