from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest
import yaml


SCRIPTS = (
    Path(__file__).resolve().parents[2]
    / "solutions"
    / "ess-maker-skills"
    / "scripts"
)
sys.path.insert(0, str(SCRIPTS))

import evaluation_runs  # noqa: E402
from evaluation_review import compose_review_description  # noqa: E402


def _deployed_components():
    return [
        {
            "botcomponentid": "set-comp",
            "componenttype": 19,
            "parentbotcomponentid": None,
            "description": "",
            "data": yaml.safe_dump({
                "kind": "EvaluationSet",
                "graders": [{"kind": "CompareMeaningGrader", "threshold": 0.7}],
            }),
        },
        {
            "botcomponentid": "case-1",
            "componenttype": 19,
            "parentbotcomponentid": "set-comp",
            "data": yaml.safe_dump({
                "kind": "EvaluationData",
                "rows": [{"input": "My pay?", "expectedOutput": "Check payroll."}],
            }),
        },
    ]


@pytest.fixture
def deployed_dataverse(monkeypatch):
    components = _deployed_components()
    config = {
        "dataverseEndpoint": "https://contoso.crm.dynamics.com",
        "environmentId": "environment-id",
        "agent": {"botId": "bot-id"},
    }
    monkeypatch.setattr(evaluation_runs, "load_config", lambda: config)
    monkeypatch.setattr(evaluation_runs, "authenticate", lambda url: "fake-token")

    def fetch(url, token, bot_id):
        assert url == config["dataverseEndpoint"]
        assert token == "fake-token"
        assert bot_id == "bot-id"
        return components

    monkeypatch.setattr(evaluation_runs, "fetch_components", fetch)
    return components


class FakeClient:
    def __init__(self):
        self.started = []
        self.list_runs_calls = 0

    def list_environments_for_user(self):
        return [{
            "id": "environment-id",
            "url": "https://contoso.crm.dynamics.com",
        }]

    def list_maker_evaluation_test_sets(self, environment_id, bot_id):
        assert environment_id == "environment-id"
        assert bot_id == "bot-id"
        return [
            {
                "id": "set-comp",
                "displayName": "Compensation",
                "state": "Active",
                "totalTestCases": 6,
            },
            {
                "id": "set-benefits",
                "displayName": "Benefits and Leave",
                "state": "Active",
                "totalTestCases": 10,
            },
            {
                "id": "set-old",
                "displayName": "Old Set",
                "state": "Inactive",
                "totalTestCases": 1,
            },
        ]

    def run_maker_evaluation_test_set(
        self,
        environment_id,
        bot_id,
        test_set_id,
        body,
    ):
        self.started.append((environment_id, bot_id, test_set_id, body))
        return {
            "runId": "run-1",
            "state": "Queued",
            "executionState": "Initializing",
            "lastUpdatedAt": "2026-08-24T15:00:00Z",
            "totalTestCases": 6,
            "testCasesProcessed": 0,
        }

    def list_maker_evaluation_test_runs(self, environment_id, bot_id):
        self.list_runs_calls += 1
        return [{
            "id": "remote-run",
            "testSetId": "set-benefits",
            "name": "Benefits nightly run",
            "state": "Completed",
            "startTime": "2026-08-24T14:00:00Z",
            "totalTestCases": 10,
        }]

    def get_maker_evaluation_test_run(self, environment_id, bot_id, run_id):
        return {
            "id": run_id,
            "testSetId": "set-comp",
            "state": "Completed",
            "testCasesResults": [{
                "testCaseId": "case-1",
                "state": "Completed",
                "metricsResults": [{
                    "type": "CompareMeaning",
                    "result": {"status": "Pass"},
                }],
            }],
        }


def test_match_test_sets_filters_inactive_and_ranks_fuzzy_name():
    client = FakeClient()
    matches = evaluation_runs.match_test_sets(
        client.list_maker_evaluation_test_sets("environment-id", "bot-id"),
        "comp evals",
    )

    assert [item["displayName"] for item in matches] == ["Compensation"]
    assert matches[0]["matchScore"] >= 0.45


def test_resolve_environment_id_matches_dataverse_hostname():
    environment_id = evaluation_runs.resolve_environment_id(
        {"dataverseEndpoint": "https://contoso.crm.dynamics.com/"},
        FakeClient(),
    )

    assert environment_id == "environment-id"


def test_resolve_environment_id_prefers_active_agent_over_stale_global():
    client = FakeClient()
    client.list_environments_for_user = lambda: pytest.fail(
        "A configured active environment must not be rediscovered"
    )
    assert evaluation_runs.resolve_environment_id({
        "environmentId": "stale-global-environment",
        "agent": {"environmentId": "active-environment"},
    }, client) == "active-environment"


def test_runtime_uses_active_environment_with_configured_dataverse_endpoint(
    monkeypatch, tmp_path,
):
    client = FakeClient()
    client.authenticate = lambda: "fake-token"
    monkeypatch.setattr(evaluation_runs, "PowerPlatformClient", lambda tenant: client)
    monkeypatch.setattr(
        evaluation_runs, "discover_tenant", lambda url: "configured-endpoint-tenant",
    )
    runtime = evaluation_runs._runtime({
        "dataverseEndpoint": "https://contoso.crm.dynamics.com",
        "environmentId": "stale-global-environment",
        "agent": {
            "environmentId": "active-environment",
            "botId": "active-bot",
            "folder": str(tmp_path),
        },
    })
    assert runtime == (client, "active-environment", "active-bot", tmp_path)


def test_list_agent_test_sets_uses_local_parent_ids_and_remote_active_state(
    tmp_path,
):
    evaluations = tmp_path / "evaluations" / "compensation"
    evaluations.mkdir(parents=True)
    (evaluations / "compensation.mcs.yml").write_text(
        "kind: EvaluationSet\n",
        encoding="utf-8",
    )
    (evaluations / "case.mcs.yml").write_text(
        "kind: EvaluationData\n",
        encoding="utf-8",
    )
    (tmp_path / ".component-map.json").write_text(
        json.dumps({
            "evaluations/compensation/compensation.mcs.yml": {
                "botcomponentid": "set-comp",
                "componenttype": 19,
                "name": "Compensation",
            }
        }),
        encoding="utf-8",
    )

    sets = evaluation_runs.list_agent_test_sets(
        FakeClient(),
        "environment-id",
        "bot-id",
        tmp_path,
        "comp",
    )

    assert len(sets) == 1
    assert sets[0]["id"] == "set-comp"
    assert sets[0]["localSetName"] == "compensation"
    assert sets[0]["localTestCaseCount"] == 1
    assert sets[0]["source"] == "Configured agent evaluations folder"


def test_list_agent_test_sets_excludes_review_requested_sets(tmp_path):
    evaluations = tmp_path / "evaluations" / "compensation"
    evaluations.mkdir(parents=True)
    (evaluations / "compensation.mcs.yml").write_text(
        "kind: EvaluationSet\n",
        encoding="utf-8",
    )
    (evaluations / "review.json").write_text(
        json.dumps({
            "status": "review_requested",
            "baseDescription": "Needs SME review",
        }),
        encoding="utf-8",
    )
    (tmp_path / ".component-map.json").write_text(
        json.dumps({
            "evaluations/compensation/compensation.mcs.yml": {
                "botcomponentid": "set-comp",
                "componenttype": 19,
                "name": "Compensation",
            }
        }),
        encoding="utf-8",
    )

    sets = evaluation_runs.list_agent_test_sets(
        FakeClient(),
        "environment-id",
        "bot-id",
        tmp_path,
        "compensation",
    )

    assert sets == []


def test_list_agent_test_sets_explains_review_pending_when_requested(
    tmp_path,
):
    evaluations = tmp_path / "evaluations" / "compensation"
    evaluations.mkdir(parents=True)
    (evaluations / "compensation.mcs.yml").write_text(
        "kind: EvaluationSet\n",
        encoding="utf-8",
    )
    (evaluations / "review.json").write_text(
        json.dumps({"status": "review_requested"}),
        encoding="utf-8",
    )
    (tmp_path / ".component-map.json").write_text(
        json.dumps({
            "evaluations/compensation/compensation.mcs.yml": {
                "botcomponentid": "set-comp",
                "componenttype": 19,
                "name": "Compensation",
            }
        }),
        encoding="utf-8",
    )

    sets = evaluation_runs.list_agent_test_sets(
        FakeClient(),
        "environment-id",
        "bot-id",
        tmp_path,
        include_blocked=True,
    )

    assert len(sets) == 1
    assert sets[0]["runnable"] is False
    assert sets[0]["blockedReason"] == (
        evaluation_runs.REVIEW_PENDING_GUIDANCE
    )


def test_list_agent_test_sets_allows_review_completed_sets(tmp_path):
    evaluations = tmp_path / "evaluations" / "compensation"
    baseline = tmp_path / ".baseline" / "evaluations" / "compensation"
    evaluations.mkdir(parents=True)
    baseline.mkdir(parents=True)
    (evaluations / "compensation.mcs.yml").write_text(
        "kind: EvaluationSet\n",
        encoding="utf-8",
    )
    (evaluations / "review.json").write_text(
        json.dumps({
            "status": "review_completed",
            "baseDescription": "Reviewed by SME",
        }),
        encoding="utf-8",
    )
    (baseline / "review.json").write_text(
        json.dumps({
            "status": "review_completed",
            "baseDescription": "Reviewed by SME",
        }),
        encoding="utf-8",
    )
    (tmp_path / ".component-map.json").write_text(
        json.dumps({
            "evaluations/compensation/compensation.mcs.yml": {
                "botcomponentid": "set-comp",
                "componenttype": 19,
                "name": "Compensation",
            }
        }),
        encoding="utf-8",
    )

    sets = evaluation_runs.list_agent_test_sets(
        FakeClient(),
        "environment-id",
        "bot-id",
        tmp_path,
    )

    assert [item["id"] for item in sets] == ["set-comp"]
    assert sets[0]["reviewStatus"] == "review_completed"


def test_list_agent_test_sets_blocks_unpushed_completion_without_baseline(
    tmp_path,
):
    evaluations = tmp_path / "evaluations" / "compensation"
    evaluations.mkdir(parents=True)
    (evaluations / "compensation.mcs.yml").write_text(
        "kind: EvaluationSet\n",
        encoding="utf-8",
    )
    (evaluations / "review.json").write_text(
        json.dumps({"status": "review_completed"}),
        encoding="utf-8",
    )
    (tmp_path / ".component-map.json").write_text(
        json.dumps({
            "evaluations/compensation/compensation.mcs.yml": {
                "botcomponentid": "set-comp",
                "componenttype": 19,
                "name": "Compensation",
            }
        }),
        encoding="utf-8",
    )

    sets = evaluation_runs.list_agent_test_sets(
        FakeClient(),
        "environment-id",
        "bot-id",
        tmp_path,
        include_blocked=True,
    )

    assert sets[0]["runnable"] is False
    assert sets[0]["blockedReason"] == (
        evaluation_runs.REVIEW_COMPLETION_NOT_PUSHED_GUIDANCE
    )


def test_list_agent_test_sets_excludes_unpushed_review_completion(tmp_path):
    evaluations = tmp_path / "evaluations" / "compensation"
    baseline = tmp_path / ".baseline" / "evaluations" / "compensation"
    evaluations.mkdir(parents=True)
    baseline.mkdir(parents=True)
    (evaluations / "compensation.mcs.yml").write_text(
        "kind: EvaluationSet\n",
        encoding="utf-8",
    )
    (evaluations / "review.json").write_text(
        json.dumps({"status": "review_completed"}),
        encoding="utf-8",
    )
    (baseline / "review.json").write_text(
        json.dumps({"status": "review_requested"}),
        encoding="utf-8",
    )
    (tmp_path / ".component-map.json").write_text(
        json.dumps({
            "evaluations/compensation/compensation.mcs.yml": {
                "botcomponentid": "set-comp",
                "componenttype": 19,
                "name": "Compensation",
            }
        }),
        encoding="utf-8",
    )

    sets = evaluation_runs.list_agent_test_sets(
        FakeClient(),
        "environment-id",
        "bot-id",
        tmp_path,
    )

    assert sets == []


def test_list_agent_test_sets_explains_unpushed_review_completion(tmp_path):
    evaluations = tmp_path / "evaluations" / "compensation"
    baseline = tmp_path / ".baseline" / "evaluations" / "compensation"
    evaluations.mkdir(parents=True)
    baseline.mkdir(parents=True)
    (evaluations / "compensation.mcs.yml").write_text(
        "kind: EvaluationSet\n",
        encoding="utf-8",
    )
    (evaluations / "review.json").write_text(
        json.dumps({"status": "review_completed"}),
        encoding="utf-8",
    )
    (baseline / "review.json").write_text(
        json.dumps({"status": "review_requested"}),
        encoding="utf-8",
    )
    (tmp_path / ".component-map.json").write_text(
        json.dumps({
            "evaluations/compensation/compensation.mcs.yml": {
                "botcomponentid": "set-comp",
                "componenttype": 19,
                "name": "Compensation",
            }
        }),
        encoding="utf-8",
    )

    sets = evaluation_runs.list_agent_test_sets(
        FakeClient(),
        "environment-id",
        "bot-id",
        tmp_path,
        include_blocked=True,
    )

    assert len(sets) == 1
    assert sets[0]["runnable"] is False
    assert sets[0]["blockedReason"] == (
        evaluation_runs.REVIEW_COMPLETION_NOT_PUSHED_GUIDANCE
    )


class _RemoteMarkerClient(FakeClient):
    """FakeClient variant that stamps a review marker on the remote set,
    simulating the live Dataverse description for set-comp."""

    def __init__(self, remote_status):
        super().__init__()
        self._remote_status = remote_status

    def list_maker_evaluation_test_sets(self, environment_id, bot_id):
        sets = super().list_maker_evaluation_test_sets(environment_id, bot_id)
        for item in sets:
            if item["id"] == "set-comp":
                item["description"] = f"[ADK-REVIEW status={self._remote_status}]"
        return sets


def test_list_agent_test_sets_blocks_when_remote_requested_but_local_untagged(
    tmp_path,
):
    """Untagged local copy must not run while the live remote set is
    review_requested — the remote marker governs when there is no pending
    local change."""
    evaluations = tmp_path / "evaluations" / "compensation"
    evaluations.mkdir(parents=True)
    (evaluations / "compensation.mcs.yml").write_text(
        "kind: EvaluationSet\n",
        encoding="utf-8",
    )
    (tmp_path / ".component-map.json").write_text(
        json.dumps({
            "evaluations/compensation/compensation.mcs.yml": {
                "botcomponentid": "set-comp",
                "componenttype": 19,
                "name": "Compensation",
            }
        }),
        encoding="utf-8",
    )

    sets = evaluation_runs.list_agent_test_sets(
        _RemoteMarkerClient("review_requested"),
        "environment-id",
        "bot-id",
        tmp_path,
        include_blocked=True,
    )

    assert len(sets) == 1
    assert sets[0]["runnable"] is False
    assert sets[0]["blockedReason"] == evaluation_runs.REVIEW_PENDING_GUIDANCE


def test_list_agent_test_sets_clears_when_remote_completed_after_local_request(
    tmp_path,
):
    """A stale local+baseline review_requested must clear once the live
    remote set is review_completed — no genuine pending local change, so
    the remote marker governs."""
    evaluations = tmp_path / "evaluations" / "compensation"
    baseline = tmp_path / ".baseline" / "evaluations" / "compensation"
    evaluations.mkdir(parents=True)
    baseline.mkdir(parents=True)
    (evaluations / "compensation.mcs.yml").write_text(
        "kind: EvaluationSet\n",
        encoding="utf-8",
    )
    for review_dir in (evaluations, baseline):
        (review_dir / "review.json").write_text(
            json.dumps({"status": "review_requested"}),
            encoding="utf-8",
        )
    (tmp_path / ".component-map.json").write_text(
        json.dumps({
            "evaluations/compensation/compensation.mcs.yml": {
                "botcomponentid": "set-comp",
                "componenttype": 19,
                "name": "Compensation",
            }
        }),
        encoding="utf-8",
    )

    sets = evaluation_runs.list_agent_test_sets(
        _RemoteMarkerClient("review_completed"),
        "environment-id",
        "bot-id",
        tmp_path,
    )

    assert [item["id"] for item in sets] == ["set-comp"]
    assert sets[0]["runnable"] is True


def test_run_command_reports_review_block_reason(
    monkeypatch,
    capsys,
    tmp_path,
):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluation_runs.py",
            "run",
            "--test-set-id",
            "set-comp",
        ],
    )
    monkeypatch.setattr(evaluation_runs, "load_config", lambda: {})
    monkeypatch.setattr(
        evaluation_runs,
        "_runtime",
        lambda config: (
            FakeClient(),
            "environment-id",
            "bot-id",
            tmp_path,
        ),
    )
    monkeypatch.setattr(
        evaluation_runs,
        "list_agent_test_sets",
        lambda *args, **kwargs: [{
            "id": "set-comp",
            "runnable": False,
            "blockedReason": evaluation_runs.REVIEW_PENDING_GUIDANCE,
        }],
    )
    monkeypatch.setattr(
        evaluation_runs,
        "resolve_mcs_connection",
        lambda *args, **kwargs: pytest.fail(
            "Blocked sets must not resolve a connection"
        ),
    )

    assert evaluation_runs.main() == 1
    assert evaluation_runs.REVIEW_PENDING_GUIDANCE in capsys.readouterr().err


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({}, "Dataverse endpoint is missing"),
        (
            {"dataverseEndpoint": "https://example.crm.dynamics.com"},
            "Configured agent details are missing",
        ),
        (
            {
                "dataverseEndpoint": "https://example.crm.dynamics.com",
                "agent": {},
            },
            "Configured agent botId or folder is missing",
        ),
    ],
)
def test_runtime_rejects_incomplete_config(config, message):
    with pytest.raises(evaluation_runs.EvaluationRunError, match=message):
        evaluation_runs._runtime(config)


def test_list_agent_test_sets_rejects_unknown_review_status(tmp_path):
    evaluations = tmp_path / "evaluations" / "compensation"
    evaluations.mkdir(parents=True)
    (evaluations / "compensation.mcs.yml").write_text(
        "kind: EvaluationSet\n",
        encoding="utf-8",
    )
    (evaluations / "review.json").write_text(
        json.dumps({
            "status": "unknown",
            "baseDescription": "Legacy metadata",
        }),
        encoding="utf-8",
    )
    (tmp_path / ".component-map.json").write_text(
        json.dumps({
            "evaluations/compensation/compensation.mcs.yml": {
                "botcomponentid": "set-comp",
                "componenttype": 19,
                "name": "Compensation",
            }
        }),
        encoding="utf-8",
    )

    with pytest.raises(
        evaluation_runs.EvaluationRunError,
        match="Review status must be",
    ):
        evaluation_runs.list_agent_test_sets(
            FakeClient(),
            "environment-id",
            "bot-id",
            tmp_path,
        )


def test_start_run_returns_api_details_without_local_mapping(
    tmp_path, deployed_dataverse,
):
    client = FakeClient()
    result = evaluation_runs.start_run(
        client,
        "environment-id",
        "bot-id",
        {
            "id": "set-comp",
            "displayName": "Compensation",
            "totalTestCases": 6,
        },
        "connection-1",
    )

    assert result["runId"] == "run-1"
    assert result["testSetName"] == "Compensation"
    assert result["testSetId"] == "set-comp"
    assert result["agentStudioUrl"] == (
        "https://copilotstudio.microsoft.com/environments/environment-id"
        "/copilots/bot-id/evaluation/runsDetails/set-comp/run-1"
    )
    assert result["state"] == "Queued"
    assert result["executionState"] == "Initializing"
    assert result["lastUpdatedAt"] == "2026-08-24T15:00:00Z"
    assert result["totalTestCases"] == 6
    assert result["testCasesProcessed"] == 0
    assert result["userGuidance"] == (
        "I've started running your test set in Copilot Studio. This may take "
        "10-15 minutes. Return here to view the results when the run is complete; "
        "you don't need to open Copilot Studio."
    )
    assert client.started[0][3]["runOnPublishedBot"] is False
    assert client.started[0][3]["mcsConnectionId"] == "connection-1"
    assert not (tmp_path / "evaluations" / "runs.json").exists()


def test_start_run_includes_resolved_tool_connections(deployed_dataverse):
    client = FakeClient()
    tools_connections = [{
        "botId": "bot-id",
        "botSchemaName": "contoso_agent",
        "connections": [{
            "connectorId": "shared_alchemy",
            "connectionId": "tool-connection",
            "connectionReferenceName": "contoso_agent.shared_alchemy.ref",
        }],
    }]

    evaluation_runs.start_run(
        client,
        "environment-id",
        "bot-id",
        {"id": "set-comp", "displayName": "Compensation"},
        "profile-connection",
        tools_connections=tools_connections,
    )

    assert client.started[0][3]["toolsConnections"] == tools_connections


def test_dataverse_run_gate_and_link_follow_active_environment(deployed_dataverse):
    config = evaluation_runs.load_config()
    config["environmentId"] = "stale-global-environment"
    config["agent"]["environmentId"] = "environment-id"
    client = FakeClient()
    result = evaluation_runs.start_run(
        client, "environment-id", "bot-id", {"id": "set-comp"}, "connection",
        config=config,
    )
    assert client.started[0][:3] == ("environment-id", "bot-id", "set-comp")
    assert "/environments/environment-id/" in result["agentStudioUrl"]
    assert "stale-global" not in result["agentStudioUrl"]


def test_dataverse_run_rejects_global_target_when_active_target_differs(
    deployed_dataverse,
):
    config = evaluation_runs.load_config()
    config["agent"]["environmentId"] = "active-environment"
    client = FakeClient()
    with pytest.raises(evaluation_runs.EvaluationRunError, match="configured environment"):
        evaluation_runs.start_run(
            client, "environment-id", "bot-id", {"id": "set-comp"}, "connection",
            config=config,
        )
    assert client.started == []


@pytest.mark.parametrize("graders", [
    None,
    [],
    {},
    ["CompareMeaningGrader"],
    [{"kind": "GeneralQualityGrader"}],
    [{"kind": "OtherGrader"}],
    [{"kind": "CompareMeaningGrader"}, {"kind": "GeneralQualityGrader"}],
    [{"kind": "CompareMeaningGrader"}, {"kind": "CompareMeaningGrader"}],
])
def test_start_run_rejects_unsupported_deployed_graders(
    deployed_dataverse, graders,
):
    deployed_dataverse[0]["data"] = yaml.safe_dump({
        "kind": "EvaluationSet", "graders": graders,
    })
    client = FakeClient()
    with pytest.raises(evaluation_runs.EvaluationMethodError, match="Compare Meaning"):
        evaluation_runs.start_run(
            client, "environment-id", "bot-id", {"id": "set-comp"}, "connection",
        )
    assert client.started == []


@pytest.mark.parametrize("child", [
    {"kind": "MultiTurnEvaluationCase", "turns": []},
    {"kind": "EvaluationData", "rows": [{"input": "My pay?"}]},
    {"kind": "EvaluationData", "rows": [
        {"input": "Valid", "expectedOutput": "Valid"},
        {"input": "Next", "expectedOutput": " \n "},
    ]},
])
def test_start_run_rejects_every_invalid_deployed_child(deployed_dataverse, child):
    deployed_dataverse.append({
        "botcomponentid": "case-bad",
        "componenttype": 19,
        "parentbotcomponentid": "set-comp",
        "data": yaml.safe_dump(child),
    })
    client = FakeClient()
    with pytest.raises(evaluation_runs.EvaluationMethodError, match="Deployed test set"):
        evaluation_runs.start_run(
            client, "environment-id", "bot-id", {"id": "set-comp"}, "connection",
        )
    assert client.started == []


def test_start_run_checks_live_definition_not_local_summary(deployed_dataverse):
    deployed_dataverse[0]["data"] = "kind: EvaluationSet\ngraders: []\n"
    client = FakeClient()
    with pytest.raises(evaluation_runs.EvaluationMethodError):
        evaluation_runs.start_run(
            client, "environment-id", "bot-id",
            {
                "id": "set-comp", "runnable": True,
                "graders": [{"kind": "CompareMeaningGrader"}],
            },
            "connection",
        )
    assert client.started == []


def test_start_run_blocks_live_review_request_even_if_summary_is_runnable(
    deployed_dataverse,
):
    deployed_dataverse[0]["description"] = compose_review_description(
        "", "review_requested",
    )
    client = FakeClient()
    with pytest.raises(evaluation_runs.EvaluationRunError, match="tagged for review"):
        evaluation_runs.start_run(
            client, "environment-id", "bot-id",
            {"id": "set-comp", "runnable": True}, "connection",
        )
    assert client.started == []


@pytest.mark.parametrize("data", ["not: [yaml", "", "[]"])
def test_start_run_cannot_read_deployed_definition(deployed_dataverse, data):
    deployed_dataverse[0]["data"] = data
    client = FakeClient()
    with pytest.raises(evaluation_runs.EvaluationRunError):
        evaluation_runs.start_run(
            client, "environment-id", "bot-id", {"id": "set-comp"}, "connection",
        )
    assert client.started == []


def test_start_run_rejects_unknown_deployed_id(deployed_dataverse):
    client = FakeClient()
    with pytest.raises(evaluation_runs.EvaluationRunError, match="was not found"):
        evaluation_runs.start_run(
            client, "environment-id", "bot-id", {"id": "other-agent-id"}, "connection",
        )
    assert client.started == []


@pytest.mark.parametrize("run_id", [None, "", "  ", 12, False])
def test_start_run_missing_id_has_no_success_or_link(
    monkeypatch, deployed_dataverse, run_id,
):
    client = FakeClient()
    monkeypatch.setattr(
        client, "run_maker_evaluation_test_set",
        lambda *args: {"runId": run_id, "state": "Queued"},
    )
    with pytest.raises(evaluation_runs.EvaluationRunError, match="run ID"):
        evaluation_runs.start_run(
            client, "environment-id", "bot-id", {"id": "set-comp"}, "connection",
        )


@pytest.mark.parametrize("origin", evaluation_runs.COPILOT_STUDIO_ORIGIN_BY_RING.values())
def test_start_and_completed_run_links_match(origin, deployed_dataverse, tmp_path):
    client = FakeClient()
    started = evaluation_runs.start_run(
        client, "environment-id", "bot-id", {"id": "set-comp"}, "connection",
        studio_origin=origin,
    )
    completed = evaluation_runs.get_run_results(
        client, "environment-id", "bot-id", tmp_path, "run-1", origin,
    )
    assert started["agentStudioUrl"] == completed["agentStudioUrl"]
    assert started["agentStudioUrl"].startswith(origin)
    assert len(client.started) == 1
    assert client.list_runs_calls == 0


def test_agent_studio_url_escapes_identifiers():
    assert evaluation_runs._agent_studio_url(
        "https://copilotstudio.test.microsoft.com",
        "env/x", "bot ?x", "set/#", "run/?", "cosmos&other=true",
    ) == (
        "https://copilotstudio.test.microsoft.com/environments/env%2Fx"
        "/copilots/bot%20%3Fx/evaluation/runsDetails/set%2F%23/run%2F%3F"
        "?agentBackend=cosmos%26other%3Dtrue"
    )


def _write_run_candidate(folder, *, review=None, grader="CompareMeaningGrader"):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "set.mcs.yml").write_text(yaml.safe_dump({
        "kind": "EvaluationSet",
        "displayName": "Compensation",
        "graders": [{"kind": grader, "threshold": 0.7}],
    }), encoding="utf-8")
    (folder / "case.mcs.yml").write_text(yaml.safe_dump({
        "kind": "EvaluationData",
        "rows": [{"input": "My pay?", "expectedOutput": "Check payroll."}],
    }), encoding="utf-8")
    if review:
        (folder / "review.json").write_text(json.dumps({
            "status": review,
        }), encoding="utf-8")


@pytest.fixture
def run_candidates_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    agent = workspace / "agents" / "current"
    config_path = tmp_path / ".local" / "config.json"
    config_path.parent.mkdir()
    config_path.write_text(json.dumps({
        "configVersion": 1,
        "agent": {"folder": str(agent), "botId": "bot-id"},
        "agents": [{"folder": str(workspace / "agents" / "other")}],
    }), encoding="utf-8")
    return workspace, agent, config_path


def test_run_candidates_include_workspace_and_current_agent_without_deployment(
    run_candidates_workspace,
):
    workspace, agent, config = run_candidates_workspace
    folders = [
        workspace / "evaluations" / "arbitrary-name",
        agent / "evaluations" / "general-knowledge-002",
    ]
    for folder in folders:
        _write_run_candidate(folder)
    _write_run_candidate(workspace / "agents" / "other" / "evaluations" / "unrelated")
    orphan = workspace / "evaluations" / "orphan"
    orphan.mkdir()
    (orphan / "case.mcs.yml").write_text("kind: EvaluationData\n", encoding="utf-8")
    before = {
        str(path): path.read_bytes()
        for path in workspace.rglob("*") if path.is_file()
    }
    candidates = evaluation_runs.list_run_candidates(workspace, config, query="comp")
    assert {item["folder"] for item in candidates} == {
        str(folder.resolve()) for folder in folders
    }
    assert all(item["canPrepare"] for item in candidates)
    assert all(not item["currentlyRunnable"] for item in candidates)
    assert all(item["testSetId"] is None for item in candidates)
    assert before == {
        str(path): path.read_bytes()
        for path in workspace.rglob("*") if path.is_file()
    }


@pytest.mark.parametrize(
    ("local_review", "baseline_review", "remote_review", "can_prepare", "runnable"),
    [
        (None, None, None, True, None),
        ("review_requested", "review_requested", "review_requested", False, False),
        (None, None, "review_requested", False, False),
        ("review_completed", "review_requested", "review_requested", True, False),
        ("review_completed", "review_completed", "review_completed", True, None),
        ("review_requested", None, None, False, False),
        ("review_requested", "review_requested", "review_completed", True, None),
    ],
)
def test_run_candidates_reconcile_review_and_deployed_identity(
    run_candidates_workspace, local_review, baseline_review, remote_review,
    can_prepare, runnable,
):
    workspace, agent, config = run_candidates_workspace
    folder = agent / "evaluations" / "pay"
    baseline = agent / ".baseline" / "evaluations" / "pay"
    _write_run_candidate(folder, review=local_review)
    _write_run_candidate(baseline, review=baseline_review)
    (agent / ".component-map.json").write_text(json.dumps({
        "evaluations/pay/set.mcs.yml": {
            "botcomponentid": "actual-deployed-id", "componenttype": 19,
        },
    }), encoding="utf-8")
    remote = {
        "id": "actual-deployed-id", "displayName": "Unimportant service name",
        "description": compose_review_description("", remote_review) if remote_review else "",
        "runnable": True,
    }
    [candidate] = evaluation_runs.list_run_candidates(
        workspace, config, remote_sets=[remote],
    )
    assert candidate["canPrepare"] is can_prepare
    assert candidate["currentlyRunnable"] is runnable
    assert candidate["requiresPreparation"] is True
    if runnable is None:
        assert "current deployed definition" in candidate["readinessReason"]
    assert candidate["testSetId"] == "actual-deployed-id"
    assert candidate["displayName"] == "Compensation"
    assert candidate["source"].startswith("Configured agent:")


@pytest.mark.parametrize("local_status,baseline_status,can_prepare,runnable", [
    ("review_requested", None, False, False),
    ("review_completed", None, True, None),
    ("review_completed", "review_completed", True, None),
    (None, "review_completed", True, None),
])
def test_native_candidates_preserve_local_review_without_new_backend_prerequisites(
    run_candidates_workspace, local_status, baseline_status, can_prepare, runnable,
):
    workspace, agent, config = run_candidates_workspace
    folder = agent / "evaluations" / "pay"
    baseline = agent / ".baseline" / "evaluations" / "pay"
    _write_run_candidate(folder, review=local_status)
    _write_run_candidate(baseline, review=baseline_status)
    (agent / ".component-map.json").write_text(json.dumps({
        "evaluations/pay/set.mcs.yml": {
            "botcomponentid": "deployed-id", "componenttype": 19,
        },
    }), encoding="utf-8")
    [candidate] = evaluation_runs.list_run_candidates(
        workspace, config, remote_sets=[{"id": "deployed-id", "runnable": True}],
        native=True,
    )
    assert candidate["canPrepare"] is can_prepare
    assert candidate["currentlyRunnable"] is runnable
    assert candidate["deployedReviewStatus"] is None
    assert candidate["blockedReason"] == (
        None if can_prepare else evaluation_runs.REVIEW_PENDING_GUIDANCE
    )


def test_run_candidates_dirty_content_must_be_prepared(run_candidates_workspace):
    workspace, agent, config = run_candidates_workspace
    folder = agent / "evaluations" / "pay"
    baseline = agent / ".baseline" / "evaluations" / "pay"
    _write_run_candidate(folder)
    _write_run_candidate(baseline)
    (folder / "case.mcs.yml").write_text(
        "kind: EvaluationData\nrows:\n- input: New question\n  expectedOutput: New answer\n",
        encoding="utf-8",
    )
    (agent / ".component-map.json").write_text(json.dumps({
        "evaluations/pay/set.mcs.yml": {
            "botcomponentid": "actual-deployed-id", "componenttype": 19,
        },
    }), encoding="utf-8")
    [candidate] = evaluation_runs.list_run_candidates(
        workspace, config, remote_sets=[{"id": "actual-deployed-id"}],
    )
    assert candidate["canPrepare"] is True
    assert candidate["currentlyRunnable"] is False
    assert candidate["hasLocalChanges"] is True


@pytest.mark.parametrize("baseline_exists", [False, True])
def test_direct_run_refuses_unprepared_local_content(
    tmp_path, deployed_dataverse, baseline_exists,
):
    folder = tmp_path / "evaluations" / "pay"
    baseline = tmp_path / ".baseline" / "evaluations" / "pay"
    _write_run_candidate(folder)
    if baseline_exists:
        _write_run_candidate(baseline)
        (folder / "case.mcs.yml").write_text(
            "kind: EvaluationData\nrows:\n- input: Edited\n  expectedOutput: Edited answer\n",
            encoding="utf-8",
        )
    before = {path: path.read_bytes() for path in folder.iterdir()}
    client = FakeClient()
    with pytest.raises(evaluation_runs.EvaluationRunError, match="unprepared local changes"):
        evaluation_runs.start_run(
            client, "environment-id", "bot-id",
            {"id": "set-comp", "localFolder": str(folder)}, "connection",
        )
    assert client.started == []
    assert before == {path: path.read_bytes() for path in folder.iterdir()}


def test_direct_run_synchronized_content_preserves_files(tmp_path, deployed_dataverse):
    folder = tmp_path / "evaluations" / "pay"
    baseline = tmp_path / ".baseline" / "evaluations" / "pay"
    _write_run_candidate(folder)
    _write_run_candidate(baseline)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    client = FakeClient()
    result = evaluation_runs.start_run(
        client, "environment-id", "bot-id",
        {"id": "set-comp", "localFolder": str(folder)}, "connection",
    )
    assert result["runId"] == "run-1"
    assert len(client.started) == 1
    assert before == {
        path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()
    }


def test_run_sync_check_matches_deployment_newline_normalization(tmp_path):
    folder = tmp_path / "evaluations" / "pay"
    baseline = tmp_path / ".baseline" / "evaluations" / "pay"
    _write_run_candidate(folder)
    _write_run_candidate(baseline)
    for path in folder.glob("*.mcs.yml"):
        text = path.read_text(encoding="utf-8")
        path.write_bytes(text.encode("utf-8"))
        (baseline / path.name).write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    evaluation_runs._require_synchronized_local_set(folder)
    assert evaluation_runs._set_payload(folder) == evaluation_runs._set_payload(baseline)


def test_run_candidates_policy_failure_remains_visible(run_candidates_workspace):
    workspace, agent, config = run_candidates_workspace
    _write_run_candidate(
        workspace / "evaluations" / "invalid", grader="GeneralQualityGrader",
    )
    [candidate] = evaluation_runs.list_run_candidates(workspace, config)
    assert candidate["canPrepare"] is False
    assert candidate["currentlyRunnable"] is False
    assert "Compare Meaning only" in candidate["blockedReason"]


def test_list_sets_include_local_without_setup_is_read_only(
    monkeypatch, capsys, tmp_path,
):
    monkeypatch.chdir(tmp_path)
    _write_run_candidate(tmp_path / "workspace" / "evaluations" / "pay")
    monkeypatch.setattr(sys, "argv", [
        "evaluation_runs.py", "list-sets", "--include-local",
    ])
    monkeypatch.setattr(
        evaluation_runs, "load_config",
        lambda: pytest.fail("Local discovery must not require setup"),
    )
    monkeypatch.setattr(
        evaluation_runs, "_runtime",
        lambda config: pytest.fail("Local discovery must not connect to a tenant"),
    )
    assert evaluation_runs.main() == 0
    [candidate] = json.loads(capsys.readouterr().out)
    assert candidate["canPrepare"] is True
    assert candidate["currentlyRunnable"] is False
    assert not (tmp_path / ".local").exists()


def test_list_sets_include_local_with_target_does_not_require_component_map(
    monkeypatch, capsys, run_candidates_workspace,
):
    workspace, agent, config = run_candidates_workspace
    _write_run_candidate(agent / "evaluations" / "new-local-set")
    _write_run_candidate(workspace / "evaluations" / "new-workspace-set")
    monkeypatch.chdir(config.parent.parent)
    monkeypatch.setattr(sys, "argv", [
        "evaluation_runs.py", "list-sets", "--include-local",
    ])
    monkeypatch.setattr(
        evaluation_runs, "_runtime",
        lambda config: (FakeClient(), "environment-id", "bot-id", agent),
    )
    assert evaluation_runs.main() == 0
    candidates = json.loads(capsys.readouterr().out)
    assert len(candidates) == 2
    assert all(item["canPrepare"] for item in candidates)
    assert all(item["testSetId"] is None for item in candidates)
    assert not (agent / ".component-map.json").exists()


def test_run_cli_starts_selected_confirmed_id_and_returns_new_link(
    monkeypatch, capsys, tmp_path, deployed_dataverse,
):
    client = FakeClient()
    client.signed_in_username = "maker@example.com"
    config = evaluation_runs.load_config()
    config["powerPlatformApiEndpoint"] = (
        "https://abc123.environment.api.test.powerplatform.com"
    )
    monkeypatch.setattr(
        evaluation_runs, "_runtime",
        lambda config: (client, "environment-id", "bot-id", tmp_path),
    )
    monkeypatch.setattr(
        evaluation_runs, "list_agent_test_sets",
        lambda *args, **kwargs: [
            {"id": "same-name-old-id", "displayName": "Compensation"},
            {"id": "set-comp", "displayName": "Compensation", "runnable": True},
        ],
    )
    monkeypatch.setattr(
        evaluation_runs, "resolve_mcs_connection",
        lambda *args: {"id": "selected-connection"},
    )
    monkeypatch.setattr(evaluation_runs, "resolve_tool_connections", lambda *args: [])
    monkeypatch.setattr(sys, "argv", [
        "evaluation_runs.py", "run", "--test-set-id", "set-comp",
        "--mcs-connection-id", "selected-connection",
    ])
    assert evaluation_runs.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["testSetId"] == "set-comp"
    assert result["runId"] == "run-1"
    assert "/set-comp/run-1" in result["agentStudioUrl"]
    assert result["agentStudioUrl"].startswith("https://copilotstudio.test.microsoft.com")
    assert result["userGuidance"] == evaluation_runs.RUN_WAIT_GUIDANCE
    assert len(client.started) == 1
    assert client.started[0][2] == "set-comp"
    assert list(tmp_path.iterdir()) == []


def test_run_cli_invalid_deployed_method_prints_failure_not_success(
    monkeypatch, capsys, tmp_path, deployed_dataverse,
):
    deployed_dataverse[0]["data"] = "kind: EvaluationSet\ngraders: []\n"
    client = FakeClient()
    client.signed_in_username = "maker@example.com"
    monkeypatch.setattr(
        evaluation_runs, "_runtime",
        lambda config: (client, "environment-id", "bot-id", tmp_path),
    )
    monkeypatch.setattr(
        evaluation_runs, "list_agent_test_sets",
        lambda *args, **kwargs: [{"id": "set-comp", "runnable": True}],
    )
    monkeypatch.setattr(
        evaluation_runs, "resolve_mcs_connection", lambda *args: {"id": "selected"},
    )
    monkeypatch.setattr(evaluation_runs, "resolve_tool_connections", lambda *args: [])
    monkeypatch.setattr(sys, "argv", [
        "evaluation_runs.py", "run", "--test-set-id", "set-comp",
    ])
    assert evaluation_runs.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Compare Meaning only" in captured.err
    assert client.started == []


@pytest.fixture
def prepared_run(monkeypatch, tmp_path, deployed_dataverse):
    import evaluation_deployment

    config = evaluation_runs.load_config()
    agent = tmp_path / "workspace" / "agents" / "current"
    source = tmp_path / "workspace" / "evaluations" / "pay"
    destination = agent / "evaluations" / "pay"
    config["agent"]["folder"] = str(agent)
    _write_run_candidate(source)
    _write_run_candidate(destination)
    _write_run_candidate(agent / ".baseline" / "evaluations" / "pay")
    deployment = {
        "status": "pushed", "backend": "dataverse", "action": "run",
        "environmentId": "environment-id", "botId": "bot-id",
        "sets": [{
            "sourceFolder": str(source),
            "agentSetFolder": str(destination),
            "testSetId": "set-comp", "deployedReviewStatus": None,
        }],
    }
    calls = []

    def deploy(set_folder, **kwargs):
        calls.append((set_folder, kwargs))
        return deployment

    monkeypatch.setattr(evaluation_deployment, "deploy_evaluation_set", deploy)
    client = FakeClient()
    client.signed_in_username = "maker@example.com"
    monkeypatch.setattr(
        evaluation_runs, "_runtime",
        lambda config: (client, "environment-id", "bot-id", agent),
    )
    monkeypatch.setattr(
        evaluation_runs, "list_agent_test_sets",
        lambda *args, **kwargs: [
            {"id": "old-same-name", "displayName": "Compensation"},
            {"id": "set-comp", "displayName": "Compensation",
             "localFolder": str(destination), "runnable": True},
        ],
    )

    def connection(config, environment_id, requested_id, username):
        assert requested_id == "selected-profile"
        return {"id": requested_id}

    monkeypatch.setattr(evaluation_runs, "resolve_mcs_connection", connection)
    monkeypatch.setattr(evaluation_runs, "resolve_tool_connections", lambda *args: [])
    args = argparse.Namespace(
        set_folder=str(source), confirmation_token="confirmed-preview-token",
        yes=True, force_delete=False, replace=False, run_name=None,
        published=False, mcs_connection_id="selected-profile",
    )
    return args, config, deployment, client, calls


@pytest.mark.parametrize("status", ["pushed", "up_to_date"])
def test_prepared_run_consumes_verified_actual_id_once(prepared_run, capsys, status):
    args, config, deployment, client, calls = prepared_run
    deployment["status"] = status
    assert evaluation_runs._prepared_run_command(args, config) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["deployment"] == deployment
    assert result["testSetId"] == "set-comp"
    assert result["runId"] == "run-1"
    assert result["agentStudioUrl"].endswith("/set-comp/run-1")
    assert result["userGuidance"] == evaluation_runs.RUN_WAIT_GUIDANCE
    assert len(client.started) == 1
    assert client.started[0][2] == "set-comp"
    assert calls == [(args.set_folder, {
        "action": "run", "confirmation_token": "confirmed-preview-token",
        "yes": True, "force_delete": False, "replace": False, "config": config,
    })]


def test_prepared_dataverse_run_matches_active_environment_precedence(prepared_run, capsys):
    args, config, deployment, client, calls = prepared_run
    config["environmentId"] = "stale-global-environment"
    config["agent"]["environmentId"] = deployment["environmentId"]
    assert evaluation_runs._prepared_run_command(args, config) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["deployment"]["environmentId"] == "environment-id"
    assert "/environments/environment-id/" in result["agentStudioUrl"]
    assert client.started[0][0] == "environment-id"


@pytest.mark.parametrize("status", ["cancelled", "blocked", "failed", "ready", None])
def test_prepared_run_never_treats_non_success_as_success(
    prepared_run, monkeypatch, capsys, status,
):
    args, config, deployment, client, calls = prepared_run
    deployment["status"] = status
    deployment["error"] = "Preparation did not complete"
    monkeypatch.setattr(
        evaluation_runs, "_runtime",
        lambda config: pytest.fail("Do not enter runtime after unsuccessful preparation"),
    )
    assert evaluation_runs._prepared_run_command(args, config) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["stage"] == "deployment"
    assert result["deployment"]["status"] == status
    assert "runId" not in result
    assert "agentStudioUrl" not in result
    assert len(calls) == 1
    assert client.started == []


@pytest.mark.parametrize("field,value", [
    ("environmentId", "another-environment"),
    ("botId", "another-agent"),
    ("backend", "minimalbot"),
    ("action", "request-review"),
])
def test_prepared_run_rejects_changed_target_or_action(
    prepared_run, capsys, field, value,
):
    args, config, deployment, client, calls = prepared_run
    deployment[field] = value
    assert evaluation_runs._prepared_run_command(args, config) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "run_failed"
    assert client.started == []
    assert len(calls) == 1


@pytest.mark.parametrize("fault", [
    "missing-set", "multiple-sets", "missing-id", "different-source", "different-destination",
])
def test_prepared_run_refuses_ambiguous_or_changed_identity(prepared_run, capsys, fault):
    args, config, deployment, client, calls = prepared_run
    if fault == "missing-set":
        deployment["sets"] = []
    elif fault == "multiple-sets":
        deployment["sets"].append(dict(deployment["sets"][0]))
    elif fault == "missing-id":
        deployment["sets"][0]["testSetId"] = ""
    elif fault == "different-source":
        deployment["sets"][0]["sourceFolder"] += "-other"
    else:
        deployment["sets"][0]["agentSetFolder"] += "-other"
    assert evaluation_runs._prepared_run_command(args, config) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "run_failed"
    assert "agentStudioUrl" not in result
    assert client.started == []
    assert len(calls) == 1


def test_prepared_run_reports_deployment_separately_if_connection_blocks(
    prepared_run, monkeypatch, capsys,
):
    args, config, deployment, client, calls = prepared_run

    def blocked(*args):
        raise evaluation_runs.EvaluationRunError("Selected connection is disconnected")

    monkeypatch.setattr(evaluation_runs, "resolve_mcs_connection", blocked)
    assert evaluation_runs._prepared_run_command(args, config) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "run_failed"
    assert result["deployment"]["status"] == "pushed"
    assert "disconnected" in result["error"]
    assert "Check for an existing run" in result["userGuidance"]
    assert "agentStudioUrl" not in result
    assert client.started == []
    assert len(calls) == 1


def test_prepared_run_transport_failure_is_not_retried(prepared_run, capsys):
    args, config, deployment, client, calls = prepared_run

    def timeout(*args):
        client.started.append(args)
        raise evaluation_runs.requests.Timeout("Run start response timed out")

    client.run_maker_evaluation_test_set = timeout
    assert evaluation_runs._prepared_run_command(args, config) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["deployment"]["status"] == "pushed"
    assert result["status"] == "run_failed"
    assert "timed out" in result["error"]
    assert "runId" not in result
    assert len(client.started) == 1
    assert len(calls) == 1


def test_run_prepared_cli_forwards_explicit_authorization(prepared_run, monkeypatch, capsys):
    args, config, deployment, client, calls = prepared_run
    monkeypatch.setattr(sys, "argv", [
        "evaluation_runs.py", "run-prepared", "--set-folder", args.set_folder,
        "--confirmation-token", args.confirmation_token, "--yes",
        "--mcs-connection-id", "selected-profile", "--replace", "--force-delete",
    ])
    assert evaluation_runs.main() == 0
    assert json.loads(capsys.readouterr().out)["testSetId"] == "set-comp"
    assert calls[0][1]["replace"] is True
    assert calls[0][1]["force_delete"] is True
    assert calls[0][1]["confirmation_token"] == "confirmed-preview-token"
    assert len(client.started) == 1


def _connection(
    connection_id,
    *,
    status="Connected",
    account_name=None,
    created_by_upn=None,
    last_modified=None,
):
    return {
        "name": connection_id,
        "properties": {
            "displayName": f"Profile {connection_id}",
            "accountName": account_name,
            "createdBy": {"userPrincipalName": created_by_upn},
            "statuses": [{"status": status}],
            "lastModifiedTime": last_modified,
        },
    }


def test_select_mcs_connection_rejects_no_connected_profiles():
    connections = [
        _connection("broken", status="Error"),
        _connection("disabled", status="Disconnected"),
    ]

    try:
        evaluation_runs.select_mcs_connection(connections)
    except evaluation_runs.EvaluationRunError as exc:
        assert "No Connected" in str(exc)
    else:
        raise AssertionError("Expected missing connection to block the run")


def test_select_mcs_connection_uses_only_connected_profile():
    selected = evaluation_runs.select_mcs_connection([
        _connection("broken", status="Error"),
        _connection("connected"),
    ])

    assert selected["id"] == "connected"


def test_select_mcs_connection_matches_signed_in_account():
    selected = evaluation_runs.select_mcs_connection(
        [
            _connection(
                "other",
                created_by_upn="other@example.com",
            ),
            _connection(
                "current",
                account_name="maker@example.com",
            ),
        ],
        signed_in_username="maker@example.com",
    )

    assert selected["id"] == "current"


def test_select_mcs_connection_uses_latest_profile_for_signed_in_account():
    selected = evaluation_runs.select_mcs_connection(
        [
            _connection(
                "older",
                account_name="maker@example.com",
                last_modified="2026-08-01T00:00:00Z",
            ),
            _connection(
                "newer",
                account_name="maker@example.com",
                last_modified="2026-09-01T00:00:00Z",
            ),
            _connection(
                "other",
                account_name="other@example.com",
                last_modified="2026-09-02T00:00:00Z",
            ),
        ],
        signed_in_username="maker@example.com",
    )

    assert selected["id"] == "newer"


def test_select_mcs_connection_rejects_ambiguous_profiles():
    connections = [
        _connection("second", created_by_upn="two@example.com"),
        _connection("first", created_by_upn="one@example.com"),
    ]

    with pytest.raises(
        evaluation_runs.EvaluationRunError,
        match="Multiple Connected",
    ):
        evaluation_runs.select_mcs_connection(
            connections,
            signed_in_username="maker@example.com",
        )


def test_select_mcs_connection_validates_explicit_profile_status():
    connections = [
        _connection("broken", status="Error"),
        _connection("connected"),
    ]

    try:
        evaluation_runs.select_mcs_connection(
            connections,
            requested_id="broken",
        )
    except evaluation_runs.EvaluationRunError as exc:
        assert "not Connected" in str(exc)
    else:
        raise AssertionError("Expected an invalid explicit profile to fail")


def test_resolve_mcs_connection_uses_ppapi_signed_in_account(monkeypatch):
    observed = {}

    class FakeAdminClient:
        signed_in_username = "maker@example.com"

        def __init__(self, tenant_id):
            observed["tenantId"] = tenant_id

        def authenticate(self, **kwargs):
            observed["authenticate"] = kwargs

        def get_connector_connections(self, environment_id, connector_name):
            return [
                _connection("other", account_name="other@example.com"),
                _connection("current", account_name="maker@example.com"),
            ]

    monkeypatch.setattr(
        evaluation_runs,
        "discover_tenant",
        lambda env_url: "tenant-id",
    )
    monkeypatch.setattr(evaluation_runs, "PPAdminClient", FakeAdminClient)

    selected = evaluation_runs.resolve_mcs_connection(
        {"dataverseEndpoint": "https://example.crm.dynamics.com"},
        "environment-id",
        signed_in_username="maker@example.com",
    )

    assert selected["id"] == "current"
    assert observed["authenticate"] == {
        "include_bap": False,
        "include_flow": False,
        "preferred_username": "maker@example.com",
    }


def test_list_mcs_connections_marks_signed_in_profile(monkeypatch):
    monkeypatch.setattr(
        evaluation_runs,
        "_discover_mcs_connections",
        lambda *args, **kwargs: (
            [
                _connection(
                    "current",
                    account_name="maker@example.com",
                ),
                _connection(
                    "other",
                    account_name="other@example.com",
                ),
            ],
            "maker@example.com",
        ),
    )

    connections = evaluation_runs.list_mcs_connections(
        {"dataverseEndpoint": "https://example.crm.dynamics.com"},
        "environment-id",
    )

    assert [item["id"] for item in connections] == ["current", "other"]
    assert connections[0]["matchesSignedInAccount"] is True
    assert connections[1]["matchesSignedInAccount"] is False


def test_list_connections_command_prints_selectable_profiles(
    monkeypatch,
    capsys,
    tmp_path,
):
    client = FakeClient()
    client.signed_in_username = "maker@example.com"
    monkeypatch.setattr(
        sys,
        "argv",
        ["evaluation_runs.py", "list-connections"],
    )
    monkeypatch.setattr(evaluation_runs, "load_config", lambda: {})
    monkeypatch.setattr(
        evaluation_runs,
        "_runtime",
        lambda config: (
            client,
            "environment-id",
            "bot-id",
            tmp_path,
        ),
    )
    monkeypatch.setattr(
        evaluation_runs,
        "list_mcs_connections",
        lambda *args, **kwargs: [{
            "id": "connection-id",
            "displayName": "Maker profile",
            "matchesSignedInAccount": True,
        }],
    )

    assert evaluation_runs.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output[0]["id"] == "connection-id"


def test_resolve_tool_connections_uses_signed_in_account(
    monkeypatch,
    tmp_path,
):
    installation = tmp_path / "config.json"
    installation.write_text(
        json.dumps({
            "installations": {
                "cea.it": {
                    "requiredConnection": {
                        "connectorApiName": "shared_alchemy",
                        "referenceLogicalName": (
                            "contoso_agent.shared_alchemy.reference"
                        ),
                    }
                }
            }
        }),
        encoding="utf-8",
    )
    observed = {}

    class FakeAdminClient:
        signed_in_username = "maker@example.com"

        def __init__(self, tenant_id):
            pass

        def authenticate(self, **kwargs):
            observed["authenticate"] = kwargs

        def get_connector_connections(self, environment_id, connector_name):
            assert connector_name == "shared_alchemy"
            return [
                _connection("other", account_name="other@example.com"),
                _connection("current", account_name="maker@example.com"),
            ]

    monkeypatch.setattr(
        evaluation_runs,
        "INSTALLATION_CONFIG_PATH",
        installation,
    )
    monkeypatch.setattr(
        evaluation_runs,
        "discover_tenant",
        lambda env_url: "tenant-id",
    )
    monkeypatch.setattr(evaluation_runs, "PPAdminClient", FakeAdminClient)

    result = evaluation_runs.resolve_tool_connections(
        {
            "dataverseEndpoint": "https://example.crm.dynamics.com",
            "agent": {"schemaName": "contoso_agent"},
        },
        "environment-id",
        "bot-id",
        "maker@example.com",
    )

    assert result == [{
        "botId": "bot-id",
        "botSchemaName": "contoso_agent",
        "connections": [{
            "connectorId": "shared_alchemy",
            "connectionId": "current",
            "connectionReferenceName": (
                "contoso_agent.shared_alchemy.reference"
            ),
        }],
    }]
    assert observed["authenticate"] == {
        "include_bap": False,
        "include_flow": False,
        "preferred_username": "maker@example.com",
    }


def test_resolve_tool_connections_does_not_require_unrelated_profile(
    monkeypatch,
    tmp_path,
):
    installation = tmp_path / "config.json"
    installation.write_text(
        json.dumps({
            "installations": {
                "cea.it": {
                    "requiredConnection": {
                        "connectorApiName": "shared_service-now",
                        "referenceLogicalName": (
                            "contoso_agent.shared_service-now.reference"
                        ),
                    }
                }
            }
        }),
        encoding="utf-8",
    )

    class FakeAdminClient:
        signed_in_username = "maker@example.com"

        def __init__(self, tenant_id):
            pass

        def authenticate(self, **kwargs):
            pass

        def get_connector_connections(self, environment_id, connector_name):
            return []

    monkeypatch.setattr(
        evaluation_runs,
        "INSTALLATION_CONFIG_PATH",
        installation,
    )
    monkeypatch.setattr(
        evaluation_runs,
        "discover_tenant",
        lambda env_url: "tenant-id",
    )
    monkeypatch.setattr(evaluation_runs, "PPAdminClient", FakeAdminClient)

    result = evaluation_runs.resolve_tool_connections(
        {
            "dataverseEndpoint": "https://example.crm.dynamics.com",
            "agent": {"schemaName": "contoso_agent"},
        },
        "environment-id",
        "bot-id",
        "maker@example.com",
    )

    assert result == []


def test_list_runs_uses_remote_api_and_joins_test_set_name():
    client = FakeClient()

    runs = evaluation_runs.list_runs(
        client,
        "environment-id",
        "bot-id",
    )

    assert runs[0]["runId"] == "remote-run"
    assert runs[0]["testSetName"] == "Benefits and Leave"
    assert runs[0]["source"] == "Power Platform API"
    assert client.list_runs_calls == 1


def test_get_results_enriches_local_test_case_and_set_names(tmp_path):
    (tmp_path / ".component-map.json").write_text(
        json.dumps({
            "evaluations/compensation/base-pay.mcs.yml": {
                "botcomponentid": "case-1",
                "parentbotcomponentid": "set-comp",
                "componenttype": 19,
                "name": "Base pay",
            }
        }),
        encoding="utf-8",
    )
    result = evaluation_runs.get_run_results(
        FakeClient(),
        "environment-id",
        "bot-id",
        tmp_path,
        "run-1",
    )

    assert result["testSetName"] == "Compensation"
    assert result["testCasesResults"][0]["testCaseName"] == "Base pay"
    assert result["analysis"]["summary"] == {
        "totalCases": 1,
        "passedCases": 1,
        "failedCases": 0,
        "passRate": 100.0,
    }
    assert result["analysis"]["scenarioGroups"][0]["group"] == "Compensation"


def test_get_results_preserves_unmapped_test_case_id(tmp_path):
    result = evaluation_runs.get_run_results(
        FakeClient(),
        "environment-id",
        "bot-id",
        tmp_path,
        "run-1",
    )

    assert result["testCasesResults"][0]["testCaseName"] == "case-1"


def test_get_results_joins_remote_test_set_name_without_local_history(tmp_path):
    result = evaluation_runs.get_run_results(
        FakeClient(),
        "environment-id",
        "bot-id",
        tmp_path,
        "run-1",
    )

    assert result["testSetName"] == "Compensation"


def test_analyze_run_results_groups_ai_reason_and_general_quality_failures():
    result = {
        "testSetName": "Compensation",
        "testCasesResults": [
            {
                "testCaseName": "Comp Ratio",
                "metricsResults": [{
                    "type": "CompareMeaning",
                    "result": {
                        "status": "Fail",
                        "aiResultReason": (
                            "The agent returned an error instead of the ratio."
                        ),
                    },
                }],
            },
            {
                "testCaseName": "Privacy",
                "metricsResults": [
                    {
                        "type": "GeneralQuality",
                        "result": {
                            "status": "Fail",
                            "data": {
                                "abstention": "Yes",
                                "completeness": "No",
                            },
                        },
                    },
                    {
                        "type": "CompareMeaning",
                        "result": {
                            "status": "Pass",
                            "aiResultReason": (
                                "The refusal matches the expected response."
                            ),
                        },
                    },
                ],
            },
            {
                "testCaseName": "Base Comp",
                "metricsResults": [{
                    "type": "CompareMeaning",
                    "result": {"status": "Pass"},
                }],
            },
        ],
    }

    analysis = evaluation_runs.analyze_run_results(result)

    assert analysis["summary"] == {
        "totalCases": 3,
        "passedCases": 1,
        "failedCases": 2,
        "passRate": 33.3,
    }
    assert analysis["scenarioGroups"] == [{
        "group": "Compensation",
        "cases": 3,
        "passed": 1,
        "failed": 2,
        "passRate": 33.3,
    }]
    assert {
        item["category"] for item in analysis["failureGroups"]
    } == {
        "Expected-meaning mismatch",
        "Abstention graded incomplete",
    }
    assert any(
        "returned an error" in item["representativeEvidence"]
        for item in analysis["failureGroups"]
    )


def test_analyze_run_results_treats_no_metrics_case_as_non_pass():
    """A completed case that produced no metric results must not be counted
    as a silent pass — it cannot be verified, so it is surfaced for review."""
    result = {
        "testSetName": "Compensation",
        "testCasesResults": [
            {
                "testCaseName": "No metrics",
                "state": "Completed",
                "metricsResults": [],
            },
            {
                "testCaseName": "Real pass",
                "state": "Completed",
                "metricsResults": [{
                    "type": "CompareMeaning",
                    "result": {"status": "Pass"},
                }],
            },
        ],
    }

    analysis = evaluation_runs.analyze_run_results(result)

    assert analysis["summary"] == {
        "totalCases": 2,
        "passedCases": 1,
        "failedCases": 1,
        "passRate": 50.0,
    }
    assert any(
        item["category"] == "Execution or metric failure"
        for item in analysis["failureGroups"]
    )
