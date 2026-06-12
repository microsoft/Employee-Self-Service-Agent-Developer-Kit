# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Shared connection-status utilities for FlightCheck checks.

Provides common helpers for inspecting Power Platform connection records
returned by the BAP Admin API (``GET /providers/Microsoft.PowerApps/scopes/
admin/environments/{env_id}/connections``). Used by workday.py, servicenow.py,
environment.py, and any future connector-specific check modules.
"""

from __future__ import annotations

from ..runner import CheckResult, Priority, Role, Status


def get_connection_status(conn: dict) -> str:
    """Extract connection status from the BAP API response.

    The PowerApps Admin API returns a ``statuses`` array on each connection
    record under ``properties.statuses``. The first entry's ``status`` field
    holds the overall connection state (e.g. "Connected", "Error").

    Args:
        conn: A single connection record dict from ``pp_admin.get_connections()``.

    Returns:
        The status string (e.g. "Connected", "Error"), or "Unknown" if the
        statuses array is missing or empty.
    """
    statuses = conn.get("properties", {}).get("statuses", [])
    if isinstance(statuses, list) and statuses:
        return statuses[0].get("status", "Unknown")
    return "Unknown"


def filter_connections_by_connector(
    all_conns: list[dict],
    connector_keyword: str | list[str],
) -> list[dict]:
    """Filter connections by connector keyword in apiId or displayName.

    Args:
        all_conns: Full list of connection records from the BAP API.
        connector_keyword: Case-insensitive substring (or list of substrings)
            to match against the connection's ``properties.apiId`` and
            ``properties.displayName`` (e.g. "workday", "service-now",
            or ["service-now", "servicenow"]).

    Returns:
        List of connections whose apiId or displayName contains any keyword.
    """
    keywords = [connector_keyword.lower()] if isinstance(connector_keyword, str) else [k.lower() for k in connector_keyword]
    return [
        c for c in all_conns
        if any(
            kw in (
                c.get("properties", {}).get("apiId", "")
                + c.get("properties", {}).get("displayName", "")
            ).lower()
            for kw in keywords
        )
    ]


def check_connector_connections(
    runner,
    *,
    connector_keyword: str | list[str],
    checkpoint_prefix: str,
    category: str,
    not_found_remediation: str,
    doc_link: str = "",
) -> list[CheckResult]:
    """Generic connection check for any Power Platform connector.

    Discovers connections matching ``connector_keyword``, reports summary
    and per-connection status. Produces checkpoint IDs like
    ``{checkpoint_prefix}-001`` (summary) and ``{checkpoint_prefix}-002+``
    (per-connection detail).

    Args:
        runner: FlightCheck runner with ``pp_admin`` and ``env_id``.
        connector_keyword: Substring or list of substrings to match in
            apiId/displayName (e.g. "workday", ["service-now", "servicenow"]).
        checkpoint_prefix: Prefix for checkpoint IDs (e.g. "WD-CONN", "SN-CONN").
        category: Check category (e.g. "Workday", "ServiceNow").
        not_found_remediation: Remediation text when no connections are found.
        doc_link: Optional documentation link for the check results.

    Returns:
        List of CheckResult entries.
    """
    results: list[CheckResult] = []
    pp = runner.pp_admin
    env_id = runner.env_id

    if not env_id or pp is None:
        results.append(CheckResult(
            checkpoint_id=f"{checkpoint_prefix}-001",
            category=category,
            priority=Priority.HIGH.value,
            status=Status.SKIPPED.value,
            description=f"{category} connections",
            result="Power Platform Admin API not available — skipping connection checks",
            roles=[Role.POWER_PLATFORM_ADMIN.value],
        ))
        return results

    try:
        all_conns = pp.get_connections(env_id)
        if isinstance(all_conns, dict) and "_error" in all_conns:
            results.append(CheckResult(
                checkpoint_id=f"{checkpoint_prefix}-001",
                category=category,
                priority=Priority.HIGH.value,
                status=Status.WARNING.value,
                description=f"{category} connections",
                result=f"Unable to list connections: {all_conns['_error']}",
                remediation="Requires Power Platform Admin role.",
                roles=[Role.POWER_PLATFORM_ADMIN.value],
            ))
            return results

        conns = filter_connections_by_connector(all_conns, connector_keyword)

        if conns:
            connected = [c for c in conns if get_connection_status(c) == "Connected"]
            errored = [c for c in conns if get_connection_status(c) != "Connected"]

            results.append(CheckResult(
                checkpoint_id=f"{checkpoint_prefix}-001",
                category=category,
                priority=Priority.HIGH.value,
                status=Status.PASSED.value if connected else Status.FAILED.value,
                description=f"{category} connections",
                result=f"{len(conns)} total — {len(connected)} connected, {len(errored)} errored",
                remediation="Re-authenticate errored connections in Power Platform." if errored else f"Validated: {len(connected)} of {len(conns)} {category} connection(s) report 'Connected' state via the Power Platform connections API (GET /providers/Microsoft.PowerApps/scopes/admin/environments/{{env_id}}/connections).",
                doc_link=doc_link,
                roles=[Role.POWER_PLATFORM_ADMIN.value],
            ))

            for i, c in enumerate(conns):
                props = c.get("properties", {})
                name = props.get("displayName", f"Connection {i + 1}")
                status = get_connection_status(c)
                cid = f"{checkpoint_prefix}-{i + 2:03d}"
                results.append(CheckResult(
                    checkpoint_id=cid,
                    category=category,
                    priority=Priority.HIGH.value,
                    status=Status.PASSED.value if status == "Connected" else Status.FAILED.value,
                    description=f"Connection: {name}",
                    result=f"Status: {status}",
                    remediation=f"Re-authenticate '{name}' in Power Platform." if status != "Connected" else f"Validated: connection '{name}' reports 'Connected' status via the Power Platform connections API.",
                    roles=[Role.POWER_PLATFORM_ADMIN.value],
                ))
        else:
            results.append(CheckResult(
                checkpoint_id=f"{checkpoint_prefix}-001",
                category=category,
                priority=Priority.HIGH.value,
                status=Status.NOT_CONFIGURED.value,
                description=f"{category} connections",
                result=f"No {category} connections found",
                remediation=not_found_remediation,
                doc_link=doc_link,
                roles=[Role.POWER_PLATFORM_ADMIN.value],
            ))
    except Exception as e:
        results.append(CheckResult(
            checkpoint_id=f"{checkpoint_prefix}-001",
            category=category,
            priority=Priority.HIGH.value,
            status=Status.WARNING.value,
            description=f"{category} connections",
            result=f"Unable to check: {e}",
            roles=[Role.POWER_PLATFORM_ADMIN.value],
        ))

    return results
