# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Integration tests for planner.cli — drives main(argv) on a temp plan.

Pure local IO (no network), so exempt from the FlightCheck cassette policy.
"""

from __future__ import annotations

import json

import pytest

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


def test_summary_is_read_only(tmp_path):
    plan_path = str(tmp_path / "plan.json")
    _run("--plan", plan_path, "init")
    md = tmp_path / "ESS-scenario-plan.md"
    md.write_text("MY UNRECONCILED EDITS", encoding="utf-8")
    _run("--plan", plan_path, "summary")
    assert md.read_text(encoding="utf-8") == "MY UNRECONCILED EDITS"  # summary didn't clobber


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


# --- init --store mcp: create-or-reuse the WeveNova plan (Bug 1) ------------- #

class _FakeMcpStore:
    """Stand-in for the McpPlanStore `open_or_create_mcp_plan` returns, so the
    cli branch can be tested without a live WeveNova server."""

    def __init__(self, summary_path: str, plan_id: str) -> None:
        self.summary_path = summary_path
        self.plan_id = plan_id
        self.warnings: list[str] = []

    def load(self) -> Plan:
        return Plan.new(objective="Deploy ESS in Bangalore")


def test_init_mcp_creates_first_plan(tmp_path, monkeypatch, capsys):
    import planner.plan_store as ps

    summary = str(tmp_path / "ESS-scenario-plan.md")
    seen: dict = {}

    def fake_open(**kwargs):
        seen.update(kwargs)
        return _FakeMcpStore(summary, "new-plan-123"), True

    monkeypatch.setattr(ps, "open_or_create_mcp_plan", fake_open)
    rc = _run("--plan", str(tmp_path / "plan.json"), "--store", "mcp",
              "init", "--objective", "Deploy ESS in Bangalore")
    assert rc == 0
    out = capsys.readouterr().out
    assert "Created a new WeveNova project plan" in out
    assert "new-plan-123" in out
    # The objective flows through to the create call, and the .md is rendered.
    assert seen["objective"] == "Deploy ESS in Bangalore"
    assert (tmp_path / "ESS-scenario-plan.md").exists()


def test_init_mcp_reuses_existing_plan(tmp_path, monkeypatch, capsys):
    import planner.plan_store as ps

    summary = str(tmp_path / "ESS-scenario-plan.md")
    monkeypatch.setattr(
        ps, "open_or_create_mcp_plan",
        lambda **k: (_FakeMcpStore(summary, "existing-plan-999"), False),
    )
    rc = _run("--plan", str(tmp_path / "plan.json"), "--store", "mcp", "init")
    assert rc == 0
    out = capsys.readouterr().out
    assert "Using the existing WeveNova project plan" in out
    assert "existing-plan-999" in out


# --- push: bulk local -> WeveNova in one pass ------------------------------- #

class _FakePushStore:
    """Captures the plan handed to a bulk push (stands in for McpPlanStore)."""

    def __init__(self, plan_id: str) -> None:
        self.plan_id = plan_id
        self.cache_path = None
        self.saved: Plan | None = None
        self.warnings: list[str] = []

    def save(self, plan: Plan) -> list[str]:
        self.saved = plan
        return []


def _seed_local_plan(tmp_path) -> str:
    """A valid local plan.json with an objective + one context entry."""
    plan_path = str(tmp_path / "plan.json")
    assert _run("--plan", plan_path, "init", "--objective", "Deploy ESS in Bangalore") == 0
    assert _run("--plan", plan_path, "set-context", "--key", "persona",
                "--value", "Employees only", "--group", "scenarioContext") == 0
    return plan_path


def test_push_creates_and_pushes_full_plan(tmp_path, monkeypatch, capsys):
    import planner.plan_store as ps

    plan_path = _seed_local_plan(tmp_path)
    store = _FakePushStore("plan-abc")
    seen: dict = {}

    def fake_open(**kwargs):
        seen.update(kwargs)
        return store, True

    monkeypatch.setattr(ps, "open_or_create_mcp_plan", fake_open)
    rc = _run("--plan", plan_path, "--store", "mcp", "push")
    out = capsys.readouterr().out
    assert rc == 0
    assert "Created and pushed the plan to WeveNova" in out
    assert "plan-abc" in out
    # the whole local plan is handed to a single save (bulk push); objective seeded
    assert seen["objective"] == "Deploy ESS in Bangalore"
    assert seen["mcp_cache"] is False              # local cache untouched until past the guard
    assert store.cache_path == plan_path           # post-push mirror re-points at plan.json
    assert store.saved is not None
    assert any(c.get("key") == "persona" for c in store.saved.context)


def test_push_refuses_existing_plan_without_force(tmp_path, monkeypatch):
    import planner.plan_store as ps

    plan_path = _seed_local_plan(tmp_path)
    monkeypatch.setattr(ps, "open_or_create_mcp_plan",
                        lambda **k: (_FakePushStore("plan-xyz"), False))
    with pytest.raises(SystemExit) as exc:
        _run("--plan", plan_path, "--store", "mcp", "push")
    assert "already exists" in str(exc.value)
    assert "--force" in str(exc.value)


def test_push_over_existing_plan_with_force(tmp_path, monkeypatch, capsys):
    import planner.plan_store as ps

    plan_path = _seed_local_plan(tmp_path)
    store = _FakePushStore("plan-xyz")
    monkeypatch.setattr(ps, "open_or_create_mcp_plan", lambda **k: (store, False))
    rc = _run("--plan", plan_path, "--store", "mcp", "push", "--force")
    out = capsys.readouterr().out
    assert rc == 0
    assert "Pushed the plan to WeveNova" in out
    assert store.saved is not None


def test_push_without_local_plan_errors(tmp_path):
    with pytest.raises(SystemExit) as exc:
        _run("--plan", str(tmp_path / "missing.json"), "--store", "mcp", "push")
    assert "no local plan" in str(exc.value)
