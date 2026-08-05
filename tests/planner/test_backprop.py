# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for back-propagation + generic capture: resolved_consumes, task_brief,
the pin-output and task-brief CLI commands. Pure logic + local IO."""

from __future__ import annotations

import json

from planner import cli
from planner.plan_model import (
    Plan,
    new_task,
    plan_artifact,
    principal_pool,
)


def _plan() -> Plan:
    p = Plan.new()
    p.add_task(new_task("T1", "Run setup",
                        description="Run /setup to onboard the ADK to the deployed agent",
                        assigned_to=principal_pool("power-platform-admin"),
                        produces=["primaryEnvironment"]))
    p.add_task(new_task("T2", "Connect Workday",
                        description="Run /connect to connect Workday to the ESS agent",
                        assigned_to=principal_pool("integration-owner"),
                        produces=["workdayConnection", "workdayEntraApp"],
                        consumes=["primaryEnvironment"]))
    return p


def test_resolved_consumes_none_then_value():
    p = _plan()
    assert p.resolved_consumes("T2") == {"primaryEnvironment": None}
    p.add_output(plan_artifact("primaryEnvironment", "Environment", {"environmentId": "e1"}, produced_by_task_id="T1"))
    assert p.resolved_consumes("T2") == {"primaryEnvironment": {"environmentId": "e1"}}


def test_task_brief_shape():
    p = _plan()
    p.add_output(plan_artifact("primaryEnvironment", "Environment", {"environmentId": "e1", "environmentUrl": "u"}, produced_by_task_id="T1"))
    b = p.task_brief("T2")
    assert b["id"] == "T2"
    assert b["title"] == "Connect Workday"
    assert "action" not in b  # brief is described by title/description, not action
    assert b["role"] == "integration-owner"
    assert b["consumes"]["primaryEnvironment"]["environmentId"] == "e1"
    assert b["produces"] == ["workdayConnection", "workdayEntraApp"]


def test_kit_setup_nudge_is_plan_env_driven():
    p = _plan()
    # No env pinned yet -> no nudge (the admin's setup task is the prerequisite).
    assert p.kit_setup_nudge("T2") is None
    # Pin the env -> the connect assignee is nudged to /setup into THAT env.
    p.add_output(plan_artifact("primaryEnvironment", "Environment",
                               {"environmentId": "e1", "environmentUrl": "u"}, produced_by_task_id="T1"))
    assert p.kit_setup_nudge("T2") == {"environmentId": "e1", "environmentUrl": "u"}
    # The setup task itself is never nudged.
    assert p.kit_setup_nudge("T1") is None
    # A task that doesn't consume the environment is never nudged, even with an
    # env pinned.
    p.add_task(new_task("T3", "Publish the agent",
                        description="In the Power Platform admin center, publish the agent",
                        assigned_to=principal_pool("power-platform-admin")))
    assert p.kit_setup_nudge("T3") is None
    # task_brief surfaces the nudge for the connect task.
    assert p.task_brief("T2")["kitSetup"] == {"environmentId": "e1", "environmentUrl": "u"}


def _run(*argv: str) -> int:
    return cli.main(list(argv))


def test_role_source_is_recorded_and_briefed(tmp_path, capsys):
    # new_task stores the Learn URL that grounded the role...
    t = new_task("T9", "Connect Workday",
                 description="Run /connect to connect Workday to the ESS agent",
                 assigned_to=principal_pool("integration-owner"),
                 role_source="https://learn.microsoft.com/.../workday")
    assert t["roleSource"] == "https://learn.microsoft.com/.../workday"
    p = Plan.new()
    p.add_task(t)
    assert p.task_brief("T9")["roleSource"] == "https://learn.microsoft.com/.../workday"

    # ...and the add-task CLI + task-brief surface it.
    plan_path = str(tmp_path / "plan.json")
    _run("--plan", plan_path, "init")
    _run("--plan", plan_path, "add-task", "--id", "T1", "--title", "Connect Workday",
         "--description", "Run /connect to connect Workday", "--role", "integration-owner",
         "--role-source", "https://learn.microsoft.com/ess/workday")
    capsys.readouterr()
    _run("--plan", plan_path, "task-brief", "--task", "T1")
    out = capsys.readouterr().out
    assert "Role grounded in: https://learn.microsoft.com/ess/workday" in out


def test_role_source_absent_by_default():
    t = new_task("T1", "x", assigned_to=principal_pool("maker"))
    assert "roleSource" not in t  # only present when grounded from Learn


def test_setup_task_id_is_the_env_producer():
    p = Plan.new()
    # A portal "provision" task is NOT the setup task; the task that PRODUCES the
    # environment is.
    p.add_task(new_task("T1", "Provision env",
                        description="In the portal, provision the environment",
                        assigned_to=principal_pool("power-platform-admin")))
    p.add_task(new_task("T2", "Run setup",
                        description="Run /setup to onboard the ADK",
                        assigned_to=principal_pool("power-platform-admin"),
                        produces=["primaryEnvironment"]))
    assert p.setup_task_id() == "T2"
    assert Plan.new().setup_task_id() is None  # no task produces the env -> None


def test_capture_setup_autodetects_setup_task(tmp_path):
    plan_path = str(tmp_path / "plan.json")
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"setup": "complete",
                               "dataverseEndpoint": "https://o.crm.dynamics.com",
                               "environmentId": "env-7"}), encoding="utf-8")
    _run("--plan", plan_path, "init")
    _run("--plan", plan_path, "add-task", "--id", "T1", "--title", "Provision env",
         "--description", "In the portal, provision the environment", "--role", "power-platform-admin")
    _run("--plan", plan_path, "add-task", "--id", "T2", "--title", "Run setup",
         "--description", "Run /setup to onboard the ADK", "--role", "power-platform-admin", "--produces", "primaryEnvironment")
    # No --task: capture-setup finds the plan's setup task (T2 produces the env), pins env, completes it.
    rc = _run("--plan", plan_path, "capture-setup", "--config", str(cfg), "--before", "{}", "--complete")
    assert rc == 0
    p = Plan.load(plan_path)
    assert p.output("primaryEnvironment")["attributes"]["environmentId"] == "env-7"
    assert p.task("T2")["state"] == "Completed"
    assert p.task("T1")["state"] == "NotStarted"  # portal task untouched


def test_cli_pin_output_commits_artifact(tmp_path, capsys):
    plan_path = str(tmp_path / "plan.json")
    _run("--plan", plan_path, "init")
    _run("--plan", plan_path, "add-task", "--id", "T2", "--title", "Connect Workday",
         "--description", "Run /connect to connect Workday", "--role", "integration-owner", "--produces", "workdayConnection")
    capsys.readouterr()
    rc = _run("--plan", plan_path, "pin-output", "--task", "T2", "--key", "workdayConnection",
              "--kind", "Connection", "--attr", "connectionId=wd-1",
              "--attr", "connector=shared_workdaysoap", "--complete")
    assert rc == 0
    assert "wd-1" in capsys.readouterr().out
    p = Plan.load(plan_path)
    art = p.output("workdayConnection")
    assert art["attributes"]["connectionId"] == "wd-1"
    assert art["provenance"]["source"] == "User"  # assignee supplied it
    assert p.task("T2")["state"] == "Completed"


def test_cli_task_brief_shows_env_and_steps(tmp_path, capsys):
    plan_path = str(tmp_path / "plan.json")
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"setup": "complete", "dataverseEndpoint": "https://o.crm.dynamics.com", "environmentId": "env-9"}), encoding="utf-8")
    _run("--plan", plan_path, "init")
    # New pattern: title + description carry the "how" (no --skill/action field);
    # setup detection is via --produces primaryEnvironment.
    _run("--plan", plan_path, "add-task", "--id", "T1", "--title", "Run setup",
         "--description", "Run /setup to onboard the ADK to the deployed agent",
         "--role", "power-platform-admin", "--produces", "primaryEnvironment")
    _run("--plan", plan_path, "add-task", "--id", "T2", "--title", "Connect Workday",
         "--description", "Run /connect to connect Workday to the ESS agent",
         "--role", "integration-owner", "--produces", "workdayConnection", "--consumes", "primaryEnvironment")
    _run("--plan", plan_path, "capture-setup", "--config", str(cfg), "--before", "{}", "--complete")
    capsys.readouterr()
    rc = _run("--plan", plan_path, "task-brief", "--task", "T2")
    assert rc == 0
    out = capsys.readouterr().out
    assert "/connect" in out             # which command to run (from the description)
    assert "env-9" in out                # the env id back-propagated from setup
    assert "/setup" in out               # nudged to connect their kit to the plan env
    assert "integration-owner" in out    # role
    assert "workdayConnection" in out    # what to capture

    # The task carries no `action` field — it's described by title + description.
    p = Plan.load(plan_path)
    assert "action" not in p.task("T2")


def test_task_brief_blocked_when_consumed_not_produced(tmp_path, capsys):
    plan_path = str(tmp_path / "plan.json")
    _run("--plan", plan_path, "init")
    _run("--plan", plan_path, "add-task", "--id", "T2", "--title", "Connect Workday", "--description", "Run /connect to connect Workday", "--role", "integration-owner", "--consumes", "primaryEnvironment")
    capsys.readouterr()
    _run("--plan", plan_path, "task-brief", "--task", "T2")
    assert "not produced yet" in capsys.readouterr().out
