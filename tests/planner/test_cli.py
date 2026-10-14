# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Integration tests for planner.cli — drives main(argv) on a temp plan.

Pure local IO (no network), so exempt from the FlightCheck cassette policy.
"""

from __future__ import annotations

import json

from planner import cli
from planner.plan_model import Plan, plan_artifact

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


def test_remove_context_moves_a_scenario_out_of_scope(tmp_path):
    plan_path = str(tmp_path / "plan.json")
    _run("--plan", plan_path, "init")
    _run("--plan", plan_path, "add-scenario", "--id", "hr-ticketing", "--label", "HR ticketing")
    assert "hr-ticketing" in Plan.load(plan_path).in_scope_scenarios()
    assert _run("--plan", plan_path, "remove-context", "--key", "hr-ticketing") == 0
    assert "hr-ticketing" not in Plan.load(plan_path).in_scope_scenarios()
    # A mistyped / unknown key fails loudly.
    assert _run("--plan", plan_path, "remove-context", "--key", "nope") == 1


def test_check_deps_flags_and_clears_a_dangling_consume(tmp_path, capsys):
    plan_path = str(tmp_path / "plan.json")
    _run("--plan", plan_path, "init")
    # A task consumes a key nothing on the plan produces (e.g. after a bad edit).
    _run("--plan", plan_path, "add-task", "--id", "T1", "--title", "Author HR topic",
         "--role", "knowledge-admin", "--consumes", "workdayConnection")
    rc = _run("--plan", plan_path, "check-deps")
    out = capsys.readouterr().out
    assert rc == 1
    assert "Task-graph gaps" in out
    assert "workdayConnection" in out
    # Re-adding the producer makes the graph coherent again.
    _run("--plan", plan_path, "add-task", "--id", "T2", "--title", "Connect Workday",
         "--role", "integration-owner", "--produces", "workdayConnection")
    capsys.readouterr()
    rc = _run("--plan", plan_path, "check-deps")
    assert rc == 0
    assert "Task graph is coherent" in capsys.readouterr().out


def test_full_flow(tmp_path, capsys):
    plan_path = str(tmp_path / "plan.json")
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "setup": "complete",
                "dataverseEndpoint": "https://org123.crm.dynamics.com",
                "environmentId": "d3f10000-0000-1111-2222-333344445555",
                "agent": {"botId": "bot-9", "name": "ESS Agent", "schemaName": "ess_agent", "slug": "ess"},
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
    # /setup also clones the agent -> pinned as an Agent artifact on the same task.
    agent = plan.output("essAgent")
    assert agent is not None
    assert agent["kind"] == "Agent"
    assert agent["attributes"]["botId"] == "bot-9"
    assert agent["producedByTaskId"] == "T1"

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
    assert "No new id/name artifacts" in capsys.readouterr().err


def test_capture_setup_dry_run_saves_nothing(tmp_path, capsys):
    plan_path = str(tmp_path / "plan.json")
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"setup": "complete", "dataverseEndpoint": "https://o.crm.dynamics.com", "environmentId": "e-1"}),
        encoding="utf-8",
    )
    _run("--plan", plan_path, "init")
    _run("--plan", plan_path, "add-task", "--id", "T1", "--title", "setup", "--description", "Run /setup",
         "--role", "power-platform-admin", "--produces", "primaryEnvironment")
    capsys.readouterr()
    rc = _run("--plan", plan_path, "capture-setup", "--task", "T1", "--config", str(config_path), "--dry-run")
    assert rc == 0
    assert "[dry-run]" in capsys.readouterr().err
    assert Plan.load(plan_path).output("primaryEnvironment") is None  # nothing pinned


def test_capture_setup_completes_every_task_the_run_produced(tmp_path, capsys):
    """A single /setup run records the environment AND clones the agent, so
    `capture-setup --complete` must close BOTH the environment task and the
    base-agent task when the plan splits them — not just the triggered one."""
    plan_path = str(tmp_path / "plan.json")
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({
            "setup": "complete",
            "dataverseEndpoint": "https://org.crm.dynamics.com",
            "environmentId": "env-123",
            "agent": {"botId": "bot-9", "name": "ESS Agent", "schemaName": "ess_agent", "slug": "ess"},
        }),
        encoding="utf-8",
    )
    _run("--plan", plan_path, "init")
    _run("--plan", plan_path, "add-task", "--id", "T1", "--title", "Set up the environment",
         "--description", "Onboard the ADK (run /setup)", "--role", "power-platform-admin",
         "--produces", "primaryEnvironment")
    _run("--plan", plan_path, "add-task", "--id", "T2", "--title", "Install the base agent",
         "--description", "Clone the ESS base agent", "--role", "env-maker",
         "--produces", "essAgent", "--consumes", "primaryEnvironment")
    capsys.readouterr()

    rc = _run("--plan", plan_path, "capture-setup", "--task", "T1",
              "--config", str(config_path), "--before", "{}", "--complete")
    assert rc == 0
    err = capsys.readouterr().err
    assert "Also completed" in err and "T2" in err  # the base-agent task, same run

    plan = Plan.load(plan_path)
    assert plan.task("T1")["state"] == "Completed"   # the triggered task
    assert plan.task("T2")["state"] == "Completed"   # closed by the same /setup run
    # The base-agent artifact is attributed to the task that OWNS it (T2), not the
    # setup task that happened to capture it — so removing the setup task later
    # cannot cascade-delete the output T2 depends on.
    assert plan.output("essAgent")["producedByTaskId"] == "T2"
    plan.remove_task("T1")
    assert plan.output("essAgent") is not None          # survives T1 removal
    assert plan.unresolved_produces("T2") == []          # T2 stays legitimately done


def test_capture_setup_only_completes_tasks_fully_produced_this_run(tmp_path, capsys):
    """A split task whose outputs were only PARTLY produced by this run stays open:
    an earlier run satisfying the rest must not let one freshly pinned key close it."""
    plan_path = str(tmp_path / "plan.json")
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({
            "setup": "complete",
            "dataverseEndpoint": "https://org.crm.dynamics.com",
            "environmentId": "env-123",
            "agent": {"botId": "bot-9", "name": "ESS Agent", "schemaName": "ess_agent", "slug": "ess"},
        }),
        encoding="utf-8",
    )
    _run("--plan", plan_path, "init")
    _run("--plan", plan_path, "add-task", "--id", "T1", "--title", "Set up the environment",
         "--description", "Onboard the ADK (run /setup)", "--role", "power-platform-admin",
         "--produces", "primaryEnvironment")
    # T2 needs BOTH essAgent (pinned this run) AND evalSuite (produced earlier).
    _run("--plan", plan_path, "add-task", "--id", "T2", "--title", "Install the base agent",
         "--description", "Clone the ESS base agent", "--role", "env-maker",
         "--produces", "essAgent,evalSuite", "--consumes", "primaryEnvironment")
    # Pin evalSuite from an EARLIER run, so unresolved_produces(T2) would be empty.
    plan = Plan.load(plan_path)
    plan.add_output(plan_artifact("evalSuite", "Custom", {"id": "s"}, produced_by_task_id="T2"))
    plan.save(plan_path)
    capsys.readouterr()

    rc = _run("--plan", plan_path, "capture-setup", "--task", "T1",
              "--config", str(config_path), "--before", "{}", "--complete")
    assert rc == 0

    plan = Plan.load(plan_path)
    assert plan.task("T1")["state"] == "Completed"
    # This run produced essAgent but NOT evalSuite, so it must not close T2.
    assert plan.task("T2")["state"] != "Completed"


def test_capture_setup_leaves_unrelated_tasks_open(tmp_path, capsys):
    """The cascade is scoped to what the run produced: a task whose `produces`
    the run did NOT satisfy stays open."""
    plan_path = str(tmp_path / "plan.json")
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({
            "setup": "complete",
            "dataverseEndpoint": "https://org.crm.dynamics.com",
            "environmentId": "env-123",
            "agent": {"botId": "bot-9", "name": "ESS Agent", "schemaName": "ess_agent", "slug": "ess"},
        }),
        encoding="utf-8",
    )
    _run("--plan", plan_path, "init")
    _run("--plan", plan_path, "add-task", "--id", "T1", "--title", "Set up the environment",
         "--description", "Onboard the ADK (run /setup)", "--role", "power-platform-admin",
         "--produces", "primaryEnvironment")
    _run("--plan", plan_path, "add-task", "--id", "T9", "--title", "Connect Workday",
         "--description", "Run /connect", "--role", "env-maker",
         "--produces", "workdayConnection", "--consumes", "primaryEnvironment")
    capsys.readouterr()

    rc = _run("--plan", plan_path, "capture-setup", "--task", "T1",
              "--config", str(config_path), "--before", "{}", "--complete")
    assert rc == 0

    plan = Plan.load(plan_path)
    assert plan.task("T1")["state"] == "Completed"
    assert plan.task("T9")["state"] != "Completed"   # /setup didn't produce workdayConnection


def test_summary_is_read_only(tmp_path):
    plan_path = str(tmp_path / "plan.json")
    _run("--plan", plan_path, "init")
    md = tmp_path / "ESS-scenario-plan.md"
    md.write_text("MY UNRECONCILED EDITS", encoding="utf-8")
    _run("--plan", plan_path, "summary")
    assert md.read_text(encoding="utf-8") == "MY UNRECONCILED EDITS"  # summary didn't clobber


def test_summary_emits_task_checklist_readback(tmp_path, capsys):
    plan_path = str(tmp_path / "plan.json")
    _run("--plan", plan_path, "init")
    _run("--plan", plan_path, "add-task", "--id", "T1", "--title", "Connect Workday",
         "--role", "workday-admin", "--stream", "Workday")
    capsys.readouterr()
    _run("--plan", plan_path, "summary")
    err = capsys.readouterr().err
    # The assistant gets a deterministic, grouped checklist to echo verbatim after
    # the download link — so it renders the breakdown instead of a bare task count.
    assert "readback:" in err
    assert "**Workday**" in err
    assert "- ⬜ Connect Workday — workday-admin" in err
    # The role is named, but the internal "pool" notion never leaks to the maker.
    assert "workday-admin (pool)" not in err


def test_pin_output_rejects_malformed_attr(tmp_path, capsys):
    plan_path = str(tmp_path / "plan.json")
    _run("--plan", plan_path, "init")
    _run("--plan", plan_path, "add-task", "--id", "T1", "--title", "t", "--role", "maker")
    capsys.readouterr()
    rc = _run("--plan", plan_path, "pin-output", "--task", "T1", "--key", "k", "--kind", "Custom", "--attr", "connectionId", "--complete")
    assert rc == 1
    assert "Invalid --attr" in capsys.readouterr().err
    assert Plan.load(plan_path).task("T1")["state"] != "Completed"  # not completed on error


def test_complete_refused_with_unresolved_produces(tmp_path, capsys):
    plan_path = str(tmp_path / "plan.json")
    _run("--plan", plan_path, "init")
    _run("--plan", plan_path, "add-task", "--id", "T1", "--title", "t", "--role", "maker", "--produces", "a,b")
    capsys.readouterr()
    rc = _run("--plan", plan_path, "pin-output", "--task", "T1", "--key", "a", "--kind", "Custom", "--attr", "x=1", "--complete")
    assert rc == 1
    assert "unresolved produces" in capsys.readouterr().err
    assert Plan.load(plan_path).task("T1")["state"] != "Completed"


def test_set_state_completed_refused_with_unresolved_produces(tmp_path, capsys):
    # The invariant is enforced in the model, so the direct `set-state --state
    # Completed` path (not just capture/pin) is guarded too.
    plan_path = str(tmp_path / "plan.json")
    _run("--plan", plan_path, "init")
    _run("--plan", plan_path, "add-task", "--id", "T1", "--title", "t", "--role", "maker", "--produces", "primaryEnvironment")
    capsys.readouterr()
    rc = _run("--plan", plan_path, "set-state", "--task", "T1", "--state", "Completed")
    assert rc == 1
    assert "unresolved produces" in capsys.readouterr().err
    assert Plan.load(plan_path).task("T1")["state"] != "Completed"


def test_set_state_completed_flags_pending_sync(tmp_path, capsys):
    # A completion applied via the direct `set-state` path (an edit.md checkbox tick
    # or a "mark it done" chat intent) is a local-not-yet-pushed completion, so it
    # lands on the push backlog exactly like a capture `--complete` — otherwise an
    # edit-driven completion on a shared plan could never reach the service.
    plan_path = str(tmp_path / "plan.json")
    _run("--plan", plan_path, "init")
    _run("--plan", plan_path, "add-task", "--id", "T1", "--title", "Approve scope", "--role", "maker")
    capsys.readouterr()
    assert _run("--plan", plan_path, "set-state", "--task", "T1", "--state", "Completed") == 0
    task = Plan.load(plan_path).task("T1")
    assert task["state"] == "Completed"
    assert task["pendingSync"] is True
    # It surfaces in the push backlog the agent reconciles on the next sync.
    capsys.readouterr()
    assert _run("--plan", plan_path, "pending-sync") == 0
    assert [t["localId"] for t in json.loads(capsys.readouterr().out)["tasks"]] == ["T1"]


def test_set_state_non_completed_does_not_flag_pending_sync(tmp_path):
    # Only a genuine transition *into* Completed is a pending push; other states
    # (and re-stating Completed) never touch the backlog.
    plan_path = str(tmp_path / "plan.json")
    _run("--plan", plan_path, "init")
    _run("--plan", plan_path, "add-task", "--id", "T1", "--title", "Approve scope", "--role", "maker")
    assert _run("--plan", plan_path, "set-state", "--task", "T1", "--state", "InProgress") == 0
    assert "pendingSync" not in Plan.load(plan_path).task("T1")


# --- setup-status: the read-only guard shared by the /setup env-reuse offer and
# --- the planner first-run-setup reconcile -------------------------------------

def _setup_status(plan_path: str, capsys) -> dict:
    """Run `setup-status` and return its parsed JSON (always exit 0 — a query)."""
    capsys.readouterr()  # drain any prior command output so .out is just the JSON
    assert _run("--plan", plan_path, "setup-status") == 0
    return json.loads(capsys.readouterr().out)


def test_setup_status_no_plan_is_safe_noop(tmp_path, capsys):
    # A standalone caller (no plan yet) gets a well-formed "nothing here" status,
    # not an error — so /setup and the planner can read it unconditionally.
    status = _setup_status(str(tmp_path / "nope.json"), capsys)
    assert status == {
        "hasPlan": False,
        "setupTaskId": None,
        "setupTaskState": None,
        "setupTaskOpen": False,
        "environmentPinned": False,
        "environment": None,
    }


def test_setup_status_reports_open_setup_task(tmp_path, capsys):
    # The admin's setup task exists but hasn't been captured yet -> the planner
    # reconcile guard must fire (setupTaskOpen) and /setup has no env to offer.
    plan_path = str(tmp_path / "plan.json")
    _run("--plan", plan_path, "init")
    _run("--plan", plan_path, "add-task", "--id", "T1", "--title", "Set up the environment",
         "--description", "Run /setup to onboard the ADK", "--role", "power-platform-admin",
         "--produces", "primaryEnvironment")
    status = _setup_status(plan_path, capsys)
    assert status["hasPlan"] is True
    assert status["setupTaskId"] == "T1"
    assert status["setupTaskState"] == "NotStarted"
    assert status["setupTaskOpen"] is True        # reconcile should run
    assert status["environmentPinned"] is False   # nothing to offer yet
    assert status["environment"] is None


def test_setup_status_after_capture_is_closed_and_offers_env(tmp_path, capsys):
    # Once the setup run is captured the task is Completed and the environment is
    # pinned: the planner reconcile must now SKIP (idempotent — setupTaskOpen
    # false, no re-pin churn) and /setup can offer the pinned environment.
    plan_path = str(tmp_path / "plan.json")
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"setup": "complete",
                    "dataverseEndpoint": "https://org.crm.dynamics.com",
                    "environmentId": "env-123"}),
        encoding="utf-8",
    )
    _run("--plan", plan_path, "init")
    _run("--plan", plan_path, "add-task", "--id", "T1", "--title", "Set up the environment",
         "--description", "Run /setup to onboard the ADK", "--role", "power-platform-admin",
         "--produces", "primaryEnvironment")
    _run("--plan", plan_path, "capture-setup", "--task", "T1", "--config", str(config_path),
         "--before", "{}", "--complete")
    capsys.readouterr()  # drain capture output

    status = _setup_status(plan_path, capsys)
    assert status["setupTaskState"] == "Completed"
    assert status["setupTaskOpen"] is False       # reconcile skips -> no re-pin churn
    assert status["environmentPinned"] is True
    assert status["environment"]["environmentId"] == "env-123"
    assert status["environment"]["environmentUrl"] == "https://org.crm.dynamics.com"


def test_setup_status_plan_without_setup_task(tmp_path, capsys):
    # A plan that doesn't model a setup task at all: no id, nothing open, nothing
    # to offer — the guard reads false on every axis without erroring.
    plan_path = str(tmp_path / "plan.json")
    _run("--plan", plan_path, "init")
    _run("--plan", plan_path, "add-task", "--id", "T9", "--title", "Connect Workday",
         "--role", "env-maker", "--produces", "workdayConnection")
    status = _setup_status(plan_path, capsys)
    assert status["hasPlan"] is True
    assert status["setupTaskId"] is None
    assert status["setupTaskState"] is None
    assert status["setupTaskOpen"] is False
    assert status["environmentPinned"] is False
    assert status["environment"] is None


def test_setup_status_environment_without_url_is_not_reusable(tmp_path, capsys):
    # An Environment artifact can carry only an environmentId and no org URL
    # (e.g. a plan synced from the planner service). The reuse path would feed an
    # empty ENV_URL, so setup-status must NOT advertise it as reusable even though
    # an environment output exists on the plan.
    plan_path = str(tmp_path / "plan.json")
    _run("--plan", plan_path, "init")
    _run("--plan", plan_path, "add-task", "--id", "T1", "--title", "Set up the environment",
         "--role", "power-platform-admin", "--produces", "primaryEnvironment")
    _run("--plan", plan_path, "pin-output", "--task", "T1", "--key", "primaryEnvironment",
         "--kind", "Environment", "--attr", "environmentId=env-only")
    status = _setup_status(plan_path, capsys)
    assert status["environmentPinned"] is False            # no URL -> not reusable
    assert status["environment"]["environmentId"] == "env-only"
    assert status["environment"]["environmentUrl"] == ""   # nothing to offer


def test_setup_status_is_read_only(tmp_path):
    # The guard is a pure read: it must never rewrite the plan or regenerate (and
    # thereby clobber) the editable Markdown view.
    plan_path = str(tmp_path / "plan.json")
    _run("--plan", plan_path, "init")
    md = tmp_path / "ESS-scenario-plan.md"
    md.write_text("MY UNRECONCILED EDITS", encoding="utf-8")
    assert _run("--plan", plan_path, "setup-status") == 0
    assert md.read_text(encoding="utf-8") == "MY UNRECONCILED EDITS"


def test_save_refuses_invalid_plan_orphan_artifact(tmp_path, capsys):
    plan_path = str(tmp_path / "plan.json")
    _run("--plan", plan_path, "init")
    _run("--plan", plan_path, "add-task", "--id", "T1", "--title", "t", "--role", "maker")
    capsys.readouterr()
    rc = _run("--plan", plan_path, "pin-output", "--task", "TX", "--key", "k", "--kind", "Custom", "--attr", "x=1")
    assert rc == 1
    assert "unknown task" in capsys.readouterr().err.lower()
    assert Plan.load(plan_path).output("k") is None  # nothing persisted


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
