"""ServiceNow MCP Server

Exposes ServiceNow REST APIs as MCP tools for ITSM, HRSD, CMDB,
Service Catalog, User resolution, Live Agent, and auth/integration setup.

Usage:
    python server.py                    # stdio transport (default)
    mcp run server.py                   # via MCP CLI
"""

import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from client import ServiceNowClient

mcp = FastMCP(
    "servicenow",
    instructions=(
        "ServiceNow REST API integration for ITSM incidents, HR cases, "
        "CMDB, service catalog, user lookup, live agent, and OAuth/OIDC setup"
    ),
)

# ── Lazy client singleton ───────────────────────────────────────

_client: Optional[ServiceNowClient] = None


def get_client() -> ServiceNowClient:
    global _client
    if _client is None:
        _client = ServiceNowClient()
    return _client


def _fmt(data: dict) -> str:
    """Format API response as readable JSON."""
    if "result" in data:
        results = data["result"]
        if isinstance(results, list):
            return json.dumps(
                {"count": len(results), "records": results},
                indent=2,
                default=str,
            )
        return json.dumps(results, indent=2, default=str)
    return json.dumps(data, indent=2, default=str)


# ═══════════════════════════════════════════════════════════════
#  GENERIC TABLE TOOLS
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def query_table(
    table: str,
    query: str = "",
    fields: str = "",
    limit: int = 10,
    offset: int = 0,
    order_by: str = "",
) -> str:
    """Query any ServiceNow table using encoded query syntax.

    Args:
        table: Table name (e.g., incident, sys_user, cmdb_ci)
        query: ServiceNow encoded query (e.g., 'state=1^priority=2')
        fields: Comma-separated field names to return (empty = all)
        limit: Max records to return (default 10, max 1000)
        offset: Starting record offset for pagination
        order_by: Field to sort by (prefix with DESC for descending)
    """
    client = get_client()
    result = await client.query_table(
        table, query, fields, min(limit, 1000), offset, order_by
    )
    return _fmt(result)


@mcp.tool()
async def get_record(table: str, sys_id: str, fields: str = "") -> str:
    """Get a single record from any ServiceNow table by sys_id.

    Args:
        table: Table name
        sys_id: The record's sys_id
        fields: Comma-separated field names to return (empty = all)
    """
    client = get_client()
    result = await client.get_record(table, sys_id, fields)
    return _fmt(result)


@mcp.tool()
async def create_record(table: str, data: str) -> str:
    """Create a new record in any ServiceNow table.

    Args:
        table: Table name
        data: JSON string of field name/value pairs
    """
    client = get_client()
    parsed = json.loads(data)
    result = await client.create_record(table, parsed)
    return _fmt(result)


@mcp.tool()
async def update_record(table: str, sys_id: str, data: str) -> str:
    """Update an existing record in any ServiceNow table.

    Args:
        table: Table name
        sys_id: The record's sys_id
        data: JSON string of field name/value pairs to update
    """
    client = get_client()
    parsed = json.loads(data)
    result = await client.update_record(table, sys_id, parsed)
    return _fmt(result)


@mcp.tool()
async def delete_record(table: str, sys_id: str) -> str:
    """Delete a record from any ServiceNow table.

    Args:
        table: Table name
        sys_id: The record's sys_id
    """
    client = get_client()
    await client.delete_record(table, sys_id)
    return json.dumps({"deleted": True, "table": table, "sys_id": sys_id})


# ═══════════════════════════════════════════════════════════════
#  ITSM: INCIDENTS
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def search_incidents(
    query: str = "",
    state: str = "",
    priority: str = "",
    assigned_to: str = "",
    category: str = "",
    limit: int = 10,
) -> str:
    """Search IT incidents with common filters.

    Args:
        query: Free text search in short_description
        state: Filter by state (1=New, 2=In Progress, 3=On Hold, 6=Resolved, 7=Closed)
        priority: Filter by priority (1=Critical, 2=High, 3=Moderate, 4=Low, 5=Planning)
        assigned_to: Filter by assigned user display name or sys_id
        category: Filter by category
        limit: Max results (default 10)
    """
    parts = []
    if query:
        parts.append(f"short_descriptionLIKE{query}")
    if state:
        parts.append(f"state={state}")
    if priority:
        parts.append(f"priority={priority}")
    if assigned_to:
        parts.append(f"assigned_to={assigned_to}")
    if category:
        parts.append(f"category={category}")

    encoded_query = "^".join(parts) if parts else ""
    fields = (
        "sys_id,number,short_description,state,priority,"
        "assigned_to,category,opened_at,updated_on"
    )

    client = get_client()
    result = await client.query_table(
        "incident", encoded_query, fields, min(limit, 100)
    )
    return _fmt(result)


@mcp.tool()
async def create_incident(
    short_description: str,
    description: str = "",
    urgency: str = "2",
    impact: str = "2",
    assigned_to: str = "",
    category: str = "",
    caller_id: str = "",
) -> str:
    """Create a new IT incident.

    Args:
        short_description: Brief summary of the incident
        description: Detailed description
        urgency: 1=High, 2=Medium, 3=Low
        impact: 1=High, 2=Medium, 3=Low
        assigned_to: User sys_id or name to assign to
        category: Incident category
        caller_id: sys_id of the person reporting
    """
    data: dict = {
        "short_description": short_description,
        "urgency": urgency,
        "impact": impact,
    }
    if description:
        data["description"] = description
    if assigned_to:
        data["assigned_to"] = assigned_to
    if category:
        data["category"] = category
    if caller_id:
        data["caller_id"] = caller_id

    client = get_client()
    result = await client.create_record("incident", data)
    return _fmt(result)


@mcp.tool()
async def resolve_incident(
    sys_id: str,
    close_code: str = "Solved (Permanently)",
    close_notes: str = "",
) -> str:
    """Resolve an incident (set state to Resolved).

    Args:
        sys_id: Incident sys_id
        close_code: Resolution code (default: Solved Permanently)
        close_notes: Resolution notes describing what was done
    """
    data: dict = {"state": "6", "close_code": close_code}
    if close_notes:
        data["close_notes"] = close_notes

    client = get_client()
    result = await client.update_record("incident", sys_id, data)
    return _fmt(result)


# ═══════════════════════════════════════════════════════════════
#  HRSD: HR CASES
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def search_hr_cases(
    query: str = "",
    state: str = "",
    hr_service: str = "",
    opened_for: str = "",
    limit: int = 10,
) -> str:
    """Search HR Service Delivery cases.

    Args:
        query: Free text search in subject
        state: Filter by state
        hr_service: Filter by HR service/category
        opened_for: Filter by employee sys_id
        limit: Max results
    """
    parts = []
    if query:
        parts.append(f"subjectLIKE{query}")
    if state:
        parts.append(f"state={state}")
    if hr_service:
        parts.append(f"hr_service={hr_service}")
    if opened_for:
        parts.append(f"opened_for={opened_for}")

    encoded_query = "^".join(parts) if parts else ""
    fields = (
        "sys_id,number,subject,state,hr_service,opened_for,opened_at,assigned_to"
    )

    client = get_client()
    result = await client.query_table(
        "sn_hr_core_case", encoded_query, fields, min(limit, 100)
    )
    return _fmt(result)


@mcp.tool()
async def create_hr_case(
    subject: str,
    description: str = "",
    hr_service: str = "",
    opened_for: str = "",
) -> str:
    """Create a new HR case.

    Args:
        subject: Brief case subject
        description: Detailed description of the HR request
        hr_service: HR service sys_id (e.g., benefits, onboarding)
        opened_for: Employee sys_id the case is for
    """
    data: dict = {"subject": subject}
    if description:
        data["description"] = description
    if hr_service:
        data["hr_service"] = hr_service
    if opened_for:
        data["opened_for"] = opened_for

    client = get_client()
    result = await client.create_record("sn_hr_core_case", data)
    return _fmt(result)


# ═══════════════════════════════════════════════════════════════
#  SERVICE CATALOG
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def browse_service_catalog(
    query: str = "",
    category: str = "",
    active: bool = True,
    limit: int = 10,
) -> str:
    """Browse the ServiceNow service catalog.

    Args:
        query: Free text search in catalog item name
        category: Filter by category sys_id
        active: Only return active items (default True)
        limit: Max results
    """
    parts = []
    if query:
        parts.append(f"nameLIKE{query}")
    if category:
        parts.append(f"category={category}")
    if active:
        parts.append("active=true")

    encoded_query = "^".join(parts) if parts else ""
    fields = "sys_id,name,short_description,category,price,active"

    client = get_client()
    result = await client.query_table(
        "sc_cat_item", encoded_query, fields, min(limit, 50)
    )
    return _fmt(result)


# ═══════════════════════════════════════════════════════════════
#  CMDB
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def search_cmdb_items(
    query: str = "",
    ci_class: str = "cmdb_ci",
    operational_status: str = "",
    limit: int = 10,
) -> str:
    """Search CMDB configuration items.

    Args:
        query: Free text search in name
        ci_class: CI class table (default: cmdb_ci; or cmdb_ci_server, cmdb_ci_computer, etc.)
        operational_status: Filter by status (1=Operational, 2=Non-Operational, 6=Retired)
        limit: Max results
    """
    parts = []
    if query:
        parts.append(f"nameLIKE{query}")
    if operational_status:
        parts.append(f"operational_status={operational_status}")

    encoded_query = "^".join(parts) if parts else ""
    fields = (
        "sys_id,name,sys_class_name,operational_status,"
        "ip_address,os,manufacturer"
    )

    client = get_client()
    result = await client.query_table(
        ci_class, encoded_query, fields, min(limit, 50)
    )
    return _fmt(result)


# ═══════════════════════════════════════════════════════════════
#  USERS
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def resolve_user(
    name: str = "",
    email: str = "",
    user_name: str = "",
    employee_number: str = "",
    limit: int = 5,
) -> str:
    """Look up ServiceNow users by name, email, username, or employee number.

    Args:
        name: Search by display name (partial match)
        email: Search by email address (exact match)
        user_name: Search by username (exact match)
        employee_number: Search by employee number
        limit: Max results
    """
    parts = []
    if name:
        parts.append(f"nameLIKE{name}")
    if email:
        parts.append(f"email={email}")
    if user_name:
        parts.append(f"user_name={user_name}")
    if employee_number:
        parts.append(f"employee_number={employee_number}")

    encoded_query = "^".join(parts) if parts else ""
    fields = "sys_id,name,email,user_name,employee_number,department,title,active"

    client = get_client()
    result = await client.query_table(
        "sys_user", encoded_query, fields, min(limit, 20)
    )
    return _fmt(result)


# ═══════════════════════════════════════════════════════════════
#  LIVE AGENT
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def search_interactions(
    query: str = "",
    state: str = "",
    channel: str = "",
    limit: int = 10,
) -> str:
    """Search live agent interaction records.

    Args:
        query: Free text search in short_description
        state: Filter by interaction state
        channel: Filter by channel type (e.g., chat, phone)
        limit: Max results
    """
    parts = []
    if query:
        parts.append(f"short_descriptionLIKE{query}")
    if state:
        parts.append(f"state={state}")
    if channel:
        parts.append(f"channel={channel}")

    encoded_query = "^".join(parts) if parts else ""

    client = get_client()
    result = await client.query_table(
        "interaction", encoded_query, "", min(limit, 50)
    )
    return _fmt(result)


@mcp.tool()
async def log_copilot_summary(
    interaction_id: str,
    summary: str,
    resolution: str = "",
    additional_fields: str = "{}",
) -> str:
    """Log a copilot chat summary to the u_ess_copilot_summary custom table.

    Args:
        interaction_id: sys_id of the related interaction record
        summary: Summary of the copilot conversation
        resolution: Resolution or outcome description
        additional_fields: JSON string of extra field/value pairs
    """
    data: dict = {
        "u_interaction": interaction_id,
        "u_summary": summary,
    }
    if resolution:
        data["u_resolution"] = resolution

    extra = json.loads(additional_fields) if additional_fields != "{}" else {}
    data.update(extra)

    client = get_client()
    result = await client.create_record("u_ess_copilot_summary", data)
    return _fmt(result)


# ═══════════════════════════════════════════════════════════════
#  AUTH & INTEGRATION SETUP
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def list_oauth_applications(query: str = "", limit: int = 10) -> str:
    """List OAuth Application Registry entries (oauth_entity table).

    Args:
        query: Free text search in application name
        limit: Max results
    """
    encoded_query = f"nameLIKE{query}" if query else ""
    fields = (
        "sys_id,name,client_id,redirect_url,token_url,auth_url,grant_type,active"
    )

    client = get_client()
    result = await client.query_table(
        "oauth_entity", encoded_query, fields, min(limit, 50)
    )
    return _fmt(result)


@mcp.tool()
async def register_oauth_application(
    name: str,
    client_id: str,
    client_secret: str,
    redirect_url: str = "",
    auth_url: str = "",
    token_url: str = "",
    grant_type: str = "authorization_code",
    comments: str = "",
) -> str:
    """Register a new OAuth application in the OAuth Application Registry.

    Args:
        name: Application name (e.g., 'Microsoft Entra ID')
        client_id: OAuth client ID from the identity provider
        client_secret: OAuth client secret
        redirect_url: OAuth redirect/callback URL
        auth_url: Authorization endpoint URL
        token_url: Token endpoint URL
        grant_type: Grant type (authorization_code, client_credentials, password, implicit)
        comments: Additional notes
    """
    data: dict = {
        "name": name,
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": grant_type,
        "default_grant_type": grant_type,
        "active": "true",
    }
    if redirect_url:
        data["redirect_url"] = redirect_url
    if auth_url:
        data["auth_url"] = auth_url
    if token_url:
        data["token_url"] = token_url
    if comments:
        data["comments"] = comments

    client = get_client()
    result = await client.create_record("oauth_entity", data)
    return _fmt(result)


@mcp.tool()
async def list_oidc_providers(query: str = "", limit: int = 10) -> str:
    """List OIDC provider registrations (oauth_oidc_entity table).
    Used for Entra ID / Azure AD user login integration.

    Args:
        query: Free text search in provider name
        limit: Max results
    """
    encoded_query = f"nameLIKE{query}" if query else ""

    client = get_client()
    result = await client.query_table(
        "oauth_oidc_entity", encoded_query, "", min(limit, 50)
    )
    return _fmt(result)


@mcp.tool()
async def register_oidc_provider(
    name: str,
    client_id: str,
    client_secret: str,
    well_known_url: str = "",
    oidc_provider: str = "",
    comments: str = "",
) -> str:
    """Register a new OIDC identity provider for user authentication.
    Typically used to configure Entra ID (Azure AD) SSO.

    Args:
        name: Provider name (e.g., 'Microsoft Entra ID')
        client_id: OIDC client ID from Entra app registration
        client_secret: OIDC client secret
        well_known_url: OpenID Connect discovery URL
        oidc_provider: OIDC provider sys_id (if linking to existing config)
        comments: Additional notes
    """
    data: dict = {
        "name": name,
        "client_id": client_id,
        "client_secret": client_secret,
        "active": "true",
    }
    if well_known_url:
        data["well_known_url"] = well_known_url
    if oidc_provider:
        data["oidc_provider"] = oidc_provider
    if comments:
        data["comments"] = comments

    client = get_client()
    result = await client.create_record("oauth_oidc_entity", data)
    return _fmt(result)


@mcp.tool()
async def get_oidc_provider_config(sys_id: str) -> str:
    """Get OIDC provider configuration details including claims mapping.

    Args:
        sys_id: sys_id of the OIDC provider configuration record
    """
    client = get_client()
    result = await client.get_record("oidc_provider_configuration", sys_id)
    return _fmt(result)


@mcp.tool()
async def check_plugin_active(plugin_id: str) -> str:
    """Check if a ServiceNow plugin is active.
    Common plugins:
      com.snc.integration.sso.multi (Multi-SSO)
      com.snc.authentication.oauth (OAuth)
      com.snc.platform.security.oidc (OIDC)

    Args:
        plugin_id: Plugin identifier (e.g., 'com.snc.integration.sso.multi')
    """
    client = get_client()
    result = await client.query_table(
        "sys_plugins",
        f"source={plugin_id}",
        "sys_id,source,name,active",
        limit=1,
    )
    return _fmt(result)


@mcp.tool()
async def get_system_properties(query: str = "", limit: int = 10) -> str:
    """Search ServiceNow system properties.
    Useful for checking OAuth/OIDC configuration flags.

    Args:
        query: Search in property name (e.g., 'glide.authenticate.sso', 'oauth')
        limit: Max results
    """
    encoded_query = f"nameLIKE{query}" if query else ""
    fields = "sys_id,name,value,description"

    client = get_client()
    result = await client.query_table(
        "sys_properties", encoded_query, fields, min(limit, 50)
    )
    return _fmt(result)


@mcp.tool()
async def set_system_property(sys_id: str, value: str) -> str:
    """Update a ServiceNow system property value.
    Use get_system_properties to find the sys_id first.

    Args:
        sys_id: sys_id of the system property record
        value: New value to set
    """
    client = get_client()
    result = await client.update_record("sys_properties", sys_id, {"value": value})
    return _fmt(result)


# ═══════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    mcp.run()
