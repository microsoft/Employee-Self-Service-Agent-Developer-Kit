# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for planner.facts — the vendored non-Learn planning facts.

The facts file holds only what the planner can't get from Learn and that isn't
a business-scenario catalogue: scenario dependency edges (each explicitly
sourced) and a small recognition lexicon. It must be absent-safe.
"""

from __future__ import annotations

import json

from planner import facts


def test_scenario_dependency_edges_are_sourced_and_not_pm_spec():
    edges = facts.scenario_dependency_edges()
    assert edges, "expected at least the seeded knowledge->ticketing edge"
    edge = next(
        e for e in edges if e["scenario"] == "hr-ticketing" and e["dependsOn"] == "hr-knowledge"
    )
    assert edge["kind"] == "recommends"
    # Sourced from the vendored ESS scenario catalogue, NOT the PM spec.
    assert edge["source"] and "spec" not in edge["source"].lower()
    assert "catalogue" in edge["source"].lower()
    assert "deflect" in edge["rationale"].lower()


def test_recognition_lexicons_present():
    roles = facts.role_lexicon()
    outputs = facts.output_lexicon()
    assert "Power Platform administrator" in roles
    assert "environment" in outputs


def test_facts_is_absent_safe(tmp_path):
    missing = tmp_path / "nope.json"
    assert facts.load_facts(missing) == {}
    assert facts.scenario_dependency_edges(missing) == []
    assert facts.role_lexicon(missing) == []
    assert facts.output_lexicon(missing) == []


def test_facts_tolerates_corrupt_file(tmp_path):
    bad = tmp_path / "planner_facts.json"
    bad.write_text("{ not valid json", encoding="utf-8")
    assert facts.load_facts(bad) == {}
    assert facts.scenario_dependency_edges(bad) == []


def test_facts_file_is_valid_json_and_shaped():
    data = facts.load_facts()
    assert data.get("schemaVersion") == 1
    # The file must NOT enumerate a business-scenario list (grounding rule).
    assert "scenarios" not in data
    # Every dependency carries an explicit source.
    for dep in data.get("scenarioDependencies", []):
        assert dep.get("source")
    # Sanity: it really is JSON on disk.
    with open(facts.FACTS_PATH, "r", encoding="utf-8") as fh:
        json.load(fh)
