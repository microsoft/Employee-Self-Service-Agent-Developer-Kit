# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Integration tests for planner.cli — drives main(argv) on a temp plan.

Pure local IO (no network), so exempt from the FlightCheck cassette policy.
"""

from __future__ import annotations

import json

from planner import cli
from planner.plan_model import Plan

PAUL = "00000000-0000-0000-0000-0000000000b1"


def _run(*argv: str) -> int:
    return cli.main(list(argv))


def test_init_creates_plan(tmp_path):
    plan_path = str(tmp_path / "plan.json")
    assert _run("--plan", plan_path, "init", "--objective", "Do ESS") == 0
    plan = Plan.load(plan_path)
    assert plan.output_value_or_context("objective") == "Do ESS"
    assert (tmp_path / "ESS-scenario-plan.md").exists()


def test_init_refuses_overwrite_without_force(tmp_path, capsys):
    plan_path = str(tmp_path / "plan.json")
    _run("--plan", plan_path, "init")
    rc = _run("--plan", plan_path, "init")
    assert rc == 1
    assert "already exists" in capsys.readouterr().err


def test_add_system_uses_scoped_keys(tmp_path):
    plan_path = str(tmp_path / "plan.json")
    _run("--plan", plan_path, "init")
    assert _run("--plan", plan_path, "add-system", "--area", "hr-knowledge", "--system", "SharePoint") == 0
    assert _run("--plan", plan_path, "add-system", "--area", "hr-ticketing", "--system", "ServiceNow HRSD") == 0
    plan = Plan.load(plan_path)
    systems = {e["key"]: e["value"] for e in plan.context if e.get("group") == "system"}
    # Two systems coexist — no collision on a single reused key.
    assert systems == {
        "system.hr-knowledge": "SharePoint",
        "system.hr-ticketing": "ServiceNow HRSD",
    }


def test_update_and_remove_task_roundtrip(tmp_path):
    plan_path = str(tmp_path / "plan.json")
    _run("--plan", plan_path, "init")
    _run("--plan", plan_path, "add-task", "--id", "T1", "--title", "Run setup",
         "--role", "power-platform-admin", "--produces", "primaryEnvironment")
    # Reconcile an edit: retitle + new description + extra produced key.
    assert _run("--plan", plan_path, "update-task", "--id", "T1",
                "--title", "Run setup (revised)", "--description", "new how-to",
                "--produces", "primaryEnvironment,extra") == 0
    plan = Plan.load(plan_path)
    t = plan.task("T1")
    assert t["title"] == "Run setup (revised)"
    assert t["description"] == "new how-to"
    assert t["produces"] == ["primaryEnvironment", "extra"]
    # Reconcile a deletion.
    assert _run("--plan", plan_path, "remove-task", "--id", "T1") == 0
    assert Plan.load(plan_path).task("T1") is None


def test_full_flow(tmp_path, capsys):
    plan_path = str(tmp_path / "plan.json")
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "setup": "complete",
                "dataverseEndpoint": "https://org123.crm.dynamics.com",
                "environmentId": "d3f10000-0000-1111-2222-333344445555",
            }
        ),
        encoding="utf-8",
    )

    assert _run("--plan", plan_path, "init", "--objective", "ESS HR ticketing") == 0
    assert _run("--plan", plan_path, "set-context", "--key", "market", "--value", "DE", "--group", "market") == 0
    assert _run(
        "--plan", plan_path, "add-task",
        "--id", "T1", "--title", "Create env & setup",
        "--description", "Run /setup to onboard the ADK to the deployed agent",
        "--role", "power-platform-admin",
        "--produces", "primaryEnvironment",
    ) == 0
    assert _run(
        "--plan", plan_path, "add-task",
        "--id", "T5", "--title", "Publish the agent",
        "--description", "In the Power Platform admin center, publish the agent",
        "--role", "power-platform-admin",
    ) == 0
    # Flow 1: assign a person to the grounded role.
    assert _run("--plan", plan_path, "assign", "--task", "T1", "--role", "power-platform-admin", "--person", PAUL) == 0
    capsys.readouterr()  # drain

    # Capture the /setup -> environmentId hand-off (observe mode).
    rc = _run(
        "--plan", plan_path, "capture-setup",
        "--task", "T1", "--config", str(config_path), "--before", "{}", "--complete",
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "d3f10000-0000-1111-2222-333344445555" in out

    plan = Plan.load(plan_path)
    assert plan.task("T1")["state"] == "Completed"
    assert plan.output("primaryEnvironment")["attributes"]["environmentId"] == "d3f10000-0000-1111-2222-333344445555"

    # Validate is clean.
    assert _run("--plan", plan_path, "validate") == 0


def test_capture_setup_no_change_returns_nonzero(tmp_path, capsys):
    plan_path = str(tmp_path / "plan.json")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"setup": "pending"}), encoding="utf-8")
    _run("--plan", plan_path, "init")
    _run("--plan", plan_path, "add-task", "--id", "T1", "--title", "setup", "--description", "Run /setup to onboard the ADK")
    capsys.readouterr()
    rc = _run("--plan", plan_path, "capture-setup", "--task", "T1", "--config", str(config_path), "--before", "{}")
    assert rc == 1
    assert "No environment change" in capsys.readouterr().err


def test_mine_json_output(tmp_path, capsys):
    plan_path = str(tmp_path / "plan.json")
    _run("--plan", plan_path, "init")
    _run("--plan", plan_path, "add-task", "--id", "T1", "--title", "Connect", "--description", "Run /connect to connect Workday", "--role", "integration-owner")
    capsys.readouterr()
    rc = _run("--plan", plan_path, "mine", "--person", PAUL, "--roles", "integration-owner", "--json")
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert "integration-owner" in data
    assert data["integration-owner"][0]["task"]["id"] == "T1"


def test_research_from_toc_file(tmp_path, capsys):
    toc_path = tmp_path / "toc.json"
    toc_path.write_text(
        json.dumps(
            {
                "items": [
                    {"href": "overview", "toc_title": "Overview"},
                    {"href": "workday", "toc_title": "Workday"},
                    {"href": "sapsuccessfactors", "toc_title": "SAP"},
                ]
            }
        ),
        encoding="utf-8",
    )
    rc = _run("--plan", str(tmp_path / "plan.json"), "research", "--tokens", "workday", "--toc", str(toc_path), "--budget", "5")
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    selected = {s["href"] for s in data["selected"]}
    assert "workday" in selected
    assert "overview" in selected  # always-include backbone
    assert "sapsuccessfactors" not in selected


def test_validate_reports_problems(tmp_path, capsys):
    plan_path = tmp_path / "plan.json"
    # Hand-write a plan with a duplicate context key.
    plan = Plan.new()
    plan.context.append({"key": "dup", "value": "1", "group": "", "description": "", "provenance": {"source": "User"}})
    plan.context.append({"key": "dup", "value": "2", "group": "", "description": "", "provenance": {"source": "User"}})
    plan.save(plan_path)
    rc = _run("--plan", str(plan_path), "validate")
    assert rc == 1
    assert "not unique" in capsys.readouterr().err
