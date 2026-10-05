# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Focused contracts for the independent Workday DA readiness checks."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest
import responses
import requests

from flightcheck.checks import workday_da
from minimalbot_evaluation import reviewed_workday_topic_schemas
from tests.conftest import require_validated_mock
from tests.mocks import agentbuilder_connectivity as ab
from tests.mocks import dataverse as dv
from tests.mocks import pp_admin as pp


require_validated_mock(ab)
require_validated_mock(dv)
require_validated_mock(pp)

SCHEMA = "gptagent_copilotforemployeeselfservicehr"
BOT_ID = "00000000-0000-0000-0000-000000001111"
ENV_URL = "https://orgmocktenant.crm.dynamics.com"
TEAM_ID = "00000000-0000-0000-0000-000000007777"
FLOW_IDS = {
    "ESS Workday Runtime References":
        "00000000-0000-0000-0000-000000007101",
    "ESS Workday Runtime REST Execution":
        "00000000-0000-0000-0000-000000007102",
    "ESS Workday Runtime":
        "00000000-0000-0000-0000-000000007103",
}


def _config() -> dict[str, Any]:
    return {
        "activeAgent": "ess-hr",
        "agents": [{
            "slug": "ess-hr",
            "schemaName": SCHEMA,
            "botId": BOT_ID,
        }],
    }


def _flows(*, inactive: str = "", omit: str = "") -> list[dict[str, Any]]:
    return [
        {
            "workflowid": flow_id,
            "name": name,
            "statecode": 0 if name == inactive else 1,
            "statuscode": 1 if name == inactive else 2,
            "category": 5,
        }
        for name, flow_id in FLOW_IDS.items()
        if name != omit
    ]


def _component(
    schema_name: str,
    *,
    dialog: dict[str, Any] | None = None,
    status: str = "Active",
) -> dict[str, Any]:
    return ab.dialog_component_change(
        schema_name=schema_name,
        dialog=dialog,
        status=status,
    )


def _component_payload(
    *,
    missing: str = "",
    inactive: str = "",
    obsolete_user_context_call: bool = False,
    misplaced_runtime_call: bool = False,
    diagnostic_schema: str = "",
) -> dict[str, Any]:
    runtime_schema = (
        f"{SCHEMA}.topic.WorkdaySystemSetRuntimeTemplateConfigurations"
    )
    user_context_schema = f"{SCHEMA}.topic.WorkdaySystemGetUserContextV2"
    conversation_schema = f"{SCHEMA}.topic.ConversationStart"
    changes = [
        _component(
            schema_name,
            status="Inactive" if schema_name == inactive else "Active",
        )
        for schema_name in reviewed_workday_topic_schemas(SCHEMA)
        if schema_name != missing
    ]
    changes = [
        change for change in changes
        if change["component"]["schemaName"] not in {
            runtime_schema,
            user_context_schema,
        }
    ]
    changes.extend([
        _component(
            runtime_schema,
            status="Inactive" if runtime_schema == inactive else "Active",
        ),
        _component(
            user_context_schema,
            dialog={
                "$kind": "AdaptiveDialog",
                "beginDialog": {
                    "$kind": "OnRedirect",
                    "actions": (
                        [{
                            "$kind": "BeginDialog",
                            "dialog": {
                                "$kind": "DialogExpression",
                                "literalValue": runtime_schema,
                            },
                        }]
                        if obsolete_user_context_call
                        else []
                    ),
                },
            },
            status="Inactive" if user_context_schema == inactive else "Active",
        ),
        _component(
            conversation_schema,
            dialog={
                "$kind": "AdaptiveDialog",
                "beginDialog": {
                    "$kind": "OnConversationStart",
                    "actions": (
                        [
                            {
                                "$kind": "BeginDialog",
                                "dialog": {
                                    "$kind": "DialogExpression",
                                    "literalValue": runtime_schema,
                                },
                            },
                            {
                                "$kind": "SendActivity",
                                "activity": "Welcome",
                            },
                            {
                                "$kind": "BeginDialog",
                                "dialog": {
                                    "$kind": "DialogExpression",
                                    "literalValue": (
                                        f"{SCHEMA}.topic."
                                        "System-UserContext-Validate"
                                    ),
                                },
                            },
                        ]
                        if misplaced_runtime_call
                        else [
                            {
                                "$kind": "BeginDialog",
                                "dialog": {
                                    "$kind": "DialogExpression",
                                    "literalValue": (
                                        f"{SCHEMA}.topic."
                                        "System-UserContext-"
                                        "Createglobalvariables"
                                    ),
                                },
                            },
                            {
                                "$kind": "SendActivity",
                                "activity": "Welcome",
                            },
                            {
                                "$kind": "BeginDialog",
                                "dialog": {
                                    "$kind": "DialogExpression",
                                    "literalValue": runtime_schema,
                                },
                            },
                            {
                                "$kind": "BeginDialog",
                                "dialog": {
                                    "$kind": "DialogExpression",
                                    "literalValue": (
                                        f"{SCHEMA}.topic."
                                        "System-UserContext-Validate"
                                    ),
                                },
                            },
                        ]
                    ),
                },
            },
            status="Inactive" if conversation_schema == inactive else "Active",
        ),
    ])
    for change in changes:
        component = change["component"]
        if component["schemaName"] == diagnostic_schema:
            component["dialog"].setdefault("diagnostics", []).append({
                "$kind": "InvalidReferenceError",
                "errorCode": "NotFound",
                "errorMessage": "CloudFlow not found",
                "referenceType": "CloudFlow",
                "referenceId": FLOW_IDS["ESS Workday Runtime"],
            })
    return ab.dialog_components(changes)


class _AgentBuilder:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.requested_bot_id = ""
        self.fetch_count = 0

    def fetch_components(self, bot_id: str) -> dict[str, Any]:
        self.requested_bot_id = bot_id
        self.fetch_count += 1
        return deepcopy(self.payload)


def _runner(**overrides: Any) -> SimpleNamespace:
    values = {
        "config": _config(),
        "agent_slug": "ess-hr",
        "_all_flows": _flows(),
        "pp_admin": object(),
        "env_id": pp.MOCK_ENV_ID,
        "env_url": ENV_URL,
        "dv_token": "token",
        "agentbuilder": _AgentBuilder(_component_payload()),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_runtime_flow_catalog_passes_exact_active_inventory(monkeypatch) -> None:
    monkeypatch.setattr(workday_da, "query_all", lambda *_a, **_k: _flows())
    row = workday_da._check_runtime_flow_catalog(_runner())[0]

    assert row.status == "Passed"
    assert "All 3 reviewed Workday runtime flows" in row.result
    assert set(row.evidence["flows"]) == set(FLOW_IDS)
    assert row.remediation == ""


def test_runtime_flow_catalog_fails_missing_and_inactive_flows(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        workday_da,
        "query_all",
        lambda *_a, **_k: _flows(
            omit="ESS Workday Runtime References",
            inactive="ESS Workday Runtime",
        ),
    )

    row = workday_da._check_runtime_flow_catalog(_runner())[0]

    assert row.status == "Failed"
    assert "missing: ESS Workday Runtime References" in row.result
    assert "inactive: ESS Workday Runtime" in row.result
    assert "activate each flow" in row.remediation


def test_runtime_flow_catalog_errors_without_dataverse_access() -> None:
    row = workday_da._check_runtime_flow_catalog(
        _runner(env_url=None, dv_token=None)
    )[0]

    assert row.status == "Error"
    assert "Dataverse access is unavailable" in row.result
    assert "Dataverse access" in row.remediation


def test_runtime_flow_catalog_errors_on_missing_flow_id(monkeypatch) -> None:
    flows = _flows()
    flows[0]["workflowid"] = ""
    monkeypatch.setattr(workday_da, "query_all", lambda *_a, **_k: flows)

    row = workday_da._check_runtime_flow_catalog(_runner())[0]

    assert row.status == "Error"
    assert "badly formed hexadecimal UUID" in row.result


def test_reviewed_topics_pass_complete_active_inventory() -> None:
    runner = _runner()

    row = workday_da._check_reviewed_workday_topics(runner)[0]

    assert row.status == "Passed"
    assert row.evidence["expected"] == len(
        reviewed_workday_topic_schemas(SCHEMA)
    )
    assert runner.agentbuilder.requested_bot_id == BOT_ID
    assert row.remediation == ""


def test_reviewed_topics_fail_missing_and_inactive_components() -> None:
    expected = sorted(reviewed_workday_topic_schemas(SCHEMA))
    runner = _runner(agentbuilder=_AgentBuilder(_component_payload(
        missing=expected[0],
        inactive=expected[1],
    )))

    row = workday_da._check_reviewed_workday_topics(runner)[0]

    assert row.status == "Failed"
    assert expected[0] in row.result
    assert expected[1] in row.result
    assert "Restore the Microsoft-shipped Workday topics" in row.remediation


def test_reviewed_topics_record_dependency_diagnostics_without_failing() -> None:
    expected = sorted(reviewed_workday_topic_schemas(SCHEMA))
    runner = _runner(agentbuilder=_AgentBuilder(_component_payload(
        diagnostic_schema=expected[0],
    )))

    row = workday_da._check_reviewed_workday_topics(runner)[0]

    assert row.status == "Passed"
    assert row.evidence["diagnosticTopics"] == [expected[0]]


def test_reviewed_topics_skip_without_agentbuilder() -> None:
    row = workday_da._check_reviewed_workday_topics(
        _runner(agentbuilder=None)
    )[0]

    assert row.status == "Skipped"
    assert "unavailable" in row.result
    assert "Authenticate to AgentBuilder" in row.remediation


def test_component_transport_failure_stays_checkpoint_scoped() -> None:
    class FailingAgentBuilder:
        def fetch_components(self, _bot_id: str) -> dict[str, Any]:
            raise requests.Timeout("backend details")

    runner = _runner(agentbuilder=FailingAgentBuilder())
    runner.should_execute = lambda checkpoint_id: checkpoint_id in {
        "WD-DA-TOPIC-001",
        "WD-DA-WIRING-001",
    }

    rows = workday_da.run_workday_da_checks(runner)

    assert [row.status for row in rows] == ["Error", "Error"]
    assert all("backend details" not in row.result for row in rows)


def test_agentbuilder_components_are_cached_across_checks() -> None:
    runner = _runner()

    topic_row = workday_da._check_reviewed_workday_topics(runner)[0]
    wiring_row = workday_da._check_runtime_template_wiring(runner)[0]

    assert topic_row.status == "Passed"
    assert wiring_row.status == "Passed"
    assert runner.agentbuilder.fetch_count == 1


def test_invalid_bot_id_is_an_explicit_component_error() -> None:
    config = _config()
    config["agents"][0]["botId"] = "not-a-guid"

    row = workday_da._check_reviewed_workday_topics(
        _runner(config=config)
    )[0]

    assert row.status == "Error"
    assert "schema and bot ID could not be resolved" in row.result


def test_da_dispatcher_executes_only_requested_checkpoint() -> None:
    runner = _runner()
    runner.should_execute = (
        lambda checkpoint_id: checkpoint_id == "WD-DA-TOPIC-001"
    )

    rows = workday_da.run_workday_da_checks(runner)

    assert [row.checkpoint_id for row in rows] == ["WD-DA-TOPIC-001"]


def test_runtime_template_wiring_passes_reviewed_chain() -> None:
    row = workday_da._check_runtime_template_wiring(_runner())[0]

    assert row.status == "Passed"
    assert "immediately before User Context Validate" in row.result
    assert row.remediation == ""


def test_runtime_template_wiring_fails_wrong_conversation_start_position() -> None:
    runner = _runner(agentbuilder=_AgentBuilder(_component_payload(
        misplaced_runtime_call=True
    )))

    row = workday_da._check_runtime_template_wiring(runner)[0]

    assert row.status == "Failed"
    assert row.evidence["runtimePrecedesValidation"] is False
    assert "immediately before User Context Validate" in row.result


def test_runtime_template_wiring_fails_obsolete_nested_call() -> None:
    runner = _runner(agentbuilder=_AgentBuilder(_component_payload(
        obsolete_user_context_call=True
    )))

    row = workday_da._check_runtime_template_wiring(runner)[0]

    assert row.status == "Failed"
    assert row.evidence["userContextContainsTarget"] is True
    assert "remove the obsolete User Context V2 nested call" in row.remediation


def test_runtime_template_wiring_fails_inactive_conversation_start() -> None:
    conversation_schema = f"{SCHEMA}.topic.ConversationStart"
    runner = _runner(agentbuilder=_AgentBuilder(_component_payload(
        inactive=conversation_schema,
    )))

    row = workday_da._check_runtime_template_wiring(runner)[0]

    assert row.status == "Failed"
    assert conversation_schema in row.evidence["inactiveComponents"]


def test_runtime_template_wiring_records_dependency_diagnostics() -> None:
    conversation_schema = f"{SCHEMA}.topic.ConversationStart"
    runner = _runner(agentbuilder=_AgentBuilder(_component_payload(
        diagnostic_schema=conversation_schema,
    )))

    row = workday_da._check_runtime_template_wiring(runner)[0]

    assert row.status == "Passed"
    assert len(row.evidence["blockingDiagnostics"]) == 1


def test_agent_flow_attachment_is_explicit_manual_contract() -> None:
    row = workday_da._check_agent_flow_attachment(_runner())[0]

    assert row.status == "Manual"
    assert row.priority == "High"
    assert set(row.evidence["expectedFlowNames"]) == {
        "ESS Workday Runtime",
        "ESS Workday Runtime REST Execution",
    }
    assert "Allow permission to share parameters" in row.remediation


@responses.activate
def test_delegated_authorization_passes_exact_team_and_shares(
    monkeypatch,
) -> None:
    runtime = workday_da._load_runtime_contract()
    by_name = {
        name.casefold(): [
            {
                "workflowid": FLOW_IDS[name],
                "name": name,
                "statecode": 1,
                "statuscode": 2,
            }
        ]
        for name in runtime["flowNames"]
    }
    monkeypatch.setattr(
        workday_da,
        "_runtime_flow_inventory",
        lambda _runner: (runtime, by_name),
    )
    responses.add(**dv.query(
        base_url=ENV_URL,
        entity_set="delegatedauthorizations",
        records=[dv.delegated_authorization(bot_id=BOT_ID)],
        select="delegatedauthorizationid,name,providertype,botid",
        filter_expr=f"botid eq '{BOT_ID}'",
    ))
    responses.add(**dv.teams_for_delegated_authorization(
        base_url=ENV_URL,
        bot_id=BOT_ID,
        teams=[dv.delegated_access_team(team_id=TEAM_ID)],
    ))
    for flow_name in runtime["agentConnectionFlowNames"]:
        responses.add(**dv.retrieve_workflow_shared_principals(
            base_url=ENV_URL,
            workflow_id=FLOW_IDS[flow_name],
            accesses=[dv.principal_access(owner_id=TEAM_ID)],
        ))

    row = workday_da._check_delegated_flow_authorization(_runner())[0]

    assert row.status == "Passed"
    assert "WriteAccess on all 2 reviewed agent-facing flows" in row.result
    assert row.evidence["teamId"] == TEAM_ID
    assert row.remediation == ""


@responses.activate
def test_delegated_authorization_fails_missing_flow_share(
    monkeypatch,
) -> None:
    runtime = workday_da._load_runtime_contract()
    by_name = {
        name.casefold(): [
            {
                "workflowid": FLOW_IDS[name],
                "name": name,
                "statecode": 1,
                "statuscode": 2,
            }
        ]
        for name in runtime["flowNames"]
    }
    monkeypatch.setattr(
        workday_da,
        "_runtime_flow_inventory",
        lambda _runner: (runtime, by_name),
    )
    responses.add(**dv.query(
        base_url=ENV_URL,
        entity_set="delegatedauthorizations",
        records=[dv.delegated_authorization(bot_id=BOT_ID)],
        select="delegatedauthorizationid,name,providertype,botid",
        filter_expr=f"botid eq '{BOT_ID}'",
    ))
    responses.add(**dv.teams_for_delegated_authorization(
        base_url=ENV_URL,
        bot_id=BOT_ID,
        teams=[dv.delegated_access_team(team_id=TEAM_ID)],
    ))
    for index, flow_name in enumerate(runtime["agentConnectionFlowNames"]):
        responses.add(**dv.retrieve_workflow_shared_principals(
            base_url=ENV_URL,
            workflow_id=FLOW_IDS[flow_name],
            accesses=(
                []
                if index == 0
                else [dv.principal_access(owner_id=TEAM_ID)]
            ),
        ))

    row = workday_da._check_delegated_flow_authorization(_runner())[0]

    assert row.status == "Failed"
    assert "missing WriteAccess" in row.result
    assert "delegated-authorization setup" in row.remediation


@responses.activate
def test_delegated_authorization_errors_on_invalid_team_guid(
    monkeypatch,
) -> None:
    runtime = workday_da._load_runtime_contract()
    by_name = {
        name.casefold(): [
            {
                "workflowid": FLOW_IDS[name],
                "name": name,
                "statecode": 1,
                "statuscode": 2,
            }
        ]
        for name in runtime["flowNames"]
    }
    monkeypatch.setattr(
        workday_da,
        "_runtime_flow_inventory",
        lambda _runner: (runtime, by_name),
    )
    responses.add(**dv.query(
        base_url=ENV_URL,
        entity_set="delegatedauthorizations",
        records=[dv.delegated_authorization(bot_id=BOT_ID)],
        select="delegatedauthorizationid,name,providertype,botid",
        filter_expr=f"botid eq '{BOT_ID}'",
    ))
    responses.add(**dv.teams_for_delegated_authorization(
        base_url=ENV_URL,
        bot_id=BOT_ID,
        teams=[dv.delegated_access_team(team_id="not-a-guid")],
    ))

    row = workday_da._check_delegated_flow_authorization(_runner())[0]

    assert row.status == "Error"
    assert "invalid delegated access-team ID" in row.result


@responses.activate
def test_delegated_authorization_errors_on_malformed_principal(
    monkeypatch,
) -> None:
    runtime = workday_da._load_runtime_contract()
    by_name = {
        name.casefold(): [
            {
                "workflowid": FLOW_IDS[name],
                "name": name,
                "statecode": 1,
                "statuscode": 2,
            }
        ]
        for name in runtime["flowNames"]
    }
    monkeypatch.setattr(
        workday_da,
        "_runtime_flow_inventory",
        lambda _runner: (runtime, by_name),
    )
    responses.add(**dv.query(
        base_url=ENV_URL,
        entity_set="delegatedauthorizations",
        records=[dv.delegated_authorization(bot_id=BOT_ID)],
        select="delegatedauthorizationid,name,providertype,botid",
        filter_expr=f"botid eq '{BOT_ID}'",
    ))
    responses.add(**dv.teams_for_delegated_authorization(
        base_url=ENV_URL,
        bot_id=BOT_ID,
        teams=[dv.delegated_access_team(team_id=TEAM_ID)],
    ))
    malformed = dv.retrieve_workflow_shared_principals(
        base_url=ENV_URL,
        workflow_id=FLOW_IDS[runtime["agentConnectionFlowNames"][0]],
        accesses=[],
    )
    malformed["json"] = {
        "PrincipalAccesses": [{
            "Principal": "not-an-object",
            "AccessMask": "WriteAccess",
        }]
    }
    responses.add(**malformed)

    row = workday_da._check_delegated_flow_authorization(_runner())[0]

    assert row.status == "Error"
    assert "invalid principal record" in row.result


def _run(
    *,
    run_id: str,
    flow_id: str,
    start_time: str,
    status: str = "Succeeded",
    response_name: str = "Respond_to_Copilot_with_Success",
) -> dict[str, Any]:
    value = pp.flow_run(
        run_id=run_id,
        flow_id=flow_id,
        status=status,
        response_name=response_name,
    )
    value["properties"]["startTime"] = start_time
    return value


class _RunHistory:
    def __init__(self, runs: dict[str, list[dict[str, Any]]]) -> None:
        self.runs = runs

    def get_flow_runs(
        self,
        _env_id: str,
        flow_id: str,
    ) -> list[dict[str, Any]]:
        return deepcopy(self.runs.get(flow_id, []))

    def get_flow_runs_since(
        self,
        _env_id: str,
        flow_id: str,
        _since,
    ) -> list[dict[str, Any]]:
        return deepcopy(self.runs.get(flow_id, []))


def _runtime_runner(
    runs: dict[str, list[dict[str, Any]]],
    **overrides: Any,
) -> SimpleNamespace:
    values = {
        "pp_admin": _RunHistory(runs),
        "runtime_evidence_attempt_id": "attempt-42",
        "runtime_evidence_start": "2026-06-01T00:00:00Z",
        "runtime_evidence_end": "2026-06-01T00:01:00Z",
        "runtime_evidence_flow_ids": tuple(runs),
        "runtime_evidence_migration_baseline": False,
        "_workday_runtime_flows": _flows(),
    }
    values.update(overrides)
    return _runner(**values)


def test_correlated_runtime_evidence_passes_recorded_attempt() -> None:
    flow_ids = list(FLOW_IDS.values())[:2]
    runs = {
        flow_id: [_run(
            run_id=f"run-{index}",
            flow_id=flow_id,
            start_time="2026-06-01T00:00:30Z",
        )]
        for index, flow_id in enumerate(flow_ids)
    }

    row = workday_da._check_correlated_runtime_evidence(
        _runtime_runner(runs)
    )[0]

    assert row.status == "Passed"
    assert "attempt-42" in row.result
    assert row.evidence["operatorEvidenceLabel"] == "attempt-42"
    assert "attemptId" not in row.evidence
    assert row.evidence["clockSkewSeconds"] == 120
    assert row.remediation == ""


@pytest.mark.parametrize("response_value", [None, [], {}, {"name": ""}])
def test_correlated_runtime_evidence_rejects_missing_or_malformed_success_action(
    response_value,
) -> None:
    flow_id = next(iter(FLOW_IDS.values()))
    run = _run(
        run_id="run-1",
        flow_id=flow_id,
        start_time="2026-06-01T00:00:30Z",
    )
    if response_value is None:
        run["properties"].pop("response")
    else:
        run["properties"]["response"] = response_value

    row = workday_da._check_correlated_runtime_evidence(
        _runtime_runner({flow_id: [run]})
    )[0]

    assert row.status == "Failed"
    assert flow_id in row.result
    assert "Open the candidate Power Automate runs" in row.remediation


def test_correlated_runtime_evidence_requires_complete_attempt_context() -> None:
    row = workday_da._check_correlated_runtime_evidence(
        _runtime_runner({}, runtime_evidence_attempt_id="")
    )[0]

    assert row.status == "NotConfigured"
    assert "Generic recent Workday run health is not accepted" in row.result
    assert "signed-in employee scenario" in row.remediation


def test_correlated_runtime_evidence_rejects_window_over_15_minutes() -> None:
    flow_id = next(iter(FLOW_IDS.values()))
    runner = _runtime_runner(
        {flow_id: []},
        runtime_evidence_end="2026-06-01T00:15:01Z",
    )

    row = workday_da._check_correlated_runtime_evidence(runner)[0]

    assert row.status == "Failed"
    assert "must not exceed 15 minutes" in row.result


def test_correlated_runtime_evidence_rejects_invalid_flow_guid() -> None:
    runner = _runtime_runner(
        {"not-a-guid": []},
        runtime_evidence_flow_ids=("not-a-guid",),
    )

    row = workday_da._check_correlated_runtime_evidence(runner)[0]

    assert row.status == "Failed"
    assert "flow ID 'not-a-guid' is invalid" in row.result


def test_correlated_runtime_evidence_errors_on_malformed_run_properties() -> None:
    flow_id = next(iter(FLOW_IDS.values()))
    malformed = _run(
        run_id="run-1",
        flow_id=flow_id,
        start_time="2026-06-01T00:00:30Z",
    )
    malformed["properties"] = []

    row = workday_da._check_correlated_runtime_evidence(
        _runtime_runner({flow_id: [malformed]})
    )[0]

    assert row.status == "Error"
    assert "Flow run properties must be an object" in row.result


def test_correlated_runtime_evidence_errors_on_malformed_start_time() -> None:
    flow_id = next(iter(FLOW_IDS.values()))
    malformed = _run(
        run_id="run-1",
        flow_id=flow_id,
        start_time="not-a-time",
    )

    row = workday_da._check_correlated_runtime_evidence(
        _runtime_runner({flow_id: [malformed]})
    )[0]

    assert row.status == "Error"
    assert "Flow run startTime must be UTC ISO-8601" in row.result


def test_correlated_runtime_evidence_blocks_ambiguous_window() -> None:
    flow_id = next(iter(FLOW_IDS.values()))
    runs = {
        flow_id: [
            _run(
                run_id="success",
                flow_id=flow_id,
                start_time="2026-06-01T00:00:20Z",
            ),
            _run(
                run_id="failure",
                flow_id=flow_id,
                start_time="2026-06-01T00:00:25Z",
                response_name=(
                    "Respond_to_Copilot_with_failure_errorMessage"
                ),
            ),
        ]
    }

    row = workday_da._check_correlated_runtime_evidence(
        _runtime_runner(runs)
    )[0]

    assert row.status == "Blocked"
    assert "multiple candidate runs" in row.result
    assert "clean, bounded window" in row.remediation


def test_correlated_runtime_evidence_blocks_multiple_successes() -> None:
    flow_id = next(iter(FLOW_IDS.values()))
    runs = {
        flow_id: [
            _run(
                run_id="success-1",
                flow_id=flow_id,
                start_time="2026-06-01T00:00:20Z",
            ),
            _run(
                run_id="success-2",
                flow_id=flow_id,
                start_time="2026-06-01T00:00:25Z",
            ),
        ]
    }

    row = workday_da._check_correlated_runtime_evidence(
        _runtime_runner(runs)
    )[0]

    assert row.status == "Blocked"
    assert "multiple candidate runs" in row.result


def test_correlated_runtime_evidence_blocks_success_plus_pending() -> None:
    flow_id = next(iter(FLOW_IDS.values()))
    pending = _run(
        run_id="pending",
        flow_id=flow_id,
        start_time="2026-06-01T00:00:25Z",
        status="Running",
    )
    runs = {
        flow_id: [
            _run(
                run_id="success",
                flow_id=flow_id,
                start_time="2026-06-01T00:00:20Z",
            ),
            pending,
        ]
    }

    row = workday_da._check_correlated_runtime_evidence(
        _runtime_runner(runs)
    )[0]

    assert row.status == "Blocked"
    assert "multiple candidate runs" in row.result


def test_correlated_runtime_evidence_blocks_single_pending_run() -> None:
    flow_id = next(iter(FLOW_IDS.values()))
    pending = _run(
        run_id="pending",
        flow_id=flow_id,
        start_time="2026-06-01T00:00:25Z",
        status="Running",
    )

    row = workday_da._check_correlated_runtime_evidence(
        _runtime_runner({flow_id: [pending]})
    )[0]

    assert row.status == "Blocked"
    assert "non-terminal or inconclusive" in row.result


def test_correlated_runtime_evidence_fails_missing_candidate_run() -> None:
    flow_id = next(iter(FLOW_IDS.values()))
    runner = _runtime_runner(
        {flow_id: []},
        runtime_evidence_migration_baseline=True,
    )

    row = workday_da._check_correlated_runtime_evidence(runner)[0]

    assert row.status == "Failed"
    assert "No terminal run was found" in row.result
    assert row.evidence["migrationBaseline"] is True
    assert "capture a fresh evidence window" in row.remediation
