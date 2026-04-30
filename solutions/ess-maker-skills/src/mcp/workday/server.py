# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Workday MCP Server

Exposes Workday SOAP and RaaS APIs as MCP tools for HR data retrieval,
absence management, compensation, organization lookup, and raw SOAP calls.

Designed as a reference implementation for the ESS Copilot Kit's Workday
onboarding/setup flow. Follows the same patterns as the ServiceNow MCP server.

Usage:
    python server.py                    # stdio transport (default)
    mcp run server.py                   # via MCP CLI
"""

import json
import os
from typing import Optional
from xml.etree import ElementTree as ET

from mcp.server.fastmcp import FastMCP

from client import WorkdayClient

mcp = FastMCP(
    "workday",
    instructions=(
        "Workday SOAP API integration for HR data, absence management, "
        "compensation, organizations, and Reports as a Service (RaaS). "
        "SOAP uses WS-Security authentication; RaaS uses HTTP Basic Auth. "
        "Requires Integration System User (ISU) credentials."
    ),
)

# ── Lazy client singleton ───────────────────────────────────────

_client: Optional[WorkdayClient] = None


def get_client() -> WorkdayClient:
    global _client
    if _client is None:
        _client = WorkdayClient()
    return _client


def _parse_json(raw: str, field_name: str) -> dict:
    """Parse a JSON-string tool argument with a friendly error.

    LLM tool calls supply these as strings; raw json.loads errors surface as
    Python tracebacks instead of recoverable MCP errors.
    """
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in '{field_name}': {e}") from e


def _xml_to_json(element: ET.Element) -> str:
    """Convert XML element to formatted JSON string."""
    data = WorkdayClient.xml_to_dict(element)
    return json.dumps(data, indent=2, default=str)


# ═══════════════════════════════════════════════════════════════
#  CONNECTIVITY
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def test_connection() -> str:
    """Test connectivity to the Workday SOAP API.

    Performs a minimal Get_Workers request (count=1) to verify authentication
    and network connectivity. Returns the worker's name if successful.
    """
    client = get_client()
    try:
        result = await client.get_workers(
            include_employment=False,
            include_personal_info=True,
            count=1,
        )
        return _xml_to_json(result)
    except Exception as e:
        return json.dumps({"error": str(e), "status": "connection_failed"})


# ═══════════════════════════════════════════════════════════════
#  HUMAN RESOURCES: WORKERS
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def get_worker(
    employee_id: str,
    as_of_date: str = "",
    include_employment: bool = True,
    include_compensation: bool = False,
    include_organizations: bool = False,
    include_roles: bool = False,
    include_personal_info: bool = True,
    include_qualifications: bool = False,
) -> str:
    """Get worker details from Workday by Employee ID.

    Calls the Human_Resources Get_Workers SOAP API.

    Args:
        employee_id: The Workday Employee ID
        as_of_date: Effective date filter (YYYY-MM-DD format). Empty = current.
        include_employment: Include employment information (hire date, job title, etc.)
        include_compensation: Include compensation details (base pay, salary range)
        include_organizations: Include organization assignments (cost center, company)
        include_roles: Include role assignments
        include_personal_info: Include personal info (name, contact details)
        include_qualifications: Include education, certifications, skills
    """
    client = get_client()
    result = await client.get_workers(
        employee_id=employee_id,
        as_of_date=as_of_date,
        include_employment=include_employment,
        include_compensation=include_compensation,
        include_organizations=include_organizations,
        include_roles=include_roles,
        include_personal_info=include_personal_info,
        include_qualifications=include_qualifications,
    )
    return _xml_to_json(result)


@mcp.tool()
async def list_workers(
    count: int = 10,
    as_of_date: str = "",
    include_employment: bool = True,
    include_personal_info: bool = True,
) -> str:
    """List workers from Workday (paginated).

    Calls the Human_Resources Get_Workers SOAP API without a specific ID
    to retrieve multiple workers.

    Args:
        count: Number of workers to return (default 10, max 100)
        as_of_date: Effective date filter (YYYY-MM-DD). Empty = current.
        include_employment: Include employment information
        include_personal_info: Include personal information
    """
    client = get_client()
    result = await client.get_workers(
        as_of_date=as_of_date,
        include_employment=include_employment,
        include_personal_info=include_personal_info,
        count=min(count, 100),
    )
    return _xml_to_json(result)


# ═══════════════════════════════════════════════════════════════
#  ABSENCE MANAGEMENT
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def get_time_off_balance(
    employee_id: str,
    as_of_date: str = "",
) -> str:
    """Get time off plan balances for a worker (vacation, sick, PTO, etc.).

    Calls the Absence_Management Get_Time_Off_Plan_Balances SOAP API.
    Returns each time off plan the worker is enrolled in, with balance hours.

    Args:
        employee_id: The Workday Employee ID
        as_of_date: Balance as of this date (YYYY-MM-DD). Empty = current.
    """
    client = get_client()
    result = await client.get_absence_balance(
        employee_id=employee_id,
        as_of_date=as_of_date,
    )
    return _xml_to_json(result)


@mcp.tool()
async def request_time_off(
    employee_id: str,
    date: str,
    time_off_type_id: str,
    hours: str = "8",
    comment: str = "",
) -> str:
    """Submit a time off request for a worker.

    Calls the Absence_Management Enter_Time_Off SOAP API.

    Args:
        employee_id: The Workday Employee ID
        date: Date of the time off (YYYY-MM-DD)
        time_off_type_id: Workday Time Off Type ID (e.g., the ID for Vacation, Sick, etc.)
        hours: Hours of time off (default "8" for a full day)
        comment: Optional comment for the time off request
    """
    client = get_client()
    result = await client.enter_time_off(
        employee_id=employee_id,
        date=date,
        time_off_type_id=time_off_type_id,
        hours=hours,
        comment=comment,
    )
    return _xml_to_json(result)


# ═══════════════════════════════════════════════════════════════
#  ORGANIZATIONS
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def get_organization(
    organization_id: str = "",
    organization_type: str = "Cost_Center_Reference_ID",
) -> str:
    """Get organization details from Workday.

    Calls the Human_Resources Get_Organizations SOAP API.
    Requires the account to have organization domain permissions.

    Args:
        organization_id: The organization ID to look up. Empty = list orgs.
        organization_type: ID type (Cost_Center_Reference_ID, Company_Reference_ID,
                          Organization_Reference_ID, etc.)
    """
    client = get_client()
    result = await client.get_organization(
        organization_id=organization_id,
        organization_type=organization_type,
    )
    return _xml_to_json(result)


# ═══════════════════════════════════════════════════════════════
#  REPORTS AS A SERVICE (RaaS)
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def run_report(
    report_owner: str,
    report_name: str,
    report_instance: str = "",
    params: str = "{}",
) -> str:
    """Run a Workday RaaS (Reports as a Service) custom report.

    Returns JSON output from the report. Used for user context retrieval,
    custom queries, and data extraction.

    Args:
        report_owner: The ISU account that owns the report
                     (e.g., ISU_WQL_COPILOT@contoso.com)
        report_name: Name of the report (e.g., WD_User_Context)
        report_instance: Report instance name (e.g., Report2). Empty if not applicable.
        params: JSON string of query parameters to pass to the report
    """
    client = get_client()
    parsed_params = _parse_json(params, "params") if params != "{}" else None
    result = await client.raas_query(
        report_owner=report_owner,
        report_name=report_name,
        report_instance=report_instance,
        params=parsed_params,
    )
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
async def get_user_context(
    user_name: str = "",
) -> str:
    """Get user context from the WD_User_Context RaaS report.

    This is the standard ESS user context report that maps a Workday username to
    employee data (Employee ID, name, org, manager status, etc.).

    The report requires the User_Name parameter (Workday username, not UPN).

    Args:
        user_name: The Workday username (e.g., lmcneil). Required by the report.
    """
    client = get_client()
    params = {}
    if user_name:
        params["User_Name"] = user_name

    # Report owner is configurable per customer. Falls back to RaaS username.
    report_owner = os.environ.get(
        "WORKDAY_RAAS_REPORT_OWNER", client._raas_username
    )

    result = await client.raas_query(
        report_owner=report_owner,
        report_name="WD_User_Context",
        params=params if params else None,
    )
    return json.dumps(result, indent=2, default=str)


# ═══════════════════════════════════════════════════════════════
#  RAW SOAP API
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def call_soap_api(
    service_name: str,
    body_xml: str,
    version: str = "v42.0",
) -> str:
    """Send a raw SOAP request to any Workday service.

    The body_xml should be the inner request element (e.g., a Get_Workers_Request).
    The server wraps it in a SOAP envelope with WS-Security UsernameToken headers.

    This is the escape hatch for calling any Workday API not covered by the
    typed tools above.

    Common services: Human_Resources, Absence_Management, Compensation,
    Staffing, Payroll, Benefits, Talent_Management, Performance_Management

    Args:
        service_name: Workday web service name (e.g., Human_Resources)
        body_xml: XML body of the SOAP request (inner element, no envelope)
        version: API version (default v42.0)
    """
    client = get_client()
    result = await client.raw_soap(
        service_name=service_name,
        body_xml=body_xml,
        version=version,
    )
    return _xml_to_json(result)


@mcp.tool()
async def extract_from_xml(
    service_name: str,
    body_xml: str,
    extract_paths: str,
    version: str = "v42.0",
) -> str:
    """Call a Workday SOAP API and extract specific values using XPath.

    Combines a SOAP call with XPath-based data extraction, matching the
    pattern used by ESS template configurations. Returns a JSON object
    mapping each key to the extracted values.

    Args:
        service_name: Workday web service name
        body_xml: XML body of the SOAP request
        extract_paths: JSON string mapping keys to XPath expressions.
                      Example: {"JobTitle": "//*[local-name()='Position_Title']/text()"}
        version: API version (default v42.0)
    """
    client = get_client()
    result = await client.raw_soap(service_name, body_xml, version)
    paths = _parse_json(extract_paths, "extract_paths")

    extracted = {}
    for key, xpath in paths.items():
        values = client.extract_xpath(result, xpath)
        extracted[key] = values[0] if len(values) == 1 else values

    return json.dumps(extracted, indent=2, default=str)


# ═══════════════════════════════════════════════════════════════
#  SERVICE DIRECTORY
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def list_services() -> str:
    """List the Workday SOAP services available through this MCP server.

    Returns service names, their typical operations, and the API version.
    This is a reference tool, no API call is made.
    """
    services = {
        "services": [
            {
                "name": "Human_Resources",
                "description": "Worker data: employment, compensation, organizations, personal info",
                "common_operations": [
                    "Get_Workers",
                    "Get_Organizations",
                    "Get_Job_Profiles",
                    "Get_Locations",
                ],
            },
            {
                "name": "Absence_Management",
                "description": "Time off: balances, requests, approvals",
                "common_operations": [
                    "Get_Time_Off_Balance",
                    "Enter_Time_Off",
                    "Get_Absence_Inputs",
                ],
            },
            {
                "name": "Compensation",
                "description": "Pay data: base compensation, salary ranges, bonus plans",
                "common_operations": [
                    "Get_Compensation_Plans",
                    "Get_Compensation_Ranges",
                ],
            },
            {
                "name": "Staffing",
                "description": "Positions, headcount, org changes, transfers",
                "common_operations": [
                    "Get_Positions",
                    "Get_Job_Families",
                ],
            },
            {
                "name": "Payroll",
                "description": "Pay stubs, tax forms, payroll results",
                "common_operations": [
                    "Get_Payroll_Results",
                ],
            },
            {
                "name": "Benefits",
                "description": "Benefits enrollment, plan details",
                "common_operations": [
                    "Get_Benefit_Plans",
                    "Get_Benefit_Enrollments",
                ],
            },
            {
                "name": "Talent_Management",
                "description": "Goals, development plans, succession",
                "common_operations": [
                    "Get_Goals",
                    "Get_Development_Plans",
                ],
            },
            {
                "name": "Performance_Management",
                "description": "Performance reviews, ratings",
                "common_operations": [
                    "Get_Performance_Reviews",
                ],
            },
        ],
        "api_version": "v42.0",
        "note": "Use call_soap_api for operations not covered by typed tools.",
    }
    return json.dumps(services, indent=2)


# ═══════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    mcp.run()
