"""End-to-end runs against the real vendored ESS reference data."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import REFERENCE_ROOT, requires_reference
from essmig import reference as reference_module
from essmig.cli import main

pytestmark = requires_reference


@pytest.fixture(scope="module")
def baseline() -> dict[str, dict]:
    return json.loads((REFERENCE_ROOT / "ca-baseline.json").read_text(encoding="utf-8"))


def test_hr_and_it_keep_separate_baselines_for_the_same_suffix(baseline: dict) -> None:
    # gpt.default exists under both agents with different instructions. Pooling them
    # would diff an HR customer's edit against IT's shipped content.
    assert baseline["hr"]["gpt.default"]["data"] != baseline["it"]["gpt.default"]["data"]


def test_no_declarative_agent_preview_solution_leaks_into_the_baseline(baseline: dict) -> None:
    solutions = {
        entry["solution"] for bucket in baseline.values() for entry in bucket.values()
    }
    assert not any("DA" in name or "Poc" in name for name in solutions), sorted(solutions)


def test_every_baseline_suffix_belongs_to_an_ess_agent(baseline: dict) -> None:
    for bucket, entries in baseline.items():
        for suffix, entry in entries.items():
            assert entry["schemaname"].endswith(f".{suffix}"), (bucket, suffix)


def test_the_reference_templates_are_alm_templated_packages() -> None:
    for vertical in ("hr", "it"):
        reference = reference_module.load(vertical)
        assert reference.package["packageType"] == "templated"
        assert reference.da_schemaname == f"gptagent_copilotforemployeeselfservice{vertical}"
        assert reference.da_components


def test_a_full_migration_produces_a_package_and_a_report(tmp_path: Path) -> None:
    reference = reference_module.load("hr")
    baseline = reference.baseline["topic.ConversationStart"]
    assert baseline.data

    snapshot = {
        "vertical": "hr",
        "solution": "msdyn_CopilotForEmployeeSelfServiceHR",
        "components": {
            "11111111-1111-1111-1111-111111111111": {
                "schemaname": baseline.schemaname,
                "name": "Conversation Start",
                "component_type": 9,
                "data": baseline.data.replace("Hi {Global", "Hello {Global"),
                "statecode": 0,
                "solutions": ["msdyn_CopilotForEmployeeSelfServiceHR", "Active"],
            },
            "22222222-2222-2222-2222-222222222222": {
                "schemaname": "msdyn_copilotforemployeeselfservicehr.topic.MyOwnTopic",
                "name": "My Own Topic",
                "component_type": 9,
                "data": (
                    "kind: AdaptiveDialog\n"
                    "beginDialog:\n"
                    "  kind: OnRedirect\n"
                    "  id: main\n"
                    "  actions:\n"
                    "    - kind: SendActivity\n"
                    "      id: a1\n"
                    "      activity: hello\n"
                ),
                "statecode": 0,
                "solutions": ["MyDevSolution"],
            },
        },
        "skipped": [],
    }
    snapshot_path = tmp_path / "customizations.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    exit_code = main(
        [
            "migrate",
            "--vertical",
            "hr",
            "--snapshot",
            str(snapshot_path),
            "--out",
            str(tmp_path / "out"),
        ]
    )

    out = tmp_path / "out"
    assert exit_code == 0
    assert (out / "gptagent_copilotforemployeeselfservicehr.zip").is_file()

    agent = (
        out / "Plugin" / "Agents" / "gptagent_copilotforemployeeselfservicehr" / "agent.yml"
    ).read_text(encoding="utf-8")
    assert "gptagent_copilotforemployeeselfservicehr.topic.MyOwnTopic" in agent
    # No CA schema reference may survive into the Declarative Agent.
    assert "msdyn_copilotforemployeeselfservice" not in agent

    report = json.loads((out / "migration-report.json").read_text(encoding="utf-8"))
    outcomes = {entry["suffix"]: entry["outcome"] for entry in report["components"]}
    assert outcomes["topic.MyOwnTopic"] == "carried-new"
    assert outcomes["topic.ConversationStart"] in {"merged", "conflicted"}

    assessment = report["assessment"]
    assert assessment["eligibility"] in {"ready", "needs-work", "blocked"}
    assert any("conversation history" in impact for impact in assessment["employeeImpact"])

    markdown = (out / "migration-report.md").read_text(encoding="utf-8")
    assert "## Verdict:" in markdown
    assert "## What changes for your employees" in markdown


def test_migrating_no_customizations_still_produces_a_valid_package(tmp_path: Path) -> None:
    snapshot = tmp_path / "empty.json"
    snapshot.write_text(json.dumps({"vertical": "hr", "components": {}}), encoding="utf-8")
    assert (
        main(
            [
                "migrate",
                "--vertical",
                "hr",
                "--snapshot",
                str(snapshot),
                "--out",
                str(tmp_path / "out"),
            ]
        )
        == 0
    )
    assert (tmp_path / "out" / "migration-report.md").is_file()
