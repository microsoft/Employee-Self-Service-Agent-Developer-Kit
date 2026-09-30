# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Validated mock builders for native AgentBuilder readiness APIs."""

from __future__ import annotations

from typing import Any, Iterable

import responses


MOCK_STATUS = "validated"
MOCK_CASSETTE = "tests/fixtures/cassettes/agentbuilder_readiness.yaml"
MOCK_CONNECTIVITY_CASSETTE = (
    "tests/fixtures/cassettes/connectivity_connections.yaml"
)

MOCK_ENV_ID = "00000000-0000-0000-0000-000000001111"
MOCK_AGENT_ID = "00000000-0000-0000-0000-000000002222"
MOCK_FAMILY_ID = "00000000-0000-0000-0000-000000003333"
MOCK_CONNECTION_ID = "mock-servicenow-connection"
MOCK_WORKDAY_CONNECTION_ID = "mock-workday-connection"
MOCK_AGENTBUILDER_BASE = (
    "https://00000000000000000000000000000000."
    "0.environment.api.test.powerplatform.com"
)
MOCK_CONNECTIVITY_BASE = "https://api.test.powerplatform.com"


def agent() -> dict[str, Any]:
    return {
        "botId": MOCK_AGENT_ID,
        "fullBotName": "Mock Employee Self-Service Agent",
        "realm": "dev",
    }


def configuration() -> dict[str, Any]:
    return {
        "realm": "Dev",
        "cdsBotId": MOCK_AGENT_ID,
        "schemaName": "gptagent_mockemployeeselfservice",
        "grsRepositoryId": MOCK_FAMILY_ID,
    }


def components() -> dict[str, Any]:
    return {
        "bot": {"cdsBotId": MOCK_AGENT_ID},
        "botComponentChanges": [
            {
                "changeType": "Insert",
                "botComponent": {
                    "name": "gptagent_mockemployeeselfservice.topic.Greeting",
                    "componentType": 9,
                    "content": "{}",
                },
            }
        ],
        "connectionReferenceChanges": [
            {
                "changeType": "Insert",
                "connectionReference": {
                    "connectionReferenceLogicalName": (
                        "gptagent_mockemployeeselfservice."
                        "shared_service-now"
                    ),
                    "connectorId": (
                        "/providers/Microsoft.PowerApps/apis/"
                        "shared_service-now"
                    ),
                    "connectionId": MOCK_CONNECTION_ID,
                },
            }
        ],
    }


def connection_reference_change(
    *,
    connector: str,
    connection_id: str | None,
    logical_name: str | None = None,
) -> dict[str, Any]:
    """One ``connectionReferenceChanges`` entry in the validated minimalBots
    components shape (cassette ``agentbuilder_readiness.yaml``; the same shape
    the shipped native ``DA-CONN-001`` check consumes). Only the ``connectorId``
    value varies from the captured ServiceNow reference, so this is
    same-endpoint value variance and needs no new cassette (see
    ``scripts/flightcheck/AGENTS.md``). ``connection_id=None`` models an unbound
    reference.
    """
    reference = {
        "connectionReferenceLogicalName": (
            logical_name
            or f"gptagent_mockemployeeselfservice.{connector}"
        ),
        "connectorId": (
            f"/providers/Microsoft.PowerApps/apis/{connector}"
        ),
        "connectionId": connection_id,
    }
    return {
        "changeType": "Insert",
        "connectionReference": reference,
    }


def workday_connection_reference(
    *,
    connection_id: str | None = MOCK_WORKDAY_CONNECTION_ID,
    logical_name: str | None = None,
) -> dict[str, Any]:
    """The Workday SOAP (``shared_workdaysoap``) connection-reference variant
    that ``DV-CONN-001`` filters on."""
    return connection_reference_change(
        connector="shared_workdaysoap",
        connection_id=connection_id,
        logical_name=logical_name,
    )


def components_with_references(
    *,
    references: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """``components()`` with its ``connectionReferenceChanges`` replaced by the
    given references (``None`` -> an empty list, modelling an agent with no
    connection references)."""
    payload = components()
    payload["connectionReferenceChanges"] = (
        [] if references is None else list(references)
    )
    return payload


def connection(
    *,
    connection_id: str = MOCK_CONNECTION_ID,
    connector: str = "shared_service-now",
    status: str = "Connected",
) -> dict[str, Any]:
    return {
        "name": connection_id,
        "id": (
            f"/providers/Microsoft.PowerApps/apis/{connector}/connections/"
            f"{connection_id}"
        ),
        "type": "Microsoft.PowerApps/apis/connections",
        "properties": {
            "apiId": f"/providers/Microsoft.PowerApps/apis/{connector}",
            "displayName": "Mock ServiceNow",
            "statuses": [{"status": status}],
        },
    }


def get_agent(*, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "method": responses.GET,
        "url": (
            f"{MOCK_AGENTBUILDER_BASE}/copilotstudio/minimalBots/api/"
            f"{MOCK_AGENT_ID}?api-version=2024-10-01"
        ),
        "json": payload or agent(),
        "status": 200,
    }


def get_configuration(
    *,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "method": responses.GET,
        "url": (
            f"{MOCK_AGENTBUILDER_BASE}/copilotstudio/minimalBots/alm/"
            f"{MOCK_AGENT_ID}/configure?api-version=2024-10-01&realm=0"
        ),
        "json": payload or configuration(),
        "status": 200,
    }


def get_components(
    *,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "method": responses.POST,
        "url": (
            f"{MOCK_AGENTBUILDER_BASE}/copilotstudio/minimalBots/api/"
            f"{MOCK_AGENT_ID}/components?api-version=2022-03-01-preview"
        ),
        "json": payload or components(),
        "status": 200,
    }


def list_connections(
    *,
    items: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "method": responses.GET,
        "url": (
            f"{MOCK_CONNECTIVITY_BASE}/connectivity/environments/"
            f"{MOCK_ENV_ID}/connections?api-version=2024-10-01"
        ),
        "json": {
            "value": list(items) if items is not None else [connection()]
        },
        "status": 200,
    }
