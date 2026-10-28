# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for back-propagation + generic capture: resolved_consumes, task_brief,
the pin-output and task-brief CLI commands. Pure logic + local IO."""

from __future__ import annotations

import json

import pytest

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


def test_first_run_setup_pending_is_the_fre_signal():
    p = _plan()
    # The admin's setup task — not yet run, no env pinned — IS the first-run
    # setup: when they ask "what are my tasks?", nudge them to run /setup now.
    assert p.first_run_setup_pending("T1") is True
    assert p.task_brief("T1")["firstRunSetup"] is True
    # A non-setup task is never the first-run setup (it's the other side of the
    # handshake — kitSetup — once an env exists).
    assert p.first_run_setup_pending("T2") is False
    assert p.task_brief("T2")["firstRunSetup"] is False
    # Once an environment is pinned the env decision is made, so it's no longer
    # the *first* run — even while the setup task is still open (e.g. the ESS
    # agent install was blocked before /setup could finish, yet the environment
    # the maker created was still persisted).
    p.add_output(plan_artifact("primaryEnvironment", "Environment",
                               {"environmentId": "e1", "environmentUrl": "u"},
                               produced_by_task_id="T1"))
    assert p.first_run_setup_pending("T1") is False
    assert p.task_brief("T1")["firstRunSetup"] is False
    # A Completed setup task is never the first-run nudge either.
    p.set_task_state("T1", "Completed")
    assert p.first_run_setup_pending("T1") is False


@pytest.mark.parametrize(("overrides", "needs_binding"), [
    ({}, False),
    ({"setup": "incomplete"}, True),
    ({"environmentId": "other-env"}, True),
    ({"environmentId": None}, True),
    ({"dataverseEndpoint": "https://other.crm.dynamics.com"}, True),
    ({"dataverseEndpoint": " HTTPS://TEST.CRM.DYNAMICS.COM/ "}, False),
    ({"agent": {"botId": "other-bot", "schemaName": "test_ess"}}, True),
    ({"agent": {}}, True),
    ({"agent": None}, True),
    ({"agent": {"botId": "BOT-1", "schemaName": "renamed"}}, False),
])
def test_task_brief_checks_current_workspace_binding(overrides, needs_binding):
    plan = _plan()
    plan.add_output(plan_artifact(
        "primaryEnvironment", "Environment",
        {"environmentId": "env-1", "environmentUrl": "https://test.crm.dynamics.com"},
        produced_by_task_id="T1",
    ))
    plan.add_output(plan_artifact(
        "essAgent", "Agent", {"botId": "bot-1", "schemaName": "test_ess"},
        produced_by_task_id="T1",
    ))
    config = {
        "setup": "complete", "environmentId": "env-1",
        "dataverseEndpoint": "https://test.crm.dynamics.com",
        "agent": {"botId": "bot-1", "schemaName": "test_ess"},
        **overrides,
    }
    brief = plan.task_brief("T2", workspace_config=config)
    assert (brief["kitSetup"] is not None) is needs_binding
    assert brief["blockedBy"] == {}
    assert brief["state"] == "NotStarted"


@pytest.mark.parametrize("state", ["Completed", "Blocked"])
def test_ineligible_task_does_not_prompt_for_workspace_binding(state):
    plan = _plan()
    plan.add_output(plan_artifact(
        "primaryEnvironment", "Environment", {"environmentId": "env"},
        produced_by_task_id="T1",
    ))
    if state == "Completed":
        for key in plan.task("T2")["produces"]:
            plan.add_output(plan_artifact(
                key, "Custom", {"name": key}, produced_by_task_id="T2",
            ))
    plan.set_task_state("T2", state)
    assert plan.task_brief("T2")["kitSetup"] is None


def test_other_missing_inputs_do_not_trigger_workspace_binding():
    plan = _plan()
    plan.add_output(plan_artifact(
        "primaryEnvironment", "Environment", {"environmentId": "env"},
        produced_by_task_id="T1",
    ))
    plan.update_task("T2", consumes=["primaryEnvironment", "tenantConfiguration"])
    brief = plan.task_brief("T2")
    assert brief["blockedBy"] == {"tenantConfiguration": []}
    assert brief["kitSetup"] is None


def test_blocked_setup_is_not_a_ready_first_run_task():
    plan = _plan()
    plan.set_task_state("T1", "Blocked")
    assert plan.task_brief("T1")["firstRunSetup"] is False


def _run(*argv: str) -> int:
    return cli.main(list(argv))


def test_task_has_only_wevenova_fields():
    # A task carries only fields that exist on the WeveNova Task entity — no
    # invented `action` or `roleSource`. The role's Learn provenance lives in the
    # research context, not on the task.
    t = new_task("T1", "Connect Workday",
                 description="Run /connect to connect Workday",
                 assigned_to=principal_pool("integration-owner"),
                 produces=["workdayConnection"], consumes=["primaryEnvironment"])
    assert set(t) == {"id", "title", "description", "assignedTo", "state", "produces", "consumes"}


@pytest.mark.parametrize("environment_key", ["primaryEnvironment", "provisionedEnvironment"])
def test_setup_task_id_is_the_env_producer(environment_key):
    p = Plan.new()
    # A portal "provision" task is NOT the setup task; the task that PRODUCES the
    # environment is.
    p.add_task(new_task("T1", "Provision env",
                        description="In the portal, provision the environment",
                        assigned_to=principal_pool("power-platform-admin")))
    p.add_task(new_task("T2", "Run setup",
                        description="Run /setup to onboard the ADK",
                        assigned_to=principal_pool("power-platform-admin"),
                        produces=[environment_key]))
    assert p.setup_task_id() == "T2"
    assert Plan.new().setup_task_id() is None  # no task produces the env -> None


def test_discover_task_id_is_the_inventory_producer():
    p = Plan.new()
    p.add_task(new_task("T1", "Run setup",
                        description="Run /setup to onboard the ADK",
                        assigned_to=principal_pool("power-platform-admin"),
                        produces=["primaryEnvironment"]))
    # The discover task is the one that PRODUCES the tenant inventory, keyed on the
    # grounded `produces` signal (never on the title/description).
    p.add_task(new_task("T2", "Discover the tenant inventory",
                        description="Run /discover to crawl the environment",
                        assigned_to=principal_pool("power-platform-admin"),
                        produces=["tenantInventory"], consumes=["primaryEnvironment"]))
    assert p.discover_task_id() == "T2"
    assert Plan.new().discover_task_id() is None  # no task produces the inventory -> None


@pytest.mark.parametrize("environment_key", ["primaryEnvironment", "provisionedEnvironment"])
@pytest.mark.parametrize("explicit_task", [False, True])
@pytest.mark.parametrize("explicit_key", [False, True])
def test_capture_setup_uses_produced_environment_key(tmp_path, environment_key, explicit_task, explicit_key):
    plan_path = str(tmp_path / "plan.json")
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"setup": "complete",
                               "dataverseEndpoint": "https://o.crm.dynamics.com",
                               "environmentId": "env-7"}), encoding="utf-8")
    _run("--plan", plan_path, "init")
    _run("--plan", plan_path, "add-task", "--id", "T1", "--title", "Provision env",
         "--description", "In the portal, provision the environment", "--role", "power-platform-admin")
    _run("--plan", plan_path, "add-task", "--id", "T2", "--title", "Run setup",
         "--description", "Run /setup to onboard the ADK", "--role", "power-platform-admin", "--produces", environment_key)
    options = ["--task", "T2"] if explicit_task else []
    if explicit_key:
        options.extend(["--key", environment_key])
    rc = _run("--plan", plan_path, "capture-setup", "--config", str(cfg), "--before", "{}", "--complete", *options)
    assert rc == 0
    p = Plan.load(plan_path)
    assert p.output(environment_key)["attributes"]["environmentId"] == "env-7"
    assert p.output(environment_key)["producedByTaskId"] == "T2"
    other_key = "primaryEnvironment" if environment_key == "provisionedEnvironment" else "provisionedEnvironment"
    assert p.output(other_key) is None
    assert p.task("T2")["state"] == "Completed"
    assert p.task("T1")["state"] == "NotStarted"  # portal task untouched


@pytest.mark.parametrize(("environment_key", "options"), [
    ("provisionedEnvironment", []),
    ("customEnvironment", ["--task", "setup", "--key", "customEnvironment"]),
])
def test_capture_setup_preview_preserves_plan_and_honors_key_override(tmp_path, capsys, environment_key, options):
    path, config = tmp_path / "plan.json", tmp_path / "config.json"
    plan = Plan.new()
    plan.add_task(new_task("setup", "Prepare environment", produces=[environment_key]))
    plan.save_all(path)
    config.write_text(json.dumps({
        "environmentId": "env-id", "dataverseEndpoint": "https://test.crm.dynamics.com",
    }), encoding="utf-8")
    before = path.read_bytes()
    args = ["--plan", str(path), "capture-setup", "--config", str(config), *options]
    assert _run(*args, "--dry-run") == 0
    preview = json.loads(capsys.readouterr().out)
    assert [artifact["key"] for artifact in preview] == [environment_key]
    assert path.read_bytes() == before

    assert _run(*args, "--complete") == 0
    saved = Plan.load(path)
    assert saved.task("setup")["state"] == "Completed"
    assert saved.output(environment_key)["producedByTaskId"] == "setup"
    assert saved.output("primaryEnvironment") is None


def _write_results(path, **overrides):
    results = {
        "correlationId": "run-9",
        "aborted": False,
        "writePath": "mcp:substrate",
        "writeDegraded": False,
        "totals": {"kindsCrawled": 2, "mapped": 3},
        "discovered": {
            "Connection": [{"naturalKey": "c1"}, {"naturalKey": "c2"}],
            "Environment": [{"naturalKey": "e1"}],
        },
    }
    results.update(overrides)
    path.write_text(json.dumps(results), encoding="utf-8")


def test_capture_discover_autodetects_and_pins(tmp_path, capsys):
    plan_path = str(tmp_path / "plan.json")
    results = tmp_path / "results.json"
    _write_results(results)
    _run("--plan", plan_path, "init")
    _run("--plan", plan_path, "add-task", "--id", "T1", "--title", "Run setup",
         "--description", "Run /setup to onboard the ADK", "--role", "power-platform-admin",
         "--produces", "primaryEnvironment")
    _run("--plan", plan_path, "add-task", "--id", "T2", "--title", "Discover the tenant inventory",
         "--description", "Run /discover to crawl the environment", "--role", "power-platform-admin",
         "--produces", "tenantInventory")
    capsys.readouterr()
    # No --task: capture-discover finds T2 (produces tenantInventory), pins the summary, completes it.
    rc = _run("--plan", plan_path, "capture-discover", "--results", str(results), "--complete")
    assert rc == 0
    assert "tenantInventory" in capsys.readouterr().out
    p = Plan.load(plan_path)
    art = p.output("tenantInventory")
    assert art is not None
    assert art["kind"] == "Custom"
    assert art["producedByTaskId"] == "T2"
    assert art["attributes"]["resourceCount"] == 3
    assert p.task("T2")["state"] == "Completed"
    assert p.task("T1")["state"] == "NotStarted"  # setup task untouched


def test_capture_discover_defaults_inventory_path_from_config(tmp_path, capsys):
    # /discover --inventory-out records where it mirrored the inventory in config.json;
    # capture-discover must pin THAT path (not the parser default) so downstream tasks
    # read the real mirror.
    plan_path = str(tmp_path / "plan.json")
    results = tmp_path / "results.json"
    _write_results(results)
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"inventoryPath": "custom/dir/inventory.json"}), encoding="utf-8")
    _run("--plan", plan_path, "init")
    _run("--plan", plan_path, "add-task", "--id", "T2", "--title", "Discover the tenant inventory",
         "--description", "Run /discover", "--role", "power-platform-admin", "--produces", "tenantInventory")
    capsys.readouterr()
    rc = _run("--plan", plan_path, "capture-discover", "--results", str(results),
              "--config", str(cfg), "--complete")
    assert rc == 0
    art = Plan.load(plan_path).output("tenantInventory")
    assert art["attributes"]["inventoryPath"] == "custom/dir/inventory.json"


def test_capture_discover_inventory_path_flag_overrides_config(tmp_path, capsys):
    # An explicit --inventory-path still wins over the config pointer.
    plan_path = str(tmp_path / "plan.json")
    results = tmp_path / "results.json"
    _write_results(results)
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"inventoryPath": "from/config.json"}), encoding="utf-8")
    _run("--plan", plan_path, "init")
    _run("--plan", plan_path, "add-task", "--id", "T2", "--title", "Discover the tenant inventory",
         "--description", "Run /discover", "--role", "power-platform-admin", "--produces", "tenantInventory")
    capsys.readouterr()
    rc = _run("--plan", plan_path, "capture-discover", "--results", str(results),
              "--config", str(cfg), "--inventory-path", "explicit/override.json", "--complete")
    assert rc == 0
    art = Plan.load(plan_path).output("tenantInventory")
    assert art["attributes"]["inventoryPath"] == "explicit/override.json"


def test_capture_discover_no_discover_task_is_noop(tmp_path, capsys):
    # A plan with no tenant-inventory task means this was a standalone /discover run,
    # not part of a tracked rollout -> the skill skips silently on this nonzero rc.
    plan_path = str(tmp_path / "plan.json")
    results = tmp_path / "results.json"
    _write_results(results)
    _run("--plan", plan_path, "init")
    _run("--plan", plan_path, "add-task", "--id", "T1", "--title", "Run setup",
         "--description", "Run /setup", "--role", "power-platform-admin", "--produces", "primaryEnvironment")
    capsys.readouterr()
    rc = _run("--plan", plan_path, "capture-discover", "--results", str(results))
    assert rc == 1
    assert "No discover task" in capsys.readouterr().err
    assert Plan.load(plan_path).output("tenantInventory") is None  # nothing pinned


def test_capture_discover_missing_results_file(tmp_path, capsys):
    plan_path = str(tmp_path / "plan.json")
    _run("--plan", plan_path, "init")
    _run("--plan", plan_path, "add-task", "--id", "T2", "--title", "Discover the tenant inventory",
         "--description", "Run /discover", "--role", "power-platform-admin", "--produces", "tenantInventory")
    capsys.readouterr()
    rc = _run("--plan", plan_path, "capture-discover", "--results", str(tmp_path / "nope.json"))
    assert rc == 1
    assert "Could not read discovery results" in capsys.readouterr().err


def test_capture_discover_aborted_pins_nothing(tmp_path, capsys):
    plan_path = str(tmp_path / "plan.json")
    results = tmp_path / "results.json"
    results.write_text(json.dumps({"aborted": True, "correlationId": "run-x"}), encoding="utf-8")
    _run("--plan", plan_path, "init")
    _run("--plan", plan_path, "add-task", "--id", "T2", "--title", "Discover the tenant inventory",
         "--description", "Run /discover", "--role", "power-platform-admin", "--produces", "tenantInventory")
    capsys.readouterr()
    rc = _run("--plan", plan_path, "capture-discover", "--results", str(results), "--complete")
    assert rc == 1
    assert "aborted" in capsys.readouterr().err.lower()
    p = Plan.load(plan_path)
    assert p.output("tenantInventory") is None
    assert p.task("T2")["state"] != "Completed"  # stays open


def test_capture_discover_dry_run_saves_nothing(tmp_path, capsys):
    plan_path = str(tmp_path / "plan.json")
    results = tmp_path / "results.json"
    _write_results(results)
    _run("--plan", plan_path, "init")
    _run("--plan", plan_path, "add-task", "--id", "T2", "--title", "Discover the tenant inventory",
         "--description", "Run /discover", "--role", "power-platform-admin", "--produces", "tenantInventory")
    capsys.readouterr()
    rc = _run("--plan", plan_path, "capture-discover", "--results", str(results), "--dry-run")
    assert rc == 0
    assert "[dry-run]" in capsys.readouterr().err
    assert Plan.load(plan_path).output("tenantInventory") is None  # nothing pinned


def _plan_with_completed_discover(tmp_path, capsys):
    """init + a discover task + capture-discover --complete, leaving T2 Completed
    and flagged pendingSync (not yet on the shared plan). Returns the plan path."""
    plan_path = str(tmp_path / "plan.json")
    results = tmp_path / "results.json"
    _write_results(results)
    _run("--plan", plan_path, "init")
    _run("--plan", plan_path, "add-task", "--id", "T2", "--title", "Discover the tenant inventory",
         "--description", "Run /discover", "--role", "power-platform-admin", "--produces", "tenantInventory")
    capsys.readouterr()
    rc = _run("--plan", plan_path, "capture-discover", "--results", str(results), "--complete")
    assert rc == 0
    return plan_path


def test_capture_discover_complete_flags_pending_and_prompts_sync(tmp_path, capsys):
    plan_path = _plan_with_completed_discover(tmp_path, capsys)
    err = capsys.readouterr().err
    assert "Progress saved locally" in err
    assert "not been shared" in err
    assert "Syncing progress to the shared plan" not in err
    plan = Plan.load(plan_path)
    assert plan.task("T2")["state"] == "Completed"
    assert plan.task("T2")["pendingSync"] is True


def test_cli_pending_sync_lists_backlog(tmp_path, capsys):
    plan_path = _plan_with_completed_discover(tmp_path, capsys)
    capsys.readouterr()
    assert _run("--plan", plan_path, "pending-sync") == 0
    payload = json.loads(capsys.readouterr().out)
    assert [t["localId"] for t in payload["tasks"]] == ["T2"]
    assert payload["tasks"][0]["outputs"][0]["key"] == "tenantInventory"


def test_cli_mark_synced_clears_flag(tmp_path, capsys):
    plan_path = _plan_with_completed_discover(tmp_path, capsys)
    capsys.readouterr()
    assert _run("--plan", plan_path, "mark-synced", "--task", "T2") == 0
    assert "pendingSync" not in Plan.load(plan_path).task("T2")
    # Backlog is now empty.
    capsys.readouterr()
    _run("--plan", plan_path, "pending-sync")
    assert json.loads(capsys.readouterr().out)["tasks"] == []


def test_cli_mark_synced_all_clears_everything(tmp_path, capsys):
    plan_path = _plan_with_completed_discover(tmp_path, capsys)
    capsys.readouterr()
    assert _run("--plan", plan_path, "mark-synced", "--all") == 0
    assert Plan.load(plan_path).pending_sync_tasks() == []


def test_cli_import_remote_plan_preserves_unpushed_completion(tmp_path, capsys):
    plan_path = _plan_with_completed_discover(tmp_path, capsys)
    local = Plan.load(plan_path)
    local.set_remote_identity(project_id="proj-1", plan_id="plan-1")
    local.save_all(plan_path)
    capsys.readouterr()
    # The service still shows the discover task NotStarted (the completion never
    # reached it). A plain pull would revert it; import must preserve it.
    remote = {
        "plan": {
            "planId": "plan-1", "projectId": "proj-1",
            "configuringAgentName": "EmployeeSelfServiceHRDA",
            "status": "Active", "outputs": [],
        },
        "tasks": {"value": [
            {"taskId": "T2", "title": "Discover the tenant inventory",
             "state": "NotStarted", "produces": ["tenantInventory"],
             "assignedTo": {"type": "Role", "id": "EntraPowerPlatformAdministrator"}},
        ]},
    }
    input_file = tmp_path / "remote.json"
    input_file.write_text(json.dumps(remote), encoding="utf-8")

    assert _run("--plan", plan_path, "import-remote-plan", "--input", str(input_file)) == 0
    err = capsys.readouterr().err
    assert "Preserved unpushed local completion(s): T2" in err
    plan = Plan.load(plan_path)
    assert plan.task("T2")["state"] == "Completed"
    assert plan.task("T2")["pendingSync"] is True
    # The produced inventory artifact is carried forward so the Completed task resolves.
    assert plan.output("tenantInventory") is not None


def test_cli_import_remote_plan_clears_pending_when_service_confirms(tmp_path, capsys):
    plan_path = _plan_with_completed_discover(tmp_path, capsys)
    local = Plan.load(plan_path)
    local.set_remote_identity(project_id="proj-1", plan_id="plan-1")
    local.save_all(plan_path)
    capsys.readouterr()
    from planner.sync import to_remote_output

    confirmed_output = {
        **to_remote_output(Plan.load(plan_path).output("tenantInventory")),
        "producedByTaskId": "T2", "state": "Active",
    }
    # The service now agrees the task is Completed (the push landed) -> flag clears.
    remote = {
        "plan": {
            "planId": "plan-1", "projectId": "proj-1",
            "configuringAgentName": "EmployeeSelfServiceHRDA",
            "status": "Active",
            "outputs": [confirmed_output],
        },
        "tasks": {"value": [
            {"taskId": "T2", "title": "Discover the tenant inventory",
             "state": "Completed", "produces": ["tenantInventory"],
             "assignedTo": {"type": "Role", "id": "EntraPowerPlatformAdministrator"}},
        ]},
    }
    input_file = tmp_path / "remote.json"
    input_file.write_text(json.dumps(remote), encoding="utf-8")

    assert _run("--plan", plan_path, "import-remote-plan", "--input", str(input_file)) == 0
    plan = Plan.load(plan_path)
    assert plan.task("T2")["state"] == "Completed"
    assert "pendingSync" not in plan.task("T2")


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


def test_cli_task_brief_nudges_first_run_setup(tmp_path, capsys):
    plan_path = str(tmp_path / "plan.json")
    _run("--plan", plan_path, "init")
    # The admin's setup task, still open, with no environment pinned yet.
    _run("--plan", plan_path, "add-task", "--id", "T1", "--title", "Run setup",
         "--description", "Run /setup to onboard the ADK to the deployed agent",
         "--role", "power-platform-admin", "--produces", "primaryEnvironment")
    capsys.readouterr()
    rc = _run("--plan", plan_path, "task-brief", "--task", "T1")
    assert rc == 0
    out = capsys.readouterr().out
    assert "First-run setup" in out   # the FRE nudge fires for the open setup task
    assert "/setup" in out            # tells them exactly what to run now


def test_task_brief_blocked_when_consumed_not_produced(tmp_path, capsys):
    plan_path = str(tmp_path / "plan.json")
    _run("--plan", plan_path, "init")
    _run("--plan", plan_path, "add-task", "--id", "T2", "--title", "Connect Workday", "--description", "Run /connect to connect Workday", "--role", "integration-owner", "--consumes", "primaryEnvironment")
    capsys.readouterr()
    _run("--plan", plan_path, "task-brief", "--task", "T2")
    assert "not produced yet" in capsys.readouterr().out


def test_cli_task_brief_uses_workspace_binding_without_mutating_plan(tmp_path, capsys):
    path, config_path = tmp_path / "plan.json", tmp_path / "config.json"
    plan = _plan()
    plan.add_output(plan_artifact(
        "primaryEnvironment", "Environment",
        {"environmentId": "env", "environmentUrl": "https://test.crm.dynamics.com"},
        produced_by_task_id="T1",
    ))
    plan.save_all(path)
    config_path.write_text(json.dumps({
        "setup": "complete", "environmentId": "env",
        "dataverseEndpoint": "https://test.crm.dynamics.com",
    }), encoding="utf-8")
    before = path.read_bytes()
    assert _run("--plan", str(path), "task-brief", "--task", "T2", "--config", str(config_path)) == 0
    output = capsys.readouterr().out
    assert "Run /connect" in output
    assert "First connect your kit" not in output
    assert path.read_bytes() == before


def test_cli_task_brief_missing_config_needs_binding_but_corrupt_config_fails(tmp_path, capsys):
    path, config_path = tmp_path / "plan.json", tmp_path / "config.json"
    plan = _plan()
    plan.add_output(plan_artifact(
        "primaryEnvironment", "Environment", {"environmentId": "env"},
        produced_by_task_id="T1",
    ))
    plan.save_all(path)
    args = ["--plan", str(path), "task-brief", "--task", "T2", "--config", str(config_path), "--json"]
    assert _run(*args) == 0
    assert json.loads(capsys.readouterr().out)["kitSetup"]["environmentId"] == "env"
    config_path.write_text("{broken", encoding="utf-8")
    assert _run(*args) == 1
    assert "invalid JSON" in capsys.readouterr().err
