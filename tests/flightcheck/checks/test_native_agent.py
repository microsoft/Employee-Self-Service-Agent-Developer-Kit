# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Classification and captured HTTP tests for native AgentBuilder FlightChecks."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock

import pytest
import responses
import yaml

from agentbuilder import AgentBuilderClient, derive_environment_host

from flightcheck.checks.native_agent import run_native_agent_checks


ENVIRONMENT_ID = "00000000-0000-4000-8000-000000001111"
AGENT_ID = "00000000-0000-4000-8000-000000002222"
TENANT_ID = "00000000-0000-4000-8000-000000003333"
FAMILY_ID = "00000000-0000-4000-8000-000000004444"


@pytest.mark.parametrize("realm", ["dev", "test", "prod", None])
def test_full_da_native_access_replays_exact_lookup_without_dev_only_setup_reads(realm):
    """Reuse the captured GET shape; realm variants exercise the known realm enum."""
    path = Path(__file__).resolve().parents[2] / "fixtures" / "cassettes" / "env004_partial_topics.yaml"
    interaction = next(
        item for item in yaml.safe_load(path.read_text(encoding="utf-8"))["interactions"]
        if item["request"]["method"] == "GET" and "/minimalBots/api/" in item["request"]["uri"]
    )
    uri = interaction["request"]["uri"]
    payload = json.loads(interaction["response"]["body"]["string"])
    if realm is None:
        payload.pop("realm")
    else:
        payload["realm"] = realm
    parsed = urlsplit(uri)
    # Rebase the recorder's redacted host, retaining the captured method/path/body.
    host = derive_environment_host(ENVIRONMENT_ID, "prod")
    uri = parsed._replace(netloc=urlsplit(host).netloc).geturl()
    bot_id = payload["botId"]
    client = AgentBuilderClient(
        host, "test-token", ring="prod", tenant_id=TENANT_ID,
        api_version=parse_qs(parsed.query)["api-version"][0],
    )
    runner = SimpleNamespace(
        agentbuilder=client, connectivity=None, env_id=ENVIRONMENT_ID, agent_slug="hr",
        config={
            "activeAgent": "hr",
            "agent": {"slug": "hr", "botId": bot_id, "schemaName": "gptagent_hr", "releaseLine": "da"},
        },
        maker_diagnostics=True, validation_context={"realm": realm},
        should_execute=lambda key: key == "DA-AGENT-001",
    )
    with responses.RequestsMock() as http:
        http.add(responses.GET, uri, json=payload, status=200)
        rows = run_native_agent_checks(runner)
        assert rows[0].status == "Passed"
        assert "accessible through the native read API" in rows[0].result
        assert rows[0].remediation == ""
        assert rows[0].evidence["realm"] == realm
        assert len(http.calls) == 1


def test_full_da_native_producer_never_runs_legacy_connection_candidates():
    path = Path(__file__).resolve().parents[2] / "fixtures" / "cassettes" / "agentbuilder_readiness.yaml"
    interactions = yaml.safe_load(path.read_text(encoding="utf-8"))["interactions"]
    reads = [
        item for item in interactions
        if "/minimalBots/api/" in item["request"]["uri"]
        and (item["request"]["method"] == "GET" or "/components" in item["request"]["uri"])
    ]
    agent = json.loads(next(item for item in reads if item["request"]["method"] == "GET")[
        "response"
    ]["body"]["string"])
    components = json.loads(next(item for item in reads if item["request"]["method"] == "POST")[
        "response"
    ]["body"]["string"])
    host = derive_environment_host(ENVIRONMENT_ID, "prod")
    connectivity = Mock()
    runner = SimpleNamespace(
        agentbuilder=AgentBuilderClient(host, "test-token", ring="prod", tenant_id=TENANT_ID),
        connectivity=connectivity, env_id=ENVIRONMENT_ID, agent_slug="hr",
        config={"activeAgent": "hr", "agent": {
            "slug": "hr", "botId": agent["botId"], "schemaName": components["bot"]["schemaName"],
            "releaseLine": "da",
        }},
        maker_diagnostics=True, validation_context={"realm": "dev"},
        should_execute=lambda _key: True,
    )
    with responses.RequestsMock() as http:
        for item in reads:
            parsed = urlsplit(item["request"]["uri"])
            uri = parsed._replace(netloc=urlsplit(host).netloc, query="").geturl()
            http.add(
                item["request"]["method"], uri,
                json=json.loads(item["response"]["body"]["string"]),
                status=item["response"]["status"]["code"],
            )
        rows = run_native_agent_checks(runner)
        assert len(http.calls) == 2
    assert {row.checkpoint_id for row in rows} == {"DA-AGENT-001", "DA-CONTENT-001"}
    assert all(row.status == "Passed" for row in rows)
    connectivity.list_connections.assert_not_called()
    assert runner._da_native_snapshot["agentId"] == agent["botId"]


def _reference(
    connector: str = "shared_service-now",
    connection_id: str | None = None,
) -> dict[str, Any]:
    return {
        "connectionReference": {
            "connectorId": (
                f"/providers/Microsoft.PowerApps/apis/{connector}"
            ),
            "connectionId": connection_id,
        }
    }


def _connection(
    name: str,
    *,
    connector: str = "shared_service-now",
    status: str = "Connected",
    display_name: str = "ServiceNow",
) -> dict[str, Any]:
    return {
        "name": name,
        "properties": {
            "apiId": f"/providers/Microsoft.PowerApps/apis/{connector}",
            "displayName": display_name,
            "statuses": [{"status": status}],
        },
    }


class _AgentBuilder:
    host = (
        "https://0000000000004000800000000000111."
        "1.environment.api.test.powerplatform.com"
    )
    ring = "test"
    tenant_id = TENANT_ID
    api_version = "2024-10-01"

    def __init__(
        self,
        references: list[dict[str, Any]],
        *,
        realm: int | str | None = 0,
    ) -> None:
        self.references = references
        self.realm = realm

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        assert agent_id == AGENT_ID
        return {
            "botId": AGENT_ID,
            "fullBotName": "Employee Self-Service",
            "realm": self.realm,
            "managedProperties": {"isManaged": False},
        }

    def get_dev_configuration(self, agent_id: str) -> dict[str, Any]:
        raise AssertionError(
            f"FlightCheck must not require published config for {agent_id}"
        )

    def get_realms(self, agent_id: str) -> dict[str, Any]:
        raise AssertionError(
            f"Native FlightCheck must not require an ALM route for {agent_id}"
        )

    def fetch_components(self, agent_id: str) -> dict[str, Any]:
        assert agent_id == AGENT_ID
        return {
            "bot": {
                "cdsBotId": AGENT_ID,
                "schemaName": "gptagent_ess",
            },
            "botComponentChanges": [
                {"component": {"$kind": "DialogComponent"}}
            ],
            "connectionReferenceChanges": self.references,
        }


class _Connectivity:
    def __init__(self, connections: list[dict[str, Any]]) -> None:
        self.connections = connections

    def list_connections(self, environment_id: str) -> list[dict[str, Any]]:
        assert environment_id == ENVIRONMENT_ID
        return self.connections


@dataclass
class _Runner:
    agentbuilder: Any
    connectivity: Any
    env_id: str = ENVIRONMENT_ID
    config: dict[str, Any] = field(
        default_factory=lambda: {
            "releaseLine": "da",
            "environmentId": ENVIRONMENT_ID,
            "agent": {
                "botId": AGENT_ID,
                "name": "Employee Self-Service",
                "schemaName": "gptagent_ess",
                "slug": "employee-self-service",
            },
            "activeAgent": "employee-self-service",
        }
    )
    native_connector_filter: tuple[str, ...] = ()
    agent_slug: str = ""


def _by_id(results, checkpoint_id: str):
    return next(
        result
        for result in results
        if result.checkpoint_id == checkpoint_id
    )


@pytest.mark.parametrize("component", [None, {}, {"component": None}, {"component": {"$kind": ""}}])
def test_full_da_malformed_authored_components_do_not_pass(monkeypatch, component):
    client = _AgentBuilder([])
    snapshot = client.fetch_components(AGENT_ID)
    snapshot["botComponentChanges"] = [component]
    monkeypatch.setattr(client, "fetch_components", lambda _agent_id: snapshot)
    runner = _Runner(agentbuilder=client, connectivity=None)
    runner.maker_diagnostics = True
    runner.validation_context = {"realm": "dev"}
    result = _by_id(run_native_agent_checks(runner), "DA-CONTENT-001")
    assert result.status == "Failed"
    assert "malformed authored component" in result.result
    assert "refresh the exact native agent workspace" in result.remediation


def test_missing_agentbuilder_auth_errors_every_native_gate() -> None:
    results = run_native_agent_checks(
        _Runner(agentbuilder=None, connectivity=None)
    )

    assert {
        result.checkpoint_id: result.status
        for result in results
    } == {
        "DA-AGENT-001": "Error",
        "DA-CONTENT-001": "Error",
        "DA-CONN-001": "Error",
    }


def test_exact_mapped_connected_reference_passes() -> None:
    connection_id = "connection-one"
    runner = _Runner(
        agentbuilder=_AgentBuilder(
            [_reference(connection_id=connection_id)]
        ),
        connectivity=_Connectivity([_connection(connection_id)]),
    )

    results = run_native_agent_checks(runner)

    assert _by_id(results, "DA-AGENT-001").status == "Passed"
    assert _by_id(results, "DA-CONTENT-001").status == "Passed"
    summary = _by_id(results, "DA-CONN-001")
    detail = _by_id(results, "DA-CONN-002")
    assert summary.status == "Passed"
    assert "1 exact mapping" in summary.result
    assert detail.status == "Passed"
    assert "Exact mapped connection" in detail.result
    assert "unverified" not in detail.result


def test_explicit_agent_slug_overrides_different_active_agent() -> None:
    runner = _Runner(
        agentbuilder=_AgentBuilder([]),
        connectivity=_Connectivity([]),
        agent_slug="selected",
        config={
            "releaseLine": "da",
            "environmentId": ENVIRONMENT_ID,
            "activeAgent": "other",
            "agent": {
                "slug": "other",
                "botId": "00000000-0000-4000-8000-000000009999",
                "schemaName": "gptagent_other",
            },
            "agents": [
                {
                    "slug": "other",
                    "botId": "00000000-0000-4000-8000-000000009999",
                    "schemaName": "gptagent_other",
                },
                {
                    "slug": "selected",
                    "botId": AGENT_ID,
                    "schemaName": "gptagent_ess",
                },
            ],
        },
    )

    results = run_native_agent_checks(runner)

    assert _by_id(results, "DA-AGENT-001").status == "Passed"
    assert _by_id(results, "DA-CONTENT-001").status == "Passed"
    assert _by_id(results, "DA-CONN-001").status == "Skipped"


def test_native_flightcheck_accepts_swagger_unenrolled_null_realm() -> None:
    runner = _Runner(
        agentbuilder=_AgentBuilder([], realm=None),
        connectivity=_Connectivity([]),
    )

    results = run_native_agent_checks(runner)

    assert _by_id(results, "DA-AGENT-001").status == "Passed"
    assert _by_id(results, "DA-CONTENT-001").status == "Passed"


def test_native_flightcheck_uses_direct_dev_over_stale_local_alm_state() -> None:
    runner = _Runner(
        agentbuilder=_AgentBuilder([], realm="dev"),
        connectivity=_Connectivity([]),
    )
    runner.config["agent"]["alm"] = {"isEnrolled": False}

    results = run_native_agent_checks(runner)

    assert _by_id(results, "DA-AGENT-001").status == "Passed"
    assert _by_id(results, "DA-CONTENT-001").status == "Passed"


@pytest.mark.parametrize("realm", ("test", "prod"))
def test_native_flightcheck_rejects_enrolled_non_dev_realm(
    realm: str,
) -> None:
    runner = _Runner(
        agentbuilder=_AgentBuilder([], realm=realm),
        connectivity=_Connectivity([]),
    )

    results = run_native_agent_checks(runner)

    access = _by_id(results, "DA-AGENT-001")
    assert access.status == "Failed"
    assert "editable Dev or unenrolled authoring target" in access.result
    assert all(
        result.checkpoint_id != "DA-CONTENT-001"
        for result in results
    )


def test_single_connected_candidate_passes_with_mapping_disclaimer() -> None:
    runner = _Runner(
        agentbuilder=_AgentBuilder([_reference()]),
        connectivity=_Connectivity(
            [_connection("candidate-one", display_name="snow-E2E")]
        ),
    )

    results = run_native_agent_checks(runner)

    summary = _by_id(results, "DA-CONN-001")
    detail = _by_id(results, "DA-CONN-002")
    assert summary.status == "Passed"
    assert "1 mapping(s) not exposed" in summary.result
    assert detail.status == "Passed"
    assert "snow-E2E" in detail.result
    assert "exact binding remains unverified" in detail.result


def test_multiple_connected_candidates_warn_without_guessing() -> None:
    runner = _Runner(
        agentbuilder=_AgentBuilder([_reference()]),
        connectivity=_Connectivity(
            [
                _connection("candidate-one", display_name="SN Dev"),
                _connection("candidate-two", display_name="SN Test"),
            ]
        ),
    )

    results = run_native_agent_checks(runner)

    assert _by_id(results, "DA-CONN-001").status == "Warning"
    detail = _by_id(results, "DA-CONN-002")
    assert detail.status == "Warning"
    assert "cannot identify which candidate" in detail.result


def test_missing_physical_candidate_is_not_configured() -> None:
    runner = _Runner(
        agentbuilder=_AgentBuilder([_reference()]),
        connectivity=_Connectivity([]),
    )

    results = run_native_agent_checks(runner)

    assert _by_id(results, "DA-CONN-001").status == "NotConfigured"
    detail = _by_id(results, "DA-CONN-002")
    assert detail.status == "NotConfigured"
    assert "no matching physical connection" in detail.result


def test_disconnected_candidates_fail() -> None:
    runner = _Runner(
        agentbuilder=_AgentBuilder([_reference()]),
        connectivity=_Connectivity(
            [_connection("candidate-one", status="Error")]
        ),
    )

    results = run_native_agent_checks(runner)

    assert _by_id(results, "DA-CONN-001").status == "Failed"
    assert _by_id(results, "DA-CONN-002").status == "Failed"


def test_exact_mapping_to_missing_connection_fails() -> None:
    runner = _Runner(
        agentbuilder=_AgentBuilder(
            [_reference(connection_id="missing-connection")]
        ),
        connectivity=_Connectivity(
            [_connection("different-connection")]
        ),
    )

    results = run_native_agent_checks(runner)

    detail = _by_id(results, "DA-CONN-002")
    assert detail.status == "Failed"
    assert "not visible" in detail.result


def test_explicit_servicenow_scope_requires_servicenow_reference() -> None:
    runner = _Runner(
        agentbuilder=_AgentBuilder(
            [_reference(connector="shared_workdaysoap")]
        ),
        connectivity=_Connectivity([]),
        native_connector_filter=("shared_service-now",),
    )

    results = run_native_agent_checks(runner)

    result = _by_id(results, "DA-CONN-001")
    assert result.status == "NotConfigured"
    assert "selected connector" in result.result
