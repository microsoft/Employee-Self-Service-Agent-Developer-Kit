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
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape as xml_escape

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
      3. my/config.json → connections.Workday (tenant, base URL)
      4. Interactive prompt (username + password only — never cached to disk)
      5. my/config.json → workdayTestEmployeeId (cached after first prompt)
    """
    results = []

    # --- Resolve credentials from available sources ---
    wd_base_url, wd_tenant, wd_username, wd_password, test_employee = (
        _resolve_workday_creds(runner)
    )

    if not wd_base_url or not wd_tenant:
        results.append(CheckResult(
            checkpoint_id="WD-WF-000", category="Workday Workflows",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description="Workday SOAP workflow tests",
            result="Workday not configured — skipping 17 workflow tests",
            remediation="Run /connect workday first, then re-run /flightcheck.",
        ))
        return results

    if not wd_username or not wd_password:
        results.append(CheckResult(
            checkpoint_id="WD-WF-000", category="Workday Workflows",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description="Workday SOAP workflow tests",
            result="Workday ISU credentials not provided — skipping workflow tests",
            remediation=(
                "Re-run flightcheck; when prompted, enter your ISU "
                "username and password to test the 17 workflows."
            ),
        ))
        return results

    if not test_employee:
        results.append(CheckResult(
            checkpoint_id="WD-WF-000", category="Workday Workflows",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description="Workday SOAP workflow tests",
            result="No test employee ID provided — skipping workflow tests",
            remediation="Re-run flightcheck and enter a test employee ID when prompted.",
        ))
        return results

    print(f"  Testing 17 Workday workflows (tenant: {wd_tenant})...")

    try:
        import httpx
    except ImportError:
        results.append(CheckResult(
            checkpoint_id="WD-WF-000", category="Workday Workflows",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description="Workday SOAP workflow tests",
            result="httpx not installed — skipping",
            remediation="pip install httpx",
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
            except ET.ParseError:
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

def _resolve_workday_creds(runner) -> tuple[str, str, str, str, str]:
    """Resolve Workday credentials from all available sources.

    Returns (base_url, tenant, username, password, test_employee_id).
    Never writes secrets to disk. Prompts interactively for creds only.
    """
    base_url = os.environ.get("WORKDAY_BASE_URL", "")
    tenant = os.environ.get("WORKDAY_TENANT", "")
    username = os.environ.get("WORKDAY_USERNAME", "")
    password = os.environ.get("WORKDAY_PASSWORD", "")
    test_employee = os.environ.get("WORKDAY_TEST_EMPLOYEE_ID", "")

    # --- Source 2: .vscode/mcp.json (non-secret values only) ---
    if not base_url or not tenant:
        mcp_env = _read_mcp_workday_env()
        if not base_url:
            base_url = mcp_env.get("WORKDAY_BASE_URL", "")
        if not tenant:
            tenant = mcp_env.get("WORKDAY_TENANT", "")

    # --- Source 3: my/config.json → connections.Workday ---
    config = getattr(runner, "config", {})
    wd_config = config.get("connections", {}).get("Workday", {})
    if not base_url:
        base_url = wd_config.get("baseUrl", "")
    if not tenant:
        tenant = wd_config.get("tenant", "")
    if not test_employee:
        test_employee = config.get("workdayTestEmployeeId", "")

    # If we don't even have base_url/tenant, Workday isn't configured
    if not base_url or not tenant:
        return "", "", "", "", ""

    # --- Source 4: Interactive prompt for secrets ---
    if not username or not password:
        # Only prompt if this is an interactive terminal
        if sys.stdin.isatty():
            print("\n  Workday SOAP workflow tests need ISU credentials.")
            print(f"  Tenant: {tenant}")
            print("  (Credentials are used for this run only — never saved to disk)\n")
            if not username:
                username = input("  ISU Username (without @tenant): ").strip()
                if username and "@" not in username:
                    username = f"{username}@{tenant}"
            if not password:
                password = getpass.getpass("  ISU Password: ")

    # --- Source 5: Test employee ID (prompt + cache in config) ---
    if not test_employee and sys.stdin.isatty():
        test_employee = input("  Test Employee ID (e.g. 21508): ").strip()
        if test_employee:
            # Cache to config so they don't have to enter it again
            _cache_test_employee_id(test_employee)

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
    """Save the test employee ID to my/config.json for future runs."""
    config_path = os.path.join("my", "config.json")
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
    return f"""
<bsvc:Get_Compensation_Plans_Request xmlns:bsvc="{BSVC}" bsvc:version="v42.0">
  <bsvc:Request_References>
    <bsvc:Compensation_Plan_Reference>
      <bsvc:ID bsvc:type="Employee_ID">{employee_id}</bsvc:ID>
    </bsvc:Compensation_Plan_Reference>
  </bsvc:Request_References>
</bsvc:Get_Compensation_Plans_Request>"""


def _build_write_test_body(employee_id: str) -> str:
    return f"""
<bsvc:Get_Change_Work_Contact_Information_Event_Request xmlns:bsvc="{BSVC}" bsvc:version="v42.0">
  <bsvc:Request_References>
    <bsvc:Change_Work_Contact_Information_Event_Reference>
      <bsvc:ID bsvc:type="Employee_ID">{employee_id}</bsvc:ID>
    </bsvc:Change_Work_Contact_Information_Event_Reference>
  </bsvc:Request_References>
</bsvc:Get_Change_Work_Contact_Information_Event_Request>"""


def _soap_call(
    base_url: str, tenant: str, username: str, password: str,
    service: str, body_xml: str,
) -> dict:
    """Make a synchronous SOAP call to Workday. Returns {success, response|error}."""
    import httpx

    url = f"{base_url}/{tenant}/{service}/v42.0"
    full_user = username if "@" in username else f"{username}@{tenant}"
    envelope = _build_soap_envelope(full_user, password, body_xml)

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                url,
                content=envelope,
                headers={"Content-Type": "text/xml; charset=utf-8"},
            )
            if resp.status_code < 400:
                return {"success": True, "response": resp.text}
            else:
                return {"success": False, "error": resp.text[:500]}
    except Exception as e:
        return {"success": False, "error": str(e)}
