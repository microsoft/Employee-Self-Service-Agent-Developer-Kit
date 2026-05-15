# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — External Systems Discovery (WD-001, SN-001, SN-002, SAP-001)

Discovers installed integration solutions by scanning flows for name patterns,
and validates ServiceNow Power Platform connections that use the
"Microsoft Entra User Sign In" auth mode (SN-002) — surfacing silent
federated-SSO / token-exchange failures before customers hit a runtime
"User Not Authenticated" error.
"""

from ..runner import CheckResult, Status, Priority

DOC_BASE = "https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service"

# Flow name patterns per integration
WORKDAY_PATTERNS = ("Workday",)
SERVICENOW_PATTERNS = ("ServiceNow",)
SAP_PATTERNS = ("SAP", "SuccessFactors")

# The Power Platform ServiceNow connector publishes its api id with the
# segment "shared_service-now". The "Microsoft Entra User Sign In" auth
# mode is identified by connectionParametersSet.name == "entraIDUserLogin"
# in the BAP/PowerApps connection record.
SERVICENOW_API_FRAGMENT = "service-now"
ENTRA_USER_LOGIN_PARAMETERS_SET = "entraIDUserLogin"


def _match_flows(flows: list, patterns: tuple) -> list:
    """Return flows whose display name contains any of the patterns."""
    matched = []
    for f in flows:
        name = f.get("properties", {}).get("displayName", f.get("displayName", ""))
        if any(p.lower() in name.lower() for p in patterns):
            matched.append(f)
    return matched


def _categorize_servicenow_flows(flows: list) -> tuple[list, list, list]:
    """Split ServiceNow flows into HRSD, ITSM, and Other."""
    hrsd, itsm, other = [], [], []
    for f in flows:
        name = f.get("properties", {}).get("displayName", f.get("displayName", ""))
        if any(k in name for k in ("HRSD", "HR Service")):
            hrsd.append(f)
        elif any(k in name for k in ("ITSM", "Incident", "Ticket")):
            itsm.append(f)
        else:
            other.append(f)
    return hrsd, itsm, other


def run_external_systems_checks(runner) -> list[CheckResult]:
    """Discover external system integrations from flow inventory."""
    pp = runner.pp_admin
    env_id = runner.env_id
    results: list[CheckResult] = []

    if not env_id:
        return results

    # Fetch all flows
    try:
        all_flows = pp.get_flows(env_id)
        if isinstance(all_flows, dict) and "_error" in all_flows:
            results.append(CheckResult(
                checkpoint_id="EXT-001", category="External Systems",
                priority=Priority.HIGH.value, status=Status.WARNING.value,
                description="Flow inventory",
                result=f"Unable to list flows: {all_flows['_error']}",
                remediation="Requires Power Platform Admin role.",
            ))
            return results
    except Exception as e:
        results.append(CheckResult(
            checkpoint_id="EXT-001", category="External Systems",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description="Flow inventory",
            result=f"Unable to list flows: {e}",
        ))
        return results

    # Store discovered flows on runner for downstream checks
    runner._all_flows = all_flows

    # ---- WD-001: Workday solution ----
    wd_flows = _match_flows(all_flows, WORKDAY_PATTERNS)
    runner._workday_flows = wd_flows
    if wd_flows:
        results.append(CheckResult(
            checkpoint_id="WD-001", category="External Systems",
            priority=Priority.HIGH.value, status=Status.PASSED.value,
            description="Workday solution installed",
            result=f"Found {len(wd_flows)} Workday flow(s)",
            doc_link=f"{DOC_BASE}/workday",
        ))
    else:
        results.append(CheckResult(
            checkpoint_id="WD-001", category="External Systems",
            priority=Priority.HIGH.value, status=Status.NOT_CONFIGURED.value,
            description="Workday solution installed",
            result="No Workday flows found in environment",
            remediation="Install the Workday extension pack if you plan to integrate.",
            doc_link=f"{DOC_BASE}/workday",
        ))

    # ---- SN-001: ServiceNow solution ----
    sn_flows = _match_flows(all_flows, SERVICENOW_PATTERNS)
    runner._servicenow_flows = sn_flows
    if sn_flows:
        hrsd, itsm, other = _categorize_servicenow_flows(sn_flows)
        detail = f"Found {len(sn_flows)} ServiceNow flow(s)"
        if hrsd:
            detail += f" ({len(hrsd)} HRSD"
        if itsm:
            detail += f", {len(itsm)} ITSM"
        if other:
            detail += f", {len(other)} other"
        if hrsd or itsm or other:
            detail += ")"
        results.append(CheckResult(
            checkpoint_id="SN-001", category="External Systems",
            priority=Priority.HIGH.value, status=Status.PASSED.value,
            description="ServiceNow solution installed",
            result=detail,
            doc_link=f"{DOC_BASE}/servicenow",
        ))
    else:
        results.append(CheckResult(
            checkpoint_id="SN-001", category="External Systems",
            priority=Priority.HIGH.value, status=Status.NOT_CONFIGURED.value,
            description="ServiceNow solution installed",
            result="No ServiceNow flows found in environment",
            remediation="Install the ServiceNow extension pack if you plan to integrate.",
            doc_link=f"{DOC_BASE}/servicenow",
        ))

    # ---- SN-002: ServiceNow "Microsoft Entra User Sign In" connections ----
    results.extend(_check_sn_entra_user_signin_connections(runner))

    # ---- SAP-001: SAP SuccessFactors solution ----
    sap_flows = _match_flows(all_flows, SAP_PATTERNS)
    runner._sap_flows = sap_flows
    if sap_flows:
        results.append(CheckResult(
            checkpoint_id="SAP-001", category="External Systems",
            priority=Priority.HIGH.value, status=Status.PASSED.value,
            description="SAP SuccessFactors solution installed",
            result=f"Found {len(sap_flows)} SAP flow(s)",
            doc_link=f"{DOC_BASE}/sap-successfactors",
        ))
    else:
        results.append(CheckResult(
            checkpoint_id="SAP-001", category="External Systems",
            priority=Priority.HIGH.value, status=Status.NOT_CONFIGURED.value,
            description="SAP SuccessFactors solution installed",
            result="No SAP SuccessFactors flows found",
            remediation="Install the SAP extension pack if you plan to integrate.",
            doc_link=f"{DOC_BASE}/sap-successfactors",
        ))

    return results


def _is_servicenow_connection(conn: dict) -> bool:
    """True if the BAP/PowerApps connection record is for the ServiceNow connector."""
    api_id = conn.get("properties", {}).get("apiId", "")
    return SERVICENOW_API_FRAGMENT in api_id.lower()


def _is_entra_user_signin(conn: dict) -> bool:
    """True if the connection uses the "Microsoft Entra User Sign In" auth mode.

    Identified by the BAP-side `connectionParametersSet.name` field 
    ServiceNow connections created via the Entra User Sign In flow carry
    `connectionParametersSet.name == "entraIDUserLogin"`. Other auth
    modes use either `connectionParameters.username` (Basic) or a
    different parameters-set name (e.g. "Oauth").
    """
    params_set = conn.get("properties", {}).get("connectionParametersSet") or {}
    return params_set.get("name") == ENTRA_USER_LOGIN_PARAMETERS_SET


def _conn_status_entry(conn: dict) -> dict:
    """First entry of the connection's `statuses` list, or {} if missing."""
    statuses = conn.get("properties", {}).get("statuses") or []
    if isinstance(statuses, list) and statuses and isinstance(statuses[0], dict):
        return statuses[0]
    return {}


def _is_entra_token_failure(status_entry: dict) -> bool:
    """True if a status-entry's error message indicates an Entra/AAD
    token-exchange failure (the federated-SSO failure mode SN-002 is
    designed to catch).

    Real failure shapes captured in flightcheck_pp_admin.yaml:
      - error.code == "Unauthorized"; error.message contains
        "Failed to refresh access token" + an "AADSTS" code,
        or "invalid_grant", or "is not authenticated".
    Any of those tokens count  we don't want to over-fit to a single
    AADSTS number because the federated-IdP rejection paths surface
    several different sub-codes.
    """
    err = status_entry.get("error") or {}
    msg = (err.get("message") or "").lower()
    code = (err.get("code") or "").lower()
    target = (status_entry.get("target") or "").lower()
    if target == "token" or "unauthorized" in code:
        return True
    return any(
        token in msg
        for token in (
            "aadsts",
            "refresh access token",
            "invalid_grant",
            "not authenticated",
        )
    )


def _conn_display_name(conn: dict) -> str:
    """Best-effort display name for a connection (falls back to its name)."""
    props = conn.get("properties", {}) or {}
    return props.get("displayName") or conn.get("name", "<unnamed connection>")


def _check_sn_entra_user_signin_connections(runner) -> list[CheckResult]:
    """SN-002: validate ServiceNow connections using "Microsoft Entra User
    Sign In" auth mode have a healthy stored token.

    Why this signal is meaningful (and how it differs from the original
    issue's literal suggested implementation):

    The issue (#42) suggested invoking a low-impact ServiceNow REST
    endpoint via the connection to assert the federated identity flow
    succeeds end-to-end. That probe is not directly executable from
    FlightCheck  Entra User Sign In connections are user-delegated, so
    only the connection owner's bearer token can call ServiceNow on
    their behalf, and FlightCheck (running with PP Admin scope) has no
    access to those tokens.

    However, BAP/PowerApps itself runs the same federated token
    exchange every time it refreshes a connection's access token, and
    persists the failure on the connection record's `statuses[*]` field
    when the exchange breaks. Real captured examples in
    `tests/fixtures/cassettes/flightcheck_pp_admin.yaml` show the
    AADSTS50173 grant-expired and "is not authenticated" surfaces
    appearing exactly here for entraIDUserLogin ServiceNow connections.

    So SN-002 reads that already-surfaced signal: an entraIDUserLogin
    ServiceNow connection in `Error` state with a token-related error
    is direct evidence that the federated identity flow the customer
    expects to work at runtime is currently broken.
    """
    results: list[CheckResult] = []
    pp = runner.pp_admin
    env_id = runner.env_id

    if not env_id or not pp:
        return results

    try:
        all_conns = pp.get_connections(env_id)
    except Exception as e:
        results.append(CheckResult(
            checkpoint_id="SN-002", category="External Systems",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description="ServiceNow Entra User Sign In connections",
            result=f"Unable to list connections: {e}",
            doc_link=f"{DOC_BASE}/servicenow",
        ))
        return results

    if isinstance(all_conns, dict) and "_error" in all_conns:
        results.append(CheckResult(
            checkpoint_id="SN-002", category="External Systems",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description="ServiceNow Entra User Sign In connections",
            result=f"Unable to list connections: {all_conns['_error']}",
            remediation="Requires Power Platform Admin role.",
            doc_link=f"{DOC_BASE}/servicenow",
        ))
        return results

    sn_conns = [c for c in all_conns if _is_servicenow_connection(c)]
    if not sn_conns:
        # Nothing to validate  SN-001 covers the "ServiceNow not installed"
        # case; staying silent here avoids duplicate noise.
        return results

    eusi_conns = [c for c in sn_conns if _is_entra_user_signin(c)]
    if not eusi_conns:
        # ServiceNow connections exist but use a different auth mode
        # (Basic, OAuth, etc.). SN-002 is specifically about the Entra
        # User Sign In federated-SSO failure mode  silently skip.
        return results

    healthy: list[dict] = []
    broken: list[tuple[dict, dict]] = []
    for c in eusi_conns:
        entry = _conn_status_entry(c)
        if entry.get("status") == "Connected":
            healthy.append(c)
        else:
            broken.append((c, entry))

    total = len(eusi_conns)
    federated_broken = [
        (c, e) for c, e in broken if _is_entra_token_failure(e)
    ]

    if not broken:
        results.append(CheckResult(
            checkpoint_id="SN-002", category="External Systems",
            priority=Priority.HIGH.value, status=Status.PASSED.value,
            description="ServiceNow Entra User Sign In connections",
            result=(
                f"{total} ServiceNow connection(s) using "
                f'"Microsoft Entra User Sign In"  all Connected'
            ),
            doc_link=f"{DOC_BASE}/servicenow",
        ))
        return results

    broken_names = ", ".join(_conn_display_name(c) for c, _ in broken)
    if healthy:
        status = Status.PASSED.value
        result_text = (
            f"{total} ServiceNow connection(s) using "
            f'"Microsoft Entra User Sign In"  '
            f"{len(healthy)} Connected, {len(broken)} in Error state "
            f"({broken_names})"
        )
    else:
        status = Status.FAILED.value
        result_text = (
            f"{total} ServiceNow connection(s) using "
            f'"Microsoft Entra User Sign In"  all in Error state '
            f"({broken_names})"
        )

    if federated_broken:
        remediation = (
            "Re-authenticate the affected ServiceNow connection(s) in Power "
            "Platform. If the failure persists, the federated identity "
            "flow between Microsoft Entra and your external IdP "
            "(PingFederate, ADFS, Okta, etc.) is not completing token "
            "exchange for the ServiceNow connector audience  verify the "
            "IdP is configured to issue tokens for the connector and "
            "that the user has an active session at the external IdP."
        )
    else:
        remediation = (
            "Re-authenticate the affected ServiceNow connection(s) in "
            "Power Platform."
        )

    results.append(CheckResult(
        checkpoint_id="SN-002", category="External Systems",
        priority=Priority.HIGH.value, status=status,
        description="ServiceNow Entra User Sign In connections",
        result=result_text,
        remediation=remediation,
        doc_link=f"{DOC_BASE}/servicenow",
    ))
    return results