# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Mock response builders for ServiceNow REST Table API.

# ─────────────────────────────────────────────────────────────────
# MOCK_STATUS = "placeholder"
#
# ⚠️ These builders are SCHEMA-GROUNDED, not cassette-validated. They
# were constructed by reading the public ServiceNow Table API
# documentation. The exact field shape, sys_* metadata fields, and
# nested reference object format that real ServiceNow instances emit
# may differ between versions and customizations.
#
# DO NOT use these mocks in FlightCheck integration tests under
# tests/flightcheck/checks/ until a cassette has been captured and
# this module has been updated to MOCK_STATUS = "validated".
#
# See tests/AGENTS.md for the workflow.
#
# To capture: requires a ServiceNow developer instance + credentials.
# Set SERVICENOW_INSTANCE / SERVICENOW_USER / SERVICENOW_PASS, then
# create tests/captures/record_flightcheck_servicenow.py modelled on
# the existing record_flightcheck_*.py wrappers.
# ─────────────────────────────────────────────────────────────────

References:
- Table API: https://developer.servicenow.com/dev.do#!/reference/api/utah/rest/c_TableAPI
- Production source for shape consumers (kit's MCP server, not
  FlightCheck — out of scope for this suite, but the response shape
  is the same): solutions/ess-maker-skills/src/mcp/servicenow/client.py
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

# Validation status — read by tests/conftest.py:require_validated_mock().
MOCK_STATUS = "placeholder"
MOCK_CASSETTE = None  # Awaiting tests/fixtures/cassettes/flightcheck_servicenow.yaml

MOCK_INSTANCE = "https://devmocktenant.service-now.com"
MOCK_SYS_ID = "0" * 32  # ServiceNow sys_ids are 32-char hex


# ────────────────────────────────────────────────────────────────────────
# Reference-object helper — ServiceNow returns nested reference fields
# as either a sys_id string OR a {"link": "...", "value": "<sys_id>"} dict
# depending on the `sysparm_display_value` and `sysparm_exclude_reference_link`
# params. The kit's MCP server uses the "value" form by default.
# ────────────────────────────────────────────────────────────────────────


def reference(*, sys_id: str = MOCK_SYS_ID, table: str = "sys_user") -> dict[str, str]:
    return {
        "link": f"{MOCK_INSTANCE}/api/now/table/{table}/{sys_id}",
        "value": sys_id,
    }


# ────────────────────────────────────────────────────────────────────────
# Record builders
# ────────────────────────────────────────────────────────────────────────


def incident(
    *,
    sys_id: str | None = None,
    number: str = "INC0010001",
    short_description: str = "Mock incident",
    state: str = "1",  # 1=New, 2=In Progress, 6=Resolved, 7=Closed
    caller_id: str | None = None,
    extra_fields: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a single ServiceNow `incident` table record (typed read).

    NOTE: schema-grounded. Real responses include ~80 sys_* metadata
    fields and table-specific columns. Cassette validation needed.
    """
    record: dict[str, Any] = {
        "sys_id": sys_id or MOCK_SYS_ID,
        "number": number,
        "short_description": short_description,
        "state": state,
        "caller_id": reference(sys_id=caller_id or MOCK_SYS_ID),
        "sys_created_on": "2026-01-01 00:00:00",
        "sys_updated_on": "2026-01-01 00:00:00",
        "active": "true",
        "priority": "3",
    }
    if extra_fields:
        record.update(extra_fields)
    return record


def hr_case(
    *,
    sys_id: str | None = None,
    number: str = "HRC0010001",
    short_description: str = "Mock HR case",
    state: str = "10",
    extra_fields: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a single `sn_hr_core_case` table record."""
    record: dict[str, Any] = {
        "sys_id": sys_id or MOCK_SYS_ID,
        "number": number,
        "short_description": short_description,
        "state": state,
        "sys_created_on": "2026-01-01 00:00:00",
        "sys_updated_on": "2026-01-01 00:00:00",
    }
    if extra_fields:
        record.update(extra_fields)
    return record


def sys_user(
    *,
    sys_id: str | None = None,
    user_name: str = "mock.user",
    name: str = "Mock User",
    email: str = "mock.user@contoso.com",
    extra_fields: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a single `sys_user` table record."""
    record: dict[str, Any] = {
        "sys_id": sys_id or MOCK_SYS_ID,
        "user_name": user_name,
        "name": name,
        "email": email,
        "active": "true",
        "sys_created_on": "2026-01-01 00:00:00",
    }
    if extra_fields:
        record.update(extra_fields)
    return record


def cmdb_ci(
    *,
    sys_id: str | None = None,
    name: str = "Mock CI",
    sys_class_name: str = "cmdb_ci_server",
    extra_fields: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a single `cmdb_ci` table record."""
    record: dict[str, Any] = {
        "sys_id": sys_id or MOCK_SYS_ID,
        "name": name,
        "sys_class_name": sys_class_name,
        "operational_status": "1",
        "sys_created_on": "2026-01-01 00:00:00",
    }
    if extra_fields:
        record.update(extra_fields)
    return record


# ────────────────────────────────────────────────────────────────────────
# Collection envelope + responses kwargs
# ────────────────────────────────────────────────────────────────────────


def collection(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Wrap records in the ServiceNow Table API `{"result": [...]}` envelope."""
    return {"result": list(records)}


def query_table(
    *,
    table: str = "incident",
    instance: str = MOCK_INSTANCE,
    records: Iterable[Mapping[str, Any]] | None = None,
    limit: int | None = None,
    status: int = 200,
) -> dict[str, Any]:
    """Mock GET /api/now/table/{table} (with optional sysparm_limit).

    Real URL also takes sysparm_query, sysparm_fields, etc. — those
    aren't included in the matcher; tests that need fine-grained
    matching can build kwargs by hand.
    """
    url = f"{instance.rstrip('/')}/api/now/table/{table}"
    if limit is not None:
        url += f"?sysparm_limit={limit}"
    return {
        "method": "GET",
        "url": url,
        "json": collection(records or []),
        "status": status,
    }


def get_record(
    *,
    table: str = "incident",
    sys_id: str = MOCK_SYS_ID,
    instance: str = MOCK_INSTANCE,
    record: Mapping[str, Any] | None = None,
    status: int = 200,
) -> dict[str, Any]:
    """Mock GET /api/now/table/{table}/{sys_id} (single-record fetch)."""
    return {
        "method": "GET",
        "url": f"{instance.rstrip('/')}/api/now/table/{table}/{sys_id}",
        "json": {"result": record or incident(sys_id=sys_id)},
        "status": status,
    }


def unauthorized(
    *,
    table: str = "incident",
    instance: str = MOCK_INSTANCE,
) -> dict[str, Any]:
    """Mock a 401 — wrong credentials or expired OAuth token."""
    return {
        "method": "GET",
        "url": f"{instance.rstrip('/')}/api/now/table/{table}",
        "json": {
            "error": {
                "message": "User Not Authenticated",
                "detail": "Required to provide Auth information",
            },
            "status": "failure",
        },
        "status": 401,
    }


def forbidden(
    *,
    table: str = "incident",
    instance: str = MOCK_INSTANCE,
) -> dict[str, Any]:
    """Mock a 403 — credentials valid but missing role for the table."""
    return {
        "method": "GET",
        "url": f"{instance.rstrip('/')}/api/now/table/{table}",
        "json": {
            "error": {
                "message": "Operation Failed",
                "detail": "ACL Exception Update Failed due to security constraints",
            },
            "status": "failure",
        },
        "status": 403,
    }
