# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from flightcheck.checks.servicenow_da_hrsd import (
    run_servicenow_da_hrsd_checks,
)
from flightcheck.runner import Status

import connect_servicenow_da as snow


ENVIRONMENT_ID = "00000000-0000-4000-8000-000000001111"
AGENT_ID = "00000000-0000-4000-8000-000000002222"
CONNECTION_ID = "00000000000040008000000000003333"
AGENT_SLUG = "employee-self-service-hr"


def _components() -> dict:
    return {
        "changeToken": "token",
        "botComponentChanges": [
            {
                "$kind": "BotComponentInsert",
                "component": {
                    "$kind": "DialogComponent",
                    "id": "00000000-0000-4000-8000-000000005555",
                    "version": 1,
                    "displayName": "ServiceNow HRSD Get Cases",
                    "schemaName": (
                        f"{snow.HR_SCHEMA_NAME}.topic.ServiceNowHRSDGetCases"
                    ),
                    "state": "Active",
                    "status": "Active",
                    "dialog": {"$kind": "TaskDialog"},
                },
            }
        ],
        "connectionReferenceChanges": [
            {
                "connectionReference": {
                    "id": "00000000-0000-4000-8000-000000004444",
                    "connectorId": snow.CONNECTOR_ID,
                    "connectionReferenceLogicalName": "servicenow-ref",
                    "displayName": "ServiceNow",
                    "connectionId": CONNECTION_ID,
                    "sharedConnectionParameters": json.dumps(
                        {"name": "entraIDUserLogin", "values": {}}
                    ),
                }
            }
        ],
        "connectorDefinitionChanges": [],
    }


def _connection() -> dict:
    return {
        "name": CONNECTION_ID,
        "properties": {
            "apiId": snow.CONNECTOR_ID,
            "displayName": "ServiceNow",
            "statuses": [{"target": "token", "status": "Connected"}],
            "connectionParametersSet": {"name": "entraIDUserLogin"},
        },
    }


def _runner(components: dict):
    return SimpleNamespace(
        config={
            "activeAgent": AGENT_SLUG,
            "agents": [
                {
                    "slug": AGENT_SLUG,
                    "botId": AGENT_ID,
                    "schemaName": snow.HR_SCHEMA_NAME,
                }
            ],
        },
        agentbuilder=SimpleNamespace(
            fetch_components=lambda _agent_id: components
        ),
        connectivity=SimpleNamespace(
            list_connections=lambda _environment_id: [_connection()]
        ),
        env_id=ENVIRONMENT_ID,
    )


def _write_state(root: Path, components: dict) -> None:
    path = (
        root
        / ".local"
        / "connect"
        / snow.PROVIDER_KEY
        / "agents"
        / AGENT_SLUG
        / "lifecycle.json"
    )
    path.parent.mkdir(parents=True)
    component_hash = snow._component_hash(components)
    path.write_text(
        json.dumps(
            {
                "provider": snow.PROVIDER_KEY,
                "agentSlug": AGENT_SLUG,
                "agentId": AGENT_ID,
                "environmentId": ENVIRONMENT_ID,
                "evidence": {
                    "credential": {"connectionId": CONNECTION_ID},
                    "agentConnection": {
                        "makerAttested": True,
                        "connectionId": CONNECTION_ID,
                        "binding": {
                            "componentHash": component_hash,
                            "connectionId": CONNECTION_ID,
                        },
                    },
                    "parameterSharing": {
                        "makerAttested": True,
                        "status": "not-exposed",
                        "binding": {
                            "componentHash": component_hash,
                            "connectionId": CONNECTION_ID,
                        },
                    },
                    "publish": {
                        "status": "completed",
                        "componentHash": component_hash,
                        "completedAt": "2026-09-28T00:00:00Z",
                    },
                    "test": {
                        "result": "pass",
                        "binding": {
                            "publishedComponentHash": component_hash,
                        },
                    },
                },
            }
        ),
        encoding="utf-8",
    )


def test_hrsd_checks_preserve_manual_maker_evidence(
    monkeypatch,
    tmp_path: Path,
) -> None:
    components = _components()
    _write_state(tmp_path, components)
    monkeypatch.chdir(tmp_path)

    results = run_servicenow_da_hrsd_checks(_runner(components))
    statuses = {result.checkpoint_id: result.status for result in results}

    assert statuses["SN-DA-HRSD-PKG-001"] == Status.PASSED.value
    assert statuses["SN-DA-HRSD-TOPICS-001"] == Status.PASSED.value
    assert statuses["SN-DA-HRSD-CREDENTIAL-001"] == Status.PASSED.value
    assert (
        statuses["SN-DA-HRSD-AGENT-CONNECTION-001"]
        == Status.MANUAL.value
    )
    assert (
        statuses["SN-DA-HRSD-PARAMETER-SHARING-001"]
        == Status.MANUAL.value
    )
    assert statuses["SN-DA-HRSD-PUBLISH-001"] == Status.PASSED.value
    assert statuses["SN-DA-HRSD-TEST-001"] == Status.MANUAL.value


def test_hrsd_checks_reopen_stale_maker_evidence(
    monkeypatch,
    tmp_path: Path,
) -> None:
    components = _components()
    _write_state(tmp_path, components)
    components["changeToken"] = "new-token"
    monkeypatch.chdir(tmp_path)

    results = run_servicenow_da_hrsd_checks(_runner(components))
    statuses = {result.checkpoint_id: result.status for result in results}

    assert (
        statuses["SN-DA-HRSD-AGENT-CONNECTION-001"]
        == Status.NOT_CONFIGURED.value
    )
    assert (
        statuses["SN-DA-HRSD-PARAMETER-SHARING-001"]
        == Status.NOT_CONFIGURED.value
    )
    assert statuses["SN-DA-HRSD-PUBLISH-001"] == Status.NOT_CONFIGURED.value
    assert statuses["SN-DA-HRSD-TEST-001"] == Status.NOT_CONFIGURED.value


def test_agent_connection_accepts_legacy_root_only_connection_id(
    monkeypatch,
    tmp_path: Path,
) -> None:
    components = _components()
    _write_state(tmp_path, components)
    path = (
        tmp_path
        / ".local"
        / "connect"
        / snow.PROVIDER_KEY
        / "agents"
        / AGENT_SLUG
        / "lifecycle.json"
    )
    state = json.loads(path.read_text(encoding="utf-8"))
    del state["evidence"]["agentConnection"]["binding"]["connectionId"]
    path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    results = run_servicenow_da_hrsd_checks(_runner(components))
    result = next(
        item
        for item in results
        if item.checkpoint_id == "SN-DA-HRSD-AGENT-CONNECTION-001"
    )

    assert result.status == Status.MANUAL.value


def test_agent_connection_rejects_conflicting_nested_and_root_ids(
    monkeypatch,
    tmp_path: Path,
) -> None:
    components = _components()
    _write_state(tmp_path, components)
    path = (
        tmp_path
        / ".local"
        / "connect"
        / snow.PROVIDER_KEY
        / "agents"
        / AGENT_SLUG
        / "lifecycle.json"
    )
    state = json.loads(path.read_text(encoding="utf-8"))
    state["evidence"]["agentConnection"]["connectionId"] = (
        "00000000000040008000000000009999"
    )
    path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    results = run_servicenow_da_hrsd_checks(_runner(components))
    result = next(
        item
        for item in results
        if item.checkpoint_id == "SN-DA-HRSD-AGENT-CONNECTION-001"
    )

    assert result.status == Status.NOT_CONFIGURED.value
    assert "conflicting connection identities" in result.result


def test_agent_connection_rejects_wrong_selected_connection_id(
    monkeypatch,
    tmp_path: Path,
) -> None:
    components = _components()
    _write_state(tmp_path, components)
    other_id = "00000000000040008000000000009999"
    path = (
        tmp_path
        / ".local"
        / "connect"
        / snow.PROVIDER_KEY
        / "agents"
        / AGENT_SLUG
        / "lifecycle.json"
    )
    state = json.loads(path.read_text(encoding="utf-8"))
    state["evidence"]["credential"]["connectionId"] = other_id
    path.write_text(json.dumps(state), encoding="utf-8")
    runner = _runner(components)
    other_connection = _connection()
    other_connection["name"] = other_id
    runner.connectivity = SimpleNamespace(
        list_connections=lambda _environment_id: [other_connection]
    )
    monkeypatch.chdir(tmp_path)

    results = run_servicenow_da_hrsd_checks(runner)
    result = next(
        item
        for item in results
        if item.checkpoint_id == "SN-DA-HRSD-AGENT-CONNECTION-001"
    )

    assert result.status == Status.NOT_CONFIGURED.value
    assert "different selected credential" in result.result


def test_agent_connection_reports_component_revision_stale(
    monkeypatch,
    tmp_path: Path,
) -> None:
    components = _components()
    _write_state(tmp_path, components)
    components["changeToken"] = "new-token"
    monkeypatch.chdir(tmp_path)

    results = run_servicenow_da_hrsd_checks(_runner(components))
    result = next(
        item
        for item in results
        if item.checkpoint_id == "SN-DA-HRSD-AGENT-CONNECTION-001"
    )

    assert result.status == Status.NOT_CONFIGURED.value
    assert "stale for this component revision" in result.result


def test_hrsd_package_absence_is_not_configured(
    monkeypatch,
    tmp_path: Path,
) -> None:
    components = _components()
    components["botComponentChanges"] = []
    components["connectionReferenceChanges"] = []
    monkeypatch.chdir(tmp_path)

    results = run_servicenow_da_hrsd_checks(_runner(components))

    assert {
        result.status for result in results
    } == {Status.NOT_CONFIGURED.value}


def test_hrsd_checks_prefer_explicit_agent_slug(
    monkeypatch,
    tmp_path: Path,
) -> None:
    components = _components()
    requested_id = "00000000-0000-4000-8000-000000008888"
    fetched: list[str] = []
    runner = _runner(components)
    runner.agent_slug = "requested-hr"
    runner.config = {
        "activeAgent": AGENT_SLUG,
        "agents": [
            {
                "slug": AGENT_SLUG,
                "botId": AGENT_ID,
                "schemaName": snow.HR_SCHEMA_NAME,
            },
            {
                "slug": "requested-hr",
                "botId": requested_id,
                "schemaName": snow.HR_SCHEMA_NAME,
            },
        ],
    }
    runner.agentbuilder = SimpleNamespace(
        fetch_components=lambda agent_id: (
            fetched.append(agent_id) or components
        )
    )
    monkeypatch.chdir(tmp_path)

    run_servicenow_da_hrsd_checks(runner)

    assert fetched == [requested_id]
