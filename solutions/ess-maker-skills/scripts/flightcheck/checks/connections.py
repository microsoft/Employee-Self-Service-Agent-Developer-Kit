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

from collections.abc import Callable

import requests

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
    connection_pin: str = "",
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
        connection_pin: Optional operator selection (a connection ``name`` or
            a ``displayName`` substring). When set and it matches at least one
            of the keyword-filtered connections, the check narrows to just the
            matching connection(s) so a tenant with several connections for the
            same connector (dev/test/prod) reports on only the one the operator
            is verifying. A pin that matches nothing is ignored (all matching
            connections are validated, as before) rather than reported as
            "not configured". Set only by standalone scope runs; single-
            checkpoint mode leaves it empty.

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

        # Narrow to the operator-selected connection when one is pinned and
        # actually matches. Matching is by the connection's ``name`` (the
        # stable connection id) OR a case-insensitive substring of its
        # ``displayName``. A pin that matches nothing is deliberately ignored
        # (fall through to validating all matches) so a stale/typo'd pin never
        # masks a real connection as "not configured".
        pin_note = ""
        pin = (connection_pin or "").strip().lower()
        if pin and conns:
            narrowed = [
                c for c in conns
                if pin == str(c.get("name", "")).strip().lower()
                or pin in str(
                    c.get("properties", {}).get("displayName", "")
                ).strip().lower()
            ]
            if narrowed:
                conns = narrowed
                pin_note = f" (scoped to selected connection '{connection_pin}')"

        if conns:
            connected = [c for c in conns if get_connection_status(c) == "Connected"]
            errored = [c for c in conns if get_connection_status(c) != "Connected"]

            results.append(CheckResult(
                checkpoint_id=f"{checkpoint_prefix}-001",
                category=category,
                priority=Priority.HIGH.value,
                status=Status.PASSED.value if connected else Status.FAILED.value,
                description=f"{category} connections",
                result=f"{len(conns)} total — {len(connected)} connected, {len(errored)} errored{pin_note}",
                remediation="Re-authenticate errored connections in Power Platform." if errored else "",
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
                    remediation=f"Re-authenticate '{name}' in Power Platform." if status != "Connected" else "",
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


def connection_owner_upn(conn: dict) -> str:
    """Return the UPN of the identity that created (owns) a connection.

    Reads ``properties.createdBy.userPrincipalName`` (falling back to
    ``email``). Returns "" when the owner is not exposed on the record, which
    callers must treat as "owner unknown", not "no owner".
    """
    props = conn.get("properties", {}) if isinstance(conn, dict) else {}
    created_by = props.get("createdBy", {}) or {}
    return (created_by.get("userPrincipalName") or created_by.get("email") or "").strip()


_OPERATOR_UPN_SENTINEL = object()


def get_operator_upn(runner) -> str:
    """Resolve the running FlightCheck operator's UPN and cache it on the runner.

    The operator is the identity that will activate the transient probe flow.
    Power Automate only activates a flow with a connection that identity owns
    or has been shared, so an active managed-connector probe must know who the
    operator is to pick a usable connection.

    Resolves via Dataverse ``WhoAmI()`` -> ``systemusers(UserId).domainname``
    (domainname is the Azure AD UPN in Dataverse). Returns "" when it cannot be
    determined; callers MUST treat "" as "ownership unknown, do not gate" so
    the probe never regresses on a tenant that hides the field or a runner that
    lacks a token. The result (including "") is cached on ``runner`` so tests
    can pre-seed ``runner._operator_upn`` and production pays the lookup once.
    """
    cached = getattr(runner, "_operator_upn", _OPERATOR_UPN_SENTINEL)
    if cached is not _OPERATOR_UPN_SENTINEL:
        return cached or ""
    upn = _resolve_operator_upn_live(runner)
    try:
        runner._operator_upn = upn
    except Exception:  # noqa: BLE001 - a read-only runner must not fail the check
        pass
    return upn


def _resolve_operator_upn_live(runner) -> str:
    env_url = (getattr(runner, "env_url", "") or "").rstrip("/")
    dv_token = getattr(runner, "dv_token", "") or ""
    if not env_url or not dv_token or not env_url.lower().startswith("https://"):
        return ""
    headers = {"Authorization": f"Bearer {dv_token}", "Accept": "application/json"}
    try:
        who = requests.get(f"{env_url}/api/data/v9.2/WhoAmI()", headers=headers, timeout=15)
        if who.status_code != 200:
            return ""
        user_id = who.json().get("UserId")
        if not user_id:
            return ""
        su = requests.get(
            f"{env_url}/api/data/v9.2/systemusers({user_id})?$select=domainname",
            headers=headers,
            timeout=15,
        )
        if su.status_code != 200:
            return ""
        return (su.json().get("domainname") or "").strip()
    except Exception:  # noqa: BLE001 - identity resolution must never fail the check
        return ""


def select_operator_owned_connection(
    *,
    connections: list[dict],
    is_target: Callable[[dict], bool],
    runtime_source: Callable[[dict], str],
    operator_upn: str,
    vendor_label: str,
    identity_path_label: str,
) -> tuple[dict | None, str]:
    """Pick the managed connection an on-demand connector probe binds to.

    Vendor-agnostic. Every managed-connector active probe (Workday,
    ServiceNow, and future ISV / custom connectors) shares this selection so
    the ownership rule lives in one place:

      1. Only ``is_target`` connections (the vendor's connector filter).
      2. Only Connected ones.
      3. Only the service-account / integration identity path, not
         OAuth-invoker (``runtime_source`` != "invoker") - AC9.
      4. Prefer a connection the running operator OWNS. Power Automate only
         activates a transient flow with a connection the activating identity
         owns or has shared; a non-owned connection returns
         ``ConnectionAuthorizationFailed`` at activate (confirmed live, PROD
         2026-08-11). Picking an operator-owned connection is what lets the
         active probe actually reach the connector instead of falling back.

    Ownership gating never regresses on incomplete data: when ``operator_upn``
    is unknown ("") or when the eligible connections do not expose an owner, it
    returns the first eligible connection instead of blocking.

    Returns ``(connection, "")`` on success, or ``(None, reason)``. The caller
    maps a "no <vendor> managed-connector connection was found" reason to
    NOT_CONFIGURED and any other reason to the passive run-history fallback, so
    reasons here deliberately avoid the "no <vendor>" token except for the
    truly-missing pre-deployment state.
    """
    target = [c for c in connections if isinstance(c, dict) and is_target(c)]
    if not target:
        return None, f"no {vendor_label} managed-connector connection was found"
    connected = [c for c in target if get_connection_status(c) == "Connected"]
    if not connected:
        return None, f"no Connected {vendor_label} managed-connector connection was found"

    service_account = [c for c in connected if runtime_source(c) != "invoker"]
    if not service_account:
        return None, (
            f"only OAuth-invoker {vendor_label} connections were found; the active "
            f"probe would exercise the maker/employee identity instead of the "
            f"{identity_path_label}"
        )

    if not operator_upn:
        # Operator identity unknown: do not gate on ownership (no regression).
        return service_account[0], ""

    op = operator_upn.strip().lower()
    owned = [c for c in service_account if connection_owner_upn(c).lower() == op]
    if owned:
        return owned[0], ""
    unknown_owner = [c for c in service_account if not connection_owner_upn(c)]
    if unknown_owner:
        # Owner not exposed on these records: try rather than block.
        return unknown_owner[0], ""
    return None, (
        f"the /flightcheck operator ({operator_upn}) does not own a Connected "
        f"{vendor_label} managed-connector connection in this environment; Power "
        f"Automate only activates a transient probe flow with a connection the "
        f"operator owns or has shared in the flow context. Run /flightcheck as "
        f"the connection owner, or have the owner share the connection, to "
        f"exercise the active probe"
    )
