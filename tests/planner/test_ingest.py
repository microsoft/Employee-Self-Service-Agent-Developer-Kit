# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the uploaded-plan path — Plan.ingest_upload / Plan.missing_slots
and the ``ingest-upload`` / ``gaps`` CLI commands.

A maker attaches a plan in their own shape; the skill parses it into the
normalized payload and this seam does the atomic, validated write plus a gap
report so the skill asks only for what is missing. Pure logic + local file IO
(no network), so exempt from the FlightCheck cassette policy per tests/AGENTS.md.
"""

from __future__ import annotations

import json

import pytest

from planner import cli
from planner.plan_model import (
    Plan,
    assignee_role_id,
    assignee_user_oid,
)

PAUL = "00000000-0000-0000-0000-0000000000b1"


def _run(*argv: str) -> int:
    return cli.main(list(argv))


def _full_payload() -> dict:
    """A complete uploaded plan — objective, four scenarios each backed by a
    system, a dependency, and two tasks — mirroring workspace/plan."""
    return {
        "objective": "Help India-based employees get HR answers and act on them",
        "market": "India",
        "persona": "Employees",
        "jtbd": ["Find HR policy", "Update my profile", "Raise an HR ticket"],
        "businessGoals": ["Deflect 30% of HR tickets"],
        "acceptanceCriteria": ["Pilot-ready for India HR"],
        "scenarios": [
            {"id": "hr-knowledge", "label": "HR knowledge", "system": "SharePoint",
             "capabilities": ["HR policy lookup"]},
            {"id": "hr-profile-read", "label": "Read my profile", "system": "Workday",
             "capabilities": ["Read profile"]},
            {"id": "hr-profile-write", "label": "Update my profile", "system": "Workday",
             "capabilities": ["Write profile"]},
            {"id": "hr-ticketing", "label": "HR ticketing", "system": "ServiceNow HRSD",
             "capabilities": ["Create ticket"]},
        ],
        "scenarioDependencies": [
            {"scenario": "hr-profile-write", "dependsOn": "hr-profile-read",
             "kind": "requires", "rationale": "Must read before write"},
        ],
        "tasks": [
            {"id": "setup-env", "title": "Run environment setup",
             "role": "EntraPowerPlatformAdministrator", "produces": ["primaryEnvironment"]},
            {"id": "author-knowledge", "title": "Author HR knowledge source",
             "stream": "content", "consumes": ["primaryEnvironment"]},
        ],
    }


# ---- model: ingest_upload -------------------------------------------------- #

def test_ingest_upload_populates_every_section():
    plan = Plan.new()
    counts = plan.ingest_upload(_full_payload())

    assert counts["objective"] == 1
    assert counts["scenarios"] == 4
    # One system per scenario.
    assert counts["systems"] == 4
    assert counts["capabilities"] == 4
    assert counts["scenarioDependencies"] == 1
    assert counts["tasks"] == 2

    assert plan.output_value_or_context("objective").startswith("Help India-based")
    assert set(plan.in_scope_scenarios()) == {
        "hr-knowledge", "hr-profile-read", "hr-profile-write", "hr-ticketing",
    }
    # The plan is persistable straight after ingest.
    assert plan.validate() == []


def test_ingest_upload_untrusted_values_land_as_context():
    plan = Plan.new()
    plan.ingest_upload(_full_payload())
    groups = {e.get("group") for e in plan.context}
    # Objective, market, audience, goals, DoD, scenarios, systems, capabilities,
    # and the dependency all persist as ordinary Context entries (data, never
    # instructions).
    assert {"objective", "market", "scenarioContext", "businessGoals",
            "acceptanceCriteria", "scenario", "system", "scenarioCapability",
            "scenarioDependsOn"} <= groups


def test_ingest_upload_assigns_task_role_and_scalars_coerce():
    plan = Plan.new()
    # jtbd + businessGoals given as scalars, not lists.
    plan.ingest_upload({
        "objective": "Do ESS",
        "jtbd": "Just one job",
        "businessGoals": "Only goal",
        "scenarios": [{"id": "hr-ticketing", "system": "ServiceNow"}],
        "tasks": [{"id": "T1", "title": "Setup", "person": PAUL,
                   "role": "EntraPowerPlatformAdministrator"}],
    })
    task = next(t for t in plan.tasks if t["id"] == "T1")
    assert assignee_user_oid(task["assignedTo"]) == PAUL
    assert assignee_role_id(task["assignedTo"]) == "EntraPowerPlatformAdministrator"
    # A scalar jtbd/businessGoal still lands.
    assert plan.validate() == []


def test_ingest_upload_scenario_without_id_raises():
    plan = Plan.new()
    with pytest.raises(ValueError):
        plan.ingest_upload({"scenarios": [{"label": "no id here"}]})


def test_ingest_upload_task_without_title_raises():
    plan = Plan.new()
    with pytest.raises(ValueError):
        plan.ingest_upload({"tasks": [{"id": "T1"}]})


# ---- model: missing_slots -------------------------------------------------- #

def test_missing_slots_full_plan_has_no_required_gaps():
    plan = Plan.new()
    plan.ingest_upload(_full_payload())
    gaps = plan.missing_slots()
    assert gaps["required"] == []
    # Everything recommended was supplied too.
    assert gaps["recommended"] == []


def test_missing_slots_flags_missing_objective_and_system():
    plan = Plan.new()
    # No objective; one scenario with no backing system.
    plan.ingest_upload({"scenarios": [{"id": "hr-ticketing", "label": "HR ticketing"}]})
    gaps = plan.missing_slots()
    required = {g["slot"] for g in gaps["required"]}
    assert "objective" in required
    assert "system:hr-ticketing" in required
    recommended = {g["slot"] for g in gaps["recommended"]}
    assert "capabilities:hr-ticketing" in recommended
    assert {"persona", "market", "businessGoals", "acceptanceCriteria"} <= recommended
    # Every gap carries a ready-to-ask prompt.
    assert all(g["prompt"] for g in gaps["required"] + gaps["recommended"])


def test_missing_slots_no_scenarios_flags_scenarios():
    plan = Plan.new(objective="Do ESS")
    gaps = plan.missing_slots()
    required = {g["slot"] for g in gaps["required"]}
    assert "scenarios" in required
    assert "objective" not in required


def test_missing_slots_is_read_only_and_shrinks():
    plan = Plan.new()
    plan.ingest_upload({"scenarios": [{"id": "hr-ticketing", "label": "HR ticketing"}]})
    before = len(plan.missing_slots()["required"])
    # Filling the missing system removes exactly that gap; re-running sees fewer.
    plan.set_system("hr-ticketing", "ServiceNow HRSD")
    after = {g["slot"] for g in plan.missing_slots()["required"]}
    assert "system:hr-ticketing" not in after
    assert len(after) < before


# ---- CLI: ingest-upload + gaps -------------------------------------------- #

def test_cli_ingest_upload_writes_plan_and_reports_gaps(tmp_path, capsys):
    plan_path = str(tmp_path / "plan.json")
    payload = _full_payload()
    # Drop hr-ticketing's system to force a required gap.
    payload["scenarios"][3].pop("system")
    upload = tmp_path / "upload.json"
    upload.write_text(json.dumps(payload), encoding="utf-8")

    rc = _run("--plan", plan_path, "ingest-upload", "--input", str(upload))
    assert rc == 0
    out = capsys.readouterr().out
    assert "Ingested the uploaded plan" in out
    assert "system:hr-ticketing" in out  # the gap is surfaced for the skill

    plan = Plan.load(plan_path)
    assert plan.output_value_or_context("objective").startswith("Help India-based")
    assert (tmp_path / "ESS-scenario-plan.md").exists()


def test_cli_ingest_upload_refuses_overwrite_without_force(tmp_path, capsys):
    plan_path = str(tmp_path / "plan.json")
    upload = tmp_path / "upload.json"
    upload.write_text(json.dumps(_full_payload()), encoding="utf-8")

    assert _run("--plan", plan_path, "ingest-upload", "--input", str(upload)) == 0
    rc = _run("--plan", plan_path, "ingest-upload", "--input", str(upload))
    assert rc == 1
    assert "already exists" in capsys.readouterr().err


def test_cli_ingest_upload_force_replaces(tmp_path):
    plan_path = str(tmp_path / "plan.json")
    upload = tmp_path / "upload.json"
    upload.write_text(json.dumps(_full_payload()), encoding="utf-8")
    _run("--plan", plan_path, "ingest-upload", "--input", str(upload))

    smaller = {"objective": "Replaced", "scenarios": [{"id": "hr-knowledge", "system": "SharePoint"}]}
    upload.write_text(json.dumps(smaller), encoding="utf-8")
    assert _run("--plan", plan_path, "ingest-upload", "--input", str(upload), "--force") == 0
    plan = Plan.load(plan_path)
    assert plan.output_value_or_context("objective") == "Replaced"
    assert set(plan.in_scope_scenarios()) == {"hr-knowledge"}


def test_cli_ingest_upload_json_output(tmp_path, capsys):
    plan_path = str(tmp_path / "plan.json")
    payload = _full_payload()
    payload["scenarios"][3].pop("system")
    upload = tmp_path / "upload.json"
    upload.write_text(json.dumps(payload), encoding="utf-8")

    rc = _run("--plan", plan_path, "ingest-upload", "--input", str(upload), "--json")
    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["ingested"]["scenarios"] == 4
    assert any(g["slot"] == "system:hr-ticketing" for g in doc["gaps"]["required"])


def test_cli_ingest_upload_bad_json_fails_cleanly(tmp_path, capsys):
    plan_path = str(tmp_path / "plan.json")
    upload = tmp_path / "upload.json"
    upload.write_text("not json at all", encoding="utf-8")
    rc = _run("--plan", plan_path, "ingest-upload", "--input", str(upload))
    assert rc == 1
    assert "Could not read the uploaded plan" in capsys.readouterr().err


def test_cli_gaps_lists_missing_slots(tmp_path, capsys):
    plan_path = str(tmp_path / "plan.json")
    _run("--plan", plan_path, "init")  # empty plan: objective + scenarios missing
    capsys.readouterr()  # drop init's stdout so only the gaps JSON remains
    rc = _run("--plan", plan_path, "gaps", "--json")
    assert rc == 0
    gaps = json.loads(capsys.readouterr().out)
    required = {g["slot"] for g in gaps["required"]}
    assert {"objective", "scenarios"} <= required
