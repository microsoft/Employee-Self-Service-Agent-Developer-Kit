# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Target dependency tests grounded in env004_dependencies.yaml.

The baseline replays actual HTTP responses through the production clients.
Boundary cases mutate that captured structural contract, not invented API
shapes. No Workday business operation or tenant mutation is performed.
"""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse
from unittest.mock import Mock

import pytest
import responses
import yaml

from agentbuilder import AgentBuilderClient, ConnectivityClient
from flightcheck.checks import _connection_dependencies as dependencies
from flightcheck.checks.environment import _check_connections_and_refs
from flightcheck.pp_admin_client import PPAdminClient


CASSETTE = Path(__file__).resolve().parents[2] / "fixtures" / "cassettes" / "env004_dependencies.yaml"
SECOND_AGENT = "00000000-0000-0000-0000-000000009999"


def _captured(path=CASSETTE):
    return yaml.safe_load(path.read_text(encoding="utf-8"))["interactions"]


def _body(interaction):
    return json.loads(interaction["response"]["body"]["string"])


@pytest.fixture
def dependency_case(monkeypatch):
    interactions = _captured()
    agent = _body(interactions[0])
    payload = _body(interactions[1])
    flows = {
        urlparse(item["request"]["uri"]).path.rsplit("/", 1)[-1]: _body(item)
        for item in interactions if "/flows/" in item["request"]["uri"]
    }
    dv = next(_body(item)["value"] for item in interactions
              if "/connectionreferences?" in item["request"]["uri"])
    inventory = next(_body(item)["value"] for item in interactions
                     if "/connectivity/" in item["request"]["uri"])
    environment = next(_body(item) for item in interactions
                       if "api.bap." in item["request"]["uri"])
    bound = {row["connectionid"].casefold() for row in dv
             if row["connectionid"] and row["connectionreferencelogicalname"].endswith("_workdayruntime")}
    case = SimpleNamespace(
        agent_id=agent["botId"], payload=payload, flows=flows, rows=dv,
        full_inventory=inventory,
        inventory=[row for row in inventory if row["name"].casefold() in bound],
        interactions=interactions,
    )
    case.native = Mock()
    case.native.get_agent.side_effect = lambda agent_id: {"botId": agent_id}
    case.native.fetch_components.side_effect = lambda _agent_id: case.payload
    case.native.get_realm_configuration.return_value = None
    pp = Mock()
    pp.get_flow.side_effect = lambda _env, flow_id: case.flows[flow_id]
    pp.get_connections.side_effect = lambda _env, **_kwargs: case.inventory
    pp.get_environment.return_value = environment
    case.runner = SimpleNamespace(
        config={}, connection_agent_ids=(case.agent_id,), agentbuilder=case.native,
        env_id=environment["name"], env_url="https://orgmocktenant.crm.dynamics.com",
        dv_token="REDACTED_TOKEN", pp_admin=pp, ring="prod",
        tenant_id="00000000-0000-0000-0000-000000001111",
        connectivity=Mock(),
    )
    case.runner.connectivity.list_connections.side_effect = lambda _env: case.inventory
    case.query = Mock(side_effect=lambda *_args, **_kwargs: case.rows)
    monkeypatch.setattr(dependencies, "query_all", case.query)
    return case


def _summary(case):
    return next(row for row in _check_connections_and_refs(case.runner)
                if row.checkpoint_id == "ENV-004")


def test_active_workday_dependencies_pass_without_setup_config(dependency_case):
    row = _summary(dependency_case)

    assert row.status == "Passed"
    assert "2 required reference(s) from 3 active flow call(s)" in row.result
    assert "2 bound" in row.result
    assert row.remediation == ""
    query = dependency_case.query.call_args.args
    assert query[2] == "connectionreferences"
    assert query[4] == (
        "connectionreferencelogicalname eq 'msdyn_sharedcommondataserviceforapps_workdayruntime' or "
        "connectionreferencelogicalname eq 'msdyn_sharedworkdaysoap_workdayruntime'"
    )
    dependency_case.native.get_agent.assert_called_once_with(dependency_case.agent_id)


def test_connection_audit_excludes_stale_same_slug_compatibility_agent(dependency_case):
    case = dependency_case
    del case.runner.connection_agent_ids
    case.runner.config = {
        "agents": [{"slug": "hr", "botId": case.agent_id}],
        "agent": {"slug": "hr", "botId": SECOND_AGENT},
    }

    row = _summary(case)

    assert row.status == "Passed"
    assert "2 required reference(s) from 3 active flow call(s)" in row.result
    assert row.remediation == ""
    case.native.get_agent.assert_called_once_with(case.agent_id)
    case.native.fetch_components.assert_called_once_with(case.agent_id)


@pytest.mark.parametrize("missing_id", [None, "", "   ", False, 0])
def test_missing_canonical_subject_warns_without_substituting_compatibility_agent(
    dependency_case, missing_id,
):
    case = dependency_case
    del case.runner.connection_agent_ids
    case.runner.config = {
        "agents": [
            {"slug": "hr", "botId": missing_id},
            {"slug": "it", "botId": case.agent_id},
        ],
        "agent": {"slug": "hr", "botId": SECOND_AGENT},
    }

    row = _summary(case)

    assert row.status == "Warning"
    assert "Agent hr: dependency discovery incomplete" in row.result
    assert "botId not available" in row.result
    assert "2 bound" in row.result
    assert "each canonical agent has its own botId" in row.remediation
    case.native.get_agent.assert_called_once_with(case.agent_id)


def _http_runner(monkeypatch, interactions):
    agent_id = _body(interactions[0])["botId"]
    environment = next(_body(item) for item in interactions
                       if "api.bap." in item["request"]["uri"])
    token = "REDACTED_TOKEN"
    pp = PPAdminClient("00000000-0000-0000-0000-000000001111")
    pp.set_read_tokens(powerapps_token=token, flow_token=token)
    tenant_id = "00000000-0000-0000-0000-000000001111"
    monkeypatch.setattr(dependencies, "discover_tenant", lambda _url: tenant_id)
    monkeypatch.setattr("agentbuilder.validate_environment_host", lambda host, _ring: host)
    runner = SimpleNamespace(
        config={}, connection_agent_ids=(agent_id,), env_id=environment["name"],
        env_url="https://orgmocktenant.crm.dynamics.com", dv_token=token, ring="prod",
        pp_admin=pp,
        tenant_id=tenant_id, connection_dependency_token=lambda _scope: token,
        agentbuilder=AgentBuilderClient(
            "https://mockenv.00.environment.api.powerplatform.com", token,
            ring="prod", tenant_id="00000000-0000-0000-0000-000000001111",
        ),
        connectivity=ConnectivityClient(token, ring="prod"),
    )
    # The captured host is deliberately redacted, so bypass only its DNS-label
    # validator, never the check's target or connection identity checks.
    runner.agentbuilder.host = "https://mockenv.00.environment.api.powerplatform.com"
    return runner


@pytest.mark.parametrize("maker_visible,malformed_collection", [
    (True, None), (False, None), (True, "dataverse"), (False, "admin"),
    (False, "admin_nextlink"), (False, "admin_odata_nextlink"),
])
def test_actual_http_capture_exercises_the_check(monkeypatch, maker_visible, malformed_collection):
    interactions = _captured()
    runner = _http_runner(monkeypatch, interactions)
    with responses.RequestsMock(assert_all_requests_are_fired=False) as replay:
        for item in interactions:
            body = _body(item)
            if not maker_visible and "/connectivity/" in item["request"]["uri"]:
                body["value"] = []
            if (
                malformed_collection == "dataverse" and "/connectionreferences?" in item["request"]["uri"]
                or malformed_collection == "admin" and "api.powerapps." in item["request"]["uri"]
            ):
                del body["value"]
            if "api.powerapps." in item["request"]["uri"]:
                if malformed_collection == "admin_nextlink":
                    body.update(value=[], nextLink=False)
                elif malformed_collection == "admin_odata_nextlink":
                    body.update(value=[], **{"@odata.nextLink": False})
            replay.add(
                item["request"]["method"],
                item["request"]["uri"].split("?")[0],
                json=body, status=item["response"]["status"]["code"],
            )
        rows = _check_connections_and_refs(runner)
        assert len(replay.calls) == (
            7 if malformed_collection == "dataverse" else 8 if maker_visible else 9
        )
    summary = next(row for row in rows if row.checkpoint_id == "ENV-004")
    if malformed_collection:
        assert summary.status == "Warning"
        assert ("invalid continuation" if "nextlink" in malformed_collection
                else "invalid collection") in summary.result
        assert "does not exist" not in summary.result
        assert "Restore read access" in summary.remediation
        return
    assert summary.status == "Passed"
    assert "2 bound" in summary.result
    assert "unverified" not in summary.result
    assert summary.remediation == ""


def test_live_partial_topic_capture_preserves_verified_bindings(monkeypatch):
    interactions = _captured(CASSETTE.with_name("env004_partial_topics.yaml"))
    runner = _http_runner(monkeypatch, interactions)

    with responses.RequestsMock(assert_all_requests_are_fired=False) as replay:
        for item in interactions:
            replay.add(
                item["request"]["method"],
                item["request"]["uri"].split("?")[0],
                json=_body(item), status=item["response"]["status"]["code"],
            )
        rows = _check_connections_and_refs(runner)

    summary = next(row for row in rows if row.checkpoint_id == "ENV-004")
    assert summary.status == "Warning"
    assert "3 required reference(s) from 3 active flow call(s)" in summary.result
    assert "3 bound" in summary.result
    assert "activation could not be verified" in summary.result
    assert summary.result.count("activation could not be verified") == 12
    assert "component state alone does not establish activation" in summary.remediation


def _workday_row(case):
    return next(row for row in case.rows
                if row["connectionreferencelogicalname"] == "msdyn_sharedworkdaysoap_workdayruntime")


@pytest.mark.parametrize("binding", [None, ""])
def test_required_unbound_reference_fails(dependency_case, binding):
    _workday_row(dependency_case)["connectionid"] = binding

    row = _summary(dependency_case)

    assert row.status == "Failed"
    assert "msdyn_sharedworkdaysoap_workdayruntime is unbound" in row.result
    assert "Connection references" in row.remediation


def test_required_missing_reference_fails(dependency_case):
    dependency_case.rows.remove(_workday_row(dependency_case))

    row = _summary(dependency_case)

    assert row.status == "Failed"
    assert "required flow reference msdyn_sharedworkdaysoap_workdayruntime is missing" in row.result
    assert "Repair the missing" in row.remediation


def test_unrelated_unbound_workday_reference_is_ignored(dependency_case):
    unrelated = deepcopy(_workday_row(dependency_case))
    unrelated.update(connectionreferencelogicalname="another_application_workday", connectionid=None)
    dependency_case.rows.append(unrelated)

    assert _summary(dependency_case).status == "Passed"


def test_inactive_servicenow_topics_do_not_require_their_unbound_reference(dependency_case):
    row = _summary(dependency_case)

    assert row.status == "Passed"
    assert "service-now" not in row.result


@pytest.mark.parametrize("status", [None, "Unknown", ""])
def test_unverified_topic_activation_preserves_known_dependencies(dependency_case, status):
    case = dependency_case
    topic = deepcopy(next(
        change for change in case.payload["botComponentChanges"]
        if "InvokeConnectorAction" in json.dumps(change)
    ))
    component = topic["component"]
    component["schemaName"] = "test.topic.Unverified"
    component["state"] = "Active"
    if status is None:
        component.pop("status", None)
    else:
        component["status"] = status
    case.payload["botComponentChanges"].insert(0, topic)

    row = _summary(case)

    assert row.status == "Warning"
    assert "test.topic.Unverified" in row.result
    assert "activation could not be verified" in row.result
    assert "2 required reference(s) from 3 active flow call(s)" in row.result
    assert "2 bound" in row.result
    assert "component state alone does not establish activation" in row.remediation
    case.query.assert_called_once()
    assert case.runner.pp_admin.get_flow.call_count == 3


def test_unverified_topic_does_not_hide_a_known_unbound_reference(dependency_case):
    case = dependency_case
    case.payload["botComponentChanges"].append({
        "component": {"$kind": "DialogComponent", "state": "Active", "dialog": {}},
    })
    _workday_row(case)["connectionid"] = None

    row = _summary(case)

    assert row.status == "Failed"
    assert "msdyn_sharedworkdaysoap_workdayruntime is unbound" in row.result
    assert "activation could not be verified" in row.result
    assert "bind" in row.remediation


@pytest.mark.parametrize("invalid_topic", ["component", "dialog", "flow"])
def test_malformed_topic_preserves_other_verified_dependencies(dependency_case, invalid_topic):
    case = dependency_case
    change = deepcopy(next(
        change for change in case.payload["botComponentChanges"]
        if change["component"].get("status") == "Active"
        and change["component"].get("$kind") == "DialogComponent"
    ))
    if invalid_topic == "component":
        change["component"] = None
    elif invalid_topic == "dialog":
        change["component"]["dialog"] = []
    else:
        change["component"]["dialog"] = {
            "$kind": "InvokeFlowAction", "flowId": "not-a-guid",
        }
    case.payload["botComponentChanges"].append(change)

    row = _summary(case)

    assert row.status == "Warning"
    assert "dependency discovery incomplete" in row.result
    assert "2 bound" in row.result
    assert "Restore read access" in row.remediation
    assert case.runner.pp_admin.get_flow.call_count == 3


def test_active_direct_topic_requires_its_native_reference(dependency_case):
    topic = next(change["component"] for change in dependency_case.payload["botComponentChanges"]
                 if "InvokeConnectorAction" in json.dumps(change))
    topic["status"] = "Active"

    row = _summary(dependency_case)

    assert row.status == "Failed"
    assert "shared_service-now is unbound" in row.result
    assert "Connection references" in row.remediation


def test_missing_active_native_reference_fails(dependency_case):
    topic = next(change["component"] for change in dependency_case.payload["botComponentChanges"]
                 if "InvokeConnectorAction" in json.dumps(change))
    topic["status"] = "Active"
    dependency_case.payload["connectionReferenceChanges"] = []

    row = _summary(dependency_case)

    assert row.status == "Failed"
    assert "required native reference" in row.result and "is missing" in row.result
    assert "Repair" in row.remediation


@pytest.mark.parametrize("reverse", [False, True])
def test_agent_local_references_are_never_deduplicated_across_agents(dependency_case, reverse):
    payload = dependency_case.payload
    topic = next(change for change in payload["botComponentChanges"]
                 if "InvokeConnectorAction" in json.dumps(change))
    topic["component"]["status"] = "Active"
    payload["botComponentChanges"] = [topic]
    ref = payload["connectionReferenceChanges"][0]["connectionReference"]
    ref["connectionId"] = "connection-for-first-agent"
    dependency_case.inventory = [{
        "name": ref["connectionId"], "properties": {"apiId": ref["connectorId"]}
    }]
    second = deepcopy(payload)
    second["connectionReferenceChanges"][0]["connectionReference"]["connectionId"] = None
    payloads = {dependency_case.agent_id: payload, SECOND_AGENT: second}
    ids = list(payloads)
    dependency_case.runner.connection_agent_ids = tuple(reversed(ids)) if reverse else tuple(ids)
    dependency_case.native.fetch_components.side_effect = payloads.__getitem__

    row = _summary(dependency_case)

    assert row.status == "Failed"
    assert "2 required reference(s)" in row.result
    assert f"Agent {SECOND_AGENT}:" in row.result
    assert "1 unbound" in row.result
    assert "bind" in row.remediation
    dependency_case.query.assert_not_called()


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("state", ["passed", "denied", "malformed"])
def test_shared_flow_is_read_once_without_losing_agent_coverage(
    dependency_case, reverse, state,
):
    ids = [dependency_case.agent_id, SECOND_AGENT]
    dependency_case.runner.connection_agent_ids = tuple(reversed(ids)) if reverse else tuple(ids)
    shared_flow = sorted(dependency_case.flows)[0]
    if state == "malformed":
        dependency_case.flows[shared_flow]["properties"]["connectionReferences"] = []
    elif state == "denied":
        def read_flow(_env, flow_id):
            if flow_id == shared_flow:
                raise RuntimeError("Shared flow read denied")
            return dependency_case.flows[flow_id]
        dependency_case.runner.pp_admin.get_flow.side_effect = read_flow

    row = _summary(dependency_case)

    reads = dependency_case.runner.pp_admin.get_flow.call_args_list
    assert len(reads) == len(dependency_case.flows)
    assert {call.args[1] for call in reads} == set(dependency_case.flows)
    assert "6 active flow call(s)" in row.result
    assert dependency_case.native.fetch_components.call_count == 2
    if state == "passed":
        assert row.status == "Passed"
        assert "4 required reference(s)" in row.result
        assert row.remediation == ""
    else:
        assert row.status == "Warning"
        assert all(f"Agent {agent_id}, flow {shared_flow}" in row.result for agent_id in ids)
        assert ("Shared flow read denied" if state == "denied" else
                "Flow detail omitted its connection-reference map") in row.result
        assert "Restore read access" in row.remediation


def test_shared_flow_cache_is_limited_to_one_audit(dependency_case):
    first = _summary(dependency_case)
    dependency_case.runner.pp_admin.get_flow.reset_mock()
    _workday_row(dependency_case)["connectionid"] = None

    second = _summary(dependency_case)

    assert first.status == "Passed"
    assert second.status == "Failed"
    assert "unbound" in second.result
    assert "bind" in second.remediation
    assert dependency_case.runner.pp_admin.get_flow.call_count == len(dependency_case.flows)


def test_different_agent_response_is_not_substituted(dependency_case):
    dependency_case.native.get_agent.side_effect = None
    dependency_case.native.get_agent.return_value = {"botId": SECOND_AGENT}

    row = _summary(dependency_case)

    assert row.status == "Warning"
    assert "different subject" in row.result
    assert "Restore read access" in row.remediation
    dependency_case.native.fetch_components.assert_not_called()


@pytest.mark.parametrize("target", [(), ("not-an-agent-guid",)])
def test_missing_or_invalid_subject_is_blocked(dependency_case, target):
    dependency_case.runner.connection_agent_ids = target
    dependency_case.runner.config = {"agents": [{"botId": SECOND_AGENT}]}

    row = _summary(dependency_case)

    assert row.status == "Blocked"
    assert "--agent-id" in row.remediation
    dependency_case.native.get_agent.assert_not_called()


def test_known_failure_wins_over_partial_flow_read(dependency_case):
    _workday_row(dependency_case)["connectionid"] = None
    dependency_case.runner.pp_admin.get_flow.side_effect = (
        lambda _env, flow_id: dependency_case.flows[flow_id]
        if flow_id != sorted(dependency_case.flows)[1]
        else (_ for _ in ()).throw(RuntimeError("Flow read denied"))
    )

    row = _summary(dependency_case)

    assert row.status == "Failed"
    assert "unbound" in row.result and "Flow read denied" in row.result
    assert "Restore read access" in row.remediation


def test_dataverse_denied_is_incomplete_not_empty_or_passed(dependency_case):
    dependency_case.query.side_effect = RuntimeError("Reference read denied")

    row = _summary(dependency_case)

    assert row.status == "Warning"
    assert "Flow reference bindings unverified" in row.result
    assert "Reference read denied" in row.result
    assert "Restore read access" in row.remediation


@pytest.mark.parametrize("where", ["reference", "physical"])
def test_wrong_connector_fails(dependency_case, where):
    if where == "reference":
        _workday_row(dependency_case)["connectorid"] = "shared_service-now"
    else:
        dependency_case.inventory[0]["properties"]["apiId"] = "shared_service-now"

    row = _summary(dependency_case)

    assert row.status == "Failed"
    assert "wrong connector" in row.result
    assert "Repair" in row.remediation


def test_confirmed_missing_physical_connection_fails(dependency_case):
    dependency_case.inventory = []

    row = _summary(dependency_case)

    assert row.status == "Failed"
    assert "bound physical connection does not exist" in row.result
    assert "Repair" in row.remediation
    dependency_case.runner.pp_admin.get_connections.assert_called_once()


def test_maker_invisible_without_admin_access_warns_not_missing(dependency_case):
    dependency_case.inventory = []
    dependency_case.runner.pp_admin.get_connections.side_effect = RuntimeError("Admin access denied")

    row = _summary(dependency_case)

    assert row.status == "Warning"
    assert "not maker-visible" in row.result
    assert "does not exist" not in row.result
    assert "Restore read access" in row.remediation


def test_admin_visible_connection_is_not_reported_missing(dependency_case):
    authoritative = deepcopy(dependency_case.inventory)
    dependency_case.inventory = []
    dependency_case.runner.pp_admin.get_connections.side_effect = lambda _env, **_kwargs: authoritative

    row = _summary(dependency_case)

    assert row.status == "Passed"
    assert row.remediation == ""


def test_additional_same_connector_connection_is_advisory_only(dependency_case):
    extra = deepcopy(dependency_case.inventory[0])
    extra["name"] = "another-agents-connection"
    dependency_case.inventory.append(extra)

    row = _summary(dependency_case)

    assert row.status == "Warning"
    assert "1 additional connection(s)" in row.result
    assert "may serve other agents" in row.result
    assert row.remediation == ""


@pytest.mark.parametrize("value", [0, False, [], "   "])
def test_invalid_falsy_connection_identity_is_not_resolved_to_another_value(dependency_case, value):
    _workday_row(dependency_case)["connectionid"] = value

    row = _summary(dependency_case)

    assert row.status == "Warning"
    assert "malformed physical connection identity" in row.result
    assert "Restore read access" in row.remediation


@pytest.mark.parametrize("field,value", [
    ("botComponentChanges", None),
    ("botComponentChanges", [None]),
    ("botComponentChanges", [{"component": {"$kind": "DialogComponent", "status": "Unknown"}}]),
])
def test_invalid_component_shapes_warn(dependency_case, field, value):
    dependency_case.payload[field] = value

    row = _summary(dependency_case)

    assert row.status == "Warning"
    assert "dependency discovery incomplete" in row.result
    assert "Restore read access" in row.remediation


@pytest.mark.parametrize("detail", [
    None, {"properties": None}, {"properties": {"connectionReferences": []}},
    {"properties": {"connectionReferences": {"x": {"apiDefinition": 4}}}},
])
def test_invalid_flow_shapes_warn(dependency_case, detail):
    dependency_case.runner.pp_admin.get_flow.side_effect = lambda *_args: detail

    row = _summary(dependency_case)

    assert row.status == "Warning"
    assert "dependencies unverified" in row.result
    assert "Restore read access" in row.remediation


@pytest.mark.parametrize("inventory", [None, [None], [{"name": "x", "properties": []}]])
def test_invalid_inventory_shapes_warn(dependency_case, inventory):
    dependency_case.inventory = inventory

    row = _summary(dependency_case)

    assert row.status == "Warning"
    assert "Physical connection existence unverified" in row.result
    assert "Restore read access" in row.remediation


def test_duplicate_physical_identity_warns(dependency_case):
    dependency_case.inventory.append(deepcopy(dependency_case.inventory[0]))

    row = _summary(dependency_case)

    assert row.status == "Warning"
    assert "Duplicate physical connection identity" in row.result
    assert "Restore read access" in row.remediation


def test_unsupported_flow_admin_ring_warns_without_using_prod_hosts(dependency_case):
    dependency_case.runner.ring = "test"

    row = _summary(dependency_case)

    assert row.status == "Warning"
    assert "only verified on the prod service ring" in row.result
    assert "Restore read access" in row.remediation
    dependency_case.runner.pp_admin.get_flow.assert_not_called()


def test_no_active_dependencies_passes_without_flow_or_dataverse_access(dependency_case):
    dependency_case.payload["botComponentChanges"] = []

    row = _summary(dependency_case)

    assert row.status == "Passed"
    assert "0 required reference(s)" in row.result
    assert row.remediation == ""
    dependency_case.query.assert_not_called()
    dependency_case.runner.pp_admin.get_flow.assert_not_called()


@pytest.mark.parametrize("mismatch", ["environment", "tenant", "url"])
def test_lazy_dataverse_access_refuses_other_subjects(dependency_case, monkeypatch, mismatch):
    runner = dependency_case.runner
    runner.connection_dependency_token = Mock(return_value="REDACTED_TOKEN")
    pp = runner.pp_admin
    pp.has_flow_token = True
    pp.has_powerapps_token = True
    monkeypatch.setattr(dependencies, "PPAdminClient", lambda *_args: pp)
    monkeypatch.setattr(dependencies, "discover_tenant", lambda _url: (
        SECOND_AGENT if mismatch == "tenant" else runner.tenant_id
    ))
    runner.env_url = "" if mismatch != "url" else "https://other.crm.dynamics.com"
    if mismatch == "environment":
        pp.get_environment.return_value["name"] = SECOND_AGENT

    row = _summary(dependency_case)

    assert row.status == "Warning"
    assert "different" in row.result
    assert "Restore read access" in row.remediation
    dependency_case.query.assert_not_called()
