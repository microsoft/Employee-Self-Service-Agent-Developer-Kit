# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

from copy import deepcopy
import json
from unittest.mock import Mock

import pytest
import requests
import responses

import add_sharepoint_library as library
from agentbuilder import AgentBuilderClient, AgentBuilderError


AGENT = "00000000-0000-4000-8000-000000002222"
ENVIRONMENT = "00000000-0000-4000-8000-000000001111"
TENANT = "00000000-0000-4000-8000-000000003333"
HOST = "https://0000000000004000800000000000111.1.environment.api.test.powerplatform.com"
ENDPOINT = f"{HOST}/copilotstudio/minimalBots/api/{AGENT}/components"
SCHEMA = "gptagent_copilotforemployeeselfservicehr"
URL = "https://contoso.sharepoint.com/sites/HR/SitePages/"
CONTEXT = {
    "agent_id": AGENT,
    "environment_id": ENVIRONMENT,
    "tenant_id": TENANT,
    "host": HOST,
    "ring": "test",
    "schema": SCHEMA,
}


@pytest.fixture
def setup():
    config = {
        "configVersion": 1,
        "releaseLine": "da",
        "activeAgent": "hr",
        "environmentId": ENVIRONMENT,
        "agent": {"slug": "hr", "botId": AGENT, "schemaName": SCHEMA},
    }
    state = {
        "schema_version": 4,
        "environment": {
            "id": ENVIRONMENT,
            "tenant_id": TENANT,
            "power_platform_api_endpoint": HOST,
            "ring": "test",
        },
        "agents": {
            AGENT: {
                "agent": {"id": AGENT, "schema_name": SCHEMA, "workspace_slug": "hr"},
                "workspace": {"folder": "hr", "agent_path": "agents/hr"},
                "steps": {"SETUP-07": {"state": "done"}},
                "connect_ready": False,
            }
        },
    }
    return config, state


@pytest.fixture
def snapshot():
    return {
        "bot": {"cdsBotId": AGENT, "schemaName": SCHEMA, "displayName": "Test HR"},
        "changeToken": "fresh-change-token",
        "botComponentChanges": [
            {
                "$kind": "BotComponentInsert",
                "component": {
                    "$kind": "DialogComponent",
                    "id": "00000000-0000-4000-8000-000000004444",
                    "schemaName": f"{SCHEMA}.topic.Greeting",
                    "dialog": {"startBehavior": "UseLatestPublishedContent"},
                },
            },
            {
                "$kind": "BotComponentInsert",
                "component": {
                    "$kind": "KnowledgeSourceComponent",
                    "id": "00000000-0000-4000-8000-000000005555",
                    "configuration": {
                        "source": {
                            "$kind": "SharePointSearchSource",
                            "site": {
                                "$kind": "StringExpression",
                                "literalValue": "https://contoso.sharepoint.com/sites/AnotherSite/",
                            },
                        }
                    },
                },
            },
        ],
        "connectionReferenceChanges": [{"connectionReference": {"connectionId": "preserve"}}],
        "connectorDefinitionChanges": [],
    }


def client():
    return AgentBuilderClient(HOST, "synthetic-token", ring="test", tenant_id=TENANT)


@responses.activate
def test_cli_preview_apply_and_rerun_preserve_existing_components(
    snapshot, setup, tmp_path, monkeypatch
):
    original = deepcopy(snapshot)
    writes = []
    reads = 0
    config, state = setup
    monkeypatch.chdir(tmp_path)
    setup_path = tmp_path / ".local" / "setup"
    setup_path.mkdir(parents=True)
    (setup_path / "config.json").write_text(json.dumps(state), encoding="utf-8")
    (setup_path.parent / "config.json").write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(library, "authenticate", Mock(return_value="synthetic-token"))

    def fetch(request):
        nonlocal reads
        reads += 1
        snapshot["changeToken"] = f"read-{reads}"
        assert json.loads(request.body) == {}
        return 200, {}, json.dumps(snapshot)

    def insert(request):
        payload = json.loads(request.body)
        writes.append(payload)
        snapshot["botComponentChanges"].extend(payload["botComponentChanges"])
        snapshot["changeToken"] = "next-change-token"
        return 200, {}, "{}"

    responses.add_callback(responses.POST, ENDPOINT, callback=fetch)
    responses.add_callback(responses.PUT, ENDPOINT, callback=insert)
    assert library.main(["--library-url", URL]) == 0
    assert writes == []
    apply_args = [
        "--apply",
        "--yes",
        "--expected-agent-id",
        AGENT,
        "--expected-environment-id",
        ENVIRONMENT,
    ]
    assert library.main(["--library-url", URL, *apply_args]) == 0
    assert len(writes) == 1
    payload = writes[0]
    assert set(payload) == {
        "changeToken",
        "botComponentChanges",
        "connectionReferenceChanges",
        "connectorDefinitionChanges",
    }
    assert payload["changeToken"] == "read-2"
    assert payload["connectionReferenceChanges"] == []
    assert payload["connectorDefinitionChanges"] == []
    assert len(payload["botComponentChanges"]) == 1
    change = payload["botComponentChanges"][0]
    assert change["$kind"] == "BotComponentInsert"
    assert change["component"]["configuration"] == {
        "$kind": "KnowledgeSourceConfiguration",
        "source": {
            "$kind": "SharePointSearchSource",
            "cascadeShare": False,
            "site": {"$kind": "StringExpression", "literalValue": URL},
        },
    }
    assert snapshot["botComponentChanges"][:-1] == original["botComponentChanges"]
    backup = list((tmp_path / ".local" / "backups" / "sharepoint-library").glob("*.json"))
    assert len(backup) == 1
    original["changeToken"] = "read-2"
    assert json.loads(backup[0].read_text(encoding="utf-8")) == original
    assert [call.request.method for call in responses.calls] == ["POST", "POST", "PUT", "POST"]
    assert all("api-version=2022-03-01-preview" in call.request.url for call in responses.calls)
    assert library.main(["--library-url", URL.rstrip("/"), *apply_args]) == 0
    assert len(writes) == 1


@pytest.mark.parametrize(
    "apply,answer,status", [(False, None, "preview"), (True, "no", "cancelled")]
)
@responses.activate
def test_preview_and_decline_never_write(snapshot, tmp_path, monkeypatch, apply, answer, status):
    responses.add(responses.POST, ENDPOINT, json=snapshot)
    monkeypatch.setattr("builtins.input", lambda _: answer)
    result = library.apply_library(client(), CONTEXT, URL, apply=apply, backup_root=tmp_path)
    assert result["status"] == status
    assert len(responses.calls) == 1
    assert list(tmp_path.iterdir()) == []


@responses.activate
def test_duplicate_normalizes_escaped_spaces_case_and_trailing_slash(snapshot, tmp_path):
    snapshot["botComponentChanges"][1]["component"]["configuration"]["source"]["site"][
        "literalValue"
    ] = "https://CONTOSO.sharepoint.com/sites/hr/Shared Documents"
    responses.add(responses.POST, ENDPOINT, json=snapshot)
    result = library.apply_library(
        client(),
        CONTEXT,
        "https://contoso.sharepoint.com/sites/HR/Shared%20Documents/",
        apply=True,
        auto_yes=True,
        backup_root=tmp_path,
    )
    assert result["status"] == "already-configured"
    assert len(responses.calls) == 1
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("failure", [409, 412, 500, requests.Timeout("response lost")])
@responses.activate
def test_write_failure_is_not_retried_and_backup_is_retained(snapshot, tmp_path, failure):
    responses.add(responses.POST, ENDPOINT, json=snapshot)
    if isinstance(failure, int):
        responses.add(
            responses.PUT, ENDPOINT, status=failure, json={"error": {"code": "TestFailure"}}
        )
    else:
        responses.add(responses.PUT, ENDPOINT, body=failure)
    with pytest.raises(AgentBuilderError, match="may have committed"):
        library.apply_library(
            client(), CONTEXT, URL, apply=True, auto_yes=True, backup_root=tmp_path
        )
    assert [call.request.method for call in responses.calls] == ["POST", "PUT"]
    assert len(list(tmp_path.glob("*.json"))) == 1


@pytest.mark.parametrize("corruption", ["missing-source", "changed-existing", "readback-timeout"])
@responses.activate
def test_readback_failure_is_not_success(snapshot, tmp_path, corruption):
    responses.add(responses.POST, ENDPOINT, json=snapshot)

    def insert(request):
        after = deepcopy(snapshot)
        if corruption != "missing-source":
            after["botComponentChanges"].extend(json.loads(request.body)["botComponentChanges"])
        if corruption == "changed-existing":
            after["botComponentChanges"][0]["component"]["displayName"] = "Concurrent edit"
        if corruption == "readback-timeout":
            responses.add(responses.POST, ENDPOINT, body=requests.Timeout("readback lost"))
        else:
            responses.add(responses.POST, ENDPOINT, json=after)
        return 200, {}, "{}"

    responses.add_callback(responses.PUT, ENDPOINT, callback=insert)
    with pytest.raises(AgentBuilderError, match="verification failed|may have committed"):
        library.apply_library(
            client(), CONTEXT, URL, apply=True, auto_yes=True, backup_root=tmp_path
        )
    assert len(responses.calls) == 3
    assert len(list(tmp_path.glob("*.json"))) == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://contoso.sharepoint.com/sites/HR/SitePages/",
        "https://contoso.sharepoint.com.evil.example/sites/HR/SitePages/",
        "https://user@contoso.sharepoint.com/sites/HR/SitePages/",
        "https://contoso.sharepoint.com/sites/HR/",
        "https://contoso.sharepoint.com/",
        "https://contoso.sharepoint.com/sites/HR/SitePages/page.aspx",
        "https://contoso.sharepoint.com/sites/HR/document.pdf",
        "https://contoso.sharepoint.com/sites/HR/Shared%20Documents/Forms/AllItems.aspx",
        URL + "?view=all",
        URL + "#fragment",
        "https://contoso.sharepoint.com/sites/HR/../",
    ],
)
def test_invalid_url_fails_before_network(url):
    transport = Mock()
    with pytest.raises(ValueError):
        library.apply_library(transport, CONTEXT, url, apply=True, auto_yes=True)
    transport.fetch_components.assert_not_called()


def test_materialized_setup_does_not_require_connector_readiness(setup):
    assert library.setup_context(*setup) == CONTEXT


@pytest.mark.parametrize(
    "problem",
    [
        "preview",
        "wrong-agent",
        "wrong-slug",
        "wrong-schema",
        "wrong-environment",
        "wrong-host",
        "workspace",
        "duplicate",
        "schema",
        "malformed",
    ],
)
def test_setup_identity_and_backend_guards(setup, problem):
    config, state = setup
    if problem == "preview":
        config["dataverseEndpoint"] = "https://example.crm.dynamics.com"
    elif problem == "wrong-agent":
        config["agent"]["botId"] = TENANT
    elif problem == "wrong-slug":
        config["agent"]["slug"] = "other"
    elif problem == "wrong-schema":
        config["agent"]["schemaName"] = "other"
    elif problem == "wrong-environment":
        config["environmentId"] = TENANT
    elif problem == "wrong-host":
        state["environment"]["power_platform_api_endpoint"] = HOST.replace("111.1.", "222.2.")
    elif problem == "workspace":
        state["agents"][AGENT]["steps"]["SETUP-07"]["state"] = "blocked"
    elif problem == "duplicate":
        state["agents"]["duplicate"] = deepcopy(state["agents"][AGENT])
    elif problem == "schema":
        state["schema_version"] = 3
    else:
        state = []
    with pytest.raises((AgentBuilderError, ValueError)):
        library.setup_context(config, state)


@responses.activate
def test_live_identity_mismatch_blocks_write(snapshot, tmp_path):
    snapshot["bot"]["cdsBotId"] = TENANT
    responses.add(responses.POST, ENDPOINT, json=snapshot)
    with pytest.raises(AgentBuilderError, match="identity"):
        library.apply_library(
            client(), CONTEXT, URL, apply=True, auto_yes=True, backup_root=tmp_path
        )
    assert len(responses.calls) == 1
    assert list(tmp_path.iterdir()) == []


def test_cli_requires_confirmed_preview_target_before_authentication(
    setup, tmp_path, monkeypatch, capsys
):
    config, state = setup
    monkeypatch.chdir(tmp_path)
    path = tmp_path / ".local" / "setup"
    path.mkdir(parents=True)
    (path / "config.json").write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(library, "load_config", lambda: config)
    auth = Mock()
    monkeypatch.setattr(library, "authenticate", auth)
    assert library.main(["--library-url", URL, "--apply", "--yes"]) == 1
    assert "matching the preview" in capsys.readouterr().out
    auth.assert_not_called()
