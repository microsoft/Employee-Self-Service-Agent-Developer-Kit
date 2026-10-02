# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentbuilder import AgentBuilderHTTPError
from flightcheck.checks.servicenow_da_hrsd import (
    run_servicenow_da_hrsd_checks,
)
from flightcheck.runner import FlightCheckRunner, Status

import connect_servicenow_da as snow
from tests.conftest import require_validated_mock
from tests.mocks import graph as graph_mock


ENVIRONMENT_ID = "00000000-0000-4000-8000-000000001111"
AGENT_ID = "00000000-0000-4000-8000-000000002222"
CONNECTION_ID = "00000000000040008000000000003333"
APP_CLIENT_ID = "00000000-0000-4000-8000-000000006666"
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
                        {
                            "name": "entraIDUserLogin",
                            "values": {
                                "token:InstanceName": {"value": "dev123"},
                                "token:ResourceUri": {
                                    "value": APP_CLIENT_ID
                                },
                            },
                        }
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
            "connectionParametersSet": {
                "name": "entraIDUserLogin",
                "values": {
                    "token:InstanceName": {"value": "dev123"},
                    "token:ResourceUri": {"value": APP_CLIENT_ID},
                },
            },
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
            list_connections=lambda _environment_id: pytest.fail(
                "ServiceNow HRSD must not use environment-wide inventory."
            ),
            list_connector_connections=lambda environment_id, connector: (
                [_connection()]
                if (
                    environment_id == ENVIRONMENT_ID
                    and connector == snow.CONNECTOR_NAME
                )
                else pytest.fail("Unexpected connector inventory target.")
            ),
        ),
        env_id=ENVIRONMENT_ID,
    )


def _registered_runner(
    components: dict,
    *,
    target_test_only: bool = False,
) -> FlightCheckRunner:
    source = _runner(components)
    runner = FlightCheckRunner(
        scope="servicenow-da-hrsd",
        target_matcher=(
            lambda checkpoint_id: checkpoint_id == "SN-DA-HRSD-TEST-001"
        )
        if target_test_only
        else None,
    )
    for name in ("config", "agentbuilder", "connectivity", "env_id"):
        setattr(runner, name, getattr(source, name))
    runner.register("ServiceNow DA HRSD", run_servicenow_da_hrsd_checks)
    return runner


def _checkpoint(results, checkpoint_id: str):
    return next(
        row for row in results if row.checkpoint_id == checkpoint_id
    )


def _graph_client(
    *,
    missing_claims: bool = False,
    foreign_consent: bool = False,
):
    require_validated_mock(graph_mock)
    application = graph_mock.application(
        app_id=APP_CLIENT_ID,
        connector_app_id=snow.SERVICENOW_CONNECTOR_APP_ID,
        optional_claim_names=(
            ("email",) if missing_claims else ("email", "upn")
        ),
    )
    service_principal = graph_mock.service_principal(
        app_id=APP_CLIENT_ID,
        sp_id="00000000-0000-4000-8000-000000007777",
        application_template_id=None,
    )
    graph_service_principal = graph_mock.service_principal(
        app_id=graph_mock.MS_GRAPH_RESOURCE_APP_ID,
        sp_id="00000000-0000-4000-8000-000000008888",
        application_template_id=None,
    )
    grant = graph_mock.oauth2_permission_grant(
        client_id=service_principal["id"],
        resource_id=(
            "00000000-0000-4000-8000-000000009999"
            if foreign_consent
            else graph_service_principal["id"]
        ),
    )

    class FakeGraph:
        def get_all(
            self,
            path: str,
            params: dict | None = None,
            *,
            raise_on_permission_error: bool = False,
        ) -> list[dict]:
            del params, raise_on_permission_error
            if path == "/applications":
                return [application]
            if path == "/oauth2PermissionGrants":
                return [grant]
            raise AssertionError(f"Unexpected Graph path: {path}")

        def get_service_principals(
            self,
            *,
            filter_expr: str = "",
            **_kwargs,
        ) -> list[dict]:
            if graph_mock.MS_GRAPH_RESOURCE_APP_ID in filter_expr:
                return [graph_service_principal]
            return [service_principal]

    return FakeGraph()


def _state_path(root: Path) -> Path:
    return (
        root
        / ".local"
        / "connect"
        / snow.PROVIDER_KEY
        / "agents"
        / AGENT_SLUG
        / "lifecycle.json"
    )


def _write_state(root: Path, components: dict) -> None:
    path = _state_path(root)
    path.parent.mkdir(parents=True)
    component_hash = snow._component_hash(components)
    discovery = {
        "source": "connectivity-readonly",
        "observedAt": "2026-09-29T00:00:00Z",
        "connectionCandidates": [],
        "requiredPlugins": [],
    }
    handoffs = {
        phase: {
            "status": "completed",
            "evidence": {
                "kind": "structured-admin-attestation",
                "recordedAt": "2026-09-29T00:00:00Z",
            },
        }
        for phase in snow.ADMIN_PHASES
    }
    handoffs["entra-registration"]["evidence"]["clientId"] = APP_CLIENT_ID
    handoffs["servicenow-oidc"]["evidence"].update(
        {
            "oidcCapabilityConfirmed": True,
            "runbookCompleted": True,
            "mappingDetailsCollected": False,
        }
    )
    draft_semantic_hash = snow._draft_semantic_hash(components)
    agent_connection = {
        "kind": "maker-attestation",
        "status": "completed",
        "makerAttested": True,
        "physicalStatus": "Connected",
        "connectionId": CONNECTION_ID,
        "recordedAt": "2026-09-29T00:00:00Z",
        "binding": {
            "draftSemanticHash": draft_semantic_hash,
            "connectionId": CONNECTION_ID,
        },
    }
    state = {
        "schemaVersion": 6,
        "provider": snow.PROVIDER_KEY,
        "profile": snow.PROFILE_KEY,
        "agentSlug": AGENT_SLUG,
        "agentId": AGENT_ID,
        "environmentId": ENVIRONMENT_ID,
        "draftSemanticHash": draft_semantic_hash,
        "adminSetup": {
            "schemaVersion": 4,
            "scope": "hrsd",
            "authMode": "entraIDUserLogin",
            "preflight": {
                "instanceName": "dev123",
                "discovery": discovery,
            },
            "phaseHandoffs": handoffs,
        },
        "evidence": {
            "credential": {"connectionId": CONNECTION_ID},
            "agentConnection": agent_connection,
        },
    }
    connection_binding_hash = snow._connection_binding_hash(
        {
            "agent": {
                "id": AGENT_ID,
                "workspace_slug": AGENT_SLUG,
            },
            "environment": {"id": ENVIRONMENT_ID},
        },
        state,
        components,
    )
    state["connectionBindingHash"] = connection_binding_hash
    state["evidence"].update(
        {
            "publish": {
                "status": "completed",
                "componentHash": component_hash,
                "publishedComponentHash": component_hash,
                "testedDraftSemanticHash": draft_semantic_hash,
                "publishedSemanticHash": draft_semantic_hash,
                "connectionBindingHash": connection_binding_hash,
                "completedAt": "2026-09-28T00:00:00Z",
            },
            "test": {
                "kind": "maker-attestation",
                "status": "completed",
                "promptCategory": "list-my-open-hr-cases",
                "result": "pass",
                "failureCategory": None,
                "binding": {
                    "draftSemanticHash": draft_semantic_hash,
                    "connectionBindingHash": connection_binding_hash,
                },
            },
        }
    )
    path.write_text(
        json.dumps(state),
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
    assert "SN-DA-HRSD-PARAMETER-SHARING-001" not in statuses
    assert statuses["SN-DA-HRSD-PUBLISH-001"] == Status.PASSED.value
    assert statuses["SN-DA-HRSD-TEST-001"] == Status.MANUAL.value


@pytest.mark.parametrize(
    ("case", "expected_phrase"),
    [
        ("disconnected", "not a Connected Microsoft Entra ID User Login"),
        ("wrong-auth", "not a Connected Microsoft Entra ID User Login"),
        ("wrong-instance", "different Instance Name or Resource URI"),
        ("wrong-resource", "different Instance Name or Resource URI"),
    ],
)
def test_test_checkpoint_propagates_current_credential_failure(
    monkeypatch,
    tmp_path: Path,
    case: str,
    expected_phrase: str,
) -> None:
    components = _components()
    _write_state(tmp_path, components)
    connection = _connection()
    if case == "disconnected":
        connection["properties"]["statuses"] = [
            {"target": "token", "status": "Disconnected"}
        ]
    elif case == "wrong-auth":
        connection["properties"]["connectionParametersSet"]["name"] = (
            "keyBasedAuth"
        )
    elif case == "wrong-instance":
        connection["properties"]["connectionParametersSet"]["values"][
            "token:InstanceName"
        ]["value"] = "dev456"
    else:
        connection["properties"]["connectionParametersSet"]["values"][
            "token:ResourceUri"
        ]["value"] = "00000000-0000-4000-8000-000000009999"
    runner = _runner(components)
    runner.connectivity = SimpleNamespace(
        list_connector_connections=lambda _environment_id, _connector: [
            connection
        ]
    )
    monkeypatch.chdir(tmp_path)

    results = run_servicenow_da_hrsd_checks(runner)
    credential = _checkpoint(results, "SN-DA-HRSD-CREDENTIAL-001")
    test = _checkpoint(results, "SN-DA-HRSD-TEST-001")

    assert credential.status == Status.FAILED.value
    assert test.status == Status.FAILED.value
    assert "Current credential prerequisite is Failed" in test.result
    assert expected_phrase in test.result
    assert test.remediation == credential.remediation


def test_test_checkpoint_propagates_connectivity_error(
    monkeypatch,
    tmp_path: Path,
) -> None:
    components = _components()
    _write_state(tmp_path, components)
    runner = _runner(components)
    runner.connectivity = SimpleNamespace(
        list_connector_connections=lambda *_args: (_ for _ in ()).throw(
            RuntimeError("synthetic inventory failure")
        )
    )
    monkeypatch.chdir(tmp_path)

    results = run_servicenow_da_hrsd_checks(runner)
    credential = _checkpoint(results, "SN-DA-HRSD-CREDENTIAL-001")
    test = _checkpoint(results, "SN-DA-HRSD-TEST-001")

    assert credential.status == Status.ERROR.value
    assert test.status == Status.ERROR.value
    assert "Current credential prerequisite is Error" in test.result
    assert "synthetic inventory failure" in test.result
    assert test.remediation == credential.remediation


@pytest.mark.parametrize(
    ("case", "prerequisite_label"),
    [
        ("credential-pending", "credential"),
        ("topics-inactive", "topics"),
        ("agent-binding-stale", "Agent Connect"),
    ],
)
def test_test_checkpoint_blocks_noncompleted_prerequisite(
    monkeypatch,
    tmp_path: Path,
    case: str,
    prerequisite_label: str,
) -> None:
    components = _components()
    _write_state(tmp_path, components)
    state_path = _state_path(tmp_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if case == "credential-pending":
        state["adminSetup"]["phaseHandoffs"]["credential"] = {
            "status": "pending"
        }
    elif case == "topics-inactive":
        components["botComponentChanges"][0]["component"]["state"] = "Inactive"
        components["botComponentChanges"][0]["component"]["status"] = "Inactive"
    else:
        state["evidence"]["agentConnection"]["binding"][
            "draftSemanticHash"
        ] = "stale-draft"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    test = _checkpoint(
        run_servicenow_da_hrsd_checks(_runner(components)),
        "SN-DA-HRSD-TEST-001",
    )

    assert test.status == Status.NOT_CONFIGURED.value
    assert (
        f"Current {prerequisite_label} prerequisite is NotConfigured"
        in test.result
    )


def test_test_checkpoint_keeps_healthy_metadata_only_evidence(
    monkeypatch,
    tmp_path: Path,
) -> None:
    components = _components()
    _write_state(tmp_path, components)
    components["changeToken"] = "server-metadata-only"
    monkeypatch.chdir(tmp_path)

    test = _checkpoint(
        run_servicenow_da_hrsd_checks(_runner(components)),
        "SN-DA-HRSD-TEST-001",
    )

    assert test.status == Status.MANUAL.value
    assert test.result == "Maker recorded a passing HRSD Test pane result."


def test_test_checkpoint_rejects_stale_test_connection_binding(
    monkeypatch,
    tmp_path: Path,
) -> None:
    components = _components()
    _write_state(tmp_path, components)
    state_path = _state_path(tmp_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["evidence"]["test"]["binding"]["connectionBindingHash"] = (
        "stale-connection-binding"
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    test = _checkpoint(
        run_servicenow_da_hrsd_checks(_runner(components)),
        "SN-DA-HRSD-TEST-001",
    )

    assert test.status == Status.NOT_CONFIGURED.value
    assert "selected connection" in test.result


@pytest.mark.parametrize("disconnected", [False, True])
def test_test_checkpoint_full_and_fixed_runs_match(
    monkeypatch,
    tmp_path: Path,
    disconnected: bool,
) -> None:
    components = _components()
    _write_state(tmp_path, components)
    full_runner = _registered_runner(components)
    fixed_runner = _registered_runner(components, target_test_only=True)
    if disconnected:
        connection = _connection()
        connection["properties"]["statuses"] = [
            {"target": "token", "status": "Disconnected"}
        ]
        inventory = SimpleNamespace(
            list_connector_connections=lambda *_args: [connection]
        )
        full_runner.connectivity = inventory
        fixed_runner.connectivity = inventory
    monkeypatch.chdir(tmp_path)

    full = full_runner.run()
    fixed = fixed_runner.run()
    full_test = _checkpoint(full.results, "SN-DA-HRSD-TEST-001")
    fixed_test = _checkpoint(fixed.results, "SN-DA-HRSD-TEST-001")

    assert vars(fixed_test) == vars(full_test)
    assert fixed.results == [fixed_test]
    assert fixed.overall == full.overall


def test_admin_prerequisites_pass_with_graph_and_structured_evidence(
    monkeypatch,
    tmp_path: Path,
) -> None:
    components = _components()
    _write_state(tmp_path, components)
    runner = _runner(components)
    runner.graph = _graph_client()
    monkeypatch.chdir(tmp_path)

    results = run_servicenow_da_hrsd_checks(runner)
    statuses = {result.checkpoint_id: result.status for result in results}

    assert statuses["SN-DA-HRSD-ADMIN-PREFLIGHT-001"] == Status.PASSED.value
    assert statuses["SN-DA-HRSD-PLUGIN-001"] == Status.MANUAL.value
    for suffix in (
        "APP",
        "CLAIMS",
        "SCOPE",
        "PREAUTH",
        "PERMISSIONS",
        "CONSENT",
    ):
        assert (
            statuses[f"SN-DA-HRSD-ENTRA-{suffix}-001"]
            == Status.PASSED.value
        )
    assert statuses["SN-DA-HRSD-OIDC-001"] == Status.MANUAL.value


def test_oidc_checkpoint_requires_capability_owned_by_oidc_phase(
    monkeypatch,
    tmp_path: Path,
) -> None:
    components = _components()
    _write_state(tmp_path, components)
    state_path = (
        tmp_path
        / ".local"
        / "connect"
        / snow.PROVIDER_KEY
        / "agents"
        / AGENT_SLUG
        / "lifecycle.json"
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["adminSetup"]["phaseHandoffs"]["servicenow-oidc"]["evidence"].pop(
        "oidcCapabilityConfirmed"
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = next(
        row
        for row in run_servicenow_da_hrsd_checks(_runner(components))
        if row.checkpoint_id == "SN-DA-HRSD-OIDC-001"
    )

    assert result.status == Status.NOT_CONFIGURED.value
    assert "OIDC capability confirmation is missing" in result.result


def test_oidc_checkpoint_rejects_legacy_mapping_details(
    monkeypatch,
    tmp_path: Path,
) -> None:
    components = _components()
    _write_state(tmp_path, components)
    state_path = (
        tmp_path
        / ".local"
        / "connect"
        / snow.PROVIDER_KEY
        / "agents"
        / AGENT_SLUG
        / "lifecycle.json"
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    evidence = state["adminSetup"]["phaseHandoffs"]["servicenow-oidc"][
        "evidence"
    ]
    evidence["claim"] = "upn"
    evidence["userField"] = "user_name"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = next(
        row
        for row in run_servicenow_da_hrsd_checks(_runner(components))
        if row.checkpoint_id == "SN-DA-HRSD-OIDC-001"
    )

    assert result.status == Status.NOT_CONFIGURED.value
    assert "privacy-minimized" in result.result


def test_publish_checkpoint_ignores_metadata_only_drift_and_reopens_on_semantic_drift(
    monkeypatch,
    tmp_path: Path,
) -> None:
    components = _components()
    _write_state(tmp_path, components)
    state_path = (
        tmp_path
        / ".local"
        / "connect"
        / snow.PROVIDER_KEY
        / "agents"
        / AGENT_SLUG
        / "lifecycle.json"
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    current_hash = snow._component_hash(components)
    semantic_hash = snow._draft_semantic_hash(components)
    state["evidence"]["publish"] = {
        "status": "completed",
        "requestedComponentHash": "pre-publish-hash",
        "publishedComponentHash": current_hash,
        "componentHash": current_hash,
        "testedDraftSemanticHash": semantic_hash,
        "publishedSemanticHash": semantic_hash,
        "connectionBindingHash": state["connectionBindingHash"],
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    current = run_servicenow_da_hrsd_checks(_runner(components))
    publish = next(
        row
        for row in current
        if row.checkpoint_id == "SN-DA-HRSD-PUBLISH-001"
    )
    assert publish.status == Status.PASSED.value

    components["changeToken"] = "later-edit"
    metadata_only = run_servicenow_da_hrsd_checks(_runner(components))
    publish = next(
        row
        for row in metadata_only
        if row.checkpoint_id == "SN-DA-HRSD-PUBLISH-001"
    )
    assert publish.status == Status.NOT_CONFIGURED.value

    state["evidence"]["publish"]["publishedComponentHash"] = snow._component_hash(
        components
    )
    state["evidence"]["publish"]["componentHash"] = snow._component_hash(
        components
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")
    metadata_only = run_servicenow_da_hrsd_checks(_runner(components))
    publish = next(
        row
        for row in metadata_only
        if row.checkpoint_id == "SN-DA-HRSD-PUBLISH-001"
    )
    assert publish.status == Status.PASSED.value

    components["botComponentChanges"][0]["component"]["displayName"] = (
        "Edited ServiceNow topic"
    )
    semantic_drift = run_servicenow_da_hrsd_checks(_runner(components))
    publish = next(
        row
        for row in semantic_drift
        if row.checkpoint_id == "SN-DA-HRSD-PUBLISH-001"
    )
    assert publish.status == Status.NOT_CONFIGURED.value


def test_publish_checkpoint_surfaces_current_semantic_drift_as_failed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    components = _components()
    _write_state(tmp_path, components)
    state_path = (
        tmp_path
        / ".local"
        / "connect"
        / snow.PROVIDER_KEY
        / "agents"
        / AGENT_SLUG
        / "lifecycle.json"
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["evidence"]["publish"] = {
        "kind": "maker-attestation",
        "status": "needs_remediation",
        "publishedComponentHash": snow._component_hash(components),
        "componentHash": snow._component_hash(components),
        "testedDraftSemanticHash": "pre-publish-semantic-hash",
        "publishedSemanticHash": snow._draft_semantic_hash(components),
        "remediation": "Run Test again before any later publish.",
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = next(
        row
        for row in run_servicenow_da_hrsd_checks(_runner(components))
        if row.checkpoint_id == "SN-DA-HRSD-PUBLISH-001"
    )

    assert result.status == Status.FAILED.value
    assert "needs remediation" in result.result


@pytest.mark.parametrize(
    "test_record",
    [
        {
            "prompt": "Show case ABC-123 for Jane Doe",
            "details": "Sensitive response",
            "result": "pass",
        },
        {
            "promptCategory": "unknown",
            "result": "pass",
            "failureCategory": None,
        },
        {
            "promptCategory": "list-my-open-hr-cases",
            "result": "pass",
            "failureCategory": "permission",
        },
    ],
)
def test_test_checkpoint_rejects_legacy_or_unbounded_evidence(
    monkeypatch,
    tmp_path: Path,
    test_record: dict,
) -> None:
    components = _components()
    _write_state(tmp_path, components)
    state_path = (
        tmp_path
        / ".local"
        / "connect"
        / snow.PROVIDER_KEY
        / "agents"
        / AGENT_SLUG
        / "lifecycle.json"
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    current_binding = state["evidence"]["test"]["binding"]
    test_record["binding"] = {
        **current_binding,
    }
    state["evidence"]["test"] = test_record
    state_path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = next(
        row
        for row in run_servicenow_da_hrsd_checks(_runner(components))
        if row.checkpoint_id == "SN-DA-HRSD-TEST-001"
    )

    assert result.status == Status.NOT_CONFIGURED.value
    assert "privacy-safe bounded evidence contract" in result.result


def test_test_checkpoint_accepts_bounded_failure_evidence(
    monkeypatch,
    tmp_path: Path,
) -> None:
    components = _components()
    _write_state(tmp_path, components)
    state_path = (
        tmp_path
        / ".local"
        / "connect"
        / snow.PROVIDER_KEY
        / "agents"
        / AGENT_SLUG
        / "lifecycle.json"
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    current_binding = state["evidence"]["test"]["binding"]
    state["evidence"]["test"] = {
        "kind": "maker-attestation",
        "status": "failed",
        "promptCategory": "list-my-open-hr-cases",
        "result": "fail",
        "failureCategory": "permission",
        "binding": current_binding,
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = next(
        row
        for row in run_servicenow_da_hrsd_checks(_runner(components))
        if row.checkpoint_id == "SN-DA-HRSD-TEST-001"
    )

    assert result.status == Status.FAILED.value


def test_entra_phase_evaluation_uses_one_logical_read_set(
    monkeypatch,
    tmp_path: Path,
) -> None:
    components = _components()
    _write_state(tmp_path, components)
    counters = {
        "agentbuilder": 0,
        "connectivity": 0,
        "applications": 0,
        "app_service_principal": 0,
        "graph_service_principal": 0,
        "permission_grants": 0,
    }
    runner = _runner(components)

    def fetch_components(_agent_id: str) -> dict:
        counters["agentbuilder"] += 1
        return components

    def list_connector_connections(
        environment_id: str,
        connector: str,
    ) -> list[dict]:
        assert environment_id == ENVIRONMENT_ID
        assert connector == snow.CONNECTOR_NAME
        counters["connectivity"] += 1
        return [_connection()]

    base_graph = _graph_client()

    class CountingGraph:
        def get_all(
            self,
            path: str,
            params: dict | None = None,
            *,
            raise_on_permission_error: bool = False,
        ) -> list[dict]:
            if path == "/applications":
                counters["applications"] += 1
            elif path == "/oauth2PermissionGrants":
                counters["permission_grants"] += 1
            return base_graph.get_all(
                path,
                params,
                raise_on_permission_error=raise_on_permission_error,
            )

        def get_service_principals(
            self,
            *,
            filter_expr: str = "",
            **kwargs,
        ) -> list[dict]:
            if graph_mock.MS_GRAPH_RESOURCE_APP_ID in filter_expr:
                counters["graph_service_principal"] += 1
            else:
                counters["app_service_principal"] += 1
            return base_graph.get_service_principals(
                filter_expr=filter_expr,
                **kwargs,
            )

    runner.agentbuilder = SimpleNamespace(fetch_components=fetch_components)
    runner.connectivity = SimpleNamespace(
        list_connections=lambda _environment_id: pytest.fail(
            "ServiceNow HRSD must not use environment-wide inventory."
        ),
        list_connector_connections=list_connector_connections,
    )
    runner.graph = CountingGraph()
    monkeypatch.chdir(tmp_path)

    results = run_servicenow_da_hrsd_checks(runner)
    entra_results = [
        result
        for result in results
        if result.checkpoint_id.startswith("SN-DA-HRSD-ENTRA-")
    ]

    assert len(entra_results) == 6
    assert counters == {
        "agentbuilder": 1,
        "connectivity": 1,
        "applications": 1,
        "app_service_principal": 1,
        "graph_service_principal": 1,
        "permission_grants": 1,
    }


def test_preflight_discovery_change_does_not_require_global_reapproval(
    monkeypatch,
    tmp_path: Path,
) -> None:
    components = _components()
    _write_state(tmp_path, components)
    state_path = (
        tmp_path
        / ".local"
        / "connect"
        / snow.PROVIDER_KEY
        / "agents"
        / AGENT_SLUG
        / "lifecycle.json"
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["adminSetup"]["preflight"]["discovery"]["connectionCandidates"] = [
        {"connectionId": "new-candidate", "status": "Connected"}
    ]
    state_path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = next(
        item
        for item in run_servicenow_da_hrsd_checks(_runner(components))
        if item.checkpoint_id == "SN-DA-HRSD-ADMIN-PREFLIGHT-001"
    )

    assert result.status == Status.PASSED.value
    assert "reused automatically" in result.result


def test_connected_connection_does_not_complete_other_admin_phases(
    monkeypatch,
    tmp_path: Path,
) -> None:
    components = _components()
    _write_state(tmp_path, components)
    state_path = (
        tmp_path
        / ".local"
        / "connect"
        / snow.PROVIDER_KEY
        / "agents"
        / AGENT_SLUG
        / "lifecycle.json"
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    for phase in (
        "plugin-prerequisites",
        "entra-registration",
        "servicenow-oidc",
    ):
        state["adminSetup"]["phaseHandoffs"][phase] = {"status": "pending"}
    state_path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    results = run_servicenow_da_hrsd_checks(_runner(components))
    statuses = {item.checkpoint_id: item.status for item in results}

    assert statuses["SN-DA-HRSD-ADMIN-PREFLIGHT-001"] == Status.PASSED.value
    assert statuses["SN-DA-HRSD-PLUGIN-001"] == Status.NOT_CONFIGURED.value
    assert statuses["SN-DA-HRSD-ENTRA-APP-001"] == Status.NOT_CONFIGURED.value
    assert statuses["SN-DA-HRSD-OIDC-001"] == Status.NOT_CONFIGURED.value


def test_graph_failure_cannot_be_overridden_by_admin_attestation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    components = _components()
    _write_state(tmp_path, components)
    runner = _runner(components)
    runner.graph = _graph_client(missing_claims=True)
    monkeypatch.chdir(tmp_path)

    results = run_servicenow_da_hrsd_checks(runner)
    claim_result = next(
        result
        for result in results
        if result.checkpoint_id == "SN-DA-HRSD-ENTRA-CLAIMS-001"
    )

    assert claim_result.status == Status.FAILED.value
    assert "upn" in claim_result.result
    assert "correct this exact application setting" in claim_result.remediation


def test_foreign_resource_consent_does_not_satisfy_graph_admin_consent(
    monkeypatch,
    tmp_path: Path,
) -> None:
    components = _components()
    _write_state(tmp_path, components)
    runner = _runner(components)
    runner.graph = _graph_client(foreign_consent=True)
    monkeypatch.chdir(tmp_path)

    result = next(
        item
        for item in run_servicenow_da_hrsd_checks(runner)
        if item.checkpoint_id == "SN-DA-HRSD-ENTRA-CONSENT-001"
    )

    assert result.status == Status.FAILED.value
    assert "openid" in result.result
    assert "tenant-wide admin consent" in result.description.casefold()


def test_graph_unavailable_uses_manual_fallback_only_with_evidence(
    monkeypatch,
    tmp_path: Path,
) -> None:
    components = _components()
    _write_state(tmp_path, components)
    runner = _runner(components)
    runner.graph = None
    monkeypatch.chdir(tmp_path)

    results = run_servicenow_da_hrsd_checks(runner)
    app = next(
        result
        for result in results
        if result.checkpoint_id == "SN-DA-HRSD-ENTRA-APP-001"
    )
    assert app.status == Status.MANUAL.value
    assert "Structured admin evidence is present" in app.result

    state_path = (
        tmp_path
        / ".local"
        / "connect"
        / snow.PROVIDER_KEY
        / "agents"
        / AGENT_SLUG
        / "lifecycle.json"
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["adminSetup"]["phaseHandoffs"]["entra-registration"] = {
        "status": "pending"
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")

    results = run_servicenow_da_hrsd_checks(runner)
    app = next(
        result
        for result in results
        if result.checkpoint_id == "SN-DA-HRSD-ENTRA-APP-001"
    )
    assert app.status == Status.NOT_CONFIGURED.value
    assert "No Application client ID" in app.result


def test_credential_rejects_resource_uri_mismatch(
    monkeypatch,
    tmp_path: Path,
) -> None:
    components = _components()
    _write_state(tmp_path, components)
    connection = _connection()
    connection["properties"]["connectionParametersSet"]["values"][
        "token:ResourceUri"
    ]["value"] = "00000000-0000-4000-8000-000000009999"
    runner = _runner(components)
    runner.connectivity = SimpleNamespace(
        list_connector_connections=lambda _environment_id, _connector: [
            connection
        ],
    )
    monkeypatch.chdir(tmp_path)

    result = next(
        item
        for item in run_servicenow_da_hrsd_checks(runner)
        if item.checkpoint_id == "SN-DA-HRSD-CREDENTIAL-001"
    )

    assert result.status == Status.FAILED.value
    assert "different Instance Name or Resource URI" in result.result
    assert "exact Application client ID" in result.result


def test_hrsd_checks_use_connector_scoped_connections_only(
    monkeypatch,
    tmp_path: Path,
) -> None:
    components = _components()
    _write_state(tmp_path, components)
    runner = _runner(components)

    calls: list[tuple[str, str]] = []
    runner.connectivity = SimpleNamespace(
        list_connections=lambda _environment_id: pytest.fail(
            "ServiceNow HRSD must not use environment-wide inventory."
        ),
        list_connector_connections=lambda environment_id, connector: (
            calls.append((environment_id, connector)) or [_connection()]
        ),
    )
    monkeypatch.chdir(tmp_path)

    results = run_servicenow_da_hrsd_checks(runner)
    statuses = {result.checkpoint_id: result.status for result in results}

    assert calls == [(ENVIRONMENT_ID, snow.CONNECTOR_NAME)]
    assert statuses["SN-DA-HRSD-CREDENTIAL-001"] == Status.PASSED.value
    assert (
        statuses["SN-DA-HRSD-AGENT-CONNECTION-001"]
        == Status.MANUAL.value
    )


@pytest.mark.parametrize("status_code", [429, 401, 403, 500])
def test_hrsd_connector_inventory_error_has_no_fallback(
    monkeypatch,
    tmp_path: Path,
    status_code: int,
) -> None:
    components = _components()
    _write_state(tmp_path, components)
    calls = 0
    runner = _runner(components)

    def fail_connector_inventory(
        _environment_id: str,
        _connector: str,
    ) -> list[dict]:
        nonlocal calls
        calls += 1
        raise AgentBuilderHTTPError(
            "Connector-scoped connection listing",
            status_code,
            request_id="request-123",
        )

    runner.connectivity = SimpleNamespace(
        list_connector_connections=fail_connector_inventory,
    )
    monkeypatch.chdir(tmp_path)

    results = run_servicenow_da_hrsd_checks(runner)
    credential = next(
        result
        for result in results
        if result.checkpoint_id == "SN-DA-HRSD-CREDENTIAL-001"
    )

    assert calls == 1
    assert credential.status == Status.ERROR.value
    assert "request-123" in credential.result


def test_hrsd_checks_reopen_stale_maker_evidence(
    monkeypatch,
    tmp_path: Path,
) -> None:
    components = _components()
    _write_state(tmp_path, components)
    components["botComponentChanges"][0]["component"]["displayName"] = (
        "Edited ServiceNow topic"
    )
    monkeypatch.chdir(tmp_path)

    results = run_servicenow_da_hrsd_checks(_runner(components))
    statuses = {result.checkpoint_id: result.status for result in results}

    assert (
        statuses["SN-DA-HRSD-AGENT-CONNECTION-001"]
        == Status.NOT_CONFIGURED.value
    )
    assert "SN-DA-HRSD-PARAMETER-SHARING-001" not in statuses
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
        list_connections=lambda _environment_id: pytest.fail(
            "ServiceNow HRSD must not use environment-wide inventory."
        ),
        list_connector_connections=(
            lambda _environment_id, _connector: [other_connection]
        ),
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
    components["botComponentChanges"][0]["component"]["displayName"] = (
        "Edited ServiceNow topic"
    )
    monkeypatch.chdir(tmp_path)

    results = run_servicenow_da_hrsd_checks(_runner(components))
    result = next(
        item
        for item in results
        if item.checkpoint_id == "SN-DA-HRSD-AGENT-CONNECTION-001"
    )

    assert result.status == Status.NOT_CONFIGURED.value
    assert "stale for this saved draft" in result.result


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
