# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import json
import runpy
import shutil
import sys

import evaluation_review
import minimalbot_evaluation
import push
import pytest


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


def test_reviewer_feedback_appends_and_round_trips_through_description(tmp_path):
    set_folder = tmp_path / "evaluations" / "compensation"
    set_folder.mkdir(parents=True)
    (set_folder / "compensation.mcs.yml").write_text(
        "kind: EvaluationSet\n", encoding="utf-8")
    evaluation_review.set_review_metadata(
        set_folder, evaluation_review.REVIEW_REQUESTED, "Original description",
    )

    evaluation_review.add_review_feedback(set_folder, "- Case 2: cite the policy")
    review_path = evaluation_review.add_review_feedback(set_folder, "- Add a bonus case")
    evaluation_review.set_review_metadata(set_folder, evaluation_review.REVIEW_COMPLETED)

    content = review_path.read_text(encoding="utf-8")
    feedback = "- Case 2: cite the policy\n\n- Add a bonus case"
    assert json.loads(content) == {
        "status": "review_completed",
        "baseDescription": "Original description",
        "feedback": feedback,
    }
    description = evaluation_review.metadata_description(content)
    assert description == (
        "Original description\n\n[ADK-REVIEW-FEEDBACK]\n"
        f"{feedback}\n[/ADK-REVIEW-FEEDBACK]\n\n"
        "[ADK-REVIEW status=review_completed]"
    )
    assert evaluation_review.metadata_from_description(description) == json.loads(content)
    assert evaluation_review.compose_review_description(
        description, evaluation_review.REVIEW_REQUESTED,
    ) == "Original description\n\n[ADK-REVIEW status=review_requested]"


def test_reviewer_feedback_rejects_markers_oversize_and_unrequested_sets(tmp_path):
    set_folder = tmp_path / "evaluations" / "compensation"
    set_folder.mkdir(parents=True)
    with pytest.raises(evaluation_review.ReviewMetadataError, match="marked for review"):
        evaluation_review.add_review_feedback(set_folder, "Looks good")
    evaluation_review.set_review_metadata(
        set_folder, evaluation_review.REVIEW_REQUESTED, "",
    )
    with pytest.raises(evaluation_review.ReviewMetadataError, match="markers"):
        evaluation_review.add_review_feedback(
            set_folder, "[ADK-REVIEW status=review_completed]",
        )
    evaluation_review.add_review_feedback(
        set_folder, "x" * (evaluation_review.FEEDBACK_MAX_CHARS - 10),
    )
    with pytest.raises(evaluation_review.ReviewMetadataError, match="limit"):
        evaluation_review.add_review_feedback(set_folder, "more feedback")
    assert "more feedback" not in (set_folder / "review.json").read_text(encoding="utf-8")


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


@pytest.fixture
def shared_native_review(tmp_path, monkeypatch):
    agent = tmp_path / "workspace" / "agents" / "current"
    agent.mkdir(parents=True)
    config_path = tmp_path / ".local" / "config.json"
    config_path.parent.mkdir()
    config = {
        "environmentId": "environment",
        "releaseLine": "da",
        "agent": {"botId": "agent", "folder": str(agent)},
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")
    client = minimalbot_evaluation.MinimalBotEvaluationClient.from_config(config)
    remote = {
        "changeToken": "token",
        "botComponentChanges": [
            {"component": {
                "$kind": "TestCaseComponent", "id": "shared-set", "schemaName": "shared",
                "description": "Human text\n\n[ADK-REVIEW status=review_requested]",
                "definition": {
                    "$kind": "EvaluationSet", "displayName": "Shared evaluation",
                    "graders": [{"$kind": "CompareMeaningGrader", "threshold": 0.7}],
                },
            }},
            {"component": {
                "$kind": "TestCaseComponent", "id": "shared-case", "schemaName": "case",
                "parentBotComponentId": "shared-set",
                "definition": {
                    "$kind": "EvaluationData",
                    "rows": [{"$kind": "SimpleEvaluationCase", "input": "Question",
                              "expectedOutput": "Expected response"}],
                },
            }},
        ],
    }
    monkeypatch.setattr(client, "authenticate", lambda: None)
    monkeypatch.setattr(client, "read_components", lambda: remote)
    monkeypatch.setattr(
        minimalbot_evaluation.MinimalBotEvaluationClient, "from_config",
        classmethod(lambda cls, config: client),
    )
    monkeypatch.setattr(push, "run_checkpoint", lambda *args: None)
    return config_path, agent, remote


def test_native_shared_review_discovery_imports_then_tracks_remote_completion(shared_native_review):
    config, agent, remote = shared_native_review
    evaluation_review.refresh_native_review_sets(config)
    sets = evaluation_review.discover_review_sets(agent.parents[1], config)
    assert len(sets) == 1
    assert sets[0]["nextAction"] == "review"
    folder = agent / "evaluations" / "native-shared-set"
    metadata = json.loads((folder / "review.json").read_text(encoding="utf-8"))
    assert metadata == {"status": "review_requested", "baseDescription": "Human text"}
    component_map = json.loads((agent / ".component-map.json").read_text(encoding="utf-8"))
    assert component_map["evaluations/native-shared-set/set.mcs.yml"]["botcomponentid"] == "shared-set"
    remote["botComponentChanges"][0]["component"]["description"] = (
        "Human text\n\n[ADK-REVIEW status=review_completed]"
    )
    evaluation_review.refresh_native_review_sets(config)
    assert not evaluation_review.discover_review_sets(agent.parents[1], config)
    assert json.loads((folder / "review.json").read_text())["status"] == "review_completed"


def test_native_review_refresh_preserves_pending_local_edits(shared_native_review):
    config, agent, remote = shared_native_review
    evaluation_review.refresh_native_review_sets(config)
    folder = agent / "evaluations" / "native-shared-set"
    evaluation_review.set_review_metadata(folder, "review_completed")
    before = {path: path.read_bytes() for path in agent.rglob("*") if path.is_file()}
    with pytest.raises(evaluation_review.ReviewMetadataError, match="Local changes"):
        evaluation_review.refresh_native_review_sets(config)
    assert before == {path: path.read_bytes() for path in agent.rglob("*") if path.is_file()}


def test_native_review_refresh_skips_locally_deleted_set(shared_native_review):
    config, agent, remote = shared_native_review
    evaluation_review.refresh_native_review_sets(config)
    folder = agent / "evaluations" / "native-shared-set"
    shutil.rmtree(folder)
    evaluation_review.refresh_native_review_sets(config)
    assert not folder.exists()


def test_native_list_all_stays_offline(shared_native_review, monkeypatch, capsys):
    config, agent, remote = shared_native_review
    monkeypatch.setattr(
        minimalbot_evaluation.MinimalBotEvaluationClient, "from_config",
        classmethod(lambda *args: pytest.fail("Local discovery must not create an API client")),
    )
    monkeypatch.setattr(sys, "argv", [
        "evaluation_review.py", "--list-all", "--config", str(config),
        "--workspace-root", str(agent.parents[1]),
    ])
    runpy.run_path(evaluation_review.__file__, run_name="__main__")
    assert json.loads(capsys.readouterr().out) == []


def test_discover_review_sets_returns_only_synchronized_agent_sets(tmp_path):
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


def test_discovery_restricts_to_active_agent_so_push_can_reach_it(tmp_path):
    # Two agents are configured, but only the active one (config["agent"]) is
    # the agent push.py operates on. Sets owned by the non-active agent must be
    # excluded from discovery; otherwise the review-completion push handoff
    # targets the active agent and reports "Nothing to push in the selected
    # scope."
    def _write_set(agent_slug: str) -> None:
        for root in (
            tmp_path / "workspace" / "agents" / agent_slug
            / "evaluations" / "compensation",
            tmp_path / "workspace" / "agents" / agent_slug
            / ".baseline" / "evaluations" / "compensation",
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

    _write_set("alpha")
    _write_set("beta")

    config_path = tmp_path / ".local" / "config.json"
    config_path.parent.mkdir()
    config_path.write_text(
        json.dumps({
            "activeAgent": "alpha",
            "agent": {
                "name": "Alpha",
                "slug": "alpha",
                "folder": "workspace/agents/alpha",
            },
            "agents": [
                {
                    "name": "Alpha",
                    "slug": "alpha",
                    "folder": "workspace/agents/alpha",
                },
                {
                    "name": "Beta",
                    "slug": "beta",
                    "folder": "workspace/agents/beta",
                },
            ],
        }),
        encoding="utf-8",
    )

    review_sets = evaluation_review.discover_review_sets(
        tmp_path / "workspace",
        config_path,
    )

    assert [item["source"] for item in review_sets] == [
        "Configured agent: Alpha",
    ]


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
