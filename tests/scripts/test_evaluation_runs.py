from __future__ import annotations

import json
import sys
from pathlib import Path


SCRIPTS = (
    Path(__file__).resolve().parents[2]
    / "solutions"
    / "ess-maker-skills"
    / "scripts"
)
sys.path.insert(0, str(SCRIPTS))

import evaluation_runs  # noqa: E402


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
                "metricsResults": [],
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
    evaluations.mkdir(parents=True)
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


def test_list_agent_test_sets_allows_unknown_review_status(tmp_path):
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

    sets = evaluation_runs.list_agent_test_sets(
        FakeClient(),
        "environment-id",
        "bot-id",
        tmp_path,
    )

    assert [item["id"] for item in sets] == ["set-comp"]
    assert sets[0]["reviewStatus"] == "unknown"


def test_start_run_returns_api_details_without_local_mapping(tmp_path):
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
    assert result["userGuidance"] == (
        "Running your evaluation may take a while. Please return in 10-15 "
        "minutes to see the results."
    )
    assert client.started[0][3]["runOnPublishedBot"] is False
    assert client.started[0][3]["mcsConnectionId"] == "connection-1"
    assert not (tmp_path / "evaluations" / "runs.json").exists()


def _connection(
    connection_id,
    *,
    status="Connected",
    account_name=None,
    created_by_upn=None,
):
    return {
        "name": connection_id,
        "properties": {
            "displayName": f"Profile {connection_id}",
            "accountName": account_name,
            "createdBy": {"userPrincipalName": created_by_upn},
            "statuses": [{"status": status}],
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


def test_select_mcs_connection_uses_deterministic_valid_profile_when_ambiguous():
    connections = [
        _connection("second", created_by_upn="two@example.com"),
        _connection("first", created_by_upn="one@example.com"),
    ]

    selected = evaluation_runs.select_mcs_connection(
        connections,
        signed_in_username="maker@example.com",
    )

    assert selected["id"] == "first"


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
