# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Mock response builders for the Power Platform Admin (BAP + PowerApps) APIs.

# ─────────────────────────────────────────────────────────────────
# MOCK_STATUS = "validated"
#
# Backed by a real captured cassette. Safe to use in FlightCheck
# integration tests under tests/flightcheck/.
#
# Cassette: tests/fixtures/cassettes/flightcheck_pp_admin.yaml
# Endpoints covered: see tests/fixtures/cassettes/INDEX.md
# ─────────────────────────────────────────────────────────────────

Used by FlightCheck integration tests for any check that reads
environments, connections, flows, or DLP policies via
solutions/ess-maker-skills/scripts/flightcheck/pp_admin_client.py.

References:
- BAP environments: https://learn.microsoft.com/power-platform/admin/list-environments
- PowerApps connections: https://learn.microsoft.com/power-apps/maker/canvas-apps/add-manage-connections
- Production source: solutions/ess-maker-skills/scripts/flightcheck/pp_admin_client.py
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

# Validation status — read by tests/conftest.py:require_validated_mock().
MOCK_STATUS = "validated"
MOCK_CASSETTE = "tests/fixtures/cassettes/flightcheck_pp_admin.yaml"

BAP_BASE = "https://api.bap.microsoft.com"
POWERAPPS_BASE = "https://api.powerapps.com"
# Flow listing endpoint lives on a different host with a different audience
# token. See solutions/ess-maker-skills/scripts/flightcheck/pp_admin_client.py
# `FLOW_BASE` and the `service.flow.microsoft.com//.default` scope.
FLOW_BASE = "https://api.flow.microsoft.com"

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
    api_name: str = "shared_workdaysoap",
    env_id: str = MOCK_ENV_ID,
    status: str = "Connected",
    error_target: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    extra_properties: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a single PowerApps connection record.

    `status` accepts any of "Connected", "Error", "PendingConfirmation",
    "Unknown". For Error statuses, real responses include a nested
    `target` + `error.{code, message}` block — pass error_target,
    error_code, error_message to populate them. Defaults to the
    "Unauthorized" / "AADSTS50173: grant expired" shape captured from
    the user's real tenant in
    tests/fixtures/cassettes/flightcheck_pp_admin.yaml.

    The check in flightcheck/checks/workday.py:_get_conn_status only
    reads statuses[0].status — the target/error block is included for
    fidelity to real API responses, not because the kit consumes it.

    Cited consumers:
      - flightcheck/pp_admin_client.py:184-190 (get_connections)
      - flightcheck/checks/workday.py:262-342 (_check_connections)

    Reference: tests/fixtures/cassettes/flightcheck_pp_admin.yaml
    """
    api_id = (
        f"/providers/Microsoft.PowerApps/scopes/admin/environments/"
        f"{env_id}/apis/{api_name}"
    )
    status_entry: dict[str, Any] = {"status": status}
    if status == "Error":
        status_entry["target"] = error_target or "token"
        status_entry["error"] = {
            "code": error_code or "Unauthorized",
            "message": error_message or (
                "Failed to refresh access token. AADSTS50173: The provided "
                "grant has expired due to it being revoked, a fresh auth "
                "token is needed."
            ),
        }

    properties: dict[str, Any] = {
        "displayName": display_name,
        "apiId": api_id,
        "iconUri": (
            f"https://static.powerapps.com/resource/ppcr/releases/v1.0.0/"
            f"{api_name.replace('shared_', '')}/icon.png"
        ),
        "statuses": [status_entry],
        "connectionParameters": {"sku": "Enterprise"},
        "keywordsRemaining": 78,
        "isSsoConnection": False,
        "createdBy": {
            "id": "00000000-0000-0000-0000-000000002222",
            "displayName": "Mock User",
            "email": "mock.user@contoso.com",
            "type": "User",
            "tenantId": "00000000-0000-0000-0000-000000001111",
            "userPrincipalName": "mock.user@contoso.com",
        },
        "createdTime": "2026-01-01T00:00:00.0000000Z",
        "lastModifiedTime": "2026-01-15T00:00:00.0000000Z",
        "environment": {
            "id": f"/providers/Microsoft.PowerApps/environments/{env_id}",
            "name": env_id,
        },
        "accountName": "mock.user@contoso.com",
        "allowSharing": False,
    }
    if extra_properties:
        properties.update(extra_properties)

    return {
        "name": name,
        "id": (
            f"/providers/Microsoft.PowerApps/scopes/admin/environments/"
            f"{env_id}/apis/{api_name}/connections/{name}"
        ),
        "type": "Microsoft.PowerApps/scopes/apis/connections",
        "properties": properties,
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
        api_name="shared_workdaysoap",
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
        api_name="shared_office365",
        status=status,
    )


def flow(
    *,
    flow_id: str | None = None,
    env_id: str = MOCK_ENV_ID,
    display_name: str = "Workday Get Worker",
    state: str = "Started",
) -> dict[str, Any]:
    """Build a single PowerApps flow record.

    `state` accepts "Started", "Stopped", "Suspended". The check in
    flightcheck/checks/workday.py:_check_flow_status treats
    {"started", "on", "enabled"} (case-insensitive) as enabled.

    `env_id` defaults to MOCK_ENV_ID so the record's `id` field is
    self-consistent with what `list_flows()` (which uses the same
    default) would serve under. Callers building a flow against a
    specific environment should pass the same env_id they pass to
    `list_flows()`.
    """
    effective_id = flow_id or "00000000-0000-0000-0000-000000007101"
    return {
        "name": effective_id,
        "id": (
            f"/providers/Microsoft.ProcessSimple/environments/{env_id}"
            f"/flows/{effective_id}"
        ),
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
    """Mock GET /providers/Microsoft.ProcessSimple/scopes/admin/environments/{env}/v2/flows.

    Hosted on `api.flow.microsoft.com` (NOT `api.powerapps.com`) and
    requires a `service.flow.microsoft.com//.default` audience token
    rather than the PowerApps audience.
    """
    return {
        "method": "GET",
        "url": (
            f"{FLOW_BASE}/providers/Microsoft.ProcessSimple/scopes/admin/environments/"
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
            f"{FLOW_BASE}/providers/Microsoft.ProcessSimple/scopes/admin/environments/"
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



