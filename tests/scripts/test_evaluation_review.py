# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import json

import evaluation_review


def test_review_status_transition_preserves_description():
    requested = evaluation_review.compose_review_description(
        "Human-authored description",
        evaluation_review.REVIEW_REQUESTED,
    )
    completed = evaluation_review.compose_review_description(
        requested,
        evaluation_review.REVIEW_COMPLETED,
    )

    assert completed == (
        "Human-authored description\n\n"
        "[ADK-REVIEW status=review_completed]"
    )
    assert "review_requested" not in completed


def test_set_review_metadata_preserves_base_description_on_completion(tmp_path):
    set_folder = tmp_path / "evaluations" / "compensation"
    set_folder.mkdir(parents=True)
    (set_folder / "compensation.mcs.yml").write_text(
        "kind: EvaluationSet\n", encoding="utf-8")

    evaluation_review.set_review_metadata(
        set_folder,
        evaluation_review.REVIEW_REQUESTED,
        "Original description",
    )
    review_path = evaluation_review.set_review_metadata(
        set_folder,
        evaluation_review.REVIEW_COMPLETED,
    )

    metadata = json.loads(review_path.read_text(encoding="utf-8"))
    assert metadata == {
        "status": "review_completed",
        "baseDescription": "Original description",
    }


def test_set_review_metadata_reads_description_from_component_map(tmp_path):
    agent = tmp_path / "agent"
    set_folder = agent / "evaluations" / "compensation"
    set_folder.mkdir(parents=True)
    parent = set_folder / "compensation.mcs.yml"
    parent.write_text("kind: EvaluationSet\n", encoding="utf-8")
    (agent / ".component-map.json").write_text(
        json.dumps({
            "evaluations/compensation/compensation.mcs.yml": {
                "componenttype": 19,
                "description": "Existing description",
            }
        }),
        encoding="utf-8",
    )

    review_path = evaluation_review.set_review_metadata(
        set_folder,
        evaluation_review.REVIEW_REQUESTED,
    )

    metadata = json.loads(review_path.read_text(encoding="utf-8"))
    assert metadata["baseDescription"] == "Existing description"


def test_discover_review_sets_finds_workspace_and_configured_agent(tmp_path):
    workspace_set = tmp_path / "workspace" / "evaluations" / "benefits"
    workspace_set.mkdir(parents=True)
    (workspace_set / "review.json").write_text(
        json.dumps({"status": "review_requested"}),
        encoding="utf-8",
    )
    (workspace_set / "benefits.mcs.yml").write_text(
        "kind: EvaluationSet\n",
        encoding="utf-8",
    )
    (workspace_set / "benefits-case.mcs.yml").write_text(
        "kind: EvaluationData\n",
        encoding="utf-8",
    )

    agent_set = (
        tmp_path
        / "workspace"
        / "agents"
        / "ess-agent"
        / "evaluations"
        / "compensation"
    )
    agent_set.mkdir(parents=True)
    (agent_set / "review.json").write_text(
        json.dumps({"status": "review_requested"}),
        encoding="utf-8",
    )
    (agent_set / "compensation.mcs.yml").write_text(
        "kind: EvaluationSet\n",
        encoding="utf-8",
    )
    for name in ("base-pay", "comp-ratio"):
        (agent_set / f"{name}.mcs.yml").write_text(
            "kind: EvaluationData\n",
            encoding="utf-8",
        )
    agent_baseline_set = (
        tmp_path
        / "workspace"
        / "agents"
        / "ess-agent"
        / ".baseline"
        / "evaluations"
        / "compensation"
    )
    agent_baseline_set.mkdir(parents=True)
    (agent_baseline_set / "compensation.mcs.yml").write_text(
        "kind: EvaluationSet\n",
        encoding="utf-8",
    )
    (agent_baseline_set / "review.json").write_text(
        json.dumps({"status": "review_requested"}),
        encoding="utf-8",
    )

    completed_set = (
        tmp_path
        / "workspace"
        / "agents"
        / "ess-agent"
        / "evaluations"
        / "completed"
    )
    completed_set.mkdir(parents=True)
    (completed_set / "review.json").write_text(
        json.dumps({"status": "review_completed"}),
        encoding="utf-8",
    )

    config_path = tmp_path / ".local" / "config.json"
    config_path.parent.mkdir()
    config_path.write_text(
        json.dumps({
            "agent": {
                "name": "ESS Agent",
                "folder": "workspace/agents/ess-agent",
            }
        }),
        encoding="utf-8",
    )

    results = evaluation_review.discover_review_sets(
        tmp_path / "workspace",
        config_path,
    )

    assert [
        (item["name"], item["source"], item["testCaseCount"])
        for item in results
    ] == [
        ("compensation", "Configured agent: ESS Agent", 2),
    ]


def test_discover_evaluation_sets_lists_all_sources_and_statuses(tmp_path):
    workspace_set = tmp_path / "workspace" / "evaluations" / "catalogue"
    workspace_set.mkdir(parents=True)
    (workspace_set / "catalogue.mcs.yml").write_text(
        "kind: EvaluationSet\n",
        encoding="utf-8",
    )
    (workspace_set / "case.mcs.yml").write_text(
        "kind: EvaluationData\n",
        encoding="utf-8",
    )

    agent_root = tmp_path / "workspace" / "agents" / "ess-agent"
    agent_set = agent_root / "evaluations" / "compensation"
    agent_set.mkdir(parents=True)
    (agent_set / "compensation.mcs.yml").write_text(
        "kind: EvaluationSet\n",
        encoding="utf-8",
    )
    (agent_set / "review.json").write_text(
        json.dumps({"status": "review_completed"}),
        encoding="utf-8",
    )

    exports = agent_root / "evaluations" / "exports"
    exports.mkdir()
    (exports / "ignored.mcs.yml").write_text(
        "kind: EvaluationSet\n",
        encoding="utf-8",
    )

    config_path = tmp_path / ".local" / "config.json"
    config_path.parent.mkdir()
    config_path.write_text(
        json.dumps({
            "agent": {
                "name": "ESS Agent",
                "folder": "workspace/agents/ess-agent",
            }
        }),
        encoding="utf-8",
    )

    results = evaluation_review.discover_evaluation_sets(
        tmp_path / "workspace",
        config_path,
    )

    assert [
        (
            item["name"],
            item["source"],
            item["localStatus"],
            item["deployedStatus"],
            item["nextAction"],
        )
        for item in results
    ] == [
        (
            "compensation",
            "Configured agent: ESS Agent",
            "review_completed",
            "not_deployed",
            "push_review_completion",
        ),
        (
            "catalogue",
            "Workspace",
            "untagged",
            "not_deployed",
            "none",
        ),
    ]


def test_local_review_request_requires_push_before_review(tmp_path):
    agent_root = tmp_path / "workspace" / "agents" / "ess-agent"
    set_folder = agent_root / "evaluations" / "compensation"
    set_folder.mkdir(parents=True)
    (set_folder / "compensation.mcs.yml").write_text(
        "kind: EvaluationSet\n",
        encoding="utf-8",
    )
    (set_folder / "review.json").write_text(
        json.dumps({"status": "review_requested"}),
        encoding="utf-8",
    )
    baseline_set = (
        agent_root / ".baseline" / "evaluations" / "compensation"
    )
    baseline_set.mkdir(parents=True)
    (baseline_set / "compensation.mcs.yml").write_text(
        "kind: EvaluationSet\n",
        encoding="utf-8",
    )
    config_path = tmp_path / ".local" / "config.json"
    config_path.parent.mkdir()
    config_path.write_text(
        json.dumps({
            "agent": {
                "name": "ESS Agent",
                "folder": "workspace/agents/ess-agent",
            }
        }),
        encoding="utf-8",
    )

    all_sets = evaluation_review.discover_evaluation_sets(
        tmp_path / "workspace",
        config_path,
    )
    review_sets = evaluation_review.discover_review_sets(
        tmp_path / "workspace",
        config_path,
    )

    assert all_sets[0]["localStatus"] == "review_requested"
    assert all_sets[0]["deployedStatus"] == "untagged"
    assert all_sets[0]["syncState"] == "pending_push"
    assert all_sets[0]["nextAction"] == "push_review_request"
    assert review_sets == []


def test_pushed_review_request_is_available_for_review(tmp_path):
    agent_root = tmp_path / "workspace" / "agents" / "ess-agent"
    for root in (
        agent_root / "evaluations" / "compensation",
        agent_root / ".baseline" / "evaluations" / "compensation",
    ):
        root.mkdir(parents=True)
        (root / "compensation.mcs.yml").write_text(
            "kind: EvaluationSet\n",
            encoding="utf-8",
        )
        (root / "review.json").write_text(
            json.dumps({"status": "review_requested"}),
            encoding="utf-8",
        )
    config_path = tmp_path / ".local" / "config.json"
    config_path.parent.mkdir()
    config_path.write_text(
        json.dumps({
            "agent": {
                "name": "ESS Agent",
                "folder": "workspace/agents/ess-agent",
            }
        }),
        encoding="utf-8",
    )

    result = evaluation_review.discover_review_sets(
        tmp_path / "workspace",
        config_path,
    )

    assert len(result) == 1
    assert result[0]["syncState"] == "in_sync"
    assert result[0]["nextAction"] == "review"


def test_match_evaluation_sets_ranks_named_set_without_auto_selecting():
    matches = evaluation_review.match_evaluation_sets(
        [
            {"name": "Benefits and Leave", "source": "Workspace"},
            {"name": "Compensation", "source": "Configured agent"},
        ],
        "comp evals",
    )

    assert [item["name"] for item in matches] == ["Compensation"]
    assert matches[0]["matchScore"] >= 0.45
