# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""WeveNova MCP Server (``weve-plan``).

Exposes live WeveNova AgentConfiguration **project**, **plan**, **task**, and
**role-assignment** operations as MCP tools so the ESS Maker Kit planner can
persist and query a rollout plan in WeveNova instead of a local ``plan.json``.

This is the in-repo, FastMCP port of the standalone ``weveOpenMcp`` reference
server. All behaviour lives in :mod:`core` (dependency-free, unit-tested); this
module is a thin FastMCP shell: one ``@mcp.tool()`` wrapper per WeveNova tool,
each delegating to :func:`core.call_wevenova`.

Every tool accepts optional ``userName`` and ``aadId`` — the token-profile
selector and AAD identity the planner reads from its ``.env`` and forwards on
every call (see ``scripts/planner/mcp_client.py``).

Run:
    python server.py                       # Streamable HTTP on 127.0.0.1:8081/mcp
    python server.py --transport stdio     # stdio transport (MCP CLI / local)
    python server.py --host 0.0.0.0 --port 8081

Point the planner at it by adding a ``weve-plan`` server to ``.vscode/mcp.json``
(see README.md).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from typing import Any

from mcp.server.fastmcp import FastMCP

# Sibling import — the server package is run with its own directory on sys.path,
# matching the workday/servicenow MCP servers in this repo.
from core import (  # type: ignore  # pylint: disable=import-error
    SERVER_VERSION,
    WeveNovaConfig,
    WeveNovaError,
    call_wevenova,
    load_user_cache,
)

CONFIG = WeveNovaConfig.from_env()
# Loaded once at startup; token_profile_by_aad is mutated in-place as callers
# associate an aadId with a userName (see core.resolve_tool_user_name).
USER_CACHE, TOKEN_PROFILE_BY_AAD = load_user_cache(CONFIG.user_cache_file)

_INSTRUCTIONS = (
    "Live WeveNova project, plan, and task operations. Every tool accepts optional "
    "userName and aadId; userName selects <tokenDirectory>/<userName>.txt. Supply "
    "userName and aadId together once so the server can associate that AAD identity "
    "with the token profile; later calls may use either. If neither is supplied, "
    "userName defaults to 'default'. Projects and plans have no DELETE route: archive "
    "projects with archive_agent_configuration_project and plans with "
    "archive_project_plan; only tasks can be permanently deleted, one at a time, via "
    "delete_project_plan_task. Before any PATCH or DELETE, call the direct get tool for "
    "the exact target entity and pass that entity's current ETag as If-Match — never a "
    "parent or list-response ETag. Retry at most once after re-reading only on an ETag "
    "mismatch. Task state transitions require the parent plan Status to be Active; "
    "Details.Code=PlanNotActive means the Draft plan must be activated by its owner. Use "
    "complete_project_plan_task to atomically set State=Completed with Outputs; use "
    "set_project_plan_task_state for lifecycle changes without outputs. For "
    "attest_plan_role, omit etag for a first attestation; its optional etag is only an "
    "existing role assignment's strong ETag, never the plan's weak W/\"...\" ETag."
)

mcp = FastMCP("weve-plan", instructions=_INSTRUCTIONS)


def _log(event: str, **details: Any) -> None:
    """Best-effort structured log line (never raises, mirrors the Node reference)."""
    if not CONFIG.log_file or CONFIG.log_file == ":memory:":
        return
    try:
        os.makedirs(os.path.dirname(CONFIG.log_file), exist_ok=True)
        entry = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "event": event, **details}
        with open(CONFIG.log_file, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def _dispatch(name: str, args: dict[str, Any]) -> Any:
    """Run one WeveNova tool through :mod:`core`, with light request logging.

    Only ``userName`` is logged as an identifier; the token itself is never read
    here and never logged.
    """
    request_id = str(uuid.uuid4())
    call_args = {key: value for key, value in args.items() if value is not None}
    _log("tool.received", requestId=request_id, tool=name, userName=call_args.get("userName"))
    started = time.time()
    try:
        result = call_wevenova(
            CONFIG,
            name,
            call_args,
            user_cache=USER_CACHE,
            token_profile_by_aad=TOKEN_PROFILE_BY_AAD,
        )
        _log("tool.completed", requestId=request_id, tool=name, durationMs=int((time.time() - started) * 1000))
        return result
    except WeveNovaError as exc:
        _log("tool.failed", requestId=request_id, tool=name, message=str(exc))
        # Re-raise so FastMCP returns an isError result the planner client can read.
        raise


# ═══════════════════════════════════════════════════════════════
#  DISCOVERY / DIRECTORY
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def find_users_by_name(name: str, userName: str | None = None, aadId: str | None = None) -> dict[str, Any]:
    """Find cached demo users by display name, alias, email, or token-profile name and return their AAD IDs."""
    return _dispatch("find_users_by_name", {"name": name, "userName": userName, "aadId": aadId})


@mcp.tool()
async def get_wevenova_lifecycle_rules(userName: str | None = None, aadId: str | None = None) -> dict[str, Any]:
    """Get authoritative project, plan, and task lifecycle capabilities before planning destructive work."""
    return _dispatch("get_wevenova_lifecycle_rules", {"userName": userName, "aadId": aadId})


@mcp.tool()
async def list_attestable_roles(userName: str | None = None, aadId: str | None = None) -> dict[str, Any]:
    """List the provider-owned role identifiers accepted by WeveNova plan attestation."""
    return _dispatch("list_attestable_roles", {"userName": userName, "aadId": aadId})


@mcp.tool()
async def list_task_roles(userName: str | None = None, aadId: str | None = None) -> dict[str, Any]:
    """List every role accepted for task grounding or pooled role assignment."""
    return _dispatch("list_task_roles", {"userName": userName, "aadId": aadId})


# ═══════════════════════════════════════════════════════════════
#  PROJECTS
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def list_agent_configuration_projects(
    query: dict[str, Any] | None = None, userName: str | None = None, aadId: str | None = None
) -> dict[str, Any]:
    """List live AgentConfiguration projects."""
    return _dispatch("list_agent_configuration_projects", {"query": query, "userName": userName, "aadId": aadId})


@mcp.tool()
async def create_agent_configuration_project(
    project: dict[str, Any], userName: str | None = None, aadId: str | None = None
) -> dict[str, Any]:
    """Create a new AgentConfiguration project."""
    return _dispatch("create_agent_configuration_project", {"project": project, "userName": userName, "aadId": aadId})


@mcp.tool()
async def get_agent_configuration_project(
    projectId: str, query: dict[str, Any] | None = None, userName: str | None = None, aadId: str | None = None
) -> dict[str, Any]:
    """Get one project and its current ETag before archiving or updating it."""
    return _dispatch(
        "get_agent_configuration_project",
        {"projectId": projectId, "query": query, "userName": userName, "aadId": aadId},
    )


@mcp.tool()
async def archive_agent_configuration_project(
    projectId: str, etag: str, userName: str | None = None, aadId: str | None = None
) -> dict[str, Any]:
    """Archive a project. Projects cannot be deleted; archiving cascades to the active plan and cancels in-flight tasks."""
    return _dispatch(
        "archive_agent_configuration_project",
        {"projectId": projectId, "etag": etag, "userName": userName, "aadId": aadId},
    )


# ═══════════════════════════════════════════════════════════════
#  PLANS
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def list_project_plans(
    projectId: str, query: dict[str, Any] | None = None, userName: str | None = None, aadId: str | None = None
) -> dict[str, Any]:
    """List plans in an AgentConfiguration project."""
    return _dispatch(
        "list_project_plans", {"projectId": projectId, "query": query, "userName": userName, "aadId": aadId}
    )


@mcp.tool()
async def get_project_plan(
    projectId: str, planId: str, query: dict[str, Any] | None = None, userName: str | None = None, aadId: str | None = None
) -> dict[str, Any]:
    """Get a plan and its current ETag before archiving or updating it."""
    return _dispatch(
        "get_project_plan",
        {"projectId": projectId, "planId": planId, "query": query, "userName": userName, "aadId": aadId},
    )


@mcp.tool()
async def create_project_plan(
    projectId: str, plan: dict[str, Any], userName: str | None = None, aadId: str | None = None
) -> dict[str, Any]:
    """Create a new plan in the specified AgentConfiguration project."""
    return _dispatch(
        "create_project_plan", {"projectId": projectId, "plan": plan, "userName": userName, "aadId": aadId}
    )


@mcp.tool()
async def update_project_plan(
    projectId: str, planId: str, patch: dict[str, Any], etag: str, userName: str | None = None, aadId: str | None = None
) -> dict[str, Any]:
    """Patch supported plan fields (owner only), including Status Draft->Active. Read the plan as its owner and use its current ETag."""
    return _dispatch(
        "update_project_plan",
        {"projectId": projectId, "planId": planId, "patch": patch, "etag": etag, "userName": userName, "aadId": aadId},
    )


@mcp.tool()
async def archive_project_plan(
    projectId: str, planId: str, etag: str, userName: str | None = None, aadId: str | None = None
) -> dict[str, Any]:
    """Archive a plan. Plans cannot be deleted; archiving cancels its in-flight tasks."""
    return _dispatch(
        "archive_project_plan",
        {"projectId": projectId, "planId": planId, "etag": etag, "userName": userName, "aadId": aadId},
    )


# ═══════════════════════════════════════════════════════════════
#  TASKS
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def list_project_plan_tasks(
    projectId: str, planId: str, query: dict[str, Any] | None = None, userName: str | None = None, aadId: str | None = None
) -> dict[str, Any]:
    """List tasks for a plan. Pass only projectId, planId, and optional query."""
    return _dispatch(
        "list_project_plan_tasks",
        {"projectId": projectId, "planId": planId, "query": query, "userName": userName, "aadId": aadId},
    )


@mcp.tool()
async def get_project_plan_task(
    projectId: str,
    planId: str,
    taskId: str,
    query: dict[str, Any] | None = None,
    userName: str | None = None,
    aadId: str | None = None,
) -> dict[str, Any]:
    """Get a task by project, plan, and task ID."""
    return _dispatch(
        "get_project_plan_task",
        {"projectId": projectId, "planId": planId, "taskId": taskId, "query": query, "userName": userName, "aadId": aadId},
    )


@mcp.tool()
async def create_project_plan_task(
    projectId: str,
    planId: str,
    task: dict[str, Any],
    idempotencyKey: str | None = None,
    userName: str | None = None,
    aadId: str | None = None,
) -> dict[str, Any]:
    """Create a user-assigned, role-pooled, or unassigned task. Role pooling uses assignedToType=Role."""
    return _dispatch(
        "create_project_plan_task",
        {
            "projectId": projectId,
            "planId": planId,
            "task": task,
            "idempotencyKey": idempotencyKey,
            "userName": userName,
            "aadId": aadId,
        },
    )


@mcp.tool()
async def create_role_assigned_project_plan_task(
    projectId: str,
    planId: str,
    role: str,
    title: str,
    description: str | None = None,
    produces: list[str] | None = None,
    consumes: list[str] | None = None,
    idempotencyKey: str | None = None,
    userName: str | None = None,
    aadId: str | None = None,
) -> dict[str, Any]:
    """Create a pooled task assigned to whoever holds the specified role for the plan."""
    return _dispatch(
        "create_role_assigned_project_plan_task",
        {
            "projectId": projectId,
            "planId": planId,
            "role": role,
            "title": title,
            "description": description,
            "produces": produces,
            "consumes": consumes,
            "idempotencyKey": idempotencyKey,
            "userName": userName,
            "aadId": aadId,
        },
    )


@mcp.tool()
async def list_project_plan_tasks_for_caller(
    projectId: str,
    planId: str,
    callerId: str,
    query: dict[str, Any] | None = None,
    userName: str | None = None,
    aadId: str | None = None,
) -> dict[str, Any]:
    """List direct and role-pooled tasks visible to the authenticated caller."""
    return _dispatch(
        "list_project_plan_tasks_for_caller",
        {"projectId": projectId, "planId": planId, "callerId": callerId, "query": query, "userName": userName, "aadId": aadId},
    )


@mcp.tool()
async def update_project_plan_task(
    projectId: str,
    planId: str,
    taskId: str,
    patch: dict[str, Any],
    etag: str,
    userName: str | None = None,
    aadId: str | None = None,
) -> dict[str, Any]:
    """Patch task content or claim a role-pooled task. To claim it, send patch { AssignedToId } only. Use the task's current ETag."""
    return _dispatch(
        "update_project_plan_task",
        {"projectId": projectId, "planId": planId, "taskId": taskId, "patch": patch, "etag": etag, "userName": userName, "aadId": aadId},
    )


@mcp.tool()
async def set_project_plan_task_state(
    projectId: str,
    planId: str,
    taskId: str,
    state: str,
    etag: str,
    userName: str | None = None,
    aadId: str | None = None,
) -> dict[str, Any]:
    """Set a task lifecycle state (NotStarted|InProgress|Completed|Cancelled) without outputs. Parent plan must be Active."""
    return _dispatch(
        "set_project_plan_task_state",
        {"projectId": projectId, "planId": planId, "taskId": taskId, "state": state, "etag": etag, "userName": userName, "aadId": aadId},
    )


@mcp.tool()
async def complete_project_plan_task(
    projectId: str,
    planId: str,
    taskId: str,
    outputs: list[dict[str, Any]],
    etag: str,
    userName: str | None = None,
    aadId: str | None = None,
) -> dict[str, Any]:
    """Atomically complete an InProgress task and persist its outputs into the parent plan ledger."""
    return _dispatch(
        "complete_project_plan_task",
        {"projectId": projectId, "planId": planId, "taskId": taskId, "outputs": outputs, "etag": etag, "userName": userName, "aadId": aadId},
    )


@mcp.tool()
async def delete_project_plan_task(
    projectId: str,
    planId: str,
    taskId: str,
    etag: str,
    userName: str | None = None,
    aadId: str | None = None,
) -> dict[str, Any]:
    """Permanently delete one task. Tasks are the only project-plan resource with a DELETE route. Use the task's current ETag."""
    return _dispatch(
        "delete_project_plan_task",
        {"projectId": projectId, "planId": planId, "taskId": taskId, "etag": etag, "userName": userName, "aadId": aadId},
    )


# ═══════════════════════════════════════════════════════════════
#  ROLE ASSIGNMENTS (tenant-sharded)
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def list_plan_role_assignments(
    tenantId: str,
    planId: str,
    subjectId: str | None = None,
    role: str | None = None,
    status: str | None = None,
    top: int | None = None,
    orderby: str | None = None,
    skiptoken: str | None = None,
    userName: str | None = None,
    aadId: str | None = None,
) -> dict[str, Any]:
    """List active or revoked role assignments for a plan to build a subject-to-role map."""
    return _dispatch(
        "list_plan_role_assignments",
        {
            "tenantId": tenantId,
            "planId": planId,
            "subjectId": subjectId,
            "role": role,
            "status": status,
            "top": top,
            "orderby": orderby,
            "skiptoken": skiptoken,
            "userName": userName,
            "aadId": aadId,
        },
    )


@mcp.tool()
async def get_role_assignment(
    tenantId: str, assignmentId: str, userName: str | None = None, aadId: str | None = None
) -> dict[str, Any]:
    """Get one role assignment by its opaque assignment ID."""
    return _dispatch(
        "get_role_assignment",
        {"tenantId": tenantId, "assignmentId": assignmentId, "userName": userName, "aadId": aadId},
    )


@mcp.tool()
async def attest_plan_role(
    tenantId: str,
    planId: str,
    subjectId: str,
    role: str,
    provider: str,
    etag: str | None = None,
    idempotencyKey: str | None = None,
    userName: str | None = None,
    aadId: str | None = None,
) -> dict[str, Any]:
    """Attest that a subject holds a provider-owned role for a plan. Omit etag for a first attestation."""
    return _dispatch(
        "attest_plan_role",
        {
            "tenantId": tenantId,
            "planId": planId,
            "subjectId": subjectId,
            "role": role,
            "provider": provider,
            "etag": etag,
            "idempotencyKey": idempotencyKey,
            "userName": userName,
            "aadId": aadId,
        },
    )


@mcp.tool()
async def revoke_role_assignment(
    tenantId: str, assignmentId: str, etag: str | None = None, userName: str | None = None, aadId: str | None = None
) -> dict[str, Any]:
    """Revoke a plan role assignment by opaque assignment ID."""
    return _dispatch(
        "revoke_role_assignment",
        {"tenantId": tenantId, "assignmentId": assignmentId, "etag": etag, "userName": userName, "aadId": aadId},
    )


# ═══════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=f"WeveNova MCP server (weve-plan) v{SERVER_VERSION}")
    parser.add_argument(
        "--transport",
        choices=["http", "stdio"],
        default=os.environ.get("WEVE_MCP_TRANSPORT", "http"),
        help="MCP transport. 'http' (default) serves Streamable HTTP at /mcp for the planner client.",
    )
    parser.add_argument("--host", default=os.environ.get("WEVE_MCP_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("WEVE_MCP_PORT", os.environ.get("PORT", "8081"))),
    )
    args = parser.parse_args(argv)

    if args.transport == "http":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
