# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""ServiceNow MCP Server

Exposes ServiceNow REST APIs as MCP tools for ITSM, HRSD, CMDB,
Service Catalog, User resolution, Live Agent, and auth/integration setup.

Usage:
    python server.py                    # stdio transport (default)
    mcp run server.py                   # via MCP CLI
"""

import json
import os
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


def _parse_json(raw: str, field_name: str) -> dict:
    """Parse a JSON-string tool argument with a friendly error.

    LLM tool calls supply these as strings; raw json.loads errors surface as
    Python tracebacks instead of recoverable MCP errors.
    """
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in '{field_name}': {e}") from e


def _resolve_secret_from_env(env_var: str, field_name: str) -> str:
    """Read a secret from a named environment variable.

    Tools that need to send secrets to ServiceNow (OAuth client_secret, OIDC
    client_secret, etc.) take the env var NAME as a tool argument rather than
    the secret value itself, so the secret never appears in MCP logs or LLM
    context. The MCP server process reads the secret from its own environment
    at execution time.
    """
    if not env_var:
        raise ValueError(
            f"{field_name} is required: pass the NAME of the env var that holds the secret "
            "(e.g. 'SERVICENOW_OAUTH_CLIENT_SECRET'), not the secret value itself."
        )
    value = os.environ.get(env_var)
    if not value:
        raise ValueError(
            f"Env var '{env_var}' is not set or empty. "
            f"Set it in the MCP server environment before invoking this tool."
        )
    return value


def _q(value: str) -> str:
    """Escape a value for ServiceNow encoded-query interpolation.

    The encoded-query syntax uses ``^`` as the AND operator and ``^OR`` for OR.
    Embedding either inside a value lets an attacker break out of a single
    filter clause and append additional ones (e.g. ``query='x^OR1=1'`` becomes
    a tautology that returns all records, or ``query='x^ORassigned_to=admin'``
    leaks records assigned to a different user).

    There is no documented official escape; the safe approach is to drop
    ``^`` characters (and the bare-newline / null bytes that some clients
    treat as separators) entirely from values supplied by the LLM/user. Tools
    must call this on every interpolated value going into a ``parts.append``.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    # Drop ^ (encoded-query AND/OR delimiter), null, CR, LF.
    return value.replace("^", " ").replace("\x00", "").replace("\r", " ").replace("\n", " ").strip()


# Feature flag for admin tools (register_oauth_application,
# register_oidc_provider, set_system_property). These tools mutate ServiceNow
# security/auth configuration and should normally be invoked from the
# /connect skill via explicit human-driven scripts, not from the LLM tool
# surface. Default: OFF. Set SERVICENOW_MCP_ENABLE_ADMIN_TOOLS=1 (or true)
# to enable for one-off setup work.
_ADMIN_TOOLS_ENABLED = os.environ.get(
    "SERVICENOW_MCP_ENABLE_ADMIN_TOOLS", ""
).lower() in ("1", "true", "yes", "on")


def _require_admin_tools(tool_name: str) -> None:
    """Raise a clear error when an admin tool is invoked without the flag."""
    if not _ADMIN_TOOLS_ENABLED:
        raise PermissionError(
            f"{tool_name} is an admin tool and is disabled by default. "
            "It mutates ServiceNow security / auth configuration and should be "
            "driven from the /connect skill (explicit human action) rather than "
            "the LLM tool surface. To enable for one-off setup, set the env var "
            "SERVICENOW_MCP_ENABLE_ADMIN_TOOLS=1 in the MCP server environment, "
            "restart the server, then disable again after the setup completes."
        )


# Tables on which non-GET methods (POST/PATCH/DELETE) are forbidden via the
# table API surface (call_api with table-API path prefixes). Read-only access
# is permitted because the typed tools (resolve_user, etc.) need to query
# sys_user records, but mutation through the generic table API would let
# prompt injection delete admin users, modify security ACLs, or escalate
# privileges by inserting into sys_user_grmember.
_CALL_API_TABLE_DENYLIST_NON_GET = frozenset({
    "sys_user",
    "sys_user_grmember",
    "sys_user_group",
    "sys_user_role",
    "sys_user_has_role",
    "sys_properties",
    "sys_audit",
    "sys_audit_delete",
    "sys_security_acl",
    "sys_security_diag",
    "oauth_entity",
    "oauth_entity_profile",
    "sys_oidc_provider",
    "sys_certificate",
    "sys_script",
    "sys_script_include",
    "sys_script_action",
    "sys_script_client",
    "sys_ws_operation",
})


import re as _re
_CALL_API_TABLE_PATH_RE = _re.compile(
    r"^/api/now/(?:v[12]/)?table/([a-z][a-z0-9_]{0,63})(?:/|$|\?)"
)


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
    parsed = _parse_json(data, "data")
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
    parsed = _parse_json(data, "data")
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
        parts.append(f"short_descriptionLIKE{_q(query)}")
    if state:
        parts.append(f"state={_q(state)}")
    if priority:
        parts.append(f"priority={_q(priority)}")
    if assigned_to:
        parts.append(f"assigned_to={_q(assigned_to)}")
    if category:
        parts.append(f"category={_q(category)}")

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
        parts.append(f"subjectLIKE{_q(query)}")
    if state:
        parts.append(f"state={_q(state)}")
    if hr_service:
        parts.append(f"hr_service={_q(hr_service)}")
    if opened_for:
        parts.append(f"opened_for={_q(opened_for)}")

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
        parts.append(f"nameLIKE{_q(query)}")
    if category:
        parts.append(f"category={_q(category)}")
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
        parts.append(f"nameLIKE{_q(query)}")
    if operational_status:
        parts.append(f"operational_status={_q(operational_status)}")

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
        parts.append(f"nameLIKE{_q(name)}")
    if email:
        parts.append(f"email={_q(email)}")
    if user_name:
        parts.append(f"user_name={_q(user_name)}")
    if employee_number:
        parts.append(f"employee_number={_q(employee_number)}")

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
        parts.append(f"short_descriptionLIKE{_q(query)}")
    if state:
        parts.append(f"state={_q(state)}")
    if channel:
        parts.append(f"channel={_q(channel)}")

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

    extra = _parse_json(additional_fields, "additional_fields") if additional_fields != "{}" else {}
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
    client_secret_env_var: str,
    redirect_url: str = "",
    auth_url: str = "",
    token_url: str = "",
    grant_type: str = "authorization_code",
    comments: str = "",
) -> str:
    """Register a new OAuth application in the OAuth Application Registry.

    ADMIN TOOL - disabled by default. Set the env var
    SERVICENOW_MCP_ENABLE_ADMIN_TOOLS=1 on the MCP server process to enable
    for one-off setup work, then unset it again. The /connect skill is the
    intended entry point for this operation.

    The OAuth client_secret is NOT passed as a tool argument. Instead, set the
    secret in an environment variable on the MCP server process and pass the env
    var NAME via client_secret_env_var. This keeps the secret out of MCP logs
    and LLM context.

    Args:
        name: Application name (e.g., 'Microsoft Entra ID')
        client_id: OAuth client ID from the identity provider
        client_secret_env_var: NAME of env var holding the OAuth client secret
            (e.g., 'SERVICENOW_OAUTH_CLIENT_SECRET'). The MCP server reads the
            actual value from os.environ at execution.
        redirect_url: OAuth redirect/callback URL
        auth_url: Authorization endpoint URL
        token_url: Token endpoint URL
        grant_type: Grant type (authorization_code, client_credentials, password, implicit)
        comments: Additional notes
    """
    _require_admin_tools("register_oauth_application")
    client_secret = _resolve_secret_from_env(client_secret_env_var, "client_secret_env_var")
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
    client_secret_env_var: str,
    well_known_url: str = "",
    oidc_provider: str = "",
    comments: str = "",
) -> str:
    """Register a new OIDC identity provider for user authentication.
    Typically used to configure Entra ID (Azure AD) SSO.

    ADMIN TOOL - disabled by default. Set the env var
    SERVICENOW_MCP_ENABLE_ADMIN_TOOLS=1 on the MCP server process to enable
    for one-off setup work, then unset it again. The /connect skill is the
    intended entry point for this operation.

    The OIDC client_secret is NOT passed as a tool argument. Instead, set the
    secret in an environment variable on the MCP server process and pass the env
    var NAME via client_secret_env_var. This keeps the secret out of MCP logs
    and LLM context.

    Args:
        name: Provider name (e.g., 'Microsoft Entra ID')
        client_id: OIDC client ID from Entra app registration
        client_secret_env_var: NAME of env var holding the OIDC client secret
            (e.g., 'SERVICENOW_OIDC_CLIENT_SECRET'). The MCP server reads the
            actual value from os.environ at execution.
        well_known_url: OpenID Connect discovery URL
        oidc_provider: OIDC provider sys_id (if linking to existing config)
        comments: Additional notes
    """
    _require_admin_tools("register_oidc_provider")
    client_secret = _resolve_secret_from_env(client_secret_env_var, "client_secret_env_var")
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

    ADMIN TOOL - disabled by default. System properties control auth modes,
    security policies, and integration toggles; arbitrary mutation can
    disable security controls. Set the env var
    SERVICENOW_MCP_ENABLE_ADMIN_TOOLS=1 on the MCP server process to enable
    for one-off setup work, then unset it again.

    Args:
        sys_id: sys_id of the system property record
        value: New value to set
    """
    _require_admin_tools("set_system_property")
    client = get_client()
    result = await client.update_record("sys_properties", sys_id, {"value": value})
    return _fmt(result)


# ═══════════════════════════════════════════════════════════════
#  GENERIC API CALL (escape hatch — restricted)
# ═══════════════════════════════════════════════════════════════

# Path allowlist for call_api: only data-plane REST endpoints.
# Admin / scripting / security paths are intentionally NOT in this list.
_CALL_API_PATH_ALLOWLIST = (
    "/api/now/table/",
    "/api/now/stats/",
    "/api/now/import/",
    "/api/now/attachment",
    "/api/now/v1/table/",
    "/api/now/v2/table/",
)

# Method allowlist for call_api: standard CRUD methods only.
_CALL_API_METHOD_ALLOWLIST = ("GET", "POST", "PATCH", "DELETE")


@mcp.tool()
async def call_api(method: str, path: str, data: str = "") -> str:
    """Call a ServiceNow data-plane REST endpoint (escape hatch).

    EXPLORATION ONLY — not for production use. Prefer the typed tools
    (query_table, get_record, create_record, update_record, delete_record, etc.)
    which cover the supported scenarios.

    For safety, this tool restricts:
      - Path: must start with one of the data-plane prefixes
        (/api/now/table/, /api/now/stats/, /api/now/import/, /api/now/attachment,
         /api/now/v1/table/, /api/now/v2/table/).
        Admin endpoints (auth, sys_security, sys_script, etc.) are blocked.
      - Method: must be one of GET, POST, PATCH, DELETE.

    Args:
        method: HTTP method (GET, POST, PATCH, DELETE)
        path: API path starting with /api/now/...
        data: Optional JSON string body for POST/PATCH requests
    """
    method_upper = method.upper()
    if method_upper not in _CALL_API_METHOD_ALLOWLIST:
        raise ValueError(
            f"call_api: method '{method}' not allowed. "
            f"Allowed methods: {', '.join(_CALL_API_METHOD_ALLOWLIST)}."
        )
    if not any(path.startswith(prefix) for prefix in _CALL_API_PATH_ALLOWLIST):
        raise ValueError(
            f"call_api: path '{path}' not on the allowlist. "
            f"Allowed prefixes: {', '.join(_CALL_API_PATH_ALLOWLIST)}. "
            "Admin and scripting endpoints are intentionally blocked. "
            "Use the typed tools (query_table, get_record, etc.) for supported scenarios."
        )

    # Table-API denylist: even though /api/now/table/* is on the path
    # allowlist, prevent non-GET methods from touching admin/security/audit
    # tables. GET (read) is permitted - the typed tools need to query sys_user
    # for resolve_user, etc.
    if method_upper != "GET":
        m = _CALL_API_TABLE_PATH_RE.match(path)
        if m and m.group(1) in _CALL_API_TABLE_DENYLIST_NON_GET:
            raise PermissionError(
                f"call_api: {method_upper} on table '{m.group(1)}' is forbidden. "
                "This table holds security/auth/audit configuration. Use a "
                "typed tool or the /connect skill for legitimate changes."
            )

    client = get_client()
    kwargs = {}
    if data and method_upper in ("POST", "PATCH"):
        kwargs["json"] = _parse_json(data, "data")
    result = await client._request(method_upper, path, **kwargs)
    return json.dumps(result, indent=2, default=str)


# ═══════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    mcp.run()
