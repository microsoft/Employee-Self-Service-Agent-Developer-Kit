# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""WeveNova MCP core — transport-agnostic WeveNova project/plan/task logic.

This module is the Python port of the ``weveOpenMcp`` reference server. It holds
**all** of the WeveNova behaviour (URL building, OData query composition, token
selection, ETag / If-Match handling, tenant sharding, role validation, and the
26 tool handlers) with **no dependency on the ``mcp`` package**. ``server.py``
imports this module and exposes each handler as a FastMCP tool.

Keeping the logic here (and out of ``server.py``) means the whole WeveNova
contract can be unit-tested with the standard library alone — inject a fake
``send`` callable and assert on the HTTP method, URL, headers, and body the
handler would forward upstream, exactly the way the Node reference is tested.

The planner talks to this server (registered as ``weve-plan`` in
``.vscode/mcp.json``) through ``scripts/planner/mcp_client.py``. The tool names,
argument names, and ETag rules mirror ``weveOpenMcp`` so the planner client is a
drop-in match.
"""

from __future__ import annotations

import json
import os
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit, quote

SERVER_VERSION = "5.6.0"

DEFAULT_PROJECTS_URL = (
    "https://localhost:444/weveb2/api/beta/me/AgentConfigurationProjects"
)
DEFAULT_TENANTS_URL = "https://localhost:444/weveb2/api/beta/tenants"

INTERNAL_TASK_ROLES = ["AgentOwner", "AgentEditor", "AgentAnnotator", "AgentViewer"]
ATTESTABLE_ROLES: list[dict[str, str]] = [
    {"provider": "External", "role": "WorkdayAdmin", "displayName": "Workday Administrator"},
    {"provider": "External", "role": "ServiceNowAdmin", "displayName": "ServiceNow Administrator"},
    {"provider": "External", "role": "ServiceNowKnowledgeManager", "displayName": "ServiceNow Knowledge Manager"},
    {"provider": "Entra", "role": "Global Administrator", "displayName": "Global Administrator"},
    {"provider": "Entra", "role": "Network Administrator", "displayName": "Network Administrator"},
    {"provider": "Entra", "role": "User Administrator", "displayName": "User Administrator"},
    {"provider": "Entra", "role": "Power Platform Administrator", "displayName": "Power Platform Administrator"},
    {"provider": "PowerPlatform", "role": "Environment Maker", "displayName": "Environment Maker"},
]
TASK_ROLES = INTERNAL_TASK_ROLES + [role["role"] for role in ATTESTABLE_ROLES]

PROVIDERS = ("External", "Entra", "PowerPlatform")
TASK_STATES = ("NotStarted", "InProgress", "Completed", "Cancelled")
OUTPUT_KINDS = ("Custom", "Environment", "Connection", "KnowledgeSource")
ROLE_ASSIGNMENT_STATES = ("Active", "Revoked")

_USER_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
# Characters left unescaped by JS encodeURIComponent — matched here so OData keys
# are percent-encoded identically to the Node reference.
_ODATA_KEY_SAFE = "-_.!~*'()"

_QUERY_NAMES = {
    "select": "$select",
    "expand": "$expand",
    "filter": "$filter",
    "orderby": "$orderby",
    "top": "$top",
    "skip": "$skip",
    "count": "$count",
    "skiptoken": "$skiptoken",
}

# The type of the injectable upstream sender: (url, method, headers, body) -> response dict
Sender = Callable[[str, str, dict[str, str], "str | None"], dict[str, Any]]


class WeveNovaError(RuntimeError):
    """A validation, transport, or upstream error surfaced back to the caller.

    ``server.py`` lets FastMCP convert this into an ``isError`` tool result, which
    the planner's MCP client turns into an ``McpError`` — the same round-trip the
    Node reference produces.
    """


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


@dataclass
class WeveNovaConfig:
    """Runtime configuration, mirroring the ``weveOpenMcp`` environment surface."""

    projects_url: str = DEFAULT_PROJECTS_URL
    tenants_url: str = DEFAULT_TENANTS_URL
    token_directory: str = "tokens"
    default_user_name: str = "default"
    user_cache_file: str = os.path.join("data", "user-cache.json")
    log_file: str = os.path.join("logs", "server.log")
    tasks_resource: str = "agentPlanTasks"
    upstream_timeout: float = 120.0

    @classmethod
    def from_env(cls, base_dir: str | None = None) -> "WeveNovaConfig":
        """Build a config from environment variables (paths resolve under ``base_dir``)."""
        base = base_dir or os.path.dirname(os.path.abspath(__file__))

        def _resolve(value: str) -> str:
            return value if os.path.isabs(value) else os.path.join(base, value)

        timeout_ms = os.environ.get("UPSTREAM_TIMEOUT_MS", "120000")
        try:
            timeout_seconds = float(timeout_ms) / 1000.0
        except ValueError:
            timeout_seconds = 120.0

        return cls(
            projects_url=os.environ.get("WEVE_PROJECTS_URL", DEFAULT_PROJECTS_URL),
            tenants_url=os.environ.get("WEVE_TENANTS_URL", DEFAULT_TENANTS_URL),
            token_directory=_resolve(os.environ.get("WEVE_TOKEN_DIRECTORY", "tokens")),
            default_user_name=os.environ.get("WEVE_DEFAULT_USER", "default"),
            user_cache_file=_resolve(
                os.environ.get("WEVE_USER_CACHE_FILE", os.path.join("data", "user-cache.json"))
            ),
            log_file=_resolve(os.environ.get("WEVE_LOG_FILE", os.path.join("logs", "server.log"))),
            tasks_resource=os.environ.get("WEVE_TASKS_RESOURCE", "agentPlanTasks"),
            upstream_timeout=timeout_seconds,
        )


# --------------------------------------------------------------------------- #
# Small validators / encoders
# --------------------------------------------------------------------------- #


def _assert_non_empty_string(value: Any, name: str) -> None:
    if not isinstance(value, str) or value.strip() == "":
        raise WeveNovaError(f"{name} must be a non-empty string")


def _assert_object(value: Any, name: str) -> None:
    if not isinstance(value, dict):
        raise WeveNovaError(f"{name} must be an object")


def _odata_key(value: Any, name: str) -> str:
    """Percent-encode an OData key segment the way the Node reference does."""
    _assert_non_empty_string(value, name)
    return quote(value, safe=_ODATA_KEY_SAFE).replace("'", "%27%27")


def _escape_odata_string(value: Any, name: str) -> str:
    """Escape a value for use inside an OData string literal (double the quote)."""
    _assert_non_empty_string(value, name)
    return value.replace("'", "''")


def _validate_known_task_role(role: Any, field_name: str) -> None:
    _assert_non_empty_string(role, field_name)
    if role not in TASK_ROLES:
        raise WeveNovaError(
            f"{field_name}: role is not a valid role. role must be one of {', '.join(TASK_ROLES)}."
        )


def _validate_task_create(task: Any, field_name: str = "task") -> None:
    _assert_object(task, field_name)
    if task.get("assignedToRoleId") is not None:
        _validate_known_task_role(task["assignedToRoleId"], f"{field_name}.assignedToRoleId")
    if task.get("assignedToType") == "Role":
        _validate_known_task_role(task.get("assignedToId"), f"{field_name}.assignedToId")


def _validate_inline_task_roles(plan: dict[str, Any]) -> None:
    tasks = plan.get("tasks")
    if tasks is None:
        return
    if not isinstance(tasks, list):
        raise WeveNovaError("plan.tasks must be an array")
    for index, task in enumerate(tasks):
        _validate_task_create(task, f"plan.tasks[{index}]")


# --------------------------------------------------------------------------- #
# URL building (OData routes)
# --------------------------------------------------------------------------- #


def _append_path(url_str: str, suffix: str) -> str:
    """Append a raw suffix to a URL's path (used for ``('key')/`` key segments)."""
    parts = urlsplit(url_str)
    return urlunsplit((parts.scheme, parts.netloc, parts.path + suffix, "", ""))


def _project_url(config: WeveNovaConfig, project_id: Any) -> str:
    return _append_path(config.projects_url, f"('{_odata_key(project_id, 'projectId')}')/")


def _tenant_url(config: WeveNovaConfig, tenant_id: Any) -> str:
    return _append_path(config.tenants_url, f"('{_odata_key(tenant_id, 'tenantId')}')/")


def _role_assignments_url(config: WeveNovaConfig, tenant_id: Any) -> str:
    return urljoin(_tenant_url(config, tenant_id), "agentRoleAssignments/")


def _role_assignment_url(config: WeveNovaConfig, tenant_id: Any, assignment_id: Any) -> str:
    return urljoin(
        _tenant_url(config, tenant_id),
        f"agentRoleAssignments('{_odata_key(assignment_id, 'assignmentId')}')",
    )


def _plans_url(config: WeveNovaConfig, project_id: Any) -> str:
    return urljoin(_project_url(config, project_id), "agentPlans")


def _plan_url(config: WeveNovaConfig, project_id: Any, plan_id: Any) -> str:
    return urljoin(
        _project_url(config, project_id),
        f"agentPlans('{_odata_key(plan_id, 'planId')}')/",
    )


def _task_path(resource: str, task_id: Any) -> str:
    return f"{resource}('{_odata_key(task_id, 'taskId')}')"


def _add_query(url_str: str, query: dict[str, Any] | None) -> str:
    """Attach OData ``$``-prefixed system query options to a URL."""
    if query is None:
        return url_str
    _assert_object(query, "query")
    parts = urlsplit(url_str)
    pairs: list[tuple[str, str]] = []
    for key, value in query.items():
        if key not in _QUERY_NAMES:
            raise WeveNovaError(f"Unsupported query option: {key}")
        if value is None:
            continue
        pairs.append((_QUERY_NAMES[key], str(value)))
    if not pairs:
        return url_str
    new_query = urlencode(pairs)
    if parts.query:
        new_query = f"{parts.query}&{new_query}"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, ""))


# --------------------------------------------------------------------------- #
# Token / identity resolution
# --------------------------------------------------------------------------- #


def _normalize_user_id(value: Any) -> str:
    return value.strip().lower() if isinstance(value, str) else ""


def _selected_user_name(config: WeveNovaConfig, user_name: str | None) -> str:
    name = user_name or config.default_user_name
    if not _USER_NAME_RE.match(name):
        raise WeveNovaError(
            "userName may contain only letters, numbers, dot, underscore, and hyphen"
        )
    return name


def resolve_tool_user_name(
    config: WeveNovaConfig,
    args: dict[str, Any],
    token_profile_by_aad: dict[str, str],
) -> str:
    """Resolve the token profile for a call from ``userName`` and/or ``aadId``.

    ``userName`` + ``aadId`` supplied together associates the AAD identity with
    the token profile; later calls may pass either. An ``aadId`` alone is only
    valid once its profile has been learned.
    """
    explicit_user = (args.get("userName") or "").strip()
    explicit_aad = _normalize_user_id(args.get("aadId"))
    aad_user = token_profile_by_aad.get(explicit_aad) if explicit_aad else None

    if explicit_user and explicit_aad and not aad_user:
        token_profile_by_aad[explicit_aad] = explicit_user
        return explicit_user
    if explicit_aad and not aad_user and not explicit_user:
        raise WeveNovaError(
            f"No token profile is known for AAD ID '{args.get('aadId')}'. "
            "Supply userName and aadId together once."
        )
    if explicit_user and aad_user and explicit_user != aad_user:
        raise WeveNovaError(
            f"userName '{explicit_user}' does not match the token profile "
            f"'{aad_user}' for AAD ID '{args.get('aadId')}'."
        )
    return explicit_user or aad_user or config.default_user_name


def authorization_for_user(config: WeveNovaConfig, user_name: str) -> str:
    """Read ``<tokenDirectory>/<userName>.txt`` and return a Bearer header value."""
    selected = _selected_user_name(config, user_name)
    token_path = os.path.join(config.token_directory, f"{selected}.txt")
    if not os.path.exists(token_path):
        raise WeveNovaError(
            f"Token file does not exist for user '{selected}': {token_path}"
        )
    token = None
    with open(token_path, "r", encoding="utf-8") as handle:
        for raw_line in handle.read().splitlines():
            line = raw_line.strip()
            if line and not line.startswith("#"):
                token = line
                break
    if not token:
        raise WeveNovaError(f"Token file is empty for user '{selected}': {token_path}")
    return token if token.startswith("Bearer ") else f"Bearer {token}"


# --------------------------------------------------------------------------- #
# User cache (demo directory for find_users_by_name)
# --------------------------------------------------------------------------- #


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_user_cache(file_path: str) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Load the demo user cache; returns ``(cache_by_aad, token_profile_by_aad)``."""
    cache: dict[str, dict[str, Any]] = {}
    token_profile_by_aad: dict[str, str] = {}
    if not file_path or file_path == ":memory:" or not os.path.exists(file_path):
        return cache, token_profile_by_aad

    with open(file_path, "r", encoding="utf-8") as handle:
        users = json.load(handle)
    if not isinstance(users, list):
        raise WeveNovaError("WEVE_USER_CACHE_FILE must contain a JSON array")

    for user in users:
        if not isinstance(user, dict):
            continue
        normalized_id = _normalize_user_id(user.get("aadId"))
        display_name = user.get("displayName")
        display_name = display_name.strip() if isinstance(display_name, str) else ""
        if not normalized_id or not display_name:
            continue
        record: dict[str, Any] = {
            "aadId": user["aadId"].strip(),
            "displayName": display_name,
            "source": user.get("source") or "persistent demo cache",
            "lastSeenAt": user.get("lastSeenAt") or _now_iso(),
        }
        for key in ("tenantId", "alias", "emailAddress", "tokenProfile"):
            if user.get(key):
                record[key] = user[key]
        cache[normalized_id] = record
        if user.get("tokenProfile"):
            token_profile_by_aad[normalized_id] = user["tokenProfile"]
    return cache, token_profile_by_aad


def find_users_by_name(user_cache: dict[str, dict[str, Any]], name: Any) -> dict[str, Any]:
    """Case-insensitive partial match over cached demo users (no upstream call)."""
    _assert_non_empty_string(name, "name")
    needle = name.strip().lower()
    users: list[dict[str, Any]] = []
    for record in user_cache.values():
        haystack = [record.get(field) for field in ("displayName", "alias", "emailAddress", "tokenProfile")]
        if any(isinstance(value, str) and needle in value.lower() for value in haystack):
            match: dict[str, Any] = {"displayName": record["displayName"], "aadId": record["aadId"]}
            for key in ("tenantId", "alias", "emailAddress"):
                if record.get(key):
                    match[key] = record[key]
            users.append(match)
    return {"users": users, "count": len(users)}


# --------------------------------------------------------------------------- #
# Static lifecycle contract
# --------------------------------------------------------------------------- #


def lifecycle_rules() -> dict[str, Any]:
    """Return the authoritative project/plan/task lifecycle capabilities."""
    return {
        "project": {
            "canCreate": True,
            "canArchive": True,
            "canDelete": False,
            "archiveCascade": "Archives the active plan and cancels in-flight tasks.",
        },
        "plan": {
            "canCreate": True,
            "canArchive": True,
            "canDelete": False,
            "archiveCascade": "Cancels in-flight child tasks.",
        },
        "task": {
            "canCreate": True,
            "canArchive": False,
            "canDelete": True,
            "deleteMode": "Delete tasks individually using projectId, planId, taskId, and current ETag.",
        },
        "mutationRule": (
            "PATCH and DELETE operations use the current target entity ETag. Create "
            "operations and first-time role attestations omit ETag; attest_plan_role "
            "accepts only an existing role assignment's strong ETag, never the plan ETag."
        ),
        "concurrencyRule": (
            "Before a mutation, call the direct get tool for the exact target entity and "
            "use its ETag, not a parent or list-response ETag. If the server reports an "
            "ETag mismatch, re-read and retry at most once. Do not retry other 409 conflicts."
        ),
        "taskStateRule": (
            "Task state transitions require the parent plan Status to be Active. A 409 with "
            "Details.Code=PlanNotActive is a lifecycle precondition failure, not an ETag "
            "conflict; activate the plan through the supported WeveNova workflow before retrying."
        ),
        "planActivationRule": (
            "Only the plan resource owner may activate a Draft plan. As the owner, call "
            "get_project_plan, then update_project_plan with patch { Status: 'Active' } and "
            "the plan's current ETag. Assigned role holders may read or execute eligible "
            "tasks but cannot change the plan lifecycle."
        ),
        "cacheRule": (
            "If delete_project_plan is visible, the client has stale tools and must refresh "
            "tools/list or reconnect."
        ),
    }


def list_task_roles() -> dict[str, Any]:
    """Every role accepted for task grounding or pooled role assignment."""
    return {
        "roles": [
            {"provider": "AgentConfiguration", "role": role, "displayName": role, "attestable": False}
            for role in INTERNAL_TASK_ROLES
        ]
        + [{**role, "attestable": True} for role in ATTESTABLE_ROLES]
    }


def _build_completion_outputs(outputs: Any) -> list[dict[str, Any]]:
    """Validate and normalize completion outputs into the WeveNova PATCH shape."""
    if not isinstance(outputs, list) or len(outputs) == 0:
        raise WeveNovaError("outputs must contain at least one completion artifact")
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for index, output in enumerate(outputs):
        _assert_object(output, f"outputs[{index}]")
        key = str(output.get("key") or "").strip()
        kind = str(output.get("kind") or "")
        if not key:
            raise WeveNovaError(f"outputs[{index}].key is required")
        if key in seen:
            raise WeveNovaError(f"outputs contains duplicate key {key}")
        seen.add(key)
        if kind not in OUTPUT_KINDS:
            raise WeveNovaError(f"outputs[{index}].kind is not supported")
        raw_attributes = output.get("attributes")
        if not isinstance(raw_attributes, list):
            raise WeveNovaError(f"outputs[{index}].attributes must be an array")
        attributes: list[dict[str, Any]] = []
        for attribute_index, attribute in enumerate(raw_attributes):
            _assert_object(attribute, f"outputs[{index}].attributes[{attribute_index}]")
            attribute_key = str(attribute.get("key") or "").strip()
            if not attribute_key:
                raise WeveNovaError(
                    f"outputs[{index}].attributes[{attribute_index}].key is required"
                )
            normalized: dict[str, Any] = {"Key": attribute_key, "Value": attribute.get("value")}
            if attribute.get("description") is not None:
                normalized["Description"] = attribute["description"]
            attributes.append(normalized)
        if kind == "Environment" and not any(
            attribute["Key"] == "environmentId" and str(attribute.get("Value") or "").strip()
            for attribute in attributes
        ):
            raise WeveNovaError(
                f"outputs[{index}] Environment requires a non-empty environmentId attribute"
            )
        normalized_output: dict[str, Any] = {"Key": key, "Kind": kind}
        if output.get("inventoryRef"):
            normalized_output["InventoryRef"] = output["inventoryRef"]
        normalized_output["Attributes"] = attributes
        result.append(normalized_output)
    return result


# --------------------------------------------------------------------------- #
# Upstream transport
# --------------------------------------------------------------------------- #


def _default_send(url: str, method: str, headers: dict[str, str], body: str | None, timeout: float) -> dict[str, Any]:
    """Send one request to WeveNova (TLS verification is skipped only for localhost)."""
    data = body.encode("utf-8") if isinstance(body, str) else None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    context: ssl.SSLContext | None = None
    if urlsplit(url).hostname == "localhost":
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            text = response.read().decode("utf-8", errors="replace")
            status = response.status
            return {"ok": 200 <= status < 300, "status": status, "statusText": response.reason or "", "text": text}
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        return {"ok": 200 <= exc.code < 300, "status": exc.code, "statusText": exc.reason or "", "text": text}
    except urllib.error.URLError as exc:
        raise WeveNovaError(f"Upstream request failed: {exc.reason}") from exc


def upstream_request(
    config: WeveNovaConfig,
    method: str,
    base_url: str,
    *,
    user_name: str,
    path: str = "",
    query: dict[str, Any] | None = None,
    body: Any = None,
    etag: Any = None,
    idempotency_key: Any = None,
    send: Sender | None = None,
) -> Any:
    """Build headers, forward the request, and return the parsed JSON payload."""
    url = urljoin(base_url, path) if path else base_url
    url = _add_query(url, query)

    headers = {
        "Accept": "application/json",
        "Authorization": authorization_for_user(config, user_name),
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    if etag is not None:
        _assert_non_empty_string(etag, "etag")
        headers["If-Match"] = etag
    if idempotency_key is not None:
        _assert_non_empty_string(idempotency_key, "idempotencyKey")
        headers["Idempotency-Key"] = idempotency_key

    sender: Sender = send or (
        lambda u, m, h, b: _default_send(u, m, h, b, config.upstream_timeout)
    )
    payload = json.dumps(body) if body is not None else None
    response = sender(url, method, headers, payload)

    text = response.get("text") or ""
    parsed: Any = None
    if text:
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            parsed = text

    if not response.get("ok"):
        detail = parsed if isinstance(parsed, str) else json.dumps(parsed)
        path_only = urlsplit(url).path
        message = (
            f"Upstream {method} {path_only} returned "
            f"{response.get('status')} {response.get('statusText')}"
        )
        if detail:
            message = f"{message}: {detail}"
        raise WeveNovaError(message)

    if parsed is None:
        return {"ok": True, "status": response.get("status"), "statusText": response.get("statusText")}
    return parsed


# --------------------------------------------------------------------------- #
# Tool dispatcher
# --------------------------------------------------------------------------- #


def call_wevenova(
    config: WeveNovaConfig,
    name: str,
    args: dict[str, Any] | None = None,
    *,
    send: Sender | None = None,
    user_cache: dict[str, dict[str, Any]] | None = None,
    token_profile_by_aad: dict[str, str] | None = None,
) -> Any:
    """Execute a WeveNova tool by name and return its parsed payload.

    This is the Python analogue of ``callToolForUser`` in the Node reference. All
    tool wrappers in ``server.py`` funnel through here so behaviour lives in one
    testable place.
    """
    args = args or {}
    _assert_object(args, "arguments")
    if token_profile_by_aad is None:
        token_profile_by_aad = {}
    if user_cache is None:
        user_cache = {}

    user_name = resolve_tool_user_name(config, args, token_profile_by_aad)

    def _req(method: str, base_url: str, **kwargs: Any) -> Any:
        return upstream_request(config, method, base_url, user_name=user_name, send=send, **kwargs)

    if name == "find_users_by_name":
        return find_users_by_name(user_cache, args.get("name"))

    if name == "get_wevenova_lifecycle_rules":
        return lifecycle_rules()

    if name == "list_agent_configuration_projects":
        return _req("GET", config.projects_url, query=args.get("query"))

    if name == "create_agent_configuration_project":
        _assert_object(args.get("project"), "project")
        return _req("POST", config.projects_url, body=args["project"])

    if name == "list_attestable_roles":
        return {"roles": [dict(role) for role in ATTESTABLE_ROLES]}

    if name == "list_task_roles":
        return list_task_roles()

    if name == "list_plan_role_assignments":
        clauses = [f"targetPlanId eq '{_escape_odata_string(args.get('planId'), 'planId')}'"]
        if args.get("subjectId") is not None:
            clauses.append(f"subjectObjectId eq '{_escape_odata_string(args['subjectId'], 'subjectId')}'")
        if args.get("role") is not None:
            clauses.append(f"roleId eq '{_escape_odata_string(args['role'], 'role')}'")
        if args.get("status") is not None:
            if args["status"] not in ROLE_ASSIGNMENT_STATES:
                raise WeveNovaError("status must be Active or Revoked")
            clauses.append(f"status eq '{args['status']}'")
        query = {
            "filter": " and ".join(clauses),
            "top": args.get("top"),
            "orderby": args.get("orderby"),
            "skiptoken": args.get("skiptoken"),
        }
        return _req("GET", _role_assignments_url(config, args.get("tenantId")), query=query)

    if name == "get_role_assignment":
        return _req("GET", _role_assignment_url(config, args.get("tenantId"), args.get("assignmentId")))

    if name == "attest_plan_role":
        if args.get("provider") not in PROVIDERS:
            raise WeveNovaError("provider must be External, Entra, or PowerPlatform")
        return _req(
            "POST",
            _role_assignments_url(config, args.get("tenantId")),
            path="attest",
            body={
                "subjectId": args.get("subjectId"),
                "role": args.get("role"),
                "target": {"type": "Plan", "id": args.get("planId")},
                "provider": args.get("provider"),
            },
            etag=args.get("etag"),
            idempotency_key=args.get("idempotencyKey"),
        )

    if name == "revoke_role_assignment":
        return _req(
            "DELETE",
            _role_assignment_url(config, args.get("tenantId"), args.get("assignmentId")),
            etag=args.get("etag"),
        )

    if name == "get_agent_configuration_project":
        return _req("GET", _project_url(config, args.get("projectId")), query=args.get("query"))

    if name == "archive_agent_configuration_project":
        return _req(
            "PATCH",
            _project_url(config, args.get("projectId")),
            body={"state": "Archived"},
            etag=args.get("etag"),
        )

    if name == "list_project_plans":
        return _req("GET", _plans_url(config, args.get("projectId")), query=args.get("query"))

    if name == "get_project_plan":
        return _req(
            "GET",
            _plan_url(config, args.get("projectId"), args.get("planId")),
            query=args.get("query"),
        )

    if name == "create_project_plan":
        _assert_object(args.get("plan"), "plan")
        _validate_inline_task_roles(args["plan"])
        return _req("POST", _plans_url(config, args.get("projectId")), body=args["plan"])

    if name == "update_project_plan":
        _assert_object(args.get("patch"), "patch")
        return _req(
            "PATCH",
            _plan_url(config, args.get("projectId"), args.get("planId")),
            body=args["patch"],
            etag=args.get("etag"),
        )

    if name == "archive_project_plan":
        return _req(
            "PATCH",
            _plan_url(config, args.get("projectId"), args.get("planId")),
            body={"status": "Archived"},
            etag=args.get("etag"),
        )

    if name == "list_project_plan_tasks":
        return _req(
            "GET",
            _plan_url(config, args.get("projectId"), args.get("planId")),
            path=config.tasks_resource,
            query=args.get("query"),
        )

    if name == "get_project_plan_task":
        return _req(
            "GET",
            _plan_url(config, args.get("projectId"), args.get("planId")),
            path=_task_path(config.tasks_resource, args.get("taskId")),
            query=args.get("query"),
        )

    if name == "create_project_plan_task":
        _validate_task_create(args.get("task"))
        return _req(
            "POST",
            _plan_url(config, args.get("projectId"), args.get("planId")),
            path=config.tasks_resource,
            body=args["task"],
            idempotency_key=args.get("idempotencyKey"),
        )

    if name == "create_role_assigned_project_plan_task":
        _validate_known_task_role(args.get("role"), "role")
        body: dict[str, Any] = {
            "title": args.get("title"),
            "assignedToId": args.get("role"),
            "assignedToType": "Role",
            "assignedToRoleId": args.get("role"),
        }
        if args.get("description") is not None:
            body["description"] = args["description"]
        if args.get("produces") is not None:
            body["produces"] = args["produces"]
        if args.get("consumes") is not None:
            body["consumes"] = args["consumes"]
        return _req(
            "POST",
            _plan_url(config, args.get("projectId"), args.get("planId")),
            path=config.tasks_resource,
            body=body,
            idempotency_key=args.get("idempotencyKey"),
        )

    if name == "list_project_plan_tasks_for_caller":
        query = dict(args.get("query") or {})
        caller_filter = f"assignedToId eq '{_escape_odata_string(args.get('callerId'), 'callerId')}'"
        query["filter"] = (
            f"{caller_filter} and ({query['filter']})" if query.get("filter") else caller_filter
        )
        return _req(
            "GET",
            _plan_url(config, args.get("projectId"), args.get("planId")),
            path=config.tasks_resource,
            query=query,
        )

    if name == "update_project_plan_task":
        _assert_object(args.get("patch"), "patch")
        for key in args["patch"].keys():
            if key not in ("Title", "Description", "AssignedToId", "Produces", "Consumes"):
                raise WeveNovaError(
                    f"patch.{key} is not accepted by WeveNova TaskUpdateRequest. "
                    "To claim a pooled task, patch only AssignedToId; role grounding "
                    "remains unchanged."
                )
        return _req(
            "PATCH",
            _plan_url(config, args.get("projectId"), args.get("planId")),
            path=_task_path(config.tasks_resource, args.get("taskId")),
            body=args["patch"],
            etag=args.get("etag"),
        )

    if name == "set_project_plan_task_state":
        if args.get("state") not in TASK_STATES:
            raise WeveNovaError("state must be NotStarted, InProgress, Completed, or Cancelled")
        return _req(
            "PATCH",
            _plan_url(config, args.get("projectId"), args.get("planId")),
            path=_task_path(config.tasks_resource, args.get("taskId")),
            body={"State": args["state"]},
            etag=args.get("etag"),
        )

    if name == "complete_project_plan_task":
        outputs = _build_completion_outputs(args.get("outputs"))
        return _req(
            "PATCH",
            _plan_url(config, args.get("projectId"), args.get("planId")),
            path=_task_path(config.tasks_resource, args.get("taskId")),
            body={"State": "Completed", "Outputs": outputs},
            etag=args.get("etag"),
        )

    if name == "delete_project_plan_task":
        return _req(
            "DELETE",
            _plan_url(config, args.get("projectId"), args.get("planId")),
            path=_task_path(config.tasks_resource, args.get("taskId")),
            etag=args.get("etag"),
        )

    if name == "delete_project_plan":
        raise WeveNovaError(
            "delete_project_plan was removed because WeveNova has no plan DELETE route. "
            "Read the plan for its current ETag, then call archive_project_plan. Archiving "
            "cancels in-flight tasks."
        )

    if name == "delete_agent_configuration_project":
        raise WeveNovaError(
            "WeveNova projects cannot be deleted. Read the project for its current ETag, "
            "then call archive_agent_configuration_project."
        )

    if name in ("call_project_plan_operation", "call_project_plan_task_operation"):
        raise WeveNovaError(
            "Bound plan/task actions are not supported by the current WeveNova API. Use the "
            "explicit PATCH/archive/task tools from tools/list."
        )

    raise WeveNovaError(f"Unknown tool: {name}")
