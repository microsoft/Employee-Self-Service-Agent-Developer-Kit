# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Offline regressions for the Planner experience-review journeys."""

import copy
import json

import pytest

from planner import cli, sync
from planner.plan_model import Plan, new_task, plan_artifact, principal_pool


def test_unknown_system_can_be_saved_shared_resumed_and_resolved(tmp_path):
    path = tmp_path / "plan.json"
    plan = Plan.new(objective="Let employees update their HR profile")
    plan.set_configuring_agent_name("EmployeeSelfServiceHRDA")
    plan.set_context("hr-profile-write", "Update HR profile", group="scenario")
    plan.add_task(new_task("setup", "Prepare environment"))
    plan.add_task(new_task("profile", "Connect profile system", consumes=["system.hr-profile-write"]))
    plan.save_all(path)

    assert cli.main(["--plan", str(path), "add-system", "--area", "hr-profile-write", "--pending"]) == 0
    plan = Plan.load(path)
    assert plan.missing_slots()["required"] == []
    assert plan.pending_decisions()[0]["key"] == "system.hr-profile-write"
    assert plan.task_consume_gaps() == []
    assert "Pending decisions" in plan.render_summary()
    assert "SharePoint" not in plan.render_summary()
    plan.set_task_state("setup", "InProgress")
    with pytest.raises(ValueError, match="Confirm the system"):
        plan.set_task_state("profile", "InProgress")

    body = sync.to_remote_plan_body(plan)
    resumed = Plan(sync.hydrate_from_remote({
        **body, "planId": "shared-plan", "status": "Active",
    }, [{"taskId": "profile", **body["tasks"][1]}]))
    assert resumed.pending_decisions()
    assert resumed.configuring_agent_name == "EmployeeSelfServiceHRDA"
    resumed.set_system("hr-profile-write", "Workday")
    assert resumed.pending_decisions() == []
    resumed.set_task_state("profile", "InProgress")
    assert resumed.resolved_consumes("profile") == {"system.hr-profile-write": {"system": "Workday"}}


@pytest.mark.parametrize("answer", ["Unknown", "Not sure", "I don't know yet", "I’m not sure yet"])
def test_uncertain_answers_are_pending_not_system_names(answer):
    plan = Plan.new()
    plan.set_system("hr-profile", answer)
    assert len(plan.pending_decisions()) == 1
    assert plan._systems_by_area() == {}


def test_system_multiselect_keeps_all_choices(tmp_path):
    path = tmp_path / "plan.json"
    assert cli.main(["--plan", str(path), "init"]) == 0
    assert cli.main([
        "--plan", str(path), "add-system", "--area", "hr-profile",
        "--system", "Workday", "--system", "SAP SuccessFactors",
    ]) == 0
    assert Plan.load(path)._systems_by_area() == {"hr-profile": "Workday; SAP SuccessFactors"}


def test_mixed_system_uncertainty_cannot_overwrite_confirmed_systems(tmp_path, capsys):
    path = tmp_path / "plan.json"
    plan = Plan.new()
    plan.set_system("hr-profile", "Workday")
    plan.save_all(path)
    before = path.read_bytes()
    assert cli.main([
        "--plan", str(path), "add-system", "--area", "hr-profile",
        "--system", "Workday", "--system", "Not sure yet",
    ]) == 1
    assert path.read_bytes() == before
    assert "separately; planning can continue" in capsys.readouterr().err


def test_deferred_owner_does_not_block_unrelated_work_or_erase_role():
    plan = Plan.new()
    plan.add_task(new_task("admin", "Set up environment", assigned_to=principal_pool("EntraPowerPlatformAdministrator"), produces=["primaryEnvironment"]))
    plan.add_task(new_task("connect", "Connect HR", consumes=["primaryEnvironment"]))
    plan.add_task(new_task("review", "Review HR scenarios"))
    plan.set_context("owner.EntraPowerPlatformAdministrator", "Not sure yet", group="pendingDecision")
    plan.set_task_state("review", "InProgress")
    with pytest.raises(ValueError, match="Set up environment"):
        plan.set_task_state("connect", "InProgress")
    assert plan.task("admin")["assignedTo"]["type"] == "Role"
    assert plan.tasks_for_person("someone-else", []) == {}
    plan.assign_task("admin", role_id="EntraPowerPlatformAdministrator", person_oid="chosen-admin")
    plan.remove_context("owner.EntraPowerPlatformAdministrator")
    assert plan.tasks_for_person("chosen-admin", ["EntraPowerPlatformAdministrator"])
    plan.add_output(plan_artifact(
        "primaryEnvironment", "Environment", {"environmentId": "test-env"}, produced_by_task_id="admin",
    ))
    plan.set_task_state("admin", "Completed")
    plan.set_task_state("connect", "InProgress")


def test_grouped_view_keeps_cross_stream_dependencies_in_order():
    plan = Plan.new()
    plan.add_task(new_task("prep", "Prepare firewall", stream="Workday"))
    plan.add_task(new_task("connect", "Connect Workday", stream="Workday", consumes=["env"]))
    plan.add_task(new_task("env", "Prepare environment", stream="Setup", produces=["env"]))
    for view in [plan.render_summary(), plan.render_task_checklist()]:
        assert view.index("Prepare environment") < view.index("Connect Workday")
        assert "waiting on Prepare environment" in view
    assert plan.blocking_inputs("prep") == {}


@pytest.mark.parametrize("state", ["InProgress", "Completed"])
def test_missing_inputs_block_execution_not_assignment(state):
    plan = Plan.new()
    plan.add_task(new_task("consumer", "Build topic", consumes=["connection"]))
    plan.assign_task("consumer", role_id="PowerPlatformEnvironmentMaker")
    with pytest.raises(ValueError, match="Connection"):
        plan.set_task_state("consumer", state)
    assert plan.task("consumer")["state"] == "NotStarted"


@pytest.mark.parametrize("command", ["set-state", "pin-output"])
def test_every_completion_path_survives_stale_pull(tmp_path, command):
    path = tmp_path / "plan.json"
    plan = Plan.new()
    plan.set_remote_identity(project_id="project", plan_id="plan")
    task = new_task("task", "Complete work")
    task["etag"] = "old-etag"
    plan.add_task(task)
    plan.save_all(path)
    remote = copy.deepcopy(plan.data)
    remote["tasks"][0]["etag"] = "new-etag"
    if command == "set-state":
        args = ["set-state", "--task", "task", "--state", "Completed"]
    else:
        args = ["pin-output", "--task", "task", "--key", "result", "--kind", "Custom", "--attr", "approved=yes", "--complete"]
    assert cli.main(["--plan", str(path), *args]) == 0
    local = Plan.load(path)
    assert local.task("task")["pendingSync"] is True
    merged = Plan(sync.preserve_local_pending(remote, local.data))
    assert merged.task("task")["state"] == "Completed"
    assert merged.task("task")["pendingSync"] is True
    assert merged.task("task")["etag"] == "old-etag"
    assert "awaiting shared confirmation" in merged.render_summary()


def test_remote_completion_without_outputs_is_not_acknowledgment():
    plan = Plan.new()
    plan.set_remote_identity(project_id="project", plan_id="plan")
    plan.add_task(new_task("setup", "Set up", produces=["primaryEnvironment"]))
    plan.add_output(plan_artifact("primaryEnvironment", "Environment", {"environmentId": "env"}, produced_by_task_id="setup"))
    plan.set_task_state("setup", "Completed")
    remote = copy.deepcopy(plan.data)
    remote["tasks"][0].pop("pendingSync")
    remote["outputs"] = []
    merged = Plan(sync.preserve_local_pending(remote, plan.data))
    assert merged.task("setup")["pendingSync"] is True
    assert merged.output("primaryEnvironment") is not None
    confirmed = copy.deepcopy(plan.data)
    confirmed["tasks"][0].pop("pendingSync")
    assert not Plan(sync.preserve_local_pending(confirmed, plan.data)).task("setup").get("pendingSync")


def test_dependent_work_waits_for_shared_metadata_not_just_local_completion():
    local = Plan.new()
    local.set_remote_identity(project_id="project", plan_id="plan")
    local.add_task(new_task("setup", "Prepare environment", produces=["primaryEnvironment"]))
    local.add_task(new_task("connect", "Connect HR", consumes=["primaryEnvironment"]))
    local.add_task(new_task("review", "Review scenarios"))
    local.add_output(plan_artifact(
        "primaryEnvironment", "Environment", {"environmentId": "env-id"}, produced_by_task_id="setup",
    ))
    local.set_task_state("setup", "Completed")
    local.set_task_state("review", "InProgress")
    with pytest.raises(ValueError, match="shared confirmation"):
        local.set_task_state("connect", "InProgress")
    assert local.task_brief("connect")["kitSetup"] is None
    confirmed = copy.deepcopy(local.data)
    confirmed["tasks"][0].pop("pendingSync")
    merged = Plan(sync.preserve_local_pending(confirmed, local.data))
    assert merged.blocking_inputs("connect") == {}
    assert merged.task_brief("connect")["kitSetup"]["environmentId"] == "env-id"
    merged.set_task_state("connect", "InProgress")


def test_retrospective_setup_capture_keeps_offline_evidence_while_sync_is_pending(tmp_path):
    path, config = tmp_path / "plan.json", tmp_path / "config.json"
    plan = Plan.new()
    plan.set_remote_identity(project_id="project", plan_id="plan")
    plan.add_task(new_task("setup", "Prepare environment", produces=["primaryEnvironment"]))
    plan.add_task(new_task("install", "Install ESS", produces=["essAgent"], consumes=["primaryEnvironment"]))
    plan.save_all(path)
    config.write_text(json.dumps({
        "setup": "complete", "environmentId": "env-id",
        "dataverseEndpoint": "https://test.crm.dynamics.com",
        "agent": {"botId": "bot-id", "name": "ESS HR", "schemaName": "test_ess", "slug": "ess"},
    }), encoding="utf-8")
    assert cli.main([
        "--plan", str(path), "capture-setup", "--config", str(config), "--before", "{}", "--complete",
    ]) == 0
    saved = Plan.load(path)
    assert {task["id"] for task in saved.pending_sync_tasks()} == {"setup", "install"}
    assert all(task["state"] == "Completed" for task in saved.tasks)
    assert saved.output("essAgent")["producedByTaskId"] == "install"


def test_sync_queue_orders_upstream_metadata_before_dependent_completions():
    plan = Plan.new()
    plan.set_remote_identity(project_id="project", plan_id="plan")
    plan.add_task(new_task("connect", "Connect HR", consumes=["env"]))
    plan.add_task(new_task("setup", "Prepare environment", produces=["env"]))
    plan.add_output(plan_artifact("env", "Environment", {"environmentId": "env-id"}, produced_by_task_id="setup"))
    plan.set_task_state("setup", "Completed")
    plan.set_task_state("connect", "Completed")
    assert [task["taskId"] for task in sync.pending_sync_payload(plan)["tasks"]] == ["setup", "connect"]


def test_partial_outputs_survive_pull_without_faking_completion():
    plan = Plan.new()
    plan.add_task(new_task("setup", "Set up", produces=["primaryEnvironment", "essAgent"]))
    remote = copy.deepcopy(plan.data)
    plan.add_output(plan_artifact("primaryEnvironment", "Environment", {"environmentId": "env"}, produced_by_task_id="setup"))
    merged = Plan(sync.preserve_local_pending(remote, plan.data))
    assert merged.task("setup")["state"] == "NotStarted"
    assert merged.output("primaryEnvironment") is not None
    assert sync.pending_sync_payload(merged)["tasks"] == []
    assert sync.pending_sync_payload(merged)["pendingOutputs"]


def test_pending_changes_do_not_leak_into_another_plan():
    plan = Plan.new()
    plan.set_remote_identity(project_id="project", plan_id="one")
    plan.add_task(new_task("task", "Do work"))
    plan.set_task_state("task", "Completed")
    other = Plan.new()
    other.set_remote_identity(project_id="project", plan_id="two")
    with pytest.raises(ValueError, match="different shared plan"):
        sync.preserve_local_pending(other.data, plan.data)


def test_first_share_rekeys_pending_completion_and_outputs():
    local = Plan.new()
    local.add_task(new_task("local-task", "Prepare environment", produces=["env"]))
    local.add_output(plan_artifact("env", "Environment", {"environmentId": "env-id"}, produced_by_task_id="local-task"))
    local.set_task_state("local-task", "Completed")
    remote = sync.hydrate_from_remote(
        {"planId": "shared", "projectId": "project"},
        [{"taskId": "remote-task", "title": "Prepare environment", "produces": ["env"], "etag": "created-etag"}],
    )
    merged = Plan(sync.preserve_local_pending(remote, local.data))
    assert len(merged.tasks) == 1
    assert merged.task("remote-task")["pendingSync"]
    assert merged.task("remote-task")["etag"] == "created-etag"
    assert merged.output("env")["producedByTaskId"] == "remote-task"


def test_conflicting_shared_output_requires_review_without_losing_local_result():
    local = Plan.new()
    local.set_remote_identity(project_id="project", plan_id="plan")
    local.add_task(new_task("task", "Record artifact", produces=["result"]))
    local.add_output(plan_artifact(
        "result", "Custom", {"name": "result"}, inventory_ref="local-ref", produced_by_task_id="task",
    ))
    local.set_task_state("task", "Completed")
    remote = copy.deepcopy(local.data)
    remote["tasks"][0].pop("pendingSync")
    remote["outputs"][0]["inventoryRef"] = "other-ref"
    merged = Plan(sync.preserve_local_pending(remote, local.data))
    assert merged.task("task")["pendingSync"]
    assert merged.task("task")["syncConflict"]
    assert "Needs review" in merged.render_summary()
    assert merged.output("result")["inventoryRef"] == "local-ref"
    assert any(output["inventoryRef"] == "other-ref" for output in merged.outputs)


def test_cycles_are_reported_and_markdown_has_stable_task_identity():
    plan = Plan.new()
    plan.add_task(new_task("A", "A", produces=["a"], consumes=["b"]))
    plan.add_task(new_task("B", "B", produces=["b"], consumes=["a"]))
    assert any("dependency cycle" in error for error in plan.validate())
    assert "<!-- task-id: A -->" in plan.render_summary()


def test_url_only_setup_is_saved_as_partial_not_completed(tmp_path, capsys):
    path = tmp_path / "plan.json"
    plan = Plan.new()
    plan.add_task(new_task("setup", "Set up", produces=["primaryEnvironment"]))
    plan.save_all(path)
    assert cli.main([
        "--plan", str(path), "pin-output", "--task", "setup", "--key", "primaryEnvironment",
        "--kind", "Environment", "--attr", "environmentUrl=https://test.crm.dynamics.com",
        "--complete",
    ]) == 1
    saved = Plan.load(path)
    assert saved.output("primaryEnvironment") is not None
    assert saved.task("setup")["state"] == "NotStarted"
    assert saved.task("setup")["pendingOutputs"]
    assert "verify environmentId" in capsys.readouterr().err
    saved.add_task(new_task("connect", "Connect HR", consumes=["primaryEnvironment"]))
    with pytest.raises(ValueError, match="verified environment ID"):
        saved.set_task_state("connect", "InProgress")


def test_setup_handoff_selects_provisioning_not_blocked_workspace_binding(tmp_path, capsys):
    path = tmp_path / "plan.json"
    plan = Plan.new()
    plan.add_task(new_task("bind", "Bind workspace", produces=["primaryEnvironment"], consumes=["provisionedEnvironment", "deployedEssAgent"]))
    plan.add_task(new_task("provision", "Provision environment", produces=["provisionedEnvironment"]))
    plan.save_all(path)
    assert plan.first_run_setup_pending("provision")
    assert not plan.first_run_setup_pending("bind")
    assert cli.main(["--plan", str(path), "setup-status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["firstRunSetupTaskId"] == "provision"
    assert status["agentPinned"] is False


def test_setup_status_reuses_provisioned_environment_before_workspace_binding(tmp_path, capsys):
    path = tmp_path / "plan.json"
    plan = Plan.new()
    plan.add_task(new_task("provision", "Provision environment", produces=["provisionedEnvironment"]))
    plan.add_task(new_task("install", "Install ESS", produces=["deployedEssAgent"], consumes=["provisionedEnvironment"]))
    plan.add_task(new_task("bind", "Bind workspace", produces=["primaryEnvironment"], consumes=["provisionedEnvironment", "deployedEssAgent"]))
    plan.add_output(plan_artifact(
        "provisionedEnvironment", "Environment",
        {"environmentId": "env-id", "environmentUrl": "https://test.crm.dynamics.com"},
        produced_by_task_id="provision",
    ))
    plan.save_all(path)
    assert cli.main(["--plan", str(path), "setup-status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["environmentPinned"] is True
    assert status["environment"]["environmentId"] == "env-id"
    assert status["agentPinned"] is False
    assert status["firstRunSetupTaskId"] is None
    plan.add_output(plan_artifact("deployedEssAgent", "Agent", {"botId": "bot-id"}, produced_by_task_id="install"))
    plan.save_all(path)
    assert cli.main(["--plan", str(path), "setup-status"]) == 0
    assert json.loads(capsys.readouterr().out)["agentPinned"] is True


def test_unshared_completion_can_be_reopened_without_losing_outputs():
    plan = Plan.new()
    plan.add_task(new_task("task", "Work", produces=["result"]))
    plan.add_output(plan_artifact("result", "Custom", {"value": "done"}, produced_by_task_id="task"))
    plan.set_task_state("task", "Completed")
    plan.set_task_state("task", "InProgress")
    assert not plan.task("task").get("pendingSync")
    assert plan.task("task")["pendingOutputs"]
    assert plan.output("result")


def test_import_never_overwrites_corrupt_local_plan(tmp_path, capsys):
    path, remote_path = tmp_path / "plan.json", tmp_path / "remote.json"
    path.write_text("{corrupt", encoding="utf-8")
    remote_path.write_text(json.dumps({"planId": "other", "tasks": []}), encoding="utf-8")
    assert cli.main(["--plan", str(path), "import-remote-plan", "--input", str(remote_path)]) == 1
    assert path.read_text(encoding="utf-8") == "{corrupt"
    assert "refusing to overwrite" in capsys.readouterr().err


@pytest.mark.parametrize("payload", [
    {"error": "plan could not be read"},
    {"plan": {"planId": "shared"}, "tasks": {"error": "tasks could not be read"}},
    {"plan": {"planId": "shared"}, "tasks": [{"title": "Missing identity"}]},
])
def test_invalid_remote_payload_never_erases_local_plan(tmp_path, payload):
    path, remote_path = tmp_path / "plan.json", tmp_path / "remote.json"
    Plan.new(objective="Keep this draft").save_all(path)
    before = path.read_bytes()
    remote_path.write_text(json.dumps(payload), encoding="utf-8")
    assert cli.main(["--plan", str(path), "import-remote-plan", "--input", str(remote_path)]) == 1
    assert path.read_bytes() == before


def test_persisted_evaluation_cases_survive_shared_roundtrip():
    plan = Plan.new(objective="HR profile")
    plan.set_configuring_agent_name("EmployeeSelfServiceHRDA")
    plan.set_context(
        "eval.hr-profile.direct", "Prompt: Show my profile. Expected: Only my supported fields.",
        group="evaluationCase", description="Draft scenario evaluation; not yet executed",
    )
    body = sync.to_remote_plan_body(plan)
    resumed = Plan(sync.hydrate_from_remote({**body, "planId": "shared"}, []))
    case = next(entry for entry in resumed.context if entry["key"] == "eval.hr-profile.direct")
    assert case["group"] == "evaluationCase"
    assert case["value"].startswith("Prompt: Show my profile")
    assert "not yet executed" in case["description"]
