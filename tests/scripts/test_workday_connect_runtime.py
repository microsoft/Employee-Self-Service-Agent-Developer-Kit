from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import json
import sys

import pytest


SCRIPTS = (
    Path(__file__).resolve().parents[2]
    / "solutions"
    / "ess-maker-skills"
    / "scripts"
)
sys.path.insert(0, str(SCRIPTS))

import workday_connect_runtime as runtime  # noqa: E402
from workday_connect_model import default_state  # noqa: E402


BOT_ID = "11111111-1111-1111-1111-111111111111"
WORKDAY_CONNECTION = "22222222-2222-2222-2222-222222222222"
DATAVERSE_CONNECTION = "33333333-3333-3333-3333-333333333333"


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
    state["operators"]["powerPlatformMaker"] = {
        "username": "maker@contoso.com"
    }
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
                    "contoso."
                    "55555555-5555-5555-5555-555555555555."
                    "shared_workdaysoap"
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
        "setup": {
            "botcomponentid": "setup-topic",
            "name": runtime.SETUP_TOPIC_NAME,
            "schemaname": "contoso.topic.setusercontext",
            "data": (
                "kind: AdaptiveDialog\n"
                "beginDialog:\n"
                "  kind: OnRedirect\n"
                "  actions: []\n"
            ),
            "statecode": 0,
            "statuscode": 1,
        },
        "target": {
            "botcomponentid": "target-topic",
            "name": runtime.TARGET_TOPIC_NAME,
            "schemaname": "contoso.topic.workdaysystemgetusercontextv2",
            "data": "",
            "statecode": 0,
            "statuscode": 1,
        },
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
        if entity_set == "botcomponents":
            if filter_expr and "componenttype eq 9" in filter_expr:
                return [records["setup"], records["target"]]
            return [records["setup"]]
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


def test_runtime_plan_uses_one_dataverse_token_and_exact_targets():
    records = _records()
    token_calls = []

    result = runtime.run_runtime_operation(
        _state(),
        apply=False,
        token_provider=lambda url, preferred_username: token_calls.append(
            (url, preferred_username)
        )
        or "token",
        identity_provider=_identity,
        **_discovery_dependencies(records),
    )

    assert token_calls == [
        ("https://org.crm.dynamics.com", "maker@contoso.com")
    ]
    bindings = result["plan"]["connectionBindings"]
    assert {
        value["connectionId"] for value in bindings.values()
    } == {WORKDAY_CONNECTION, DATAVERSE_CONNECTION}
    assert result["approvalSummary"]["connections"] == [
        "Workday",
        "Dataverse",
    ]
    assert result["approvalSummary"]["userContextTarget"] == (
        runtime.TARGET_TOPIC_NAME
    )
    serialized_summary = __import__("json").dumps(
        result["approvalSummary"],
        sort_keys=True,
    )
    assert WORKDAY_CONNECTION not in serialized_summary
    assert DATAVERSE_CONNECTION not in serialized_summary
    assert len(result["plan"]["flows"]) == 3
    assert result["plan"]["userContext"]["targetTopicSchema"].endswith(
        "workdaysystemgetusercontextv2"
    )
    assert "token" not in json.dumps(result).casefold()


def test_runtime_plan_stops_on_custom_user_context():
    records = _records()
    records["setup"]["data"] = (
        "kind: AdaptiveDialog\n"
        "beginDialog:\n"
        "  kind: OnRedirect\n"
        "  actions:\n"
        "    - kind: SendActivity\n"
        "      activity: custom\n"
    )

    with pytest.raises(
        runtime.WorkdayConnectRuntimeError,
        match="custom content",
    ):
        runtime.run_runtime_operation(
            _state(),
            apply=False,
            token_provider=lambda *_args, **_kwargs: "token",
            identity_provider=_identity,
            **_discovery_dependencies(records),
        )


def test_runtime_apply_verifies_all_mutations(monkeypatch):
    records = _records()
    verified_hashes = []

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
        if entity_set == "botcomponents" and record_id == "setup-topic":
            records["setup"].update(data)
            return True
        raise AssertionError((entity_set, record_id, data))

    monkeypatch.setattr(runtime.shutil, "which", lambda _name: "pwsh.exe")

    def authorization_runner(command, **_kwargs):
        assert command[-2] == "-WorkflowId"
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
        **_discovery_dependencies(records),
    )

    assert verified_hashes == [(result["plan"]["planHash"], "approved")]
    assert result["applied"]["verified"] is True
    assert all(
        value["connectionid"]
        for value in records["references"].values()
    )
    assert all(
        value["statecode"] == 1 and value["statuscode"] == 2
        for value in records["flows"].values()
    )
    assert runtime._redirect_state(
        records["setup"]["data"],
        records["target"]["schemaname"],
    ) == "configured"


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
                "apiId": (
                    "/providers/Microsoft.PowerApps/apis/shared_workdaysoap"
                ),
                "displayName": "Workday Primary",
                "statuses": [{"status": "Connected"}],
            },
        },
        {
            "name": "raw-connection-id-that-must-not-appear",
            "properties": {
                "apiId": (
                    "/providers/Microsoft.PowerApps/apis/shared_workdaysoap"
                ),
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


def test_runtime_authorization_timeout_is_structured(monkeypatch):
    plan = {
        "scope": {"dataverseUrl": "https://contoso.crm.dynamics.com"},
        "delegatedAuthorization": {
            "script": "alm/Enable-CosmosDAFlowAuthorization.ps1",
            "botId": BOT_ID,
            "workflowIds": ["workflow-id"],
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
