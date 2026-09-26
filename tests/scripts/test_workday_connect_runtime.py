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
        },
        "flows": {
            name: {
                "workflowid": f"44444444-4444-4444-4444-{index:012d}",
                "name": name,
                "statecode": 0,
                "statuscode": 1,
                "category": 5,
            }
            for index, name in enumerate(flow_names, start=1)
        },
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
        **_discovery_dependencies(records),
    )

    assert token_calls == [
        ("https://org.crm.dynamics.com", "maker@contoso.com")
    ]
    assert result["plan"]["connectionBindings"] == {
        runtime.load_catalog()["connectionReferences"]["workday"][
            "logicalName"
        ]: WORKDAY_CONNECTION,
        runtime.load_catalog()["connectionReferences"]["dataverse"][
            "logicalName"
        ]: DATAVERSE_CONNECTION,
    }
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
            **_discovery_dependencies(_records()),
        )
