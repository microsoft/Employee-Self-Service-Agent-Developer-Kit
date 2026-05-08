# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Mock response builders for the Power Platform Admin (BAP + PowerApps) APIs.

Used by FlightCheck integration tests for any check that reads
environments, connections, flows, or DLP policies via
solutions/ess-maker-skills/scripts/flightcheck/pp_admin_client.py.

Each builder either returns a connection/flow/env dict (for assembling
into a list) or returns a `responses.add(**...)` kwargs dict for direct
registration.

⚠️ Status: schema-grounded. Cassettes captured via
tests/captures/record_flightcheck_pp_admin.py supersede this when they
disagree.

References:
- BAP environments: https://learn.microsoft.com/power-platform/admin/list-environments
- PowerApps connections: https://learn.microsoft.com/power-apps/maker/canvas-apps/add-manage-connections
- Production source: solutions/ess-maker-skills/scripts/flightcheck/pp_admin_client.py
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

BAP_BASE = "https://api.bap.microsoft.com"
POWERAPPS_BASE = "https://api.powerapps.com"

MOCK_ENV_ID = "Default-00000000-0000-0000-0000-000000001111"
MOCK_ORG_ID = "00000000-0000-0000-0000-000000005555"


# ────────────────────────────────────────────────────────────────────────
# Payload builders — return single records suitable for assembling into
# a {"value": [...]} response collection.
# ────────────────────────────────────────────────────────────────────────


def environment(
    *,
    env_id: str = MOCK_ENV_ID,
    display_name: str = "Mock Environment",
    organization_id: str = MOCK_ORG_ID,
    instance_url: str = "https://orgmocktenant.crm.dynamics.com/",
) -> dict[str, Any]:
    """Build a single BAP environment record.

    Cited consumers:
      - flightcheck/pp_admin_client.py:148-162 (get_environments / get_environment)
      - flightcheck/pp_admin_client.py:240+ (derive_environment_id)
    """
    return {
        "id": f"/providers/Microsoft.BusinessAppPlatform/scopes/admin/environments/{env_id}",
        "name": env_id,
        "type": "Microsoft.BusinessAppPlatform/scopes/admin/environments",
        "properties": {
            "displayName": display_name,
            "createdTime": "2026-01-01T00:00:00.000Z",
            "linkedEnvironmentMetadata": {
                "instanceUrl": instance_url,
                "instanceState": "Ready",
                "resourceId": organization_id,
                "uniqueName": f"unq{organization_id[:8]}",
            },
            "environmentSku": "Production",
            "states": {
                "management": {"id": "Ready"},
                "runtime": {"id": "Enabled"},
            },
        },
    }


def connection(
    *,
    name: str = "shared-workdaysoap-mock-001",
    display_name: str = "Mock Workday SOAP",
    api_id: str = "/providers/Microsoft.PowerApps/apis/shared_workdaysoap",
    status: str = "Connected",
    extra_status_fields: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a single PowerApps connection record.

    `status` accepts any of "Connected", "Error", "PendingConfirmation",
    "Unknown". The check in flightcheck/checks/workday.py:_get_conn_status
    looks at properties.statuses[0].status only, so additional status
    entries are ignored.

    Cited consumers:
      - flightcheck/pp_admin_client.py:184-190 (get_connections)
      - flightcheck/checks/workday.py:262-342 (_check_connections)
    """
    status_entry: dict[str, Any] = {"status": status}
    if extra_status_fields:
        status_entry.update(extra_status_fields)
    return {
        "name": name,
        "id": f"/providers/Microsoft.PowerApps/apis/{api_id.split('/')[-1]}/connections/{name}",
        "type": "Microsoft.PowerApps/apis/connections",
        "properties": {
            "displayName": display_name,
            "apiId": api_id,
            "statuses": [status_entry],
            "createdTime": "2026-01-01T00:00:00.000Z",
        },
    }


def workday_connection(
    *, status: str = "Connected", display_name: str = "Workday SOAP — ISU"
) -> dict[str, Any]:
    """Convenience: a Workday SOAP connection. The check filters by
    'workday' substring in apiId+displayName, so both the api_id and
    the display_name reference Workday."""
    return connection(
        name=f"workday-{status.lower()}-{display_name[:8].lower().replace(' ', '-')}",
        display_name=display_name,
        api_id="/providers/Microsoft.PowerApps/apis/shared_workdaysoap",
        status=status,
    )


def non_workday_connection(
    *, display_name: str = "Office 365", status: str = "Connected"
) -> dict[str, Any]:
    """Convenience: a non-Workday connection (Office 365, Dataverse,
    SharePoint, etc.) used to verify the Workday filter excludes them."""
    return connection(
        name="office365-mock-001",
        display_name=display_name,
        api_id="/providers/Microsoft.PowerApps/apis/shared_office365",
        status=status,
    )


def flow(
    *,
    flow_id: str | None = None,
    display_name: str = "Workday Get Worker",
    state: str = "Started",
) -> dict[str, Any]:
    """Build a single PowerApps flow record.

    `state` accepts "Started", "Stopped", "Suspended". The check in
    flightcheck/checks/workday.py:_check_flow_status treats
    {"started", "on", "enabled"} (case-insensitive) as enabled.
    """
    return {
        "name": flow_id or "00000000-0000-0000-0000-000000007101",
        "id": f"/providers/Microsoft.ProcessSimple/environments/{{env}}/flows/{flow_id}",
        "type": "Microsoft.ProcessSimple/environments/flows",
        "properties": {
            "displayName": display_name,
            "state": state,
            "createdTime": "2026-01-01T00:00:00.000Z",
        },
    }


# ────────────────────────────────────────────────────────────────────────
# Collection wrappers
# ────────────────────────────────────────────────────────────────────────


def collection(
    records: Iterable[Mapping[str, Any]],
    *,
    next_link: str | None = None,
) -> dict[str, Any]:
    """Wrap a list of records in the BAP/PowerApps {"value": [...]} envelope."""
    payload: dict[str, Any] = {"value": list(records)}
    if next_link:
        payload["nextLink"] = next_link
    return payload


# ────────────────────────────────────────────────────────────────────────
# `responses` registration helpers
# ────────────────────────────────────────────────────────────────────────


def list_connections(
    *,
    env_id: str = MOCK_ENV_ID,
    connections: Iterable[Mapping[str, Any]] | None = None,
    status: int = 200,
) -> dict[str, Any]:
    """Mock GET /providers/Microsoft.PowerApps/scopes/admin/environments/{env}/connections."""
    return {
        "method": "GET",
        "url": (
            f"{POWERAPPS_BASE}/providers/Microsoft.PowerApps/scopes/admin/environments/"
            f"{env_id}/connections"
        ),
        "json": collection(connections or []),
        "status": status,
    }


def list_environments(
    *,
    environments: Iterable[Mapping[str, Any]] | None = None,
    status: int = 200,
) -> dict[str, Any]:
    """Mock GET /providers/Microsoft.BusinessAppPlatform/scopes/admin/environments."""
    return {
        "method": "GET",
        "url": (
            f"{BAP_BASE}/providers/Microsoft.BusinessAppPlatform/scopes/admin/environments"
        ),
        "json": collection(environments or []),
        "status": status,
    }


def list_flows(
    *,
    env_id: str = MOCK_ENV_ID,
    flows: Iterable[Mapping[str, Any]] | None = None,
    status: int = 200,
) -> dict[str, Any]:
    """Mock GET /providers/Microsoft.ProcessSimple/scopes/admin/environments/{env}/v2/flows."""
    return {
        "method": "GET",
        "url": (
            f"{POWERAPPS_BASE}/providers/Microsoft.ProcessSimple/scopes/admin/environments/"
            f"{env_id}/v2/flows"
        ),
        "json": collection(flows or []),
        "status": status,
    }


def insufficient_permissions(
    *,
    env_id: str = MOCK_ENV_ID,
    endpoint: str = "connections",
) -> dict[str, Any]:
    """Mock a 403 from BAP/PowerApps — the production code maps
    401/403 to {"_error": "insufficient_permissions"} dict.

    See flightcheck/pp_admin_client.py:126-127.
    """
    if endpoint == "connections":
        url = (
            f"{POWERAPPS_BASE}/providers/Microsoft.PowerApps/scopes/admin/environments/"
            f"{env_id}/connections"
        )
    elif endpoint == "flows":
        url = (
            f"{POWERAPPS_BASE}/providers/Microsoft.ProcessSimple/scopes/admin/environments/"
            f"{env_id}/v2/flows"
        )
    elif endpoint == "environments":
        url = (
            f"{BAP_BASE}/providers/Microsoft.BusinessAppPlatform/scopes/admin/environments"
        )
    else:
        raise ValueError(f"unknown endpoint {endpoint!r}")

    return {
        "method": "GET",
        "url": url,
        "json": {
            "error": {
                "code": "Forbidden",
                "message": "User does not have Power Platform Admin role.",
            }
        },
        "status": 403,
    }
