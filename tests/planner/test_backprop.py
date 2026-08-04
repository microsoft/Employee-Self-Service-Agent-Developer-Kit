# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for back-propagation + generic capture: resolved_consumes, task_brief,
the pin-output and task-brief CLI commands. Pure logic + local IO."""

from __future__ import annotations

import json

from planner import cli
from planner.plan_model import (
    Plan,
    action_kit_skill,
    new_task,
    plan_artifact,
    principal_pool,
)


def _plan() -> Plan:
    p = Plan.new()
    p.add_task(new_task("T1", "setup", action=action_kit_skill("onboarding"),
                        assigned_to=principal_pool("power-platform-admin"),
                        produces=["primaryEnvironment"]))
    p.add_task(new_task("T2", "Connect Workday", action=action_kit_skill("connect"),
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
    assert b["action"]["skill"] == "connect"
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
    # A non-kit task (portal/manual) is never nudged, even with an env pinned.
    from planner.plan_model import action_portal
    p.add_task(new_task("T3", "Publish", action=action_portal("https://doc"),
                        assigned_to=principal_pool("power-platform-admin")))
    assert p.kit_setup_nudge("T3") is None
    # task_brief surfaces the nudge for the connect task.
    assert p.task_brief("T2")["kitSetup"] == {"environmentId": "e1", "environmentUrl": "u"}


def _run(*argv: str) -> int:
    return cli.main(list(argv))


def test_cli_pin_output_commits_artifact(tmp_path, capsys):
    plan_path = str(tmp_path / "plan.json")
    _run("--plan", plan_path, "init")
    _run("--plan", plan_path, "add-task", "--id", "T2", "--title", "Connect Workday",
         "--skill", "connect", "--role", "integration-owner", "--produces", "workdayConnection")
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
    _run("--plan", plan_path, "add-task", "--id", "T1", "--title", "setup", "--skill", "onboarding", "--role", "power-platform-admin", "--produces", "primaryEnvironment")
    _run("--plan", plan_path, "add-task", "--id", "T2", "--title", "Connect Workday", "--skill", "connect", "--role", "integration-owner", "--produces", "workdayConnection", "--consumes", "primaryEnvironment")
    _run("--plan", plan_path, "capture-setup", "--task", "T1", "--config", str(cfg), "--before", "{}", "--complete")
    capsys.readouterr()
    rc = _run("--plan", plan_path, "task-brief", "--task", "T2")
    assert rc == 0
    out = capsys.readouterr().out
    assert "/connect" in out             # which skill to run
    assert "env-9" in out                # the env id back-propagated from setup
    assert "/setup" in out               # nudged to connect their kit to the plan env
    assert "integration-owner" in out    # role
    assert "workdayConnection" in out    # what to capture


def test_task_brief_blocked_when_consumed_not_produced(tmp_path, capsys):
    plan_path = str(tmp_path / "plan.json")
    _run("--plan", plan_path, "init")
    _run("--plan", plan_path, "add-task", "--id", "T2", "--title", "Connect Workday", "--skill", "connect", "--role", "integration-owner", "--consumes", "primaryEnvironment")
    capsys.readouterr()
    _run("--plan", plan_path, "task-brief", "--task", "T2")
    assert "not produced yet" in capsys.readouterr().out
