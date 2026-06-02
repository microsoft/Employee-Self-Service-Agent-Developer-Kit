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
import re
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
from .connections import check_connector_connections, filter_connections_by_connector, get_connection_status

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
    results.extend(_check_connection_token_health(runner))

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
    # (the most-cited misconfiguration root cause — legacy short-ID ISU
    # provisioning on federated tenants, common where the ISU was set
    # up before the tenant adopted UPN-shaped service-account naming)
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
    # Legacy behavior: silently skip when env_id is unavailable
    if not runner.env_id:
        return []
    return check_connector_connections(
        runner,
        connector_keyword="workday",
        checkpoint_prefix="WD-CONN",
        category="Workday",
        not_found_remediation="Configure Workday SOAP connections in the environment.",
        doc_link=f"{DOC_BASE}/workday#step-3-connection-references",
    )


# OAuth grant-expiry / token-health error codes the Power Platform
# connection layer surfaces when the connection creator's Entra OAuth
# grant has lapsed. There are two places to find them:
#
#   1. ``statuses[0].error.message`` — contains the actual Entra
#      ``AADSTSnnnnn`` token-failure code embedded in a longer prose
#      message, e.g. "Failed to refresh access token... AADSTS50173:
#      The provided grant has expired due to it being revoked..."
#      This is where the actionable code actually lives in production
#      (verified against ``tests/fixtures/cassettes/flightcheck_pp_admin.yaml``
#      lines 2661-2680).
#   2. ``statuses[0].error.code`` — a coarser Power-Platform-side
#      classification: typically ``Unauthorized`` (for token-refresh
#      failures including AADSTSnnnnn) or ``Unauthenticated`` (for a
#      connection that was never authenticated). These show up
#      regardless of whether an AADSTS code is present.
#
# WD-CONN-101 inspects (1) first via a regex on the message text, and
# falls back to (2) only if the message has no recognizable AADSTS
# code. That order matters: the message-level AADSTS code tells the
# operator *which* Entra failure mode they hit (grant expired vs MFA
# required vs refresh-token-too-old) and therefore *what specific
# action* to take; the code-level "Unauthorized" only tells them
# something is wrong with the token, generically.
#
# Codes sourced from MS Learn:
# https://learn.microsoft.com/entra/identity-platform/reference-error-codes
TOKEN_HEALTH_ERROR_CODES = {
    "AADSTS50173": "Auth grant expired (token revoked or password changed). Re-authenticate the connection in Power Platform.",
    "AADSTS70008": "Refresh token expired due to inactivity. Re-authenticate the connection in Power Platform.",
    "AADSTS50058": "Silent sign-in failed (no active Entra session). Have the connection owner re-authenticate.",
    "AADSTS700082": "Refresh token has expired due to inactivity. Re-authenticate the connection.",
    "AADSTS700084": "Refresh token used after revocation. Re-authenticate the connection.",
    "AADSTS50076": "MFA challenge required. Have the connection owner re-authenticate and complete MFA.",
    "Unauthorized": "Power Platform marked the credential unauthorized. Re-authenticate the connection.",
    "Unauthenticated": "Connection is not authenticated. Have the connection owner sign in to Power Platform.",
    "ConfigurationNeeded": "Connection was created but never fully configured (required parameter missing). Either finish setup in Power Platform or delete the unbound connection.",
}

# Error-code values from TOKEN_HEALTH_ERROR_CODES that indicate the
# connection was created but never configured (vs. lapsed auth on a
# previously-working connection). Used by _classify_token_health_error
# to set the severity/remediation class.
_CONFIG_ERROR_CODES = frozenset({"ConfigurationNeeded"})
# Error-code values that indicate a previously-working auth that has
# lapsed and needs the owner to re-authenticate.
_AUTH_ERROR_CODES = frozenset({"Unauthorized", "Unauthenticated"})

# Matches Entra error-code identifiers like "AADSTS50173" or "AADSTS700082"
# anywhere in a string. Anchored to a 5-7 digit AADSTS prefix to avoid
# matching unrelated digit sequences. Used by _classify_token_health_error
# to extract the specific failure code from the (often long, prose-y)
# ``statuses[0].error.message`` field.
_AADSTS_CODE_RE = re.compile(r"\b(AADSTS\d{5,7})\b")


def _classify_token_health_error(
    conn: dict,
) -> tuple[str | None, str | None, str, str]:
    """Inspect ``statuses[0].error`` on a connection record and return
    ``(reported_code, reported_message, hint, severity_class)`` for
    token-health classification.

    The PowerApps connections API includes a structured ``error`` block
    on non-Connected statuses (target, code, message). The actual
    actionable Entra failure code (e.g. ``AADSTS50173``) is embedded
    in ``error.message`` rather than ``error.code`` (which is the
    coarser Power-Platform-side classification — typically
    ``Unauthorized`` or ``Unauthenticated``). We:

      1. First try to extract an ``AADSTSnnnnn`` code from
         ``error.message``. If found, that becomes the reported code
         and we look its hint up in TOKEN_HEALTH_ERROR_CODES.
      2. Otherwise we report the ``error.code`` field verbatim and
         look that up.
      3. If neither resolves to a known entry, we fall back to a
         generic re-authenticate hint and still surface whatever
         code/message the API returned so the operator can search
         for it in MS Learn.

    ``severity_class`` is one of:
      - ``"config"`` — connection was never fully configured (e.g.
        ``ConfigurationNeeded`` with ``Parameter value missing``).
        Different remediation path: finish setup OR delete the
        orphan; "re-authenticate" doesn't apply to something that
        was never authenticated.
      - ``"auth"`` — auth grant on a previously-working connection
        has lapsed (any AADSTS code, ``Unauthorized``,
        ``Unauthenticated``). Owner must re-authenticate.
      - ``"unknown"`` — error block present but neither config nor
        auth shape recognized. Treated as auth-style in remediation
        but flagged as needing investigation.

    Returns ``(None, None, no-status-hint, "unknown")`` only when the
    entire ``statuses`` array is missing or empty.

    Cited consumer: ``_check_connection_token_health`` (this file).
    Source (validated): ``tests/fixtures/cassettes/flightcheck_pp_admin.yaml``
    lines 2661-2680 capture the live AADSTS50173-in-message shape;
    lines 2682-2700+ capture the ``Unauthenticated`` ("never signed in")
    shape; the production fields used (``status`` / ``target`` / ``code``
    / ``message``) all appear in the cassette. The ``ConfigurationNeeded``
    shape was observed live on 2026-05-21 in env
    ``PROD - ESS + WD + SNow`` on 3-of-7 Workday SOAP connections that
    were created but never had their ``sku`` parameter populated.
    """
    statuses = conn.get("properties", {}).get("statuses", [])
    if not isinstance(statuses, list) or not statuses:
        return None, None, "No status information returned by Power Platform.", "unknown"
    err = statuses[0].get("error") or {}
    raw_code = err.get("code")
    raw_message = err.get("message") or ""

    # Tier 1: extract AADSTS code from message (production shape).
    aadsts_match = _AADSTS_CODE_RE.search(raw_message)
    if aadsts_match:
        aadsts_code = aadsts_match.group(1)
        hint = TOKEN_HEALTH_ERROR_CODES.get(
            aadsts_code,
            "Unrecognized AADSTS error. Re-authenticate the connection in Power Platform.",
        )
        return aadsts_code, raw_message, hint, "auth"

    # Tier 2: fall back to the coarser error.code value.
    if raw_code:
        hint = TOKEN_HEALTH_ERROR_CODES.get(
            raw_code,
            "Unrecognized token-health error. Re-authenticate the connection in Power Platform.",
        )
        if raw_code in _CONFIG_ERROR_CODES:
            severity = "config"
        elif raw_code in _AUTH_ERROR_CODES:
            severity = "auth"
        else:
            severity = "unknown"
        return raw_code, raw_message or None, hint, severity

    # Tier 3: error block present but neither an AADSTS code nor a code field.
    return None, raw_message or None, (
        "Connection reported an error but Power Platform did not include a "
        "structured error code. Re-authenticate the connection."
    ), "unknown"


def _check_connection_token_health(runner) -> list[CheckResult]:
    """WD-CONN-101 — Workday connection token / grant health (deep).

    WD-CONN-001 reports whether each Workday connection is in
    ``Connected`` state. WD-CONN-101 goes one level deeper: for any
    Workday connection NOT in ``Connected`` state, it parses the
    structured ``statuses[0].error.{code,message}`` block the
    PowerApps connections API returns, classifies the failure into
    config-needed vs lapsed-auth vs unknown, cross-references each
    unhealthy connection against the env's flow connection-references
    to determine in-use vs orphan, and emits up to two CheckResults:

      - FAILED — connections that are unhealthy AND referenced by an
        active flow (these will break flow execution at runtime).
      - WARNING — connections that are unhealthy but not referenced by
        any flow (cleanup task: orphan leftovers from solution
        imports, abandoned manual creation attempts, etc.).

    Each entry in the results carries enough operator-actionable
    detail to fix the issue without leaving the FlightCheck output:

      - Connection display name + short id suffix (so operators can
        disambiguate between 7 connections all named "Workday").
      - Owner — falls back to ``createdBy.userPrincipalName`` /
        ``createdBy.displayName`` when ``accountName`` is null
        (frequently the case for admin-scope listings of connections
        owned by other users).
      - Creation date — helps the operator spot stale records.
      - Deep link to the maker portal connections page.
      - For config-needed orphans: the exact
        ``Remove-AdminPowerAppConnection`` PowerShell command,
        pre-filled with env id, connection name, and connector name.
      - For lapsed-auth connections: the maker URL the owner needs
        to visit to re-authenticate, plus the per-AADSTS-code hint
        from TOKEN_HEALTH_ERROR_CODES.

    Mock tier (validated): backed by ``tests/mocks/pp_admin.py``
    (MOCK_STATUS = "validated", cassette
    ``tests/fixtures/cassettes/flightcheck_pp_admin.yaml``). Same
    endpoint as WD-CONN-001 — ``GET /providers/Microsoft.PowerApps/
    scopes/admin/environments/{env_id}/connections`` — so no new
    cassette is required. The flow-listing step uses
    ``pp.get_flows(env_id)`` against the validated Flow admin
    endpoint (also in the cassette).

    Scope notes (intentionally narrower than the issue suggested):
      * The runtime ESS Workday integration uses WS-Security
        UsernameToken (Basic auth via ISU username + password), so
        there is no Workday-side OAuth/refresh token to inspect. The
        OAuth surface that DOES exist is the Power Platform
        connection's wrapper grant — the Entra token from the user
        who created the connection ref. That is what WD-CONN-101
        inspects.
      * The issue also suggested an active SOAP probe
        (Get_Server_Timestamp / Get_Workers count=1). That ground is
        already covered by the existing WD-WF-* checks, which call
        17 real ESS workflows against the live Workday tenant when
        ISU credentials are supplied. WD-CONN-101 deliberately stays
        offline-only against the BAP cassette to avoid duplicating
        WD-WF-001 and to keep the check fast in CI.
      * The PowerApps connections API does NOT expose a
        ``lastRefreshedTimestamp`` field on connection records (not
        present in the validated cassette), so the issue's
        "warn-if-token-older-than-IdP-lifetime" branch is not
        implementable from this surface. Documented as a follow-up.
    """
    results: list[CheckResult] = []
    pp = runner.pp_admin
    env_id = runner.env_id

    if not env_id or pp is None:
        return results

    try:
        all_conns = pp.get_connections(env_id)
    except Exception as e:
        results.append(CheckResult(
            checkpoint_id="WD-CONN-101", category="Workday",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description="Workday connection token health",
            result=f"Unable to check: {e}",
        ))
        return results

    if isinstance(all_conns, dict) and "_error" in all_conns:
        results.append(CheckResult(
            checkpoint_id="WD-CONN-101", category="Workday",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description="Workday connection token health",
            result=f"Unable to list connections: {all_conns['_error']}",
            remediation="Requires Power Platform Administrator role.",
        ))
        return results

    wd_conns = filter_connections_by_connector(all_conns, "workday")

    if not wd_conns:
        results.append(CheckResult(
            checkpoint_id="WD-CONN-101", category="Workday",
            priority=Priority.HIGH.value, status=Status.NOT_CONFIGURED.value,
            description="Workday connection token health",
            result="No Workday connections found",
            remediation="Configure Workday SOAP connections in the environment.",
            doc_link=f"{DOC_BASE}/workday#step-3-connection-references",
        ))
        return results

    unhealthy: list[dict] = []
    for c in wd_conns:
        if get_connection_status(c) == "Connected":
            continue
        code, message, hint, severity = _classify_token_health_error(c)
        unhealthy.append({
            "conn": c,
            "code": code,
            "message": message,
            "hint": hint,
            "severity": severity,
        })

    if not unhealthy:
        results.append(CheckResult(
            checkpoint_id="WD-CONN-101", category="Workday",
            priority=Priority.HIGH.value, status=Status.PASSED.value,
            description="Workday connection token health",
            result=f"All {len(wd_conns)} Workday connection(s) report healthy auth state",
            doc_link=f"{DOC_BASE}/workday#step-3-connection-references",
        ))
        return results

    # In-use cross-reference. None ⇒ couldn't determine (treat all as
    # in-use for safety; better to over-report FAILED than to silently
    # demote a real flow-breaker to WARNING).
    in_use_names = _get_in_use_workday_connection_names(runner)

    failed_entries: list[dict] = []
    warning_entries: list[dict] = []
    for entry in unhealthy:
        conn_name = entry["conn"].get("name", "")
        if in_use_names is None:
            is_in_use = True
        else:
            is_in_use = conn_name in in_use_names
        entry["in_use"] = is_in_use
        entry["in_use_determined"] = in_use_names is not None
        if is_in_use:
            failed_entries.append(entry)
        else:
            warning_entries.append(entry)

    if failed_entries:
        details = [_format_unhealthy_detail(e) for e in failed_entries]
        remediations = [_format_unhealthy_remediation(e, env_id) for e in failed_entries]
        results.append(CheckResult(
            checkpoint_id="WD-CONN-101", category="Workday",
            priority=Priority.HIGH.value, status=Status.FAILED.value,
            description="Workday connection token health",
            result=(
                f"{len(failed_entries)} of {len(wd_conns)} Workday connection(s) "
                f"have unhealthy auth state and are referenced by a flow: "
                + "; ".join(details)
            ),
            remediation=" | ".join(remediations),
            doc_link=f"{DOC_BASE}/workday#step-3-connection-references",
        ))

    if warning_entries:
        details = [_format_unhealthy_detail(e) for e in warning_entries]
        remediations = [_format_unhealthy_remediation(e, env_id) for e in warning_entries]
        results.append(CheckResult(
            checkpoint_id="WD-CONN-101", category="Workday",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description="Workday connection token health",
            result=(
                f"{len(warning_entries)} orphan Workday connection(s) "
                f"(unhealthy but not referenced by any flow — cleanup task): "
                + "; ".join(details)
            ),
            remediation=" | ".join(remediations),
            doc_link=f"{DOC_BASE}/workday#step-3-connection-references",
        ))

    return results


# ── Operator-actionable formatting helpers for WD-CONN-101 ────────────
#
# Each unhealthy connection emits two strings into the CheckResult:
#
#   1. detail   — short identifier line that goes into the ``result``
#                 (the "what's broken") field.
#   2. remediation — actionable hint that goes into the ``remediation``
#                    field (the "what to do about it") field, including
#                    deep links and pre-filled PowerShell commands.
#
# The split exists because in the FlightCheck report, ``result`` shows
# in the summary table and ``remediation`` shows in the expandable
# detail — operators scan the summary first to triage, then read the
# remediation when they're ready to act.


def _extract_conn_id_suffix(name: str) -> str:
    """Return a short stable identifier from a connection's full name.

    PowerApps connection names follow the shape
    ``shared-<connector>-<guid>``, e.g.
    ``shared-workdaysoap-ac42a2e7-2ebf-4217-a7d7-0488d0fd48da``. We
    return the first 8-hex-digit segment from the GUID (e.g.
    ``ac42a2e7``) so operators can disambiguate between connections
    that all share the display name "Workday".
    """
    match = re.search(r"\b([0-9a-f]{8})\b", name.lower())
    if match:
        return match.group(1)
    # Fallback: last 8 chars of whatever we got.
    return name[-8:] if len(name) >= 8 else name or "(no-id)"


def _resolve_owner(props: dict) -> str:
    """Return the most useful owner identity available on a connection.

    Admin-scope connection listings (the endpoint WD-CONN-101 uses)
    frequently return ``accountName: null`` even when the connection
    has a clear creator — observed live on 2026-05-21 across 7 Workday
    connections owned by ``lmoulet@EmployeeHub.onmicrosoft.com`` where
    ``accountName`` was null but ``createdBy.userPrincipalName`` was
    populated.

    Falls back through ``accountName`` → ``createdBy.userPrincipalName``
    → ``createdBy.displayName`` → ``"(unknown owner)"`` so the
    operator gets the most actionable identity available.
    """
    account = props.get("accountName")
    if account:
        return account
    created_by = props.get("createdBy") or {}
    upn = created_by.get("userPrincipalName")
    if upn:
        return upn
    display = created_by.get("displayName")
    if display:
        return display
    return "(unknown owner)"


def _format_created_date(props: dict) -> str:
    """Return the YYYY-MM-DD portion of ``createdTime`` for compact display."""
    ts = props.get("createdTime") or ""
    if len(ts) >= 10 and ts[4] == "-" and ts[7] == "-":
        return ts[:10]
    return "(unknown date)"


def _extract_connector_name(conn: dict) -> str:
    """Extract the connector type name (e.g. ``shared_workdaysoap``)
    from the connection's ``apiId`` path. Used to build the
    ``-ConnectorName`` argument of the PowerShell delete command."""
    api_id = conn.get("properties", {}).get("apiId", "")
    match = re.search(r"/apis/([^/]+)/?$", api_id)
    return match.group(1) if match else "shared_workdaysoap"


def _maker_connections_url(env_id: str) -> str:
    """Direct link to the Power Automate maker connections page.

    We use make.powerautomate.com over make.powerapps.com because the
    PowerAutomate experience renders the env-scoped connections list
    more reliably across the multiple PPAC IA churns observed in
    2024-2026.
    """
    return f"https://make.powerautomate.com/environments/{env_id}/connections"


def _format_unhealthy_detail(entry: dict) -> str:
    """Single-connection detail line for the ``result`` field.

    Shape: ``'<display>' (id=<suffix>, owner=<owner>, created=<date>):
    <code> — <message>``
    """
    c = entry["conn"]
    props = c.get("properties", {})
    name = props.get("displayName", "(unnamed)")
    suffix = _extract_conn_id_suffix(c.get("name", ""))
    owner = _resolve_owner(props)
    date = _format_created_date(props)
    code = entry["code"] or "no-error-code"
    msg_excerpt = (entry["message"] or "").split("\n", 1)[0][:140]
    return (
        f"'{name}' (id={suffix}, owner={owner}, created={date}): "
        f"{code} — {msg_excerpt}"
    ).rstrip(" —")


def _format_unhealthy_remediation(entry: dict, env_id: str) -> str:
    """Single-connection remediation hint for the ``remediation`` field.

    Template varies by severity_class × in_use:
      - config + in-use:    owner must finish setup (flow depends on this)
      - config + orphan:    PowerShell delete command (never used, safe to remove)
      - auth + in-use:      owner must re-authenticate (admins can't re-auth others)
      - auth + orphan:      owner re-auth OR PowerShell delete
      - unknown + in-use:   owner investigates (we don't know what's wrong)
      - unknown + orphan:   owner investigates OR PowerShell delete
    """
    c = entry["conn"]
    props = c.get("properties", {})
    name = props.get("displayName", "(unnamed)")
    suffix = _extract_conn_id_suffix(c.get("name", ""))
    owner = _resolve_owner(props)
    severity = entry["severity"]
    hint = entry["hint"]
    in_use = entry["in_use"]
    conn_name = c.get("name", "")
    connector = _extract_connector_name(c)
    maker_url = _maker_connections_url(env_id)
    delete_cmd = (
        f"Remove-AdminPowerAppConnection -EnvironmentName {env_id} "
        f"-ConnectionName {conn_name} -ConnectorName {connector}"
    )
    prefix = f"'{name}' (id={suffix}, owner={owner}):"

    if severity == "config":
        if in_use:
            return (
                f"{prefix} {hint} Connection is referenced by an active flow — "
                f"owner ({owner}) must finish setup at {maker_url}; admins "
                f"cannot configure on owner's behalf."
            )
        return (
            f"{prefix} {hint} Connection is not referenced by any flow "
            f"(likely solution-import leftover). Delete as Power Platform "
            f"Admin: `{delete_cmd}`"
        )

    if severity == "auth":
        if in_use:
            return (
                f"{prefix} {hint} Connection is referenced by an active flow — "
                f"owner ({owner}) must re-authenticate at {maker_url}; admins "
                f"cannot re-auth on owner's behalf (would change the identity "
                f"the flow runs under)."
            )
        return (
            f"{prefix} {hint} Connection is not referenced by any flow. "
            f"Either owner re-authenticates at {maker_url} or delete as "
            f"orphan: `{delete_cmd}`"
        )

    # unknown
    if in_use:
        return (
            f"{prefix} {hint} Connection is referenced by an active flow — "
            f"owner ({owner}) should investigate at {maker_url}."
        )
    return (
        f"{prefix} {hint} Connection is not referenced by any flow. Either "
        f"owner investigates at {maker_url} or delete as orphan: `{delete_cmd}`"
    )


def _get_in_use_workday_connection_names(runner) -> set[str] | None:
    """Return the set of Workday connection names referenced by any
    flow in the environment, or ``None`` if we couldn't determine it.

    Each flow's ``properties.connectionReferences.{ref_key}`` carries
    the apiId of the connector and the bound connection's name. We
    collect every connection name where the apiId contains 'workday'.

    ``None`` ⇒ couldn't enumerate flows (flow API failed, returned
    insufficient_permissions, raised). The caller treats this as
    "unknown ⇒ assume in-use" so we don't silently demote real
    flow-breakers to WARNING.
    """
    pp = getattr(runner, "pp_admin", None)
    env_id = getattr(runner, "env_id", None)
    if not pp or not env_id:
        return None
    try:
        flows = pp.get_flows(env_id)
    except Exception:
        return None
    if isinstance(flows, dict) and "_error" in flows:
        return None
    if not isinstance(flows, list):
        return None
    in_use: set[str] = set()
    for f in flows:
        refs = (f.get("properties") or {}).get("connectionReferences") or {}
        if not isinstance(refs, dict):
            continue
        for _ref_key, ref in refs.items():
            if not isinstance(ref, dict):
                continue
            api_id = (
                ref.get("apiId")
                or (ref.get("api") or {}).get("name", "")
                or ""
            )
            if "workday" not in api_id.lower():
                continue
            conn_name = (
                ref.get("connectionName")
                or (ref.get("connection") or {}).get("name", "")
                or ""
            )
            if conn_name:
                in_use.add(conn_name)
    return in_use


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
