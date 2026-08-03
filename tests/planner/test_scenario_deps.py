# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for scenario dependencies — modelled in the open Context bag.

Scenario dependency is not a new typed collection: a scenario in scope is a
Context entry (group 'scenario'), and a dependency edge is a Context entry
(group 'scenarioDependsOn') whose key encodes "A -> B" and whose scalar value
is the kind. Pure logic; exempt from the cassette policy.
"""

from __future__ import annotations

import json

import pytest

from planner import cli
from planner.plan_model import (
    DEPENDS_ON_GROUP,
    SCENARIO_GROUP,
    Plan,
    context_entry,
    dependency_key,
    known_scenario_dependencies,
    parse_dependency_key,
)


def _plan_with_ticketing() -> Plan:
    plan = Plan.new()
    plan.set_context("hr-ticketing", "HR ticketing", group=SCENARIO_GROUP)
    return plan


# --------------------------------------------------------------------------- #
# Edge encoding + storage (it's just Context entries)
# --------------------------------------------------------------------------- #

def test_dependency_key_round_trips():
    key = dependency_key("hr-ticketing", "hr-knowledge")
    assert parse_dependency_key(key) == ("hr-ticketing", "hr-knowledge")


def test_add_scenario_dependency_is_stored_as_context_entry():
    plan = _plan_with_ticketing()
    plan.add_scenario_dependency(
        "hr-ticketing", "hr-knowledge", kind="requires", rationale="PM spec"
    )
    # No new top-level collection — it's a Context entry in the DEPENDS_ON_GROUP.
    assert "scenarioDependencies" not in plan.data
    dep_entries = [e for e in plan.context if e.get("group") == DEPENDS_ON_GROUP]
    assert len(dep_entries) == 1
    assert dep_entries[0]["value"] == "requires"

    edges = plan.scenario_dependencies()
    assert edges[0]["scenario"] == "hr-ticketing"
    assert edges[0]["dependsOn"] == "hr-knowledge"
    assert edges[0]["kind"] == "requires"
    assert edges[0]["rationale"] == "PM spec"


def test_add_scenario_dependency_dedupes():
    plan = _plan_with_ticketing()
    plan.add_scenario_dependency("hr-ticketing", "hr-knowledge", kind="requires")
    plan.add_scenario_dependency("hr-ticketing", "hr-knowledge", kind="recommends")
    edges = plan.scenario_dependencies()
    assert len(edges) == 1
    assert edges[0]["kind"] == "recommends"  # overwritten in place


def test_add_scenario_dependency_rejects_self_and_bad_kind():
    plan = _plan_with_ticketing()
    with pytest.raises(ValueError):
        plan.add_scenario_dependency("hr-ticketing", "hr-ticketing")
    with pytest.raises(ValueError):
        plan.add_scenario_dependency("hr-ticketing", "hr-knowledge", kind="bogus")


def test_round_trip_through_disk(tmp_path):
    plan = _plan_with_ticketing()
    plan.add_scenario_dependency("hr-ticketing", "hr-knowledge", rationale="x")
    path = tmp_path / "plan.json"
    plan.save(path)
    reloaded = Plan.load(path)
    assert reloaded.scenario_dependencies() == plan.scenario_dependencies()


# --------------------------------------------------------------------------- #
# In-scope scenarios + unmet detection (exposed to the sponsor)
# --------------------------------------------------------------------------- #

def test_in_scope_scenarios_reads_group():
    plan = _plan_with_ticketing()
    plan.set_context("hr-knowledge", "HR knowledge", group=SCENARIO_GROUP)
    assert plan.in_scope_scenarios() == {
        "hr-ticketing": "HR ticketing",
        "hr-knowledge": "HR knowledge",
    }


def test_known_dependency_is_seeded():
    edges = known_scenario_dependencies()
    assert {"scenario": "hr-ticketing", "dependsOn": "hr-knowledge"}.items() <= edges[0].items()
    assert edges[0]["kind"] == "requires"
    # Sourced honestly from the facts file — NOT attributed to the PM spec.
    assert edges[0]["source"] and "spec" not in edges[0]["source"].lower()
    assert "deflect" in edges[0]["rationale"].lower()


def test_unmet_surfaces_known_knowledge_before_ticketing():
    # Ticketing in scope, knowledge NOT -> the known edge is surfaced as unmet.
    plan = _plan_with_ticketing()
    unmet = plan.unmet_scenario_dependencies()
    assert len(unmet) == 1
    assert unmet[0]["scenario"] == "hr-ticketing"
    assert unmet[0]["dependsOn"] == "hr-knowledge"
    assert "deflect" in unmet[0]["rationale"].lower()


def test_unmet_clears_when_prerequisite_added():
    plan = _plan_with_ticketing()
    plan.set_context("hr-knowledge", "HR knowledge", group=SCENARIO_GROUP)
    assert plan.unmet_scenario_dependencies() == []


def test_unmet_ignores_known_when_dependent_not_in_scope():
    # Neither scenario in scope beyond a stray one -> nothing to advise.
    plan = Plan.new()
    plan.set_context("something-else", "x", group=SCENARIO_GROUP)
    assert plan.unmet_scenario_dependencies() == []


# --------------------------------------------------------------------------- #
# Validation + rendering
# --------------------------------------------------------------------------- #

def test_validate_flags_invalid_dependency_kind():
    plan = _plan_with_ticketing()
    plan.context.append(context_entry("hr-ticketing -> hr-knowledge", "someday", group=DEPENDS_ON_GROUP))
    assert any("invalid kind" in e for e in plan.validate())


def test_validate_flags_malformed_dependency_key():
    plan = _plan_with_ticketing()
    plan.context.append(context_entry("noarrowhere", "requires", group=DEPENDS_ON_GROUP))
    assert any("malformed" in e for e in plan.validate())


def test_summary_shows_missing_dependency():
    plan = _plan_with_ticketing()  # knowledge not in scope
    summary = plan.render_summary()
    assert "## Scenario dependencies" in summary
    assert "hr-knowledge" in summary
    assert "MISSING" in summary


def test_summary_shows_met_dependency():
    plan = _plan_with_ticketing()
    plan.set_context("hr-knowledge", "HR knowledge", group=SCENARIO_GROUP)
    plan.add_scenario_dependency("hr-ticketing", "hr-knowledge")
    summary = plan.render_summary()
    assert "| hr-ticketing | hr-knowledge | requires | met |" in summary


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def test_cli_scenario_dependency_flow(tmp_path, capsys):
    plan_path = str(tmp_path / "plan.json")
    cli.main(["--plan", plan_path, "init"])
    cli.main(["--plan", plan_path, "add-scenario", "--id", "hr-ticketing", "--label", "HR ticketing"])
    capsys.readouterr()

    # check-deps surfaces the PM-spec knowledge->ticketing dependency as unmet.
    rc = cli.main(["--plan", plan_path, "check-deps", "--json"])
    assert rc == 0
    unmet = json.loads(capsys.readouterr().out)
    assert unmet[0]["dependsOn"] == "hr-knowledge"

    # Add knowledge + the explicit edge -> no longer unmet.
    cli.main(["--plan", plan_path, "add-scenario", "--id", "hr-knowledge", "--label", "HR knowledge"])
    cli.main([
        "--plan", plan_path, "add-scenario-dependency",
        "--scenario", "hr-ticketing", "--depends-on", "hr-knowledge",
        "--kind", "requires", "--rationale", "PM spec",
    ])
    capsys.readouterr()
    rc = cli.main(["--plan", plan_path, "check-deps"])
    assert rc == 0
    assert "No unmet scenario dependencies" in capsys.readouterr().out

    assert cli.main(["--plan", plan_path, "validate"]) == 0


def test_scenario_dependency_status_flags_met_and_unmet():
    # Unmet: ticketing in scope, knowledge not.
    plan = _plan_with_ticketing()
    status = plan.scenario_dependency_status()
    assert len(status) == 1
    assert status[0]["met"] is False
    # Met: add the prerequisite scenario.
    plan.set_context("hr-knowledge", "HR knowledge", group=SCENARIO_GROUP)
    status = plan.scenario_dependency_status()
    assert len(status) == 1
    assert status[0]["met"] is True


def test_cli_check_deps_lists_met_dependencies(tmp_path, capsys):
    plan_path = str(tmp_path / "plan.json")
    cli.main(["--plan", plan_path, "init"])
    cli.main(["--plan", plan_path, "add-scenario", "--id", "hr-ticketing", "--label", "HR ticketing"])
    cli.main(["--plan", plan_path, "add-scenario", "--id", "hr-knowledge", "--label", "HR knowledge"])
    capsys.readouterr()
    rc = cli.main(["--plan", plan_path, "check-deps"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Met scenario dependencies" in out
    assert "hr-ticketing requires hr-knowledge" in out
    assert "No unmet scenario dependencies" in out
