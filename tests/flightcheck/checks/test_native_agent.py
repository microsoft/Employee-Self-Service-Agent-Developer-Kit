# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Pure classification tests for native AgentBuilder FlightChecks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from flightcheck.checks.native_agent import run_native_agent_checks


ENVIRONMENT_ID = "00000000-0000-4000-8000-000000001111"
AGENT_ID = "00000000-0000-4000-8000-000000002222"
TENANT_ID = "00000000-0000-4000-8000-000000003333"
FAMILY_ID = "00000000-0000-4000-8000-000000004444"


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

    def __init__(self, references: list[dict[str, Any]]) -> None:
        self.references = references

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        assert agent_id == AGENT_ID
        return {
            "botId": AGENT_ID,
            "fullBotName": "Employee Self-Service",
            "schemaName": "gptagent_ess",
            "realm": 0,
            "managedProperties": {"isManaged": False},
        }

    def get_dev_configuration(self, agent_id: str) -> dict[str, Any]:
        assert agent_id == AGENT_ID
        return {
            "realm": "Dev",
            "cdsBotId": AGENT_ID,
            "schemaName": "gptagent_ess",
            "grsRepositoryId": FAMILY_ID,
        }

    def fetch_components(self, agent_id: str) -> dict[str, Any]:
        assert agent_id == AGENT_ID
        return {
            "bot": {"cdsBotId": AGENT_ID},
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
                "slug": "employee-self-service",
            },
            "activeAgent": "employee-self-service",
        }
    )
    native_connector_filter: tuple[str, ...] = ()


def _by_id(results, checkpoint_id: str):
    return next(
        result
        for result in results
        if result.checkpoint_id == checkpoint_id
    )


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
