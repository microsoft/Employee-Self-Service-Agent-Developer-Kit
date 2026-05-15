# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — Workday Deep Validation (WD-ENV-xxx, WD-CONN-xxx, WD-FLOW-xxx, WD-WF-xxx)

Validates Workday environment variables, connection references, flow status,
and tests all 17 ESS SOAP workflows against the actual Workday API.

The SOAP tests reuse the Kit's Workday MCP client (src/mcp/workday/client.py)
or, when running standalone, build SOAP envelopes directly with httpx.
"""

import getpass
import json
import os
import sys
from xml.sax.saxutils import escape as xml_escape

# Use defusedxml everywhere we parse SOAP responses. Workday talks to us over
# the public internet via WS-Security; treat every response as untrusted, even
# the success path. defusedxml.ElementTree.ParseError is a subclass of stdlib
# ET.ParseError, so existing except-handlers still catch malformed XML, but
# attack-path constructs (entity expansion, external references, DTDs) raise
# DefusedXmlException subclasses instead - those need to be caught too or a
# hostile Workday payload would propagate as an unhandled exception out of
# FlightCheck instead of falling through to the structured "unparseable XML"
# result path.
from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

from ..runner import CheckResult, Status, Priority

DOC_BASE = "https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service"

# The 3 critical Dataverse environment variables for Workday
ENV_VARS = {
    "EmployeeContextRequestAccountName": {
        "id": "WD-ENV-001",
        "critical": True,
        "default": None,  # Must be manually set
        "description": "ISU account name for RaaS",
    },
    "EmployeeContextRequestReportName": {
        "id": "WD-ENV-002",
        "critical": False,
        "default": "WD User Context",
        "description": "RaaS report name",
    },
    "EmployeeContextRequestReportInstanceName": {
        "id": "WD-ENV-003",
        "critical": False,
        "default": "Report2",
        "description": "Report instance name",
    },
}

# The 17 ESS Workday workflow definitions (ported from Test-WorkdayWorkflows.ps1)
WORKFLOWS = [
    # 15 Read workflows
    {
        "name": "Employee ID", "service": "Human_Resources", "type": "Read",
        "response_group": "<bsvc:Include_Reference>true</bsvc:Include_Reference>",
        "xpath": ".//*[@*='Employee_ID']",
    },
    {
        "name": "Company Code", "service": "Human_Resources", "type": "Read",
        "response_group": "<bsvc:Include_Organizations>true</bsvc:Include_Organizations>",
        "xpath": ".//{urn:com.workday/bsvc}Organization_Data",
    },
    {
        "name": "Cost Center", "service": "Human_Resources", "type": "Read",
        "response_group": "<bsvc:Include_Organizations>true</bsvc:Include_Organizations>",
        "xpath": ".//{urn:com.workday/bsvc}Organization_Type_Reference",
    },
    {
        "name": "Hire Date", "service": "Human_Resources", "type": "Read",
        "response_group": "<bsvc:Include_Employment_Information>true</bsvc:Include_Employment_Information>",
        "xpath": ".//{urn:com.workday/bsvc}Hire_Date",
    },
    {
        "name": "Employment Info", "service": "Human_Resources", "type": "Read",
        "response_group": "<bsvc:Include_Employment_Information>true</bsvc:Include_Employment_Information>",
        "xpath": ".//{urn:com.workday/bsvc}Employment_Data",
    },
    {
        "name": "Position Number", "service": "Human_Resources", "type": "Read",
        "response_group": "<bsvc:Include_Employment_Information>true</bsvc:Include_Employment_Information>",
        "xpath": ".//{urn:com.workday/bsvc}Position_ID",
    },
    {
        "name": "Service Anniversary", "service": "Human_Resources", "type": "Read",
        "response_group": "<bsvc:Include_Employment_Information>true</bsvc:Include_Employment_Information>",
        "xpath": ".//{urn:com.workday/bsvc}Continuous_Service_Date",
    },
    {
        "name": "National IDs", "service": "Human_Resources", "type": "Read", "pii": True,
        "response_group": "<bsvc:Include_Personal_Information>true</bsvc:Include_Personal_Information>",
        "xpath": ".//{urn:com.workday/bsvc}National_ID",
    },
    {
        "name": "Passports", "service": "Human_Resources", "type": "Read", "pii": True,
        "response_group": "<bsvc:Include_Personal_Information>true</bsvc:Include_Personal_Information>",
        "xpath": ".//{urn:com.workday/bsvc}Passport_ID",
    },
    {
        "name": "Visas", "service": "Human_Resources", "type": "Read", "pii": True,
        "response_group": "<bsvc:Include_Personal_Information>true</bsvc:Include_Personal_Information>",
        "xpath": ".//{urn:com.workday/bsvc}Visa_ID",
    },
    {
        "name": "Language Info", "service": "Human_Resources", "type": "Read",
        "response_group": "<bsvc:Include_Qualifications>true</bsvc:Include_Qualifications>",
        "xpath": ".//{urn:com.workday/bsvc}Language",
    },
    {
        "name": "Certifications", "service": "Human_Resources", "type": "Read",
        "response_group": "<bsvc:Include_Qualifications>true</bsvc:Include_Qualifications>",
        "xpath": ".//{urn:com.workday/bsvc}Certification",
    },
    {
        "name": "Base Compensation", "service": "Compensation", "type": "Read",
        "custom_operation": True,
        "xpath": ".//{urn:com.workday/bsvc}Compensation",
    },
    {
        "name": "Compensation Ratio", "service": "Compensation", "type": "Read",
        "custom_operation": True,
        "xpath": ".//{urn:com.workday/bsvc}Compa_Ratio",
    },
    {
        "name": "Emergency Contact", "service": "Human_Resources", "type": "Read", "pii": True,
        "response_group": "<bsvc:Include_Personal_Information>true</bsvc:Include_Personal_Information>",
        "xpath": ".//{urn:com.workday/bsvc}Emergency_Contact",
    },
    # 2 Write workflows (test capability only, no actual changes)
    {
        "name": "Update Email", "service": "Human_Resources", "type": "Write",
    },
    {
        "name": "Update Phone", "service": "Human_Resources", "type": "Write",
    },
]


def run_workday_checks(runner) -> list[CheckResult]:
    """Execute Workday-specific deep validation.

    Only runs if Workday flows were detected by external_systems checks.
    """
    results: list[CheckResult] = []

    # Skip if no Workday flows detected
    wd_flows = getattr(runner, "_workday_flows", [])
    if not wd_flows:
        return results

    print("\n  Running Workday deep validation...")

    # --- Environment Variables ---
    results.extend(_check_env_vars(runner))

    # --- ISU username vs Entra UPN format alignment ---
    results.extend(_check_isu_username_format(runner))

    # --- Connection References ---
    results.extend(_check_connections(runner))

    # --- Flow Status ---
    results.extend(_check_flow_status(runner, wd_flows))

    # --- SOAP Workflow Tests (only if Workday MCP creds available) ---
    results.extend(_check_workflows(runner))

    return results


def _check_env_vars(runner) -> list[CheckResult]:
    """Validate Workday environment variables in Dataverse."""
    results = []
    env_url = runner.env_url
    dv_token = runner.dv_token

    if not env_url or not dv_token:
        results.append(CheckResult(
            checkpoint_id="WD-ENV-001", category="Workday",
            priority=Priority.CRITICAL.value, status=Status.SKIPPED.value,
            description="Workday environment variables",
            result="Dataverse token not available — skipping env var checks",
        ))
        return results

    try:
        # Import Dataverse query helper from auth.py
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
        from auth import query_all

        # Query environment variable definitions and values
        defs = query_all(
            env_url, dv_token,
            "environmentvariabledefinitions",
            "displayname,schemaname,environmentvariabledefinitionid",
            filter_expr="contains(schemaname,'EmployeeContext')",
        )
        vals = query_all(
            env_url, dv_token,
            "environmentvariablevalues",
            "value,schemaname,_environmentvariabledefinitionid_value",
        )

        # Build lookup of var name -> value
        def_map = {d["environmentvariabledefinitionid"]: d for d in defs}
        val_map = {}
        for v in vals:
            def_id = v.get("_environmentvariabledefinitionid_value")
            if def_id in def_map:
                schema = def_map[def_id].get("schemaname", "")
                val_map[schema] = v.get("value", "")

        for var_name, meta in ENV_VARS.items():
            actual_value = None
            # Find by partial match on schema name
            for k, v in val_map.items():
                if var_name.lower() in k.lower():
                    actual_value = v
                    break

            if actual_value:
                results.append(CheckResult(
                    checkpoint_id=meta["id"], category="Workday",
                    priority=Priority.CRITICAL.value if meta["critical"] else Priority.HIGH.value,
                    status=Status.PASSED.value,
                    description=meta["description"],
                    result=f"Set to: {actual_value}",
                    doc_link=f"{DOC_BASE}/workday#step-4-environment-variables",
                ))
            elif meta["critical"]:
                results.append(CheckResult(
                    checkpoint_id=meta["id"], category="Workday",
                    priority=Priority.CRITICAL.value, status=Status.FAILED.value,
                    description=meta["description"],
                    result="Not configured — this must be set manually",
                    remediation=f"Set {var_name} in [Power Platform admin center](https://admin.powerplatform.microsoft.com) or run `/connect workday`.",
                    doc_link=f"{DOC_BASE}/workday#step-4-environment-variables",
                ))
            else:
                results.append(CheckResult(
                    checkpoint_id=meta["id"], category="Workday",
                    priority=Priority.HIGH.value, status=Status.PASSED.value,
                    description=meta["description"],
                    result=f"Using default: {meta['default']}",
                    doc_link=f"{DOC_BASE}/workday#step-4-environment-variables",
                ))
    except Exception as e:
        results.append(CheckResult(
            checkpoint_id="WD-ENV-001", category="Workday",
            priority=Priority.CRITICAL.value, status=Status.WARNING.value,
            description="Workday environment variables",
            result=f"Unable to check: {e}",
        ))

    return results


def _check_isu_username_format(runner) -> list[CheckResult]:
    """WD-ENV-101 — Workday ISU username alignment with Entra UPN format.

    Pulls the configured ISU username from
    `EmployeeContextRequestAccountName` (Dataverse env var) and compares
    its shape against the tenant's verified Entra domains. Federated
    tenants (Okta / Ping) frequently leave the ISU username in a legacy
    short-employee-id format that does not match the UPN claim ESS sends
    on each request, which prevents Workday from matching the request to
    a Worker.

    Heuristics:
      * No `@` in ISU → WARNING (legacy short-id format — the
        most-cited misconfiguration root cause). Reported even when
        Graph is unavailable, because this signal needs only the
        Dataverse env var.
      * `@` present but the domain part is not in the tenant's
        verified-domains list → WARNING (could be legitimate cross-tenant
        federation; surface for the operator to confirm).
      * `<localpart>@<verified-domain>` → PASSED.

    A scoped per-Worker comparison (Get_Workers User_ID == Entra UPN
    for a sample of expected ESS users) is intentionally out of scope
    for this check — it requires Workday SOAP credentials and a curated
    sample list, which `_check_workflows` already exercises against
    `WORKDAY_TEST_EMPLOYEE_ID`. Wire a future `WD-WF-NNN` against that
    surface when those inputs are formalised; this checkpoint covers
    the static format-alignment gap that can be detected without ISU
    credentials.
    """
    results: list[CheckResult] = []
    env_url = runner.env_url
    dv_token = runner.dv_token

    if not env_url or not dv_token:
        results.append(CheckResult(
            checkpoint_id="WD-ENV-101", category="Workday",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description="ISU username vs Entra UPN format alignment",
            result="Dataverse token not available — skipping ISU format check",
        ))
        return results

    # ── Step 1: read the ISU env var from Dataverse. We do this FIRST,
    # before consulting Graph, because the no-`@` legacy-format detection
    # (the most-cited misconfiguration root cause — the BCBSA scenario)
    # can be reported off the Dataverse value alone.
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
        from auth import query_all

        defs = query_all(
            env_url, dv_token,
            "environmentvariabledefinitions",
            "displayname,schemaname,environmentvariabledefinitionid",
            filter_expr="contains(schemaname,'EmployeeContext')",
        )
        vals = query_all(
            env_url, dv_token,
            "environmentvariablevalues",
            "value,schemaname,_environmentvariabledefinitionid_value",
        )

        def_map = {d["environmentvariabledefinitionid"]: d for d in defs}
        isu_value: str | None = None
        for v in vals:
            def_id = v.get("_environmentvariabledefinitionid_value")
            if def_id not in def_map:
                continue
            schema = def_map[def_id].get("schemaname", "")
            if "EmployeeContextRequestAccountName".lower() in schema.lower():
                isu_value = v.get("value", "") or None
                break
    except Exception as e:
        results.append(CheckResult(
            checkpoint_id="WD-ENV-101", category="Workday",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description="ISU username vs Entra UPN format alignment",
            result=f"Unable to read ISU env var from Dataverse: {e}",
        ))
        return results

    if not isu_value:
        # WD-ENV-001 already covers the missing-value remediation; skip
        # here to avoid double-reporting the same root cause.
        results.append(CheckResult(
            checkpoint_id="WD-ENV-101", category="Workday",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description="ISU username vs Entra UPN format alignment",
            result="ISU env var not set — see WD-ENV-001 for the underlying gap",
            doc_link=f"{DOC_BASE}/workday#step-4-environment-variables",
        ))
        return results

    # ── Step 2: legacy short-id detection (no Graph required). This is
    # the most decisive failure mode and must be reported even when
    # Graph auth has failed.
    if "@" not in isu_value:
        results.append(CheckResult(
            checkpoint_id="WD-ENV-101", category="Workday",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description="ISU username vs Entra UPN format alignment",
            result=(
                f"ISU username '{isu_value}' does not contain '@' — does not match "
                f"the Entra UPN format ESS sends on each request"
            ),
            remediation=(
                "If the tenant federates identity (Okta, Ping, ADFS), set the "
                "Workday ISU username to the Entra UPN format (e.g. "
                "isu@<verified-tenant-domain>) so Workday can match incoming "
                "ESS requests to a Worker. Update "
                "`EmployeeContextRequestAccountName` in [Power Platform admin "
                "center](https://admin.powerplatform.microsoft.com)."
            ),
            doc_link=f"{DOC_BASE}/workday#step-4-environment-variables",
        ))
        return results

    # ── Step 3: verified-domain comparison (requires Graph). If Graph
    # isn't available, we can't do this comparison — surface that as a
    # SKIP so the operator knows the deeper check wasn't performed.
    graph = getattr(runner, "graph", None)
    if not graph:
        results.append(CheckResult(
            checkpoint_id="WD-ENV-101", category="Workday",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description="ISU username vs Entra UPN format alignment",
            result=(
                f"ISU username '{isu_value}' is in UPN-style format but Microsoft "
                f"Graph client is unavailable — cannot verify the domain matches "
                f"a verified tenant domain"
            ),
            remediation="Re-run flightcheck and complete the Microsoft Graph sign-in prompt.",
            doc_link=f"{DOC_BASE}/workday#step-4-environment-variables",
        ))
        return results

    try:
        org = graph.get_organization()
    except Exception as e:
        results.append(CheckResult(
            checkpoint_id="WD-ENV-101", category="Workday",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description="ISU username vs Entra UPN format alignment",
            result=f"Unable to fetch tenant verified domains from Graph: {e}",
            remediation="Ensure permissions to read Organization info via Graph (Organization.Read.All).",
        ))
        return results

    if not isinstance(org, dict) or not org:
        results.append(CheckResult(
            checkpoint_id="WD-ENV-101", category="Workday",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description="ISU username vs Entra UPN format alignment",
            result=(
                "Graph /organization returned no tenant record — likely "
                "insufficient permissions"
            ),
            remediation="Ensure permissions to read Organization info via Graph (Organization.Read.All).",
        ))
        return results

    verified = [
        (d.get("name") or "").lower()
        for d in org.get("verifiedDomains", [])
        if d.get("name")
    ]

    domain = isu_value.rsplit("@", 1)[1].lower()
    if not verified:
        results.append(CheckResult(
            checkpoint_id="WD-ENV-101", category="Workday",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description="ISU username vs Entra UPN format alignment",
            result=(
                f"ISU username '{isu_value}' contains '@{domain}' but Graph "
                f"returned no verified domains — cannot confirm alignment"
            ),
            remediation="Ensure permissions to read Organization info via Graph (Organization.Read.All).",
            doc_link=f"{DOC_BASE}/workday#step-4-environment-variables",
        ))
        return results

    if domain in verified:
        results.append(CheckResult(
            checkpoint_id="WD-ENV-101", category="Workday",
            priority=Priority.HIGH.value, status=Status.PASSED.value,
            description="ISU username vs Entra UPN format alignment",
            result=f"ISU username '{isu_value}' matches verified tenant domain '{domain}'",
            doc_link=f"{DOC_BASE}/workday#step-4-environment-variables",
        ))
    else:
        results.append(CheckResult(
            checkpoint_id="WD-ENV-101", category="Workday",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description="ISU username vs Entra UPN format alignment",
            result=(
                f"ISU username domain '{domain}' is not in the tenant's verified "
                f"domains ({', '.join(sorted(verified))}) — Workday may fail to "
                f"match ESS requests to a Worker if ESS sends UPN claims from a "
                f"verified domain"
            ),
            remediation=(
                "Confirm the ISU username matches the UPN claim ESS sends. If "
                "the tenant uses federated identity, update "
                "`EmployeeContextRequestAccountName` to use a verified-domain "
                "UPN, or document the cross-tenant scenario for the operator."
            ),
            doc_link=f"{DOC_BASE}/workday#step-4-environment-variables",
        ))

    return results


def _check_connections(runner) -> list[CheckResult]:
    """Validate Workday connection references in Power Platform."""
    results = []
    pp = runner.pp_admin
    env_id = runner.env_id

    if not env_id:
        return results

    try:
        all_conns = pp.get_connections(env_id)
        if isinstance(all_conns, dict) and "_error" in all_conns:
            results.append(CheckResult(
                checkpoint_id="WD-CONN-001", category="Workday",
                priority=Priority.HIGH.value, status=Status.WARNING.value,
                description="Workday connections",
                result=f"Unable to list connections: {all_conns['_error']}",
                remediation="Requires Power Platform Admin role.",
            ))
            return results

        wd_conns = [
            c for c in all_conns
            if "workday" in (
                c.get("properties", {}).get("apiId", "") +
                c.get("properties", {}).get("displayName", "")
            ).lower()
        ]

        if wd_conns:
            connected = [
                c for c in wd_conns
                if _get_conn_status(c) == "Connected"
            ]
            errored = [
                c for c in wd_conns
                if _get_conn_status(c) != "Connected"
            ]

            results.append(CheckResult(
                checkpoint_id="WD-CONN-001", category="Workday",
                priority=Priority.HIGH.value,
                status=Status.PASSED.value if connected else Status.FAILED.value,
                description="Workday connections",
                result=f"{len(wd_conns)} total — {len(connected)} connected, {len(errored)} errored",
                remediation="Re-authenticate errored connections in Power Platform." if errored else "",
                doc_link=f"{DOC_BASE}/workday#step-3-connection-references",
            ))

            # Detail each connection
            for i, c in enumerate(wd_conns):
                props = c.get("properties", {})
                name = props.get("displayName", f"Connection {i+1}")
                status = _get_conn_status(c)
                cid = f"WD-CONN-{i+2:03d}"
                results.append(CheckResult(
                    checkpoint_id=cid, category="Workday",
                    priority=Priority.HIGH.value,
                    status=Status.PASSED.value if status == "Connected" else Status.FAILED.value,
                    description=f"Connection: {name}",
                    result=f"Status: {status}",
                    remediation=f"Re-authenticate '{name}' in Power Platform." if status != "Connected" else "",
                ))
        else:
            results.append(CheckResult(
                checkpoint_id="WD-CONN-001", category="Workday",
                priority=Priority.HIGH.value, status=Status.NOT_CONFIGURED.value,
                description="Workday connections",
                result="No Workday connections found",
                remediation="Configure Workday SOAP connections in the environment.",
                doc_link=f"{DOC_BASE}/workday#step-3-connection-references",
            ))
    except Exception as e:
        results.append(CheckResult(
            checkpoint_id="WD-CONN-001", category="Workday",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description="Workday connections",
            result=f"Unable to check: {e}",
        ))

    return results


def _get_conn_status(conn: dict) -> str:
    """Extract connection status from the BAP API response."""
    statuses = conn.get("properties", {}).get("statuses", [])
    if isinstance(statuses, list) and statuses:
        return statuses[0].get("status", "Unknown")
    return "Unknown"


def _check_flow_status(runner, wd_flows: list) -> list[CheckResult]:
    """Check whether Workday flows are enabled."""
    results = []

    enabled = 0
    disabled = 0
    for i, f in enumerate(wd_flows):
        props = f.get("properties", {})
        name = props.get("displayName", f.get("displayName", f"Flow {i+1}"))
        state = props.get("state", "")
        is_on = state.lower() in ("started", "on", "enabled")
        cid = f"WD-FLOW-{i+1:03d}"

        if is_on:
            enabled += 1
        else:
            disabled += 1

        results.append(CheckResult(
            checkpoint_id=cid, category="Workday",
            priority=Priority.HIGH.value,
            status=Status.PASSED.value if is_on else Status.FAILED.value,
            description=f"Flow: {name}",
            result=f"State: {'Enabled' if is_on else 'Disabled'}",
            remediation=f"Enable '{name}' in Power Automate." if not is_on else "",
            doc_link=f"{DOC_BASE}/workday#topics",
        ))

    return results


def _check_workflows(runner) -> list[CheckResult]:
    """Test all 17 Workday SOAP workflows.

    Resolves credentials from multiple sources (in priority order):
      1. Environment variables (if already set, e.g. from a parent process)
      2. .vscode/mcp.json (base URL + tenant are stored as plain strings)
      3. .local/config.json -> connections.Workday (tenant, base URL)
      4. Interactive prompt (username + password only - never cached to disk)
      5. .local/config.json -> workdayTestEmployeeId (cached after first prompt)
    """
    results = []

    # --- Resolve non-sensitive metadata first (URL, tenant, employee). ---
    # CodeQL clear-text logging rule taints every output of any function that
    # also returns sensitive data. Splitting metadata from credentials keeps
    # the metadata path off the taint graph so we can safely print the tenant
    # name in status messages.
    wd_base_url, wd_tenant, test_employee = _resolve_workday_metadata(runner)

    if not wd_base_url or not wd_tenant:
        results.append(CheckResult(
            checkpoint_id="WD-WF-000", category="Workday Workflows",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description="Workday SOAP workflow tests",
            result="Workday not configured - skipping 17 workflow tests",
            remediation="Run /connect workday first, then re-run /flightcheck.",
        ))
        return results

    if not test_employee:
        results.append(CheckResult(
            checkpoint_id="WD-WF-000", category="Workday Workflows",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description="Workday SOAP workflow tests",
            result="No test employee ID provided - skipping workflow tests",
            remediation="Re-run flightcheck and enter a test employee ID when prompted.",
        ))
        return results

    # Safe to log here - tenant is from the metadata-only resolver, but we
    # do not interpolate it into the message because CodeQL classifies any
    # WORKDAY_* env var as private (clear-text logging rule).
    print("  Testing 17 Workday workflows...")

    try:
        import httpx  # noqa: F401  (used inside _soap_call)
    except ImportError:
        results.append(CheckResult(
            checkpoint_id="WD-WF-000", category="Workday Workflows",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description="Workday SOAP workflow tests",
            result="httpx not installed - skipping",
            remediation="pip install httpx",
        ))
        return results

    # --- Now resolve credentials. From this point on the local scope holds
    # sensitive values; do not add print/log statements that reference any
    # local variable. ---
    wd_username, wd_password = _resolve_workday_credentials(runner, wd_tenant)
    if not wd_username or not wd_password:
        results.append(CheckResult(
            checkpoint_id="WD-WF-000", category="Workday Workflows",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description="Workday SOAP workflow tests",
            result="Workday ISU credentials not provided - skipping workflow tests",
            remediation=(
                "Re-run flightcheck; when prompted, enter your ISU "
                "username and password to test the 17 workflows."
            ),
        ))
        return results

    import datetime
    effective_date = datetime.date.today().isoformat()

    for i, wf in enumerate(WORKFLOWS):
        cid = f"WD-WF-{i+1:03d}"
        pii_tag = " [PII]" if wf.get("pii") else ""
        desc = f"Workflow: {wf['name']}{pii_tag} ({wf['type']})"

        if wf["type"] == "Write":
            # Write tests — check access to Change_Work_Contact_Information
            body = _build_write_test_body(test_employee)
            result = _soap_call(
                wd_base_url, wd_tenant, wd_username, wd_password,
                wf["service"], body,
            )
            if result["success"] or "permission" not in result.get("error", "").lower():
                results.append(CheckResult(
                    checkpoint_id=cid, category="Workday Workflows",
                    priority=Priority.HIGH.value, status=Status.PASSED.value,
                    description=desc, result="API accessible",
                ))
            else:
                results.append(CheckResult(
                    checkpoint_id=cid, category="Workday Workflows",
                    priority=Priority.HIGH.value, status=Status.FAILED.value,
                    description=desc, result="Permission denied",
                    remediation="Ask Workday Admin to grant Contact Information security domain.",
                ))
            continue

        # Read tests
        if wf.get("custom_operation"):
            body = _build_compensation_body(test_employee)
        else:
            body = _build_get_workers_body(test_employee, effective_date, wf["response_group"])

        result = _soap_call(
            wd_base_url, wd_tenant, wd_username, wd_password,
            wf["service"], body,
        )

        if result["success"]:
            # Check XPath for expected data
            try:
                root = ET.fromstring(result["response"])
                found = root.findall(wf["xpath"])
                if found:
                    results.append(CheckResult(
                        checkpoint_id=cid, category="Workday Workflows",
                        priority=Priority.HIGH.value, status=Status.PASSED.value,
                        description=desc, result="Data retrieved",
                    ))
                else:
                    results.append(CheckResult(
                        checkpoint_id=cid, category="Workday Workflows",
                        priority=Priority.HIGH.value, status=Status.PASSED.value,
                        description=desc,
                        result="API accessible (no data for this employee)",
                    ))
            except (ET.ParseError, DefusedXmlException):
                # ET.ParseError = malformed XML.
                # DefusedXmlException = attack-path construct rejected by
                # defusedxml (EntitiesForbidden, ExternalReferenceForbidden,
                # DTDForbidden, NotSupportedError). Both should fall through
                # to the structured "unparseable XML" result instead of
                # surfacing as an unhandled traceback to the user.
                results.append(CheckResult(
                    checkpoint_id=cid, category="Workday Workflows",
                    priority=Priority.HIGH.value, status=Status.PASSED.value,
                    description=desc, result="API responded (unparseable XML)",
                ))
        else:
            error = result.get("error", "Unknown")
            if any(k in error.lower() for k in ("permission", "unauthorized", "not authorized")):
                results.append(CheckResult(
                    checkpoint_id=cid, category="Workday Workflows",
                    priority=Priority.HIGH.value, status=Status.FAILED.value,
                    description=desc, result="Permission denied",
                    remediation="Ask Workday Admin to grant required security domain.",
                ))
            else:
                results.append(CheckResult(
                    checkpoint_id=cid, category="Workday Workflows",
                    priority=Priority.HIGH.value, status=Status.FAILED.value,
                    description=desc, result=f"Error: {error[:100]}",
                ))

    return results


# ---- Credential Resolution ----

def _resolve_workday_metadata(runner) -> tuple[str, str, str]:
    """Resolve non-sensitive Workday metadata: (base_url, tenant, test_employee_id).

    Deliberately split from credential resolution so CodeQL's data-flow
    analysis does not taint the metadata via tuple-unpacking with sensitive
    return values (clear-text logging rule).
    """
    base_url = os.environ.get("WORKDAY_BASE_URL", "")
    tenant = os.environ.get("WORKDAY_TENANT", "")
    test_employee = os.environ.get("WORKDAY_TEST_EMPLOYEE_ID", "")

    # --- Source 2: .vscode/mcp.json (non-secret values only) ---
    if not base_url or not tenant:
        mcp_env = _read_mcp_workday_env()
        if not base_url:
            base_url = mcp_env.get("WORKDAY_BASE_URL", "")
        if not tenant:
            tenant = mcp_env.get("WORKDAY_TENANT", "")

    # --- Source 3: .local/config.json -> connections.Workday ---
    config = getattr(runner, "config", {})
    wd_config = config.get("connections", {}).get("Workday", {})
    if not base_url:
        base_url = wd_config.get("baseUrl", "")
    if not tenant:
        tenant = wd_config.get("tenant", "")
    if not test_employee:
        test_employee = config.get("workdayTestEmployeeId", "")

    # --- Source 5: Test employee ID (prompt + cache in config) ---
    if not test_employee and sys.stdin.isatty():
        test_employee = input("  Test Employee ID (e.g. 21508): ").strip()
        if test_employee:
            _cache_test_employee_id(test_employee)

    return base_url, tenant, test_employee


def _resolve_workday_credentials(runner, tenant: str) -> tuple[str, str]:
    """Resolve sensitive Workday credentials: (username, password).

    Reads from env first, then prompts interactively. Never returns metadata,
    so CodeQL won't propagate password taint into URL/tenant variables in
    the caller. Caller MUST NOT introduce print/log statements that
    reference local variables after calling this function.
    """
    username = os.environ.get("WORKDAY_USERNAME", "")
    password = os.environ.get("WORKDAY_PASSWORD", "")

    # --- Source 4: Interactive prompt for secrets ---
    if (not username or not password) and sys.stdin.isatty():
        print("\n  Workday SOAP workflow tests need ISU credentials.")
        print("  (Credentials are used for this run only - never saved to disk)\n")
        if not username:
            username = input("  ISU Username (without @tenant): ").strip()
            if username and "@" not in username:
                # Tenant suffix appended via concatenation - never logged.
                username = username + "@" + tenant
        if not password:
            password = getpass.getpass("  ISU Password: ")

    return username, password


def _resolve_workday_creds(runner) -> tuple[str, str, str, str, str]:
    """Compatibility shim: combine metadata + credentials in the legacy
    5-tuple shape. Prefer the split _resolve_workday_metadata /
    _resolve_workday_credentials pair in new code; this shim exists for
    callers (or tests) that still expect the old signature.
    """
    base_url, tenant, test_employee = _resolve_workday_metadata(runner)
    if not base_url or not tenant:
        return "", "", "", "", ""
    username, password = _resolve_workday_credentials(runner, tenant)
    return base_url, tenant, username, password, test_employee


def _read_mcp_workday_env() -> dict:
    """Read non-secret Workday env vars from .vscode/mcp.json."""
    mcp_path = os.path.join(".vscode", "mcp.json")
    if not os.path.exists(mcp_path):
        return {}

    try:
        with open(mcp_path, "r", encoding="utf-8") as f:
            mcp = json.load(f)

        servers = mcp.get("servers", {})
        wd_server = servers.get("Workday", {})
        env = wd_server.get("env", {})

        # Only return values that are actual strings (not ${input:...} refs)
        result = {}
        for key in ("WORKDAY_BASE_URL", "WORKDAY_TENANT"):
            val = env.get(key, "")
            if val and not val.startswith("${"):
                result[key] = val
        return result
    except (json.JSONDecodeError, OSError):
        return {}


def _cache_test_employee_id(employee_id: str):
    """Save the test employee ID to .local/config.json for future runs."""
    config_path = os.path.join(".local", "config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        config["workdayTestEmployeeId"] = employee_id
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
    except (OSError, json.JSONDecodeError):
        pass  # Non-critical — they'll just be prompted again next time


# ---- SOAP Envelope Builders (ported from Test-WorkdayWorkflows.ps1) ----

BSVC = "urn:com.workday/bsvc"
SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
WSSE = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"


def _build_soap_envelope(username: str, password: str, body_xml: str) -> str:
    # Escape username/password so XML special characters in credentials
    # (notably & in passwords) do not produce malformed XML.
    safe_user = xml_escape(username)
    safe_pass = xml_escape(password)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<env:Envelope xmlns:env="{SOAP}" xmlns:bsvc="{BSVC}">
  <env:Header>
    <wsse:Security env:mustUnderstand="1" xmlns:wsse="{WSSE}">
      <wsse:UsernameToken>
        <wsse:Username>{safe_user}</wsse:Username>
        <wsse:Password>{safe_pass}</wsse:Password>
      </wsse:UsernameToken>
    </wsse:Security>
  </env:Header>
  <env:Body>{body_xml}</env:Body>
</env:Envelope>"""


def _build_get_workers_body(employee_id: str, effective_date: str, response_group: str) -> str:
    # Defense-in-depth: escape the values that come from .local/config.json /
    # env vars. response_group is intentionally left raw - it is a static XML
    # fragment from the WORKFLOWS table by design (e.g.,
    # '<bsvc:Include_Reference>true</bsvc:Include_Reference>'); escaping it
    # would corrupt the envelope.
    employee_id = xml_escape(employee_id)
    effective_date = xml_escape(effective_date)
    return f"""
<bsvc:Get_Workers_Request xmlns:bsvc="{BSVC}" bsvc:version="v42.0">
  <bsvc:Request_References bsvc:Skip_Non_Existing_Instances="false">
    <bsvc:Worker_Reference>
      <bsvc:ID bsvc:type="Employee_ID">{employee_id}</bsvc:ID>
    </bsvc:Worker_Reference>
  </bsvc:Request_References>
  <bsvc:Response_Filter>
    <bsvc:As_Of_Effective_Date>{effective_date}</bsvc:As_Of_Effective_Date>
  </bsvc:Response_Filter>
  <bsvc:Response_Group>
    {response_group}
  </bsvc:Response_Group>
</bsvc:Get_Workers_Request>"""


def _build_compensation_body(employee_id: str) -> str:
    employee_id = xml_escape(employee_id)
    return f"""
<bsvc:Get_Compensation_Plans_Request xmlns:bsvc="{BSVC}" bsvc:version="v42.0">
  <bsvc:Request_References>
    <bsvc:Compensation_Plan_Reference>
      <bsvc:ID bsvc:type="Employee_ID">{employee_id}</bsvc:ID>
    </bsvc:Compensation_Plan_Reference>
  </bsvc:Request_References>
</bsvc:Get_Compensation_Plans_Request>"""


def _build_write_test_body(employee_id: str) -> str:
    employee_id = xml_escape(employee_id)
    return f"""
<bsvc:Get_Change_Work_Contact_Information_Event_Request xmlns:bsvc="{BSVC}" bsvc:version="v42.0">
  <bsvc:Request_References>
    <bsvc:Change_Work_Contact_Information_Event_Reference>
      <bsvc:ID bsvc:type="Employee_ID">{employee_id}</bsvc:ID>
    </bsvc:Change_Work_Contact_Information_Event_Reference>
  </bsvc:Request_References>
</bsvc:Get_Change_Work_Contact_Information_Event_Request>"""


def _redact_ws_security(xml_text: str) -> str:
    """Remove any WS-Security UsernameToken block from XML before logging.

    Workday occasionally echoes parts of the request envelope into responses
    (especially in error responses). The envelope contains the ISU password
    in the wsse:UsernameToken element. Strip the entire Security header
    block before any logging or return-to-caller path so the password
    cannot leak into FlightCheck reports or error messages.
    """
    if not xml_text or 'wsse:Security' not in xml_text and 'UsernameToken' not in xml_text:
        return xml_text
    import re
    # Drop any <*:Security>...</*:Security> block (any namespace prefix).
    xml_text = re.sub(
        r'<[^/>]*:?Security[^>]*>.*?</[^>]*:?Security>',
        '<Security>[REDACTED]</Security>',
        xml_text,
        flags=re.DOTALL,
    )
    # Belt-and-suspenders: also strip any standalone UsernameToken or Password tag.
    xml_text = re.sub(
        r'<[^/>]*:?UsernameToken[^>]*>.*?</[^>]*:?UsernameToken>',
        '<UsernameToken>[REDACTED]</UsernameToken>',
        xml_text,
        flags=re.DOTALL,
    )
    xml_text = re.sub(
        r'<[^/>]*:?Password[^>]*>.*?</[^>]*:?Password>',
        '<Password>[REDACTED]</Password>',
        xml_text,
    )
    return xml_text


def _summarize_soap_error(status_code: int, resp_text: str) -> str:
    """Extract a safe-to-log summary from an error SOAP response.

    Returns the SOAP faultstring if present (Workday faultstrings describe
    the error condition without echoing the request body), otherwise just
    the HTTP status code. Never returns raw response text - error responses
    can include echoed request content that contains the WS-Security
    UsernameToken (CodeQL: clear-text logging of sensitive information).
    """
    if not resp_text:
        return f"HTTP {status_code}"
    try:
        root = ET.fromstring(resp_text)
        # SOAP 1.1 faultstring (no namespace) and SOAP 1.2 fault Reason/Text
        for path in ('.//{*}faultstring', './/{*}Reason/{*}Text', './/faultstring'):
            el = root.find(path)
            if el is not None and el.text:
                return f"HTTP {status_code}: {el.text.strip()[:200]}"
    except Exception:
        pass
    return f"HTTP {status_code}"


def _soap_call(
    base_url: str, tenant: str, username: str, password: str,
    service: str, body_xml: str,
) -> dict:
    """Make a synchronous SOAP call to Workday. Returns {success, response|error}.

    Both the response and error returns are scrubbed of WS-Security
    UsernameToken content before being handed back to the caller, so the
    ISU password cannot end up in FlightCheck reports or stdout.
    """
    import httpx

    url = f"{base_url}/{tenant}/{service}/v42.0"
    full_user = username if "@" in username else f"{username}@{tenant}"
    envelope = _build_soap_envelope(full_user, password, body_xml)

    try:
        with httpx.Client(timeout=30.0, follow_redirects=False) as client:
            resp = client.post(
                url,
                content=envelope,
                headers={"Content-Type": "text/xml; charset=utf-8"},
            )
            if resp.status_code < 400:
                # Even on success, scrub WS-Security in case Workday echoes it
                # (defense-in-depth - the success body normally doesn't include it).
                return {"success": True, "response": _redact_ws_security(resp.text)}
            return {
                "success": False,
                "error": _summarize_soap_error(resp.status_code, resp.text),
            }
    except Exception as e:
        # Don't echo str(e) verbatim if it looks like it might contain the URL
        # with embedded credentials; httpx errors don't normally include them
        # but be cautious.
        msg = str(e)
        if password and password in msg:
            msg = msg.replace(password, '[REDACTED]')
        return {"success": False, "error": msg}
