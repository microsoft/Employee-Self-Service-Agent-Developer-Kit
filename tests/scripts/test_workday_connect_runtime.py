from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import base64
import json
import sys

import pytest
import requests
import responses


SCRIPTS = (
    Path(__file__).resolve().parents[2] / "solutions" / "ess-maker-skills" / "scripts"
)
sys.path.insert(0, str(SCRIPTS))

import workday_connect_runtime as runtime  # noqa: E402
from workday_connect_model import default_state  # noqa: E402
from tests.conftest import require_validated_mock  # noqa: E402
from tests.mocks import agentbuilder_connectivity as native  # noqa: E402


require_validated_mock(native)


BOT_ID = "11111111-1111-1111-1111-111111111111"
WORKDAY_CONNECTION = "22222222-2222-2222-2222-222222222222"
DATAVERSE_CONNECTION = "33333333-3333-3333-3333-333333333333"
TENANT_ID = "00000000-0000-0000-0000-000000004444"
BUSINESS_UNIT_ID = "44444444-4444-4444-4444-444444444444"
AUTHORIZATION_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TEAM_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
TEAM_NAME = f"ESS DA HR Workday - Development - {BOT_ID}"


def _state():
    state = default_state()
    state["scope"].update(
        {
            "dataverseUrl": "https://org.crm.dynamics.com",
            "packageFlavor": "runtime",
            "ring": "prod",
            "agent": {"botId": BOT_ID},
        }
    )
    state["operators"]["powerPlatformMaker"] = {"username": "maker@contoso.com"}
    state["phases"]["connections"]["status"] = "complete"
    return state


def _connections():
    return {
        "value": [
            {
                "name": WORKDAY_CONNECTION,
                "properties": {
                    "apiId": "/providers/Microsoft.PowerApps/apis/shared_workdaysoap",
                    "displayName": "Workday",
                    "statuses": [{"status": "Connected"}],
                },
            },
            {
                "name": DATAVERSE_CONNECTION,
                "properties": {
                    "apiId": (
                        "/providers/Microsoft.PowerApps/apis/"
                        "shared_commondataserviceforapps"
                    ),
                    "displayName": "Dataverse",
                    "statuses": [{"status": "Connected"}],
                },
            },
        ]
    }


def _api_state(ring="test"):
    state = _state()
    state["scope"].update(
        {
            "environmentId": native.MOCK_ENV_ID,
            "entraTenantId": TENANT_ID,
            "ring": ring,
        }
    )
    return state


def _api_token(username="maker@contoso.com", tenant_id=TENANT_ID):
    claims = {"preferred_username": username, "tid": tenant_id}
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode()
    return f"header.{payload.rstrip('=')}.signature"


def _no_pac():
    pytest.fail("PAC must not be used after a successful API response or identity mismatch")


@pytest.mark.parametrize(
    ("ring", "host"),
    [
        ("prod", "https://api.powerplatform.com"),
        ("preprod", "https://api.preprod.powerplatform.com"),
        ("test", "https://api.test.powerplatform.com"),
    ],
)
@responses.activate
def test_connection_api_is_primary_and_uses_selected_ring_tenant_and_maker(
    monkeypatch, ring, host,
):
    calls = []

    def authenticate(tenant_id, service_ring, **kwargs):
        calls.append((tenant_id, service_ring, kwargs))
        return _api_token()

    monkeypatch.setattr(runtime, "authenticate_connections", authenticate)
    response = native.list_connections(items=_connections()["value"])
    response["url"] = response["url"].replace(native.MOCK_CONNECTIVITY_BASE, host)
    responses.add(**response)

    evidence = runtime.verify_physical_connections(
        _api_state(ring), pac_resolver=_no_pac,
    )

    assert evidence["connectionIds"] == {
        "workday": WORKDAY_CONNECTION,
        "dataverse": DATAVERSE_CONNECTION,
    }
    assert calls == [
        (
            TENANT_ID,
            ring,
            {
                "account_hint": "maker@contoso.com",
                "scopes": (f"{host}/Connectivity.Connections.Read",),
            },
        )
    ]
    assert all(call.request.method == "GET" for call in responses.calls)


@pytest.mark.parametrize("failure", ["denied", "service", "malformed", "timeout", "auth"])
@responses.activate
def test_connection_api_failure_falls_back_to_pac_for_same_target(
    monkeypatch, capsys, failure,
):
    def authenticate(*_args, **_kwargs):
        if failure == "auth":
            raise runtime.AgentBuilderError("Consent is required.")
        return _api_token()

    monkeypatch.setattr(runtime, "authenticate_connections", authenticate)
    response = native.list_connections()
    if failure == "timeout":
        response.pop("json")
        response["body"] = requests.Timeout("Connection inventory timed out.")
    elif failure == "malformed":
        response["json"] = {"unexpected": []}
    elif failure != "auth":
        response["status"] = 403 if failure == "denied" else 500
    responses.add(**response)
    auth_calls = []
    commands = []

    def runner(command, **kwargs):
        commands.append(command)
        return _pac_runner(command, **kwargs)

    evidence = runtime.verify_physical_connections(
        _api_state(),
        pac_resolver=lambda: Path("pac.exe"),
        pac_auth=lambda pac, **kwargs: auth_calls.append((pac, kwargs)),
        runner=runner,
    )

    assert evidence["connectionIds"]["workday"] == WORKDAY_CONNECTION
    assert auth_calls == [
        (
            Path("pac.exe"),
            {
                "ring": "preprod",
                "environment_url": "https://org.crm.dynamics.com",
                "preferred_username": "maker@contoso.com",
                "runner": runner,
            },
        )
    ]
    assert commands == [
        [
            "pac.exe", "connectivity", "list-connections", "--environment",
            "https://org.crm.dynamics.com", "--json",
        ]
    ]
    warning = capsys.readouterr().err
    assert "[WARNING] Power Platform connection API discovery failed:" in warning
    assert "Falling back to PAC for the same environment and maker account." in warning


@pytest.mark.parametrize(
    ("token", "message"),
    [
        (_api_token(username="other@contoso.com"), "different account"),
        (
            _api_token(tenant_id="00000000-0000-0000-0000-000000005555"),
            "different Microsoft Entra tenant",
        ),
        ("unreadable-token", "readable identity claims"),
    ],
)
def test_connection_api_identity_failure_does_not_fall_back(
    monkeypatch, token, message,
):
    monkeypatch.setattr(
        runtime, "authenticate_connections", lambda *_args, **_kwargs: token,
    )
    with pytest.raises(runtime.WorkdayConnectRuntimeError, match=message):
        runtime.verify_physical_connections(_api_state(), pac_resolver=_no_pac)


@pytest.mark.parametrize("inventory", ["empty", "disconnected", "ambiguous"])
@responses.activate
def test_valid_api_inventory_with_unresolved_connections_does_not_use_pac(
    monkeypatch, inventory,
):
    monkeypatch.setattr(
        runtime, "authenticate_connections", lambda *_args, **_kwargs: _api_token(),
    )
    connections = _connections()["value"]
    if inventory == "empty":
        connections = []
    elif inventory == "disconnected":
        connections[1]["properties"]["statuses"] = [{"status": "Error"}]
    else:
        duplicate = native.connection(
            connection_id="alternate-dataverse",
            connector="shared_commondataserviceforapps",
        )
        connections.append(duplicate)
    responses.add(**native.list_connections(items=connections))

    with pytest.raises(runtime.WorkdayConnectRuntimeError) as raised:
        runtime.verify_physical_connections(_api_state(), pac_resolver=_no_pac)

    assert raised.value.details["connector"] == "shared_commondataserviceforapps"


@responses.activate
def test_api_inventory_reuses_recorded_connection_ids(monkeypatch):
    monkeypatch.setattr(
        runtime, "authenticate_connections", lambda *_args, **_kwargs: _api_token(),
    )
    state = _api_state()
    state["phases"]["connections"]["evidence"] = [
        {
            "action": "physical-connections-verified",
            "outcome": "verified",
            "connectionIds": {
                "workday": WORKDAY_CONNECTION,
                "dataverse": DATAVERSE_CONNECTION,
            },
        }
    ]
    connections = _connections()["value"]
    connections.append(
        native.connection(connection_id="other-workday", connector="shared_workdaysoap")
    )
    responses.add(**native.list_connections(items=connections))

    evidence = runtime.verify_physical_connections(state, pac_resolver=_no_pac)

    assert evidence["connectionIds"]["workday"] == WORKDAY_CONNECTION


@pytest.mark.parametrize(
    ("path", "guidance"),
    [
        (
            r"C:\Users\maker\.dotnet\tools\pac.exe",
            "dotnet tool update --global Microsoft.PowerApps.CLI.Tool",
        ),
        (
            r"C:\Users\maker\.vscode\extensions\microsoft.powerplatform\pac.exe",
            "Update the Microsoft Power Platform Tools extension",
        ),
        (
            r"C:\Users\maker\AppData\Local\InternalTools\pac\pac.exe",
            "Update this exact PAC installation",
        ),
    ],
)
def test_unsupported_pac_fallback_reports_exact_installation_and_upgrade(
    monkeypatch, path, guidance,
):
    def failed_api(*_args, **_kwargs):
        raise runtime.AgentBuilderError("Connection listing failed with HTTP 403")

    monkeypatch.setattr(runtime, "authenticate_connections", failed_api)
    with pytest.raises(runtime.WorkdayConnectRuntimeError) as raised:
        runtime.verify_physical_connections(
            _api_state(),
            pac_resolver=lambda: Path(path),
            pac_auth=lambda *_args, **_kwargs: None,
            runner=lambda *_args, **_kwargs: SimpleNamespace(
                returncode=1,
                stdout="Microsoft PowerPlatform CLI\nVersion: 1.44.0\n",
                stderr="Error: Not a valid command. Try running 'pac [command] help'.",
            ),
        )

    message = str(raised.value)
    assert "HTTP 403" in message
    assert "PAC fallback failed:" in message
    assert path in message
    assert "version 1.44.0" in message
    assert guidance in message
    assert "connectivity list-connections help" in message
    assert "updating a different PAC on PATH will not update that copy" in message
    assert "Do not use 'pac connection list' as a substitute" in message


def test_pac_permission_error_is_not_reported_as_version_problem():
    with pytest.raises(runtime.WorkdayConnectRuntimeError) as raised:
        runtime._list_connections(
            Path("pac.exe"),
            "https://org.crm.dynamics.com",
            runner=lambda *_args, **_kwargs: SimpleNamespace(
                returncode=1, stdout="", stderr="Access denied.",
            ),
        )
    assert "Check the selected maker's access and PAC sign-in" in str(raised.value)
    assert "Update" not in str(raised.value)


@pytest.mark.parametrize("payload", [[], {"value": [None]}, {"value": {}}])
def test_pac_rejects_malformed_inventory_instead_of_dropping_rows(payload):
    with pytest.raises(runtime.WorkdayConnectRuntimeError, match="valid value array"):
        runtime._list_connections(
            Path("pac.exe"),
            "https://org.crm.dynamics.com",
            runner=lambda *_args, **_kwargs: SimpleNamespace(
                returncode=0, stdout=json.dumps(payload), stderr="",
            ),
        )


def _pac_runner(command, **_kwargs):
    if command[1:3] == ["auth", "list"]:
        return SimpleNamespace(
            returncode=0,
            stdout="[1] * maker@contoso.com Public\n",
            stderr="",
        )
    if command[1:3] == ["connectivity", "list-connections"]:
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(_connections()),
            stderr="",
        )
    raise AssertionError(command)


def _pac_runner_with_connections(payload):
    def runner(command, **_kwargs):
        if command[1:3] == ["auth", "list"]:
            return SimpleNamespace(
                returncode=0,
                stdout="[1] * maker@contoso.com Public\n",
                stderr="",
            )
        if command[1:3] == ["connectivity", "list-connections"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(payload),
                stderr="",
            )
        raise AssertionError(command)

    return runner


def _records():
    catalog = runtime.load_catalog()
    logical_names = [
        catalog["connectionReferences"]["workday"]["logicalName"],
        catalog["connectionReferences"]["dataverse"]["logicalName"],
    ]
    flow_names = catalog["packages"]["runtime"]["flowNames"]
    flows = {
        name: {
            "workflowid": f"44444444-4444-4444-4444-{index:012d}",
            "name": name,
            "statecode": 0,
            "statuscode": 1,
            "category": 5,
        }
        for index, name in enumerate(flow_names, start=1)
    }
    return {
        "references": {
            logical_names[0]: {
                "connectionreferenceid": "ref-workday",
                "connectionreferencelogicalname": logical_names[0],
                "connectionid": None,
            },
            logical_names[1]: {
                "connectionreferenceid": "ref-dataverse",
                "connectionreferencelogicalname": logical_names[1],
                "connectionid": None,
            },
            "agent-workday": {
                "connectionreferencelogicalname": (
                    "contoso.55555555-5555-5555-5555-555555555555.shared_workdaysoap"
                ),
                "connectionreferencedisplayname": "ESS HR Workday",
                "connectionid": "agent-workday-connection",
                "connectionparametersetconfig": '{"values":{}}',
            },
            "agent-dataverse": {
                "connectionreferencelogicalname": (
                    "contoso."
                    "66666666-6666-6666-6666-666666666666."
                    "shared_commondataserviceforapps"
                ),
                "connectionreferencedisplayname": "Microsoft Dataverse",
                "connectionid": "agent-dataverse-connection",
                "connectionparametersconfig": '{"values":{}}',
            },
        },
        "solution": {
            "solutionid": "77777777-7777-7777-7777-777777777777",
            "uniquename": "msdyn_EssWorkdayRuntime",
        },
        "flows": flows,
    }


def _query_for(records):
    def query(_url, _token, entity_set, _select, filter_expr=None):
        if entity_set == "connectionreferences":
            return list(records["references"].values())
        if entity_set == "solutions":
            return [records["solution"]]
        if entity_set == "solutioncomponents":
            return [
                {"objectid": flow["workflowid"], "componenttype": 29}
                for flow in records["flows"].values()
            ]
        if entity_set == "workflows":
            return list(records["flows"].values())
        if entity_set == "delegatedauthorizations":
            return records.get("authorizations", [])
        if entity_set == "businessunits":
            return records.get("businessunits", [{"businessunitid": BUSINESS_UNIT_ID}])
        if entity_set == "teams":
            return records.get(
                "teams" if filter_expr.startswith("delegatedauthorizationid/")
                else "nameConflicts",
                [],
            )
        raise AssertionError(entity_set)

    return query


def _discovery_dependencies(records):
    return {
        "query": _query_for(records),
        "pac_resolver": lambda: Path("pac.exe"),
        "runner": _pac_runner,
    }


def _identity(_token, *, preferred_username):
    return {
        "username": preferred_username,
        "tenantId": "tenant-id",
    }


def _authorization_records(*, team_name=TEAM_NAME):
    records = _records()
    records["authorizations"] = [{
        "delegatedauthorizationid": AUTHORIZATION_ID,
        "botid": BOT_ID,
        "providertype": 3,
    }]
    records["teams"] = [{
        "teamid": TEAM_ID,
        "name": team_name,
        "teamtype": 1,
        "_delegatedauthorizationid_value": AUTHORIZATION_ID,
        "_businessunitid_value": BUSINESS_UNIT_ID,
    }]
    return records


def _authorization_target(records, *, bot_id=BOT_ID, realm="dev"):
    return runtime._authorization_target(
        "https://org.crm.dynamics.com", "token", realm, bot_id,
        query=_query_for(records),
    )


def test_new_team_names_separate_agents_in_the_same_reused_environment():
    records = _records()
    first = _authorization_target(records)
    second = _authorization_target(
        records, bot_id="CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC",
    )
    assert first["teamName"] == TEAM_NAME
    assert second["teamName"] == (
        "ESS DA HR Workday - Development - cccccccc-cccc-cccc-cccc-cccccccccccc"
    )
    assert first["teamName"] != second["teamName"]
    assert first["businessUnitId"] == second["businessUnitId"] == BUSINESS_UNIT_ID
    assert _authorization_target(records, realm="test")["teamName"] == (
        f"ESS DA HR Workday - Test - {BOT_ID}"
    )


def test_existing_exact_agent_legacy_team_is_reused_without_a_name_lookup():
    legacy_name = "ESS DA HR Workday - Development"
    records = _authorization_records(team_name=legacy_name)
    records["nameConflicts"] = [{"teamid": "unrelated-team"}]

    target = _authorization_target(records)

    assert target == {
        "authorizationId": AUTHORIZATION_ID,
        "teamId": TEAM_ID,
        "teamName": legacy_name,
        "businessUnitId": BUSINESS_UNIT_ID,
    }


def test_authorization_created_before_a_failure_can_resume_without_a_team():
    records = _authorization_records()
    records["teams"] = []

    target = _authorization_target(records)

    assert target["authorizationId"] == AUTHORIZATION_ID
    assert target["teamId"] is None
    assert target["teamName"] == TEAM_NAME


@pytest.mark.parametrize("fault", [
    "duplicate-authorization", "duplicate-team", "wrong-provider", "foreign-bot",
    "wrong-team-type", "foreign-authorization", "orphan-team", "unreadable",
    "unreadable-row",
    "missing-business-unit", "ambiguous-business-unit", "foreign-name",
])
def test_authorization_conflicts_fail_before_any_runtime_mutation(fault):
    records = _authorization_records()
    if fault == "duplicate-authorization":
        records["authorizations"] *= 2
    elif fault == "duplicate-team":
        records["teams"] *= 2
    elif fault == "wrong-provider":
        records["authorizations"][0]["providertype"] = 2
    elif fault == "foreign-bot":
        records["authorizations"][0]["botid"] = TEAM_ID
    elif fault == "wrong-team-type":
        records["teams"][0]["teamtype"] = 0
    elif fault == "foreign-authorization":
        records["teams"][0]["_delegatedauthorizationid_value"] = TEAM_ID
    elif fault == "orphan-team":
        records["authorizations"] = []
    elif fault == "unreadable":
        records["authorizations"] = None
    elif fault == "unreadable-row":
        records["authorizations"] = [{}]
        records["teams"] = []
    else:
        records["teams"] = []
        if fault == "missing-business-unit":
            records["businessunits"] = []
        elif fault == "ambiguous-business-unit":
            records["businessunits"] = [{"businessunitid": BUSINESS_UNIT_ID}] * 2
        else:
            records["nameConflicts"] = [{"teamid": "foreign-team"}]
    writes = []
    with pytest.raises(runtime.WorkdayConnectRuntimeError) as error:
        runtime.apply_runtime_plan(
            {
                "scope": {"dataverseUrl": "https://org.crm.dynamics.com", "realm": "dev"},
                "delegatedAuthorization": {"botId": BOT_ID},
            },
            token="token", query=_query_for(records),
            updater=lambda *args: writes.append(args),
        )
    assert writes == []
    assert "administrator" in str(error.value)
    if fault == "foreign-name":
        assert error.value.details["cause"] == "team-name-conflict"
        assert error.value.details["stage"] == "authorization-preflight"
        assert "No runtime changes were made" in str(error.value)


def test_unreadable_authorization_ownership_is_not_treated_as_absent():
    def denied(*_args, **_kwargs):
        raise requests.HTTPError("403 raw confidential response")

    with pytest.raises(runtime.WorkdayConnectRuntimeError) as error:
        runtime._authorization_target(
            "https://org.crm.dynamics.com", "token", "dev", BOT_ID, query=denied,
        )

    assert error.value.details["cause"] == "read-failed"
    assert "verify read access" in str(error.value)
    assert "confidential" not in str(error.value)


def test_apply_rechecks_reviewed_authorization_identity_before_runtime_writes():
    records = _authorization_records()
    approved = _authorization_target(records)
    records["teams"][0]["teamid"] = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    writes = []

    with pytest.raises(runtime.WorkdayConnectRuntimeError, match="changed after approval"):
        runtime.apply_runtime_plan(
            {
                "scope": {"dataverseUrl": "https://org.crm.dynamics.com", "realm": "dev"},
                "delegatedAuthorization": {"botId": BOT_ID, **approved},
            },
            token="token", query=_query_for(records),
            updater=lambda *args: writes.append(args),
        )
    assert writes == []


@pytest.mark.parametrize(("output", "cause"), [
    ("Dataverse POST failed: ndx_TeamName_BusinessUnitId", "team-name-conflict"),
    ("[WD-AUTH-TEAM-NAME-CONFLICT]", "team-name-conflict"),
    ("403 Forbidden", "forbidden"),
    ("[WD-AUTH-INVALID-RECORDS]", "invalid-records"),
    ("unexpected subprocess failure", "script-failed"),
])
@pytest.mark.parametrize("preview", [False, True])
def test_authorization_errors_are_actionable_without_echoing_raw_output(
    monkeypatch, output, cause, preview,
):
    monkeypatch.setattr(runtime.shutil, "which", lambda _name: "pwsh")
    plan = {
        "scope": {
            "dataverseUrl": "https://org.crm.dynamics.com",
            "makerUsername": "maker@contoso.com",
            "realm": "dev",
        },
        "flows": [{"name": "Read Workday"}],
        "delegatedAuthorization": {
            "botId": BOT_ID, "teamName": TEAM_NAME, "script": runtime.AUTHORIZATION_SCRIPT,
            "workflowIds": [WORKDAY_CONNECTION],
        },
    }
    with pytest.raises(runtime.WorkdayConnectRuntimeError) as error:
        runtime._run_authorization(
            plan, preview=preview,
            runner=lambda *_args, **_kwargs: SimpleNamespace(
                returncode=1, stdout=output, stderr="Bearer private-token password=private",
            ),
        )
    message = str(error.value)
    assert "private" not in message
    if cause == "script-failed" and preview:
        assert "preview" in message
    else:
        assert error.value.details["cause"] == cause
        assert error.value.details["nextAction"]
        assert "administrator" in message
        assert "not complete" in message or "No runtime changes" in message


@pytest.mark.parametrize("preview", [False, True])
def test_successful_authorization_does_not_treat_record_names_or_guids_as_errors(
    monkeypatch, preview,
):
    monkeypatch.setattr(runtime.shutil, "which", lambda _name: "pwsh")
    plan = {
        "scope": {
            "dataverseUrl": "https://org.crm.dynamics.com",
            "makerUsername": "maker@contoso.com",
            "realm": "dev",
        },
        "flows": [{"name": "Read Workday"}],
        "delegatedAuthorization": {
            "botId": BOT_ID, "teamName": "Forbidden Legacy Team",
            "script": runtime.AUTHORIZATION_SCRIPT,
            "workflowIds": [WORKDAY_CONNECTION],
            "authorizationId": AUTHORIZATION_ID,
            "teamId": TEAM_ID,
            "businessUnitId": BUSINESS_UNIT_ID,
        },
    }

    def runner(command, **_kwargs):
        assert f"-ExpectedAuthorizationId '{AUTHORIZATION_ID}'" in command[-1]
        assert f"-ExpectedTeamId '{TEAM_ID}'" in command[-1]
        assert f"-BusinessUnitId '{BUSINESS_UNIT_ID}'" in command[-1]
        return SimpleNamespace(
            returncode=0, stderr="",
            stdout="\n".join([
                "[reuse] delegatedauthorization 40311111-1111-1111-1111-111111111111",
                "[reuse] team team-id 'Forbidden Legacy Team' (teamtype 1)",
                "[reuse] 'Read Workday' already shared with the team",
                "Dataverse authorization is in place.",
            ]),
        )

    result = runtime._run_authorization(plan, preview=preview, runner=runner)

    assert result["outcome"] == ("already-configured" if preview else "verified")


def _authorization_preview_runner(command, **_kwargs):
    assert command[-1].endswith("-WhatIf")
    flow_names = runtime.load_catalog()["packages"]["runtime"]["flowNames"]
    output = [
        "  [reuse]  delegatedauthorization authorization-id (providertype 3)",
        "  [reuse]  team team-id 'ESS DA HR Workday - Development' (teamtype 1)",
        *[
            f"  [reuse]  '{flow_name}' already shared with the team "
            "(mask: ReadAccess,WriteAccess)"
            for flow_name in flow_names
        ],
        "Dataverse authorization is in place.",
    ]
    return SimpleNamespace(returncode=0, stdout="\n".join(output), stderr="")


@responses.activate
def test_runtime_plan_uses_one_dataverse_token_and_exact_targets(monkeypatch):
    records = _records()
    token_calls = []
    monkeypatch.setattr(runtime.shutil, "which", lambda _name: "pwsh")
    monkeypatch.setattr(
        runtime, "authenticate_connections", lambda *_args, **_kwargs: _api_token(),
    )
    responses.add(**native.list_connections(items=_connections()["value"]))

    result = runtime.run_runtime_operation(
        _api_state(),
        apply=False,
        token_provider=lambda url, preferred_username: (
            token_calls.append((url, preferred_username)) or "token"
        ),
        identity_provider=_identity,
        authorization_runner=_authorization_preview_runner,
        query=_query_for(records),
        pac_resolver=_no_pac,
    )

    assert token_calls == [("https://org.crm.dynamics.com", "maker@contoso.com")]
    bindings = result["plan"]["connectionBindings"]
    assert {value["connectionId"] for value in bindings.values()} == {
        WORKDAY_CONNECTION,
        DATAVERSE_CONNECTION,
    }
    assert result["approvalSummary"]["connections"] == [
        "Workday",
        "Dataverse",
    ]
    assert result["approvalSummary"]["targetRealm"] == "Development"
    assert result["approvalSummary"]["authorizationTeam"] == (
        "Create a new internal Dataverse access team for this agent."
    )
    assert result["plan"]["delegatedAuthorization"]["teamName"] == TEAM_NAME
    assert result["authorizationPreview"]["outcome"] == "already-configured"
    serialized_summary = __import__("json").dumps(
        result["approvalSummary"],
        sort_keys=True,
    )
    assert WORKDAY_CONNECTION not in serialized_summary
    assert DATAVERSE_CONNECTION not in serialized_summary
    assert BOT_ID not in serialized_summary
    assert len(result["plan"]["flows"]) == 3
    assert "userContext" not in result["plan"]
    assert "token" not in json.dumps(result).casefold()


def test_runtime_plan_requires_verified_physical_connections():
    state = _state()
    state["phases"]["connections"]["status"] = "pending"

    with pytest.raises(
        runtime.WorkdayConnectRuntimeError,
        match="connection sign-ins",
    ):
        runtime.run_runtime_operation(
            state,
            apply=False,
            token_provider=lambda *_args, **_kwargs: "token",
            identity_provider=_identity,
            **_discovery_dependencies(_records()),
        )


def test_physical_connection_verification_returns_selected_connection_ids():
    result = runtime.verify_physical_connections(
        _state(),
        pac_resolver=lambda: Path("pac.exe"),
        runner=_pac_runner,
    )

    assert result == {
        "makerUsername": "maker@contoso.com",
        "connectionIds": {
            "workday": WORKDAY_CONNECTION,
            "dataverse": DATAVERSE_CONNECTION,
        },
        "connections": [
            {
                "connector": "shared_workdaysoap",
                "displayName": "Workday",
            },
            {
                "connector": "shared_commondataserviceforapps",
                "displayName": "Dataverse",
            },
        ],
    }


def test_physical_connection_verification_reports_dataverse_before_workday():
    with pytest.raises(runtime.WorkdayConnectRuntimeError) as raised:
        runtime.verify_physical_connections(
            _state(),
            pac_resolver=lambda: Path("pac.exe"),
            runner=_pac_runner_with_connections({"value": []}),
        )

    assert raised.value.details["connector"] == (
        "shared_commondataserviceforapps"
    )


def test_physical_connection_verification_reports_workday_after_dataverse():
    payload = {
        "value": [
            value
            for value in _connections()["value"]
            if value["name"] == DATAVERSE_CONNECTION
        ]
    }

    with pytest.raises(runtime.WorkdayConnectRuntimeError) as raised:
        runtime.verify_physical_connections(
            _state(),
            pac_resolver=lambda: Path("pac.exe"),
            runner=_pac_runner_with_connections(payload),
        )

    assert raised.value.details["connector"] == "shared_workdaysoap"


@pytest.mark.parametrize(
    ("connector_name", "duplicate_id", "display_name"),
    [
        (
            "shared_workdaysoap",
            "88888888-8888-8888-8888-888888888888",
            "Workday alternate",
        ),
        (
            "shared_commondataserviceforapps",
            "99999999-9999-9999-9999-999999999999",
            "Dataverse alternate",
        ),
    ],
)
def test_physical_connection_ambiguity_exposes_structured_candidates(
    connector_name: str,
    duplicate_id: str,
    display_name: str,
):
    payload = _connections()
    payload["value"].append(
        {
            "name": duplicate_id,
            "properties": {
                "apiId": (
                    f"/providers/Microsoft.PowerApps/apis/{connector_name}"
                ),
                "displayName": display_name,
                "statuses": [{"status": "Connected"}],
            },
        }
    )

    def runner(command, **_kwargs):
        if command[1:3] == ["auth", "list"]:
            return SimpleNamespace(
                returncode=0,
                stdout="[1] * maker@contoso.com Public\n",
                stderr="",
            )
        if command[1:3] == ["connectivity", "list-connections"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(payload),
                stderr="",
            )
        raise AssertionError(command)

    with pytest.raises(runtime.WorkdayConnectRuntimeError) as raised:
        runtime.verify_physical_connections(
            _state(),
            pac_resolver=lambda: Path("pac.exe"),
            runner=runner,
        )

    details = raised.value.details
    candidates = details["candidateConnections"]
    assert details["connector"] == connector_name
    assert {value["connectionId"] for value in candidates} == {
        duplicate_id,
        (
            WORKDAY_CONNECTION
            if connector_name == "shared_workdaysoap"
            else DATAVERSE_CONNECTION
        ),
    }
    assert duplicate_id not in str(raised.value)


def test_runtime_plan_reuses_recorded_connection_ids(monkeypatch):
    state = _state()
    monkeypatch.setattr(runtime.shutil, "which", lambda _name: "pwsh")
    state["phases"]["connections"]["evidence"] = [
        {
            "action": "physical-connections-verified",
            "outcome": "verified",
            "connectionIds": {
                "workday": WORKDAY_CONNECTION,
                "dataverse": DATAVERSE_CONNECTION,
            },
        }
    ]
    duplicate_workday = "99999999-9999-9999-9999-999999999999"
    payload = _connections()
    payload["value"].append(
        {
            "name": duplicate_workday,
            "properties": {
                "apiId": (
                    "/providers/Microsoft.PowerApps/apis/shared_workdaysoap"
                ),
                "displayName": "Workday duplicate",
                "statuses": [{"status": "Connected"}],
            },
        }
    )

    def runner(command, **_kwargs):
        if command[1:3] == ["auth", "list"]:
            return SimpleNamespace(
                returncode=0,
                stdout="[1] * maker@contoso.com Public\n",
                stderr="",
            )
        if command[1:3] == ["connectivity", "list-connections"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(payload),
                stderr="",
            )
        raise AssertionError(command)

    result = runtime.run_runtime_operation(
        state,
        apply=False,
        token_provider=lambda *_args, **_kwargs: "token",
        identity_provider=_identity,
        authorization_runner=_authorization_preview_runner,
        runner=runner,
        query=_query_for(_records()),
        pac_resolver=lambda: Path("pac.exe"),
    )

    bindings = result["plan"]["connectionBindings"].values()
    assert next(
        binding["connectionId"]
        for binding in bindings
        if binding["connector"] == "shared_workdaysoap"
    ) == WORKDAY_CONNECTION


def test_runtime_plan_rejects_connection_id_drift_after_verification():
    state = _state()
    state["phases"]["connections"]["evidence"] = [
        {
            "action": "physical-connections-verified",
            "outcome": "verified",
            "connectionIds": {
                "workday": WORKDAY_CONNECTION,
                "dataverse": DATAVERSE_CONNECTION,
            },
        }
    ]

    with pytest.raises(
        runtime.WorkdayConnectRuntimeError,
        match="differs from the connection verified",
    ):
        runtime.run_runtime_operation(
            state,
            apply=False,
            workday_connection_id=(
                "99999999-9999-9999-9999-999999999999"
            ),
            token_provider=lambda *_args, **_kwargs: "token",
            identity_provider=_identity,
            **_discovery_dependencies(_records()),
        )


def test_runtime_apply_verifies_all_mutations(monkeypatch, capsys):
    records = _records()
    verified_hashes = []
    recorded_stages = []

    def updater(_url, _token, entity_set, record_id, data):
        if entity_set == "connectionreferences":
            for value in records["references"].values():
                if value["connectionreferenceid"] == record_id:
                    value.update(data)
                    return True
        if entity_set == "workflows":
            for value in records["flows"].values():
                if value["workflowid"] == record_id:
                    value.update(data)
                    return True
        raise AssertionError((entity_set, record_id, data))

    monkeypatch.setattr(runtime.shutil, "which", lambda _name: "pwsh.exe")

    def authorization_runner(command, **_kwargs):
        invocation = command[-1]
        assert "-PreferredUsername 'maker@contoso.com'" in invocation
        assert "-WorkflowId @(" in invocation
        for value in records["flows"].values():
            assert value["workflowid"] in invocation
        assert (
            f"-TeamName '{TEAM_NAME}'" in invocation
        )
        assert "-WhatIf" not in invocation
        return SimpleNamespace(
            returncode=0,
            stdout="Dataverse authorization is in place.",
            stderr="",
        )

    result = runtime.run_runtime_operation(
        _state(),
        apply=True,
        approved_hash="approved",
        verifier=lambda plan, approved_hash: verified_hashes.append(
            (plan["planHash"], approved_hash)
        ),
        token_provider=lambda *_args, **_kwargs: "token",
        identity_provider=_identity,
        updater=updater,
        authorization_runner=authorization_runner,
        stage_recorder=lambda action, evidence: recorded_stages.append(
            (action, evidence["outcome"])
        ),
        **_discovery_dependencies(records),
    )

    assert len(verified_hashes) == 1
    assert len(verified_hashes[0][0]) == 64
    assert verified_hashes[0][1] == "approved"
    assert "plan" not in result
    assert result["applied"]["verified"] is True
    assert recorded_stages == [
        ("connection-references-bound", "verified"),
        ("runtime-flows-active", "verified"),
        ("delegated-authorization-configured", "verified"),
    ]
    assert all(value["connectionid"] for value in records["references"].values())
    assert all(
        value["statecode"] == 1 and value["statuscode"] == 2
        for value in records["flows"].values()
    )
    messages = capsys.readouterr().err
    script = "alm/Enable-CosmosDAFlowAuthorization.ps1"
    assert (
        f"[INFO] Running {script} once for 3 reviewed Workday flows in "
        "Development."
    ) in messages
    assert (
        f"[INFO] {script} completed in Development; Dataverse authorization "
        "was verified."
    ) in messages
    assert messages.count("Dataverse authorization was verified.") == 1
    assert result["applied"]["delegatedAuthorization"] == {
        "outcome": "verified",
        "realm": "dev",
        "teamName": TEAM_NAME,
        "workflowCount": 3,
    }
    assert len(result["applied"]["flows"]) == 3
    assert "[ERROR]" not in messages


def test_runtime_records_verified_stages_before_later_failure(monkeypatch, capsys):
    records = _records()
    recorded_stages = []

    def updater(_url, _token, entity_set, record_id, data):
        collections = {
            "connectionreferences": records["references"].values(),
            "workflows": records["flows"].values(),
        }
        if entity_set in collections:
            id_key = (
                "connectionreferenceid"
                if entity_set == "connectionreferences"
                else "workflowid"
            )
            for value in collections[entity_set]:
                if value[id_key] == record_id:
                    value.update(data)
                    return True
        raise AssertionError((entity_set, record_id, data))

    monkeypatch.setattr(runtime.shutil, "which", lambda _name: "pwsh.exe")

    with pytest.raises(
        runtime.WorkdayConnectRuntimeError,
        match="authorization failed",
    ):
        runtime.run_runtime_operation(
            _state(),
            apply=True,
            approved_hash="approved",
            verifier=lambda *_args: None,
            token_provider=lambda *_args, **_kwargs: "token",
            identity_provider=_identity,
            updater=updater,
            authorization_runner=lambda *_args, **_kwargs: SimpleNamespace(
                returncode=1,
                stdout="[FAIL] denied",
                stderr="",
            ),
            stage_recorder=lambda action, _evidence: recorded_stages.append(action),
            **_discovery_dependencies(records),
        )

    assert recorded_stages == [
        "connection-references-bound",
        "runtime-flows-active",
    ]
    assert all(value["connectionid"] for value in records["references"].values())
    assert all(
        value["statecode"] == 1 and value["statuscode"] == 2
        for value in records["flows"].values()
    )
    messages = capsys.readouterr().err
    script = "alm/Enable-CosmosDAFlowAuthorization.ps1"
    assert f"[INFO] Running {script} once for 3 reviewed Workday flows" in messages
    assert f"[ERROR] {script} failed in Development" in messages
    assert "explicit [FAIL] result" in messages
    assert "Dataverse authorization was verified." not in messages


def test_runtime_requires_completed_connection_phase():
    state = _state()
    state["phases"]["connections"]["status"] = "active"

    with pytest.raises(
        runtime.WorkdayConnectRuntimeError,
        match="connection sign-ins",
    ):
        runtime.run_runtime_operation(
            state,
            apply=True,
            approved_hash="approved",
            verifier=lambda *_args: None,
            token_provider=lambda *_args, **_kwargs: "token",
            identity_provider=_identity,
            **_discovery_dependencies(_records()),
        )


def test_runtime_plan_rejects_same_named_flow_outside_package():
    records = _records()
    first_flow = next(iter(records["flows"].values()))
    original_id = first_flow["workflowid"]

    def query(_url, _token, entity_set, _select, filter_expr=None):
        if entity_set == "solutioncomponents":
            return [
                {"objectid": flow["workflowid"], "componenttype": 29}
                for flow in records["flows"].values()
                if flow["workflowid"] != original_id
            ]
        return _query_for(records)(
            _url,
            _token,
            entity_set,
            _select,
            filter_expr,
        )

    with pytest.raises(
        runtime.WorkdayConnectRuntimeError,
        match="outside the selected installed package",
    ):
        runtime.run_runtime_operation(
            _state(),
            apply=False,
            token_provider=lambda *_args, **_kwargs: "token",
            identity_provider=_identity,
            query=query,
            pac_resolver=lambda: Path("pac.exe"),
            runner=_pac_runner,
        )


def test_runtime_connection_inventory_timeout_is_structured():
    def timed_out(command, **_kwargs):
        if command[1:3] == ["auth", "list"]:
            return SimpleNamespace(
                returncode=0,
                stdout="[1] * maker@contoso.com Public\n",
                stderr="",
            )
        raise __import__("subprocess").TimeoutExpired(command, 120)

    with pytest.raises(
        runtime.WorkdayConnectRuntimeError,
        match="within 2 minutes",
    ):
        runtime.run_runtime_operation(
            _state(),
            apply=False,
            token_provider=lambda *_args, **_kwargs: "token",
            identity_provider=_identity,
            query=_query_for(_records()),
            pac_resolver=lambda: Path("pac.exe"),
            runner=timed_out,
        )


def test_runtime_ambiguity_reports_only_safe_display_names():
    records = _records()
    connections = [
        {
            "name": WORKDAY_CONNECTION,
            "properties": {
                "apiId": ("/providers/Microsoft.PowerApps/apis/shared_workdaysoap"),
                "displayName": "Workday Primary",
                "statuses": [{"status": "Connected"}],
            },
        },
        {
            "name": "raw-connection-id-that-must-not-appear",
            "properties": {
                "apiId": ("/providers/Microsoft.PowerApps/apis/shared_workdaysoap"),
                "displayName": "Workday Secondary",
                "statuses": [{"status": "Connected"}],
            },
        },
        {
            "name": DATAVERSE_CONNECTION,
            "properties": {
                "apiId": (
                    "/providers/Microsoft.PowerApps/apis/"
                    "shared_commondataserviceforapps"
                ),
                "displayName": "Dataverse",
                "statuses": [{"status": "Connected"}],
            },
        },
    ]

    def runner(command, **_kwargs):
        if command[1:3] == ["auth", "list"]:
            return SimpleNamespace(
                returncode=0,
                stdout="[1] * maker@contoso.com Public\n",
                stderr="",
            )
        return SimpleNamespace(
            returncode=0,
            stdout=__import__("json").dumps({"value": connections}),
            stderr="",
        )

    with pytest.raises(runtime.WorkdayConnectRuntimeError) as exc_info:
        runtime.run_runtime_operation(
            _state(),
            apply=False,
            token_provider=lambda *_args, **_kwargs: "token",
            identity_provider=_identity,
            query=_query_for(records),
            pac_resolver=lambda: Path("pac.exe"),
            runner=runner,
        )

    message = str(exc_info.value)
    assert "Workday Primary" in message
    assert "Workday Secondary" in message
    assert WORKDAY_CONNECTION not in message
    assert "raw-connection-id-that-must-not-appear" not in message


def test_runtime_rejects_a_different_dataverse_identity():
    import workday_connect_auth as auth

    def mismatch(_token, *, preferred_username):
        raise auth.WorkdayConnectIdentityError(
            "Dataverse authentication used a different account from the "
            "selected Environment Maker."
        )

    with pytest.raises(
        runtime.WorkdayConnectRuntimeError,
        match="different account",
    ):
        runtime.run_runtime_operation(
            _state(),
            apply=False,
            token_provider=lambda *_args, **_kwargs: "token",
            identity_provider=mismatch,
            **_discovery_dependencies(_records()),
        )


def test_runtime_authorization_timeout_is_structured(monkeypatch, capsys):
    plan = {
        "scope": {
            "realm": "test",
            "realmDisplayName": "Test",
            "dataverseUrl": "https://contoso.crm.dynamics.com",
            "makerUsername": "maker@contoso.com",
        },
        "flows": [{"name": "Get Employee Information"}],
        "delegatedAuthorization": {
            "script": "alm/Enable-CosmosDAFlowAuthorization.ps1",
            "botId": BOT_ID,
            "workflowIds": ["workflow-id"],
            "teamName": "ESS DA HR Workday - Test",
        },
    }

    def timed_out(command, **_kwargs):
        raise __import__("subprocess").TimeoutExpired(command, 600)

    monkeypatch.setattr(runtime.shutil, "which", lambda _name: "pwsh")
    with pytest.raises(
        runtime.WorkdayConnectRuntimeError,
        match="within 10 minutes",
    ):
        runtime._run_authorization(
            plan,
            runner=timed_out,
        )

    messages = capsys.readouterr().err
    script = "alm/Enable-CosmosDAFlowAuthorization.ps1"
    assert (
        f"[INFO] Running {script} once for 1 reviewed Workday flows in Test."
    ) in messages
    assert (
        f"[ERROR] {script} failed in Test: "
        "execution did not finish within 10 minutes."
    ) in messages
    assert "Dataverse authorization was verified." not in messages


def test_runtime_authorization_accepts_first_time_whatif_preview(monkeypatch):
    workflow_ids = [
        "44444444-4444-4444-4444-000000000001",
        "44444444-4444-4444-4444-000000000002",
        "44444444-4444-4444-4444-000000000003",
    ]
    flow_names = [
        "Get Employee Information",
        "Get Employee Time Off",
        "Get Employee Time Off Balances",
    ]
    plan = {
        "scope": {
            "realm": "test",
            "realmDisplayName": "Test",
            "dataverseUrl": "https://contoso.crm.dynamics.com",
            "makerUsername": "maker@contoso.com",
        },
        "flows": [
            {"name": name, "workflowId": workflow_id}
            for name, workflow_id in zip(flow_names, workflow_ids, strict=True)
        ],
        "delegatedAuthorization": {
            "script": "alm/Enable-CosmosDAFlowAuthorization.ps1",
            "botId": BOT_ID,
            "workflowIds": workflow_ids,
            "teamName": "ESS DA HR Workday - Test",
        },
    }
    output = "\n".join(
        [
            "  [create] would create delegatedauthorization (providertype 3)",
            "  [create] would create access team (teamtype 1)",
            *[
                f"  [create] would share '{name}' with the team"
                for name in flow_names
            ],
            (
                "  [FAIL] GetTeamsForBotId returned 0 teams; Flow-RP takes "
                "the first and expects exactly one"
            ),
            *[
                f"  [FAIL] {workflow_id} is NOT shared with the team "
                "with WriteAccess"
                for workflow_id in workflow_ids
            ],
            "Verification FAILED - see [FAIL] lines above.",
        ]
    )
    commands = []

    def runner(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=1, stdout=output, stderr="")

    monkeypatch.setattr(runtime.shutil, "which", lambda _name: "pwsh")
    result = runtime._run_authorization(plan, runner=runner, preview=True)

    assert len(commands) == 1
    assert commands[0][-1].endswith("-WhatIf")
    assert result == {
        "outcome": "changes-required",
        "realm": "test",
        "teamName": "ESS DA HR Workday - Test",
        "workflowCount": 3,
        "changesRequired": True,
    }


def test_runtime_authorization_rejects_unsafe_whatif_preview(monkeypatch):
    plan = {
        "scope": {
            "realm": "test",
            "realmDisplayName": "Test",
            "dataverseUrl": "https://contoso.crm.dynamics.com",
            "makerUsername": "maker@contoso.com",
        },
        "flows": [{"name": "Get Employee Information"}],
        "delegatedAuthorization": {
            "script": "alm/Enable-CosmosDAFlowAuthorization.ps1",
            "botId": BOT_ID,
            "workflowIds": [
                "44444444-4444-4444-4444-000000000001",
            ],
            "teamName": "ESS DA HR Workday - Test",
        },
    }
    output = "\n".join(
        [
            "  [reuse] delegatedauthorization authorization-id",
            "  [create] would create access team (teamtype 1)",
            (
                "  [create] would share 'Get Employee Information' "
                "with the team"
            ),
            "Access denied while reading workflow shares.",
        ]
    )
    monkeypatch.setattr(runtime.shutil, "which", lambda _name: "pwsh")

    with pytest.raises(
        runtime.WorkdayConnectRuntimeError,
        match="unsafe or ambiguous",
    ):
        runtime._run_authorization(
            plan,
            runner=lambda *_args, **_kwargs: SimpleNamespace(
                returncode=1,
                stdout=output,
                stderr="",
            ),
            preview=True,
        )
